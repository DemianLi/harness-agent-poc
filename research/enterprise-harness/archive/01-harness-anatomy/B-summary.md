# Topic: 工具層設計

## Key Findings

- 根據 Anthropic 官方文件，工具描述品質是影響工具呼叫正確率「最重要的單一因素」，建議每個描述至少 3-4 句話，並提供好/壞範例對照；同行評審研究（Trace-Free+, 2026-02）獨立證實描述改寫能在 150+ 工具目錄下把準確率劣化幅度降低 29.23%（[B-001](#), [B-017](#)）。
- 工具數量增加確實會系統性降低選擇正確率——這不只是傳聞：Anthropic 官方文件自己承認「超過 30-50 個可用工具後選擇正確率會下降」，同行評審的 BiasBusters 研究（ICLR 2026 poster）進一步發現位置偏誤（清單中段工具被選中率明顯較低，源於 RoPE 長期衰減效應）（[B-006](#), [B-008](#)）。
- Anthropic 已把「工具數量爆炸」正式產品化為 Tool Search Tool（2025-11-19 上線）：用 defer_loading 讓工具定義不進 context 前綴，需要時才搜尋展開，官方數字是典型 5-MCP-server 設定省下 85%+ token（55k→數千），且不破壞 prompt cache（[B-005](#), [B-010](#)）。
- 工具錯誤回傳有明確官方規範（is_error 旗標 + 「可操作」錯誤訊息），但本專案目前的實作（字串式 `Error: xxx`）只做到一半——有錯誤碼但沒有下一步建議，也沒有用到結構化的 is_error 機制（[B-003](#), [B-004](#)）。
- 本專案 6 個工具的規模遠低於 Anthropic 建議啟用工具層進階機制（tool search、namespacing、consolidation）的門檻，這些是「還不需要但要有意識地不要引入」的層，而非「缺了」的層——真正的落差在描述品質與錯誤語意的細節，不是缺基礎設施（[B-002](#), [B-007](#), [B-012](#)）。

## Detailed Findings

### 1. 工具 schema 設計對正確率的實證數據（Focus Q1）

根據 [Anthropic 官方 Define Tools 文件](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)（2026），工具描述品質被明確列為「迄今為止最重要的效能因素」（"by far the most important factor in tool performance"）。官方給出的具體規範：至少 3-4 句話，要涵蓋工具做什麼、何時該用/不該用、每個參數的意義、以及重要限制。文件並列出對照範例——差的描述 `"Gets the stock price for a ticker."` vs. 好的描述說明了 ticker 必須是哪個交易所的合法代號、回傳幣別、以及「不會」回傳的資訊。文件另建議：把相關操作合併成單一工具（用 `action` 參數而非為每個動作各建一個工具）以降低選擇歧義，並用服務前綴做命名空間（`github_list_prs`、`slack_send_message`），這在使用 tool search 時尤其重要（[B-001](#), [B-011](#)）。

同行評審的 [Trace-Free+ 論文](https://arxiv.org/abs/2602.20426)（Intuit AI Research, 2026-02，本研究僅透過 WebSearch 摘要取得，未能直接開啟論文全文核對圖表）提供了量化佐證：在工具目錄擴大到 150+ 候選工具的情境下，用他們提出的 curriculum learning 框架改寫工具描述，可讓準確率劣化幅度減少 29.23%，並在 Stable-ToolBench 上讓平均查詢層級成功率提升 60.89%。這跟 Anthropic 定性建議的方向一致，且提供了「工具描述品質」與「正確率」之間有量化因果關係的獨立證據，而非單一廠商的自我背書（[B-017](#)）。

**對照本專案**：直接檢視 `harness_agent/tools/filesystem.py` 發現，6 個工具（ls/read_file/glob/grep/write_file/edit_file）的描述皆為單句 docstring（例如 `read_file` 只有 "Read file content with line numbers (cat -n format)."），沒有使用 `input_examples` 欄位，也沒有服務前綴命名空間。在目前只有 6 個工具、單一服務（檔案系統）的情境下，這個落差造成的實際風險可能不高——但若未來要接 git 操作或 HTTP 請求等第二個工具來源，裸動詞命名（`write`、`read`）會立刻產生跨服務命名衝突風險（[B-002](#), [B-012](#)）。

### 2. 工具數量爆炸與 context 膨脹（Focus Q2）

Anthropic 官方文件承認一個具體的規模問題：一個典型的多 MCP-server 設定（GitHub + Slack + Sentry + Grafana + Splunk）在使用者輸入任何內容之前，就會消耗約 55k tokens 的工具定義；而工具選擇正確率會在「超過 30-50 個可用工具」後開始下降（[B-005](#), [B-006](#)）。這是官方自己承認的量化門檻，不是外部批評——[Anthropic Tool Search Tool 官方文件](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool) 給出明確的「何時該用」判準：工具數 ≥10、工具定義 >10k tokens、或聚合了 200+ 工具的多個 MCP server 時就該用；反之工具數 <10 且每次都會用到全部工具時，標準做法（不用 tool search）更合適。

機制上，Tool Search Tool 讓開發者在工具定義中標記 `defer_loading: true`，這些工具的定義不會進入 system prompt 前綴（因此不影響 prompt caching），只有在 Claude 主動搜尋（regex 或 BM25 兩種變體）命中後才由 API 展開成完整定義塞進對話。這跟 topic-C 負責的「整體 context 預算/compaction」是不同層次的機制：tool search 解決的是「工具*定義*要不要一開始就佔位」，而 topic-C 的 `clear_tool_uses_20250919` 解決的是「工具*結果*用完之後要不要留著」。兩者已與 topic-C 協調確認分工邊界（[B-005](#), [B-016](#)）。

MCP 生態在企業規模下除了 context 膨脹，還有規格層級的問題：MCP 授權規格把 MCP server 同時當成 resource server 與 authorization server，這跟需要 session/token 撤銷狀態的企業 IdP 實務有摩擦；還有經典的「confused deputy」問題——透過 MCP server 執行動作的使用者，可能因為 MCP server 本身的權限比使用者高，而拿到原本不該有的資源存取權（[B-013](#)，本研究未能直接開啟 atolio.com/cdata.com 原文，整理自多篇部落格摘要交叉比對，屬 MEDIUM confidence）。這一段內容 [CONNECTS TO: Topic D — 這是權限控制/sandbox 設計要處理的直接輸入]。

**對照本專案**：6 個工具、無外部 MCP server，遠低於官方 10 工具/10k token 門檻，因此現階段確實不需要 tool search / defer_loading 這層。這是這次研究裡少數「POC 沒有的層，暫時也不該加」的結論——過早引入 tool search 基礎設施對 6 個工具的專案是不必要的複雜度，但這是需要「有意識地延後」而非「遺漏」（[B-007](#)）。

### 3. 工具錯誤如何回傳給模型（Focus Q3）

[Anthropic Handle Tool Calls 官方文件](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls) 定義了明確的錯誤語意機制：`tool_result` 可以帶 `is_error: true` 旗標，並強烈建議錯誤訊息要「可操作」——原文範例把 generic 的 `"failed"` 跟具體的 `"Rate limit exceeded. Retry after 60 seconds."` 做對比，明確說「這給 Claude 恢復或調整所需的脈絡，而不用用猜的」。文件也指出一個有趣的行為現象：當工具呼叫缺少必要參數時，Claude 通常會自行重試 2-3 次修正後才向使用者道歉——這代表『可恢復性』的設計不只是錯誤訊息寫得好不好，也包括系統本身容許幾輪修正嘗試。文件另外建議用 `strict: true` 的 strict tool use 從根本上讓工具輸入必定符合 schema，避免無效呼叫這整類問題（[B-003](#)）。

**對照本專案**：`filesystem.py` 的錯誤回傳是機器碼式短字串（`Error: path_not_found: {path}`、`Error: not_a_directory: {path}`），符合「語意化錯誤碼」的精神，但除了 `edit_file` 對重複字串的錯誤有給出具體建議（"Add more surrounding context"）之外，其餘工具都沒有「下一步該怎麼做」的可恢復性提示。更根本的問題是：底層用 LangChain `@tool` 裝飾器回傳純字串，沒有見到 `is_error` 或等效的 status 欄位傳遞機制，模型在結構層面無法區分「正常結果字串恰好包含 Error 字樣」跟「真正的工具執行失敗」。這是一個具體、可行動的落差——LangChain 的 `ToolMessage` 物件本身支援 `status="error"` 欄位，理論上可以達到類似效果，這是框架已支援但專案尚未使用的能力（[B-004](#)）。

### 4. 失敗模式與量化研究（Focus Q4，Adversarial）

除了 Anthropic 自己承認的 30-50 工具門檻，同行評審的 [BiasBusters 論文](https://www.alphaxiv.org/overview/2510.00307v1)（arXiv 2510.00307，ICLR 2026 poster）提供了更細緻的失敗模式：位置偏誤。在 741 個工具的候選集中，位於清單開頭與結尾的工具準確率約 31-32%，位於清單中段（40%-60% 位置）的工具準確率只有 22-52%（依模型而異）。作者將此歸因於 Transformer 的 RoPE 長期衰減效應——這是架構層級的偏誤，不分模型廠商都存在，緩解手段是先過濾出相關子集、再均勻取樣，而非固定塞入一個長清單（[B-008](#)，本研究未能直接讀取論文全文，數字來自二手摘要交叉比對）。

另外從多篇部落格文章（含引用 LongFuncEval, arXiv 2505.10570）整理到的數字顯示，工具數從 10 增加到 100+ 時，某基準測試準確率可能從 78% 崩跌到 13.62%；工具數從 207 到 417 時，某模型準確率從 64% 掉到 20%。**這兩組具體百分比數字我標記為 LOW confidence**——本次研究只透過 WebSearch 摘要取得，沒有開啟原始論文或部落格全文驗證方法論（樣本模型、任務類型、是否單一實驗孤例），且是多篇來源混合引用、有以訛傳訛風險。它們作為「工具越多、選擇越差」的方向性佐證是合理的（跟官方 30-50 門檻、BiasBusters 研究方向一致），但作為精確數字引用前應該再溯源驗證（[B-009](#)）。

**[ADVERSARIAL — 與 Topic D 交叉驗證的失敗模式]**：本研究另外發現一個與「工具過多」不同性質但同樣重要的失敗模式——**宣告式的工具權限跟執行期實際強制之間的落差**。Anthropic API 層級有 `allowed_callers` 屬性可限制工具只能被特定執行環境呼叫（例如只能從 code execution 內呼叫，模型不能直接呼叫），這是可驗證的 API 層機制。但公開 GitHub issue（`anthropics/claude-agent-sdk-typescript#172`，經 peer topic-D 直接 WebFetch 驗證為真、狀態 OPEN、2026-02-12 開單）顯示：SDK 層級的 sub-agent 工具白名單/黑名單（`AgentDefinition.tools` / `disallowedTools`）並未在 child process 層級被強制執行，CLI spawn sub-agent 時沒有把這些設定映射成對應的 CLI flags，導致 sub-agent 能呼叫理論上被禁止的工具。這代表「工具層權限控制」不是單一機制，而是分散在 API schema（`allowed_callers`，可驗證）跟 SDK 執行期（`disallowedTools`，目前不可靠）兩個不同、成熟度不同的層次（[B-014](#), [B-015](#)）。

## Investigation Log

- **From corpus:** 使用 corpus 條目 #2（Claude Cookbook context engineering，直接 WebFetch 成功）、#8-11（tool schema / MCP 相關，皆 403 無法直接開啟，改用 WebSearch + 官方文件替代路徑取得等效資訊）。corpus 標記為此主題來源最少（5 條），確實比其他主題更依賴補充搜尋。
- **Supplementary searches:** "Anthropic tool search tool MCP context window many tools 2026"、"too many tools LLM function calling accuracy degradation study"、"MCP Model Context Protocol enterprise scale problems security limitations criticism"、"BiasBusters study LLM tool selection position bias"、"Learning to Rewrite Tool Descriptions"、"Piebald-AI claude-code-system-prompts tool descriptions token count"，另外直接查看專案原始碼 `harness_agent/tools/filesystem.py` 做 gap analysis。
- **Discarded:** amitness.com（403）、Obot AI（403）、MCP 官方 spec 頁面（403）、ToolSpec 論文 PDF（403）、atcyrus.com/tianpan.co/growthmethod.com（皆 403，未能驗證其具體數字，故未直接引用，改以官方文件與 WebSearch 摘要的一致性佐證同類論點）、arxiv 2602.20426/2605.24660 全文（皆 403，僅用摘要）。
- **Contradictions debated:** 無直接數字矛盾；B-006（官方 30-50 門檻）與 B-009（部落格引用的 78%→13.62%、64%→20%）數字量級不完全一致（官方講門檻位置，部落格講崩跌幅度），已在 claims 中分別標註信心等級（HIGH vs LOW）避免混為一談。
- **Peer findings incorporated:** topic-A 確認並獨立驗證了 tool-use system prompt 模板結構的發現（B-010）；topic-C 確認 tool search/defer_loading（我方）vs clear_tool_uses_20250919 整體 context 預算（topic-C 方）的分工邊界，並指出我方 defer_loading 對 prompt cache 穩定性的發現對他的成本模型章節有直接貢獻；topic-D 獨立 WebFetch 驗證了 GitHub issue #172，確認為真實 bug，並將其與我方 allowed_callers 發現做對照，形成「API 層可驗證 vs SDK 層文件承諾未兌現」的完整對照（B-015）。
- **Adversarial search results:** BiasBusters 位置偏誤研究（同行評審）、MCP 企業級授權規格缺陷（confused deputy、resource/auth server 混合）、GitHub issue #172（sub-agent 工具白名單未強制執行）。三者都是具體、可查證的限制，不是泛泛而談的「有風險」。
- **Challenges issued:** 未直接對其他 specialist 的既有 claim 提出反駁式 challenge（研究開始時尚無其他 specialist 的既有 claims 可查），但主動提出 Overlap 協調（與 topic-C）並提供可能挑戰 topic-D 現有假設的素材（GitHub issue #172，若 topic-D 原先假設『宣告式白名單=實際強制』會被此發現直接挑戰）——topic-D 已驗證並採納，形成互補而非牴觸。
- **Challenges received:** 無直接 challenge 收到（topic-A/C/D 皆為 Finding/Overlap/CONVERGING 類訊息，無反駁）。

## Unresolved

- B-009 的具體崩跌數字（78%→13.62%、64%→20%）僅為二手摘要，標記 LOW confidence，需後續直接開啟原始論文（LongFuncEval, arXiv 2505.10570）核對方法論與樣本規模。
- B-013（MCP 企業授權規格問題）與 B-014（allowed_callers）皆未能直接開啟官方/一手來源全文（皆遭代理 403 阻擋），僅透過 WebSearch 摘要交叉比對確認，建議之後有機會應直接驗證。
- 本專案（POC）是否該現在就導入 `ToolMessage(status="error")` 或等效的結構化錯誤欄位、以及是否該把工具描述擴充到官方建議的 3-4 句標準，是具體可執行但尚未實作的建議，留待專案團隊決策（非研究層面的 unresolved，是工程決策層面的 open item）。
