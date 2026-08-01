# Harness 架構分層：模型與使用者之間到底有幾層 — Research Synthesis

> 研究系列 Backlog 01｜2026-07-31
> 研究團隊：scout（來源池）＋ topic-A（system prompt 組裝／harness 解剖）、topic-B（工具層）、topic-C（context 管理／記憶）、topic-D（權限／sub-agent），Opus sweep（覆蓋度檢查、補洞、框架）
> 本篇提出的 **L0–L9 分層骨架**將被後續 25 篇研究引用。骨架的正確性優先於篇幅。

---

## 執行摘要

這輪研究要回答的問題是：在 Claude Code、ChatGPT、Cursor 這類正式上線的 agent harness 裡，模型與使用者之間實際存在哪些架構層。四位 specialist 分頭調查 system prompt 組裝、工具層、context window 管理與記憶、權限控制與 sub-agent orchestration，共產出 78 條帶來源與 confidence 標記的 claims。結論是：**這中間至少有十層，而且最底下那一層不在 harness 開發者的控制範圍內。** Anthropic API 只要帶 `tools` 參數，就會自動組出「固定工具說明 → 工具 JSON Schema → 使用者自訂 system prompt → 工具設定」的模板（[官方文件](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)，HIGH），而 Sonnet 5/4.6/4.5、Haiku 4.5 還會被自動注入 `<budget:token_budget>` 與 `<system_warning>` 標籤（[官方文件](https://platform.claude.com/docs/en/build-with-claude/context-windows)，HIGH）。也就是說，「分層」不是從 harness 開始的，是從 API 契約層就已經開始了——你寫的 system prompt 從來不是第一句話。

三個橫跨全部十層的張力貫穿本篇。**第一，每一層都在同一個 context window 上競價，而且各層的節省手段互相衝突。** Tool Search 讓工具定義不進前綴以省 55k tokens 且不破壞 cache（[Anthropic](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)，HIGH）；compaction 省 token 卻必然打斷 cache 前綴、迫使下一輪用 1.25×–2× 價格重建（[prompt caching 文件](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)，HIGH）；system-reminder 為了保住 cache 而改注入使用者訊息，代價是實測吃掉 15%–50% 的 context（[issue #17601](https://github.com/anthropics/claude-code/issues/17601)，HIGH）。**cache 友善與 context 節省是方向相反的目標**，L4 與 L6 對同一個張力給了相反的解。**第二，也是本輪最有價值的發現：架構圖上畫的層，不等於 runtime 真的攔得住的層。** topic-D 挑戰 topic-A 的「7 層獨立安全防線」說法，端出 [claude-agent-sdk-typescript issue #172](https://github.com/anthropics/claude-agent-sdk-typescript/issues/172)（OPEN，2026-02-12，經直接 fetch 驗證，HIGH）：sub-agent 的工具白名單／黑名單在 CLI spawn child process 時**完全沒有被強制執行**。topic-A 據此下修了原 claim 的信心評級。這個「宣告 ≠ 強制」模式在本研究中至少出現六次，橫跨 L2、L3、L4、L7，是一種獨立於「模型被說服做壞事」之外的失敗模式類別。**第三，資訊透明度本身就是發現。** Claude Code 因原始碼外流與逆向工程社群活躍，可被追蹤到 prompt 片段等級與 246+ 個版本的演進；Cursor 只有互相轉載的外流文本；ChatGPT 只有官方模糊帶過的產品文案。三者的架構其實高度收斂，落差在可驗證性。

本輪也有兩處證據互相打架，我們選擇不調和。**Multi-agent 的成本效益**：Anthropic 自家 orchestrator-worker 研究系統以 15 倍 token 換 90.2% 提升（MEDIUM，且原文已逾 12 個月），但某客服案例是 2 倍成本換 2.1 個百分點（LOW），另有窄領域事件應變宣稱 100% vs 1.7%（LOW）。三筆資料的任務類型、評測基準、證據品質完全不同，沒有任何一份研究同時涵蓋兩種場景。「視任務類型而定」是合理的調和假說，但它是對三筆不相容資料的事後解釋，本身沒有直接證據。**system-reminder 的帳**：效益（保 cache）與代價（15–50% context、malware 警告 10,040 次觸發 0 次真陽性）兩邊都有具體證據，可以同時為真。值得注意的是兩邊的證據強度不對稱——代價側是 HIGH（mitmproxy 實測流量），效益側是 MEDIUM（機制推論，Anthropic 從未公開說明設計意圖，issue 被關為 not planned 且無官方回應）。**證據較弱的一側恰好是對廠商有利的一側**，讀者應自行權衡，本篇不代為下「這是必要之惡」的結論。

對 `harness-agent-poc` 的建議路徑很明確，而且順序很重要。**先修正確性，再補層。** sweep 階段直接讀了 repo 程式碼，發現三件 specialist 網路研究看不到的事：(1) `compact.py` 的壓縮結果從未寫回 graph state（`agent.py:72` 賦值給區域變數，`agent.py:88` 只回傳 `[response]`，而 `add_messages` 是 append reducer），所以每次超過 50K 之後**每一輪都會重跑一次全量 LLM 摘要卻永遠不會真的變短**；(2) `edit_file` 完全繞過 HITL（`filesystem.py:205`），而 `prompts/system.md:17` 與 `memory.py:33` 都在主動指示模型用 `edit_file` 寫檔——harness 的 prompt 層親手把寫入流量導向沒有防護的那條路；(3) 壓縮摘要以 `HumanMessage` 回填（`compact.py:54`），把源自檔案內容的資訊提升到「使用者說的話」這個權限等級。這三件都不是「缺一層」，是既有層沒有真的生效——正是本篇主軸失敗模式在自家 repo 的翻版。修完之後，`pyproject.toml` 已宣告的 `langchain>=1.2.14` 與 `langchain-anthropic>=1.4.0` 裡就有 `ContextEditingMiddleware`、`SummarizationMiddleware`、`HumanInTheLoopMiddleware`、`AnthropicPromptCachingMiddleware` 等現成實作，多數缺口不需要自己造。完整 backlog 見第 5 節。

---

## 方法論限制（請先讀這段）

**本輪研究的執行環境對外 HTTPS 走 agent proxy，大多數非 Anthropic 官方網域的直接 `WebFetch` 被 403 擋下。** 受影響的來源包括但不限於：Anthropic 工程部落格（anthropic.com）、VS Code 官方文件、OpenAI Codex 文件、Cursor 官方文件、OWASP、Trail of Bits、arXiv 全文（abs 與 pdf 皆然）、docs.langchain.com、reference.langchain.com、以及多篇技術部落格。這代表：

- **凡引用非 Anthropic 官方文件與 GitHub 的論點，多數只透過 WebSearch 的搜尋引擎摘要間接取得，未能逐字核對原文。** topic-A 與 topic-D 都明確標註了這一點；sweep 階段重試 docs.langchain.com 與 reference.langchain.com 同樣 403。
- **證據強度必須據此打折。** 本文保留每一條 claim 的 confidence 標記（HIGH／MEDIUM／LOW），讀者應把 MEDIUM 讀成「方向可信、細節未核實」，把 LOW 讀成「單一來源或二手轉述，引用前需自行溯源」。
- **完成逐字核實（直接 fetch 原文成功）的來源只有：** Anthropic platform.claude.com 系列文件與 cookbook、code.claude.com 的 sub-agents 文件、以及 GitHub 上的 issue 與 repo。本文中標為 HIGH 的 claim 幾乎全部來自這三類。
- **一個重要的例外是 repo 本身。** 第 5 節對 `harness-agent-poc` 的所有陳述都來自 sweep 階段直接讀取的原始碼，附檔案路徑與行號，是本文證據強度最高的部分——它們不受 proxy 限制。

此外有兩個本輪確定**填不起來**的缺口，已列入待答問題：Governance Decay 論文（arXiv 2606.22528）的 0%→30% 數字無法核對全文方法論；以及**沒有任何一家廠商（Anthropic、OpenAI、Anysphere）公開說明自家 system prompt 如何做版本控管與回歸測試**——這一項經多輪搜尋後判定為產業普遍不揭露，而非搜尋失敗。

---

## 1. 問題定義

當使用者在 Claude Code 裡打一行字，到模型真正看到 token 之間，發生了什麼？

直覺答案是「system prompt 加上使用者訊息」。這個答案錯得相當徹底。實際上使用者輸入的那行字，在抵達模型時通常已經是**整個請求裡靠後的一小部分**，前面疊了固定的 API 模板、工具 schema、靜態身分 prompt、專案指令檔、記憶內容、環境資訊，中間還被塞進了 UI 不顯示的行為提醒，而它能觸發的動作在送出之前已經先過了一道權限判定。

這裡的核心工程問題不是「怎麼寫好 prompt」，而是**「哪些資訊在哪一層被組進去、由誰決定、失敗時怎麼表現」**。VILA-Lab 對 Claude Code 的逆向分析用一句話概括了這件事的重量：「98.4% Infrastructure, 1.6% AI」——agent loop 本身就是一個 while 迴圈，護城河在模型碰不到的確定性基礎設施（[Dive-into-Claude-Code](https://github.com/VILA-Lab/Dive-into-Claude-Code)，MEDIUM，非官方逆向工程來源）。Anthropic 官方對 harness 的定義也指向同一處：harness 是圍繞 agent 的支援基礎設施，核心工作是 **context engineering**——決定每次呼叫模型時該納入或排除哪些資訊（[Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)，2025-11-26，MEDIUM，原文 403 未能逐字核實）。

因此本篇要建立的，是一套**可以拿來定位任何 harness 設計決策的座標系**：給定一個問題（「工具太多怎麼辦」「記憶要放哪」「權限一次授權多大」），能明確指出它屬於哪一層、那一層的業界做法有哪些、以及那一層失效時長什麼樣子。

三個橫切主題貫穿全篇：

1. **Context 是稀缺資源。** 每一層——prompt、工具定義、記憶、sub-agent 回傳——都在搶同一個 context window。各層的設計取捨最終都回到「這值不值得佔 token」。Anthropic 官方文件本身就把 **context rot**（token 數增加導致準確率與回憶能力下降）列為 context 管理的核心動機而非邊緣案例（[context windows 文件](https://platform.claude.com/docs/en/build-with-claude/context-windows)，HIGH）。
2. **信任邊界。** 工具輸出、檔案內容、web 內容都是不可信輸入。權限層與 prompt 層對此的責任怎麼劃分，是本篇最後收斂出的 defense-in-depth 分工。
3. **狀態放哪。** prompt 內 vs 檔案 vs 外部儲存，是各家分層差異的主軸。

---

## 2. 業界做法：L0–L9 分層骨架

本節是全篇主軸。骨架由 topic-A 整合提出（A-018），依據為 VILA-Lab 的 5 層模型、arXiv《Inside the Scaffold》的 3 層分類法、OPENDEV 論文的三大工程挑戰、noelzappy 的可快取前綴／後綴模型、以及 Anthropic 官方「harness = context engineering」定義，並經與 topic-B/C/D 交叉驗證。

**關於這個骨架本身的誠實聲明（A-018 標記 LOW）：** 這是分析性框架，不是可被單一來源驗證的事實。不同來源對層數本來就沒共識（3 層／5 層／10 層都有），對「邊界該畫在哪」也有分歧——例如記憶與 context 管理是否該分開、sub-agent 是獨立一層還是工具層的特例。**後續研究引用時應視為「一個站得住腳但非唯一正確」的參考框架，不是業界標準。** 我們選擇 10 層的理由是：每一層都有一個**獨立的失效模式**與**獨立的設計決策空間**，合併任兩層都會使某個真實存在的取捨消失。

| 層 | 名稱 | 解決什麼問題 | 誰控制 |
|---|---|---|---|
| L0 | 模型 API 契約層 | 工具說明模板、context-awareness 自動注入 | 模型廠商（開發者不可改） |
| L1 | 靜態身分／行為層 | 可全域快取的 system prompt 前綴 | Harness 開發者 |
| L2 | 環境與專案上下文層 | CLAUDE.md／AGENTS.md 階層、cwd/git 狀態 | 使用者與專案 |
| L3 | 工具層 | schema、命名空間、MCP、延遲載入 | Harness 開發者 |
| L4 | Context window 管理層 | compaction、tool-result clearing、cache 邊界 | Harness 開發者 |
| L5 | 長期記憶層 | 跨 session 持久化 | Harness ＋使用者 |
| L6 | 對話中途動態注入層 | system-reminder、system_warning | Harness（對使用者隱藏） |
| L7 | 權限／sandbox 層 | deny-first 判定、傷害半徑控制 | Harness ＋使用者 |
| L8 | 子代理 orchestration 層 | 任務分派、context 隔離、摘要回傳 | Harness |
| L9 | 應用／UI 層 | CLI/SDK/IDE、hooks、diff 呈現 | Harness |

### L0 — 模型 API 契約層

**解決的問題：** 讓模型知道「工具」這個概念存在、以及自己還剩多少預算。這一層的存在本身通常被開發者忽略，因為它不出現在任何你寫的程式碼裡。

**業界做法。** According to [Anthropic Define Tools 官方文件](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)（2026，經直接 WebFetch 逐字核實，**HIGH**），只要請求帶 `tools` 參數，API 就會自動組出固定模板：

```
In this environment you have access to a set of tools...
{{ FORMATTING INSTRUCTIONS }}
Here are the functions available in JSONSchema format:
{{ TOOL DEFINITIONS IN JSON SCHEMA }}
{{ USER SYSTEM PROMPT }}
{{ TOOL CONFIGURATION }}
```

注意順序：**工具 schema 在使用者自訂 system prompt「之前」**（A-001／B-010，兩位 specialist 獨立發現同一份文件並互相核實）。這對成本模型有直接意涵——工具描述的 token 不是「附加」的，它是固定前綴的一部分，因此也是 prompt cache 邊界的一部分。

同一層還有開發者完全不能關閉的自動注入。According to [context windows 官方文件](https://platform.claude.com/docs/en/build-with-claude/context-windows)（**HIGH**，A-002／C-021），Sonnet 5/4.6/4.5 與 Haiku 4.5 的每次請求都會被塞入 `<budget:token_budget>200000</budget:token_budget>`，且每次工具呼叫後追加 `<system_warning>Token usage: X/Y remaining</system_warning>`；文件明講「你永遠不用自己送這些標籤」。有意思的是 Opus 4.7 以後的 Opus 模型、Fable 5、Mythos 5 **不會**收到這組注入，改成開發者自行設定的 beta task budgets——同一家公司在不同模型線上對「自動注入 vs 開發者顯式控制」做了相反選擇，這本身就是一個分層設計的取捨案例。

**[SWEEP ADDITION] LangChain 對應：** 沒有。L0 對任何框架都是不可見的，這正是它值得單獨成一層的理由——**你在 L1 做的所有 token 預算計算，如果沒把 L0 的固定模板算進去，就都是錯的。**

### L1 — 靜態身分／行為層

**解決的問題：** 給模型一個穩定的身分與行為規則，且這段內容必須能被 prompt cache 完整命中。

**業界做法。** According to [noelzappy/claude-code-system-prompts](https://github.com/noelzappy/claude-code-system-prompts) 與 [Piebald-AI/claude-code-system-prompts](https://github.com/Piebald-AI/claude-code-system-prompts)（後者直接從編譯後 JS bundle 萃取字串，2026-07-24，A-005／A-006／A-007，**MEDIUM–HIGH**），Claude Code 的 system prompt **不是單一字串，而是 500+ 條件載入的片段**，歸為六類：Core Identity、Orchestration（多工作者 4 階段流程）、Specialized Agents（verification／exploration／agent-creation／terminal）、Security & Permissions（2 階段安全分類器）、Utilities（session 搜尋、記憶選取、進度摘要）、Context Management（壓縮、session 回顧）。

組裝上採「**globally cacheable prefix**（靜態身分與行為規則）＋ **session-specific suffix**（動態環境細節、記憶內容、model overrides）」。這個切法的唯一理由就是 prompt caching：只要前綴不變就能重複命中，環境資訊等易變內容放到後綴，不拖累命中率。

Piebald-AI 的 CHANGELOG 追蹤了自 v2.0.14 起 246+ 個版本、至 v2.1.220（2026-07-24）的 prompt 變更，涵蓋 27 個內建工具描述、Plan/Explore/Task 等子代理 prompt，每段附精確 token 數（A-007，**HIGH**）。實務意涵：**在 Claude Code 這種產品裡，「system prompt 版本控管」實質上等同於「產品版本控管」的一部分，而不是獨立的 prompt-ops 流程。**

### L2 — 環境與專案上下文層

**解決的問題：** 讓 agent 知道「這個專案」的規則，而不只是「這個產品」的規則。

**業界做法（三個真實系統對照）。**

**Claude Code**：CLAUDE.md 依 enterprise config → user global → project shared → project rules → local private config 五層優先序疊加，支援巢狀 `@include`（最大深度 5）（A-006，**MEDIUM**）。VILA-Lab 給出方向一致但層數略異的說法（「4-level hierarchy: managed, user, project, local」），並提出一個關鍵區分：**CLAUDE.md 等專案指令是作為「使用者 context」注入（模型機率性遵從），而非放進 system prompt（確定性）**（A-009，**MEDIUM**）。這解釋了一個實務上人人踩過的坑——為什麼專案層規則有時會被模型「忽略」：它在架構上就不是「指令」層級，是「建議」層級。

**ChatGPT**：分層為 OpenAI 隱藏的 pre-prompt → Custom GPT 指令 → 使用者 Custom Instructions（上限 1500 字元，每次新對話被重寫成一段簡短 system message）→ 使用者訊息（A-015，**LOW**，第三方部落格，部分來源帶記憶工具推銷動機）。

**Cursor**：外流的 system prompt 顯示其特徵是**每次訊息自動附加使用者目前狀態**（開啟檔案、游標位置、最近瀏覽、編輯歷史、linter 錯誤），並明確指示模型「絕不要把程式碼直接輸出給使用者，一律用編輯工具落地」（A-014，**LOW**，外流未經官方證實；多篇報導內容高度重疊，更可能是互相轉載同一份文本而非獨立驗證）。

**[SWEEP ADDITION] L2 已經在標準化，這件事四位 specialist 都沒提到。** According to [Linux Foundation 新聞稿](https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation) 與 [OpenAI 公告](https://openai.com/index/agentic-ai-foundation/)（2025-12，**MEDIUM**，WebSearch 摘要），**Agentic AI Foundation（AAIF）成立，OpenAI 的 AGENTS.md 與 Anthropic 的 MCP 雙雙捐入 Linux Foundation 治理**。AGENTS.md 現由 AAIF 託管，被 Codex、Cursor、Copilot、Gemini CLI、Aider、Windsurf、Zed 等 20+ 工具原生讀取，採用倉庫數 60,000+（**MEDIUM**，二手來源，數字未經一手核實）。這對本骨架的意涵是：**L2 是第一個跨廠商收斂的層**，而 L1（各家自己的身分 prompt）與 L6（各家自己的注入機制）仍然完全私有。如果你在設計 harness 的專案指令層，2026 年的預設選擇應該是 AGENTS.md 而不是自訂格式。

**[SWEEP ADDITION] 而 L2 也是「宣告 ≠ 載入」的第一個案例。** 多份 2026 年的 Cursor 指南指出：**`.cursorrules` 格式只在 Chat 與 Tab（自動補全）情境被讀取，在 Agent mode session 中不會被載入**（**LOW**，多篇二手指南交叉印證，無官方文件核實）。如果屬實，這意味著大量使用者維護了一份自以為在約束 agent、但 agent 從來沒看到的規則檔——**這與 L7 的權限白名單未被強制執行是同一種失敗模式，只是發生在 context 層而非權限層**。詳見第 4 節。

### L3 — 工具層

**解決的問題：** 模型怎麼知道有哪些工具、怎麼選對、選錯時怎麼恢復；以及工具變多時 context 怎麼不爆。

**工具描述品質是最重要的單一因素。** According to [Anthropic Define Tools 文件](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)（**HIGH**，B-001），工具描述品質被明確列為「by far the most important factor in tool performance」。規範是：至少 3–4 句話，涵蓋工具做什麼、何時該用／不該用、每個參數的意義、以及重要限制。官方給了對照範例——差的 `"Gets the stock price for a ticker."` vs 好的（說明 ticker 必須是哪個交易所的合法代號、回傳幣別、以及「不會」回傳什麼）。

這不只是廠商自我背書。同行評審的 [Trace-Free+](https://arxiv.org/abs/2602.20426)（Intuit AI Research，2026-02，**MEDIUM**，僅取得摘要）在 150+ 候選工具的情境下，用 curriculum learning 改寫工具描述，讓準確率劣化幅度減少 **29.23%**，並在 Stable-ToolBench 上讓平均查詢層級成功率提升 **60.89%**（B-017）。

**工具數量有一個官方承認的門檻。** Anthropic 自己的文件寫明「tool selection accuracy degrades once you exceed 30–50 available tools」（**HIGH**，B-006）；一個典型的 5-MCP-server 配置（GitHub + Slack + Sentry + Grafana + Splunk）在使用者輸入任何東西之前就吃掉約 **55k tokens** 的工具定義（**HIGH**，B-005）。

**業界對此的產品化解法是 Tool Search Tool**（`tool_search_tool_regex_20251119` / `..._bm25_20251119`，2025-11-19 上線，**HIGH**，B-005）：開發者在工具定義上標記 `defer_loading: true`，這些定義**不進入 system prompt 前綴**（因此不影響 prompt cache），只在 Claude 主動搜尋命中後才展開。官方數字是典型配置省 85%+（55k → 數千）。官方也給了明確的「何時該用」判準：工具數 ≥10、工具定義 >10k tokens、或聚合 200+ 工具的多個 MCP server；**反之工具數 <10 且每次都會用到全部工具時，不用 tool search 才是對的**。

**但工具層的 context 佔用主要不是來自定義。** 在 Anthropic 官方 cookbook 的研究 agent 範例中，三個工具的定義只佔約 1–2K tokens，而**檔案讀取結果佔了 96.3%（約 322,946 tokens）**（**HIGH**，B-016）。這是本骨架 L3 與 L4 邊界的關鍵：tool search 解決的是「工具*定義*要不要一開始就佔位」，tool-result clearing 解決的是「工具*結果*用完後要不要留著」。**兩者解決的是不同瓶頸，選錯機制等於白做。**

**錯誤語意有明確官方規範。** `tool_result` 可帶 `is_error: true`，且錯誤訊息要「可操作」——官方拿 generic 的 `"failed"` 對比 `"Rate limit exceeded. Retry after 60 seconds."`，明說後者「給 Claude 恢復或調整所需的脈絡，而不用用猜的」（**HIGH**，B-003）。文件另指出一個行為現象：參數缺漏時 Claude 通常會自行重試 2–3 次修正後才向使用者道歉——**可恢復性不只取決於錯誤訊息寫得好不好，也取決於系統容許幾輪修正嘗試**。

**MCP 在企業規模下有規格層級的問題**（B-013，**MEDIUM**，原文 403，多篇部落格摘要交叉比對）：授權規格把 MCP server 同時當成 resource server 與 authorization server，與需要 session/token 撤銷狀態的企業 IdP 實務衝突；以及經典的 **confused deputy**——透過 MCP server 執行動作的使用者可能因 server 本身權限較高而取得原本不該有的存取權。

**[SWEEP ADDITION] LangChain 對應：** `LLMToolSelectorMiddleware` 用一個快速模型在主呼叫前從工具註冊表篩出相關工具，是 tool search 的框架側等價物（[Prebuilt middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in)，**MEDIUM**，403 未逐字核實）。

### L4 — Context window 管理層

**解決的問題：** 對話總會超過預算。要丟什麼、怎麼丟、丟的時候會不會順手把 cache 也砸了。

**業界標準是兩層，不是一層。** Anthropic 明確把兩個機制分開（**HIGH**，C-006／C-002）：

1. **Tool-Result Clearing**（`clear_tool_uses_20250919`）——純機械式地把舊 `tool_result` 內容替換成 `"[cleared to save context]"`，保留 `tool_use` 呼叫記錄，**零推論成本**。可設 `keep`（保留最近 N 個結果）、`exclude_tools`（例如排除 memory tool）、`clear_at_least`（至少要清多少才值得動作）。實測：335,279 → 173,137 tokens（48% 減少）；topic-B 另一組數字為 128,740 → 43,060（67%，keep=1）。
2. **Compaction**（`compact_20260112`，beta header `compact-2026-01-12`）——LLM 摘要，處理對話語意。觸發門檻**預設 150K tokens、最低可設 50K**，可用 `instructions` 完全覆寫預設摘要 prompt。實測：335,279 tokens 的研究對話壓成約 2,783 tokens 的摘要。

**設計邏輯是：先用零成本的機械清除處理「可重新取得」的工具輸出，再用有成本的 LLM 摘要處理真正需要語意壓縮的對話。**

**[SWEEP ADDITION] 關於 `clear_tool_uses` 預設 trigger 值的矛盾，本 sweep 判定為引用層級的誤會。** topic-C 引用 cookbook 範例的 30K–50K，topic-B 稱預設 100K，雙方都標為未解決。實際上：LangChain 的 `ContextEditingMiddleware`（`ClearToolUsesEdit` 策略，文件明確宣稱對齊 Anthropic `clear_tool_uses_20250919`）預設 trigger 為 **100,000 tokens**，Anthropic context-editing 文件的標準範例同樣使用 `{"type":"input_tokens","value":100000}`（**MEDIUM**，WebSearch 摘要，原文 403）。cookbook 的 30K–50K 應是為了在小型 demo 中觸發而刻意調低的示範值。**兩位 specialist 都沒錯，但都各自引用了不完整的證據。**

**Compaction 的資訊損失是系統性的，不是隨機的。** Anthropic 自己的 cookbook 用具體 probe 測試（**HIGH**，C-004）：3 個「高層次事實」（例如 C. elegans 壽命中位數 18 天）**100% 保留**；3 個「晦澀細節」（附錄表格裡的 I-squared 值 61、效應量 55、PhenoAge 比值 0.72）**0% 保留**。這與多篇 2026 業界文章的描述一致：「消失的通常是第二輪給的限制條件、第八輪確認的精確值」，而且「**失敗看起來不像失敗**——對話仍在跑，token 數持續下降」。

**Prompt caching 讓「縮短對話」不再等於「省錢」。** According to [prompt caching 官方文件](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)（**HIGH**，C-016／C-017／C-018）：

- TTL 預設 5 分鐘（ephemeral），可付費延長至 1 小時；TTL 內每次被讀取都會免費刷新。
- 定價：5 分鐘 cache write = 1.25× 基礎 input 價；1 小時 = 2×；**cache read = 0.1×**。
- 最小可快取前綴長度依模型從 512 到 4,096 tokens 不等（Opus 5 最低 512，Haiku 4.5 需 4,096）；短於此長度**不會報錯，只是靜默不快取**，只能靠 `cache_creation_input_tokens` / `cache_read_input_tokens` 驗證。
- **失效規則是階層式的：`tools → system → messages`。** 改工具定義 → 三層全失效；改 web search／citations／speed 設定 → system + messages 失效；改 `tool_choice` 或圖片 → 只有 messages 失效。

最關鍵的一句官方陳述：「**快取的 prompt 前綴仍然完整佔用 context window：prompt caching 改變的是你付多少錢，不是它算不算 token。**」這代表 context 管理從此是二維問題——token 數，以及**打斷快取前綴的代價**。過早或過度頻繁的 compaction 即使降低 token 數，也可能因強迫下一輪以 1.25×–2× 價格重建 cache 而**提高**實際成本。這正是 `clear_at_least` 參數存在的理由。

**[SWEEP ADDITION] LangChain 對應：** `ContextEditingMiddleware` + `ClearToolUsesEdit`（對齊 `clear_tool_uses_20250919`，預設 trigger 100k，參數含 `keep`／`clear_tool_inputs`／`exclude_tools`／`placeholder`，且刻意設計為 model-agnostic）；`SummarizationMiddleware`（參數 `max_tokens_before_summary`、`messages_to_keep` 預設 20、`trim_token_limit`）；`AnthropicPromptCachingMiddleware`（自動在 system message 最後一個 content block 與最後一個 tool definition 打 `cache_control`，type 僅支援 `ephemeral`，ttl 預設 `5m`）。三者皆為 `langchain>=1.x` / `langchain-anthropic` 的內建件（**MEDIUM**，皆為 WebSearch 摘要，docs.langchain.com 與 reference.langchain.com 均 403）。**這代表 L4 的業界標準兩層設計，在 LangChain 生態裡是「裝上去」而不是「寫出來」的。**

### L5 — 長期記憶層

**與 L4 的差異在於：L4 是「這一輪對話內的工作記憶」，L5 是「跨對話的長期記憶」。** 兩者常被混為一談，但失效模式完全不同——L4 失效是資訊被摘要掉，L5 失效是資訊過期後主動誤導。

**官方 memory tool 是 pull 模式。** `memory_20250818` 是獨立於一般 file-edit 工具的專用工具，protocol 明確要求 agent「先看 `/memories` 目錄再做任何事」，支援 view/create/str_replace/insert/delete/rename 六種操作，內建路徑穿越防護（**HIGH**，C-008）。跨 session 實測效益明顯：無記憶時 Session 2 要重讀 4 份文件（~108K tokens），有記憶時只需載入一份 ~3K tokens 的摘要檔。

**2026 年出現明確的 markdown-first 趨勢，但這是 trade-off 不是免費午餐**（C-010／C-011，**MEDIUM**，此表述經 topic-A 挑戰後由 topic-C 修正）。Claude Code、Manus、OpenClaw 都用 markdown 而非向量資料庫作記憶主體，理由是可檢視、可 diff、可攜、git-native。但代價是**仍然需要一個選擇機制**：VILA-Lab 觀察到 Claude Code 的做法是「LLM 掃描 memory 檔案標頭、最多選 5 個相關檔案，無 embedding、無向量相似度」——這只是用 LLM 呼叫成本取代向量基礎設施成本，不是真正免費。Milvus/zilliztech 的分析給出更具體的量化限制：**grep-based 檢索（甚至不是 LLM 掃描）加上 200 行索引上限**，在專案歷史累積後造成擴展性瓶頸（同標題另有一篇獨立 dev.to 文章印證）。業界正收斂到的模式是「**markdown 為 source of truth、向量索引為可隨時從 .md 重建的衍生索引**」——不是二選一，而是分層。

**per-user vs per-project 的業界慣例是三層**（C-014，**MEDIUM**）：Global（`~/.claude/`，跨所有專案，個人偏好）、Project（隨 repo 走，團隊共享）、Auto Memory（每個 git repo 一個獨立目錄，agent 自動記筆記）。優先序：System instructions > Global CLAUDE.md > Project CLAUDE.md > CLAUDE.local.md > Auto memory > 對話歷史 > 已壓縮摘要。

**[SWEEP ADDITION] ChatGPT 的記憶分層現在有官方來源了。** topic-A 只找到第三方部落格（A-015，LOW）。According to [OpenAI Help Center](https://help.openai.com/en/articles/8590148-memory-faq) 與 [How does "Reference saved memories" work?](https://help.openai.com/en/articles/11146739-how-does-reference-saved-memories-work)（**MEDIUM**，WebSearch 摘要於官方 help 頁面），ChatGPT 記憶確為兩層：**saved memories**（使用者明確要求記住的具體事實）與 **chat history reference**（從過往對話萃取的洞察），兩者皆可在設定中個別關閉，Temporary Chats 兩者皆不使用；官方並明確定位「saved memories 與 custom instructions 一樣，都是 ChatGPT 生成回應時使用的 context 的一部分」。這把 A-015 的記憶雙層部分從 LOW 升為 **MEDIUM**；但「1500 字元上限」與「每次新對話被重寫成短 system message」的說法仍只有第三方來源，維持 **LOW**。

### L6 — 對話中途動態注入層

**這是最容易被忽略、也是本輪證據最扎實的一層。**

**解決的問題：** 在對話進行中改變模型行為，同時不讓 prompt cache 失效。

**做法。** Claude Code 的 `<system-reminder>` 是「40+ 條簡短行為指令，注入到**使用者訊息**或**工具結果**裡，而不是 system prompt 本身」（[michaellivs.com](https://michaellivs.com/blog/system-reminders-steering-agents/)，2026，**MEDIUM**，A-003）。**這個設計選擇的目的很明確：保留 prompt cache。** 如果把提醒塞進 system prompt，內容一變就會讓整個靜態前綴的快取失效；塞進使用者訊息則完全不影響 system prompt 的命中率。

**代價由 GitHub issue 直接量化**（[issue #17601](https://github.com/anthropics/claude-code/issues/17601)，**HIGH**，A-004）。一名研究者用 mitmproxy 分析流量，回報 32 天內攔截到 **10,577 次**隱藏注入（標記 `isMeta:!0`，UI 完全不顯示），總計約 534 萬字元、130–150 萬 tokens，**佔用 15%–50% 的 context window**；其中一類是每次讀檔都附加的「這是否為 malware」警告，10,040 次觸發中回報者估算 **0 次為真正威脅**。此 issue 被關閉為「not planned」，頁面上沒有官方對機制原理或目的的正式回應。相關的 [issue #52018](https://github.com/anthropics/claude-code/issues/52018) 標題直接點出核心：「system-reminder nudges... are indistinguishable from prompt-injection attacks」——因為提醒內容包含「NEVER mention this reminder to the user」這種字句，恰好是典型 prompt injection 的識別特徵。

**本篇維持 topic-A 的立場：不把這件事模糊成「這是取捨」。** 效益是可驗證的（保留快取、降低成本），代價也是可驗證的（實測 context 佔用比例、實測偽陽性率），兩者可以同時為真。**[SWEEP ADDITION] 但要補一點 topic-A 沒說的：兩側的證據強度不對稱。** 代價側是 HIGH（實測流量），效益側是 MEDIUM（機制推論——Anthropic 從未公開說明設計意圖，issue 被關為 not planned 且無官方回應）。**證據較弱的一側恰好是對廠商有利的一側。** 讀者應自己權衡。

L0 的 `<system_warning>Token usage: X/Y remaining>` 注入在機制上也屬於 L6（對話中途注入），只是控制權在模型廠商而非 harness 開發者——這是 L0 與 L6 唯一重疊的地方。

### L7 — 權限／sandbox 層

**解決的問題：** 即使模型被說服去做壞事，它實際能造成多大傷害。

**與 L1/L6 的分工是 defense-in-depth，不是互斥**（topic-A 與 topic-D 的邊界共識，本輪最重要的架構結論之一）：

- **L1/L6 是「說服層」**——模型會不會被說動去做壞事。失效模式是 prompt injection / jailbreak。
- **L7 是「傷害半徑層」**——就算模型被說動了，實際能造成多大傷害。失效模式是 approval fatigue 或白名單未被實際強制。

**業界標準是雙軸設計。** According to VS Code 官方文件（**MEDIUM**，原文 403，WebSearch 摘要）：「The sandbox defines technical boundaries, while the approval policy decides when the agent must stop and ask before crossing them.」OpenAI Codex 是這個模式的具體實例（D-002，**MEDIUM**）：三種 sandbox mode（read-only／workspace-write／danger-full-access）與三種 approval policy（untrusted／on-request／never）**正交組合**；workspace-write 預設關閉網路存取，需顯式設 `network_access = true`，且即使開了網路，`.git`／`.codex`／`.agents` 仍維持唯讀。

**Cursor 的 allowlist 是反面教材，而且是官方自承的。** 官方文件明說「the allowlist is best-effort, **not a security boundary**. Determined agents or prompt injection might bypass it.」且有真實漏洞：Auto-Run + Allowlist 模式下，shell built-ins 可繞過 allowlist、透過環境變數毒化影響後續「已核准」指令的實際行為（Cursor 2.3 之前版本受影響，D-003，**MEDIUM**）。

**Sandbox 的隔離強度是光譜，不是二元的有／無**（D-006，**MEDIUM**，Northflank 技術部落格）：標準 Docker 共用 host kernel，default seccomp profile 只封鎖約 **44/300+** syscalls；gVisor 用 user-space kernel（Sentry process）攔截 syscall 大幅降低 host kernel 攻擊面，但 gVisor 自身實作變成新的信任邊界（有 bug 時逃逸向量只是換了地方）。業界對「執行不受信任程式碼」的建議是預設用 **Firecracker microVM 或 Kata Containers**，並明確主張**不應該用標準 Docker 處理不受信任的程式碼**。

**Approval fatigue 已被業界視為安全漏洞，而非 UX 抱怨**（D-004，**MEDIUM**）：Anthropic 數據顯示使用者實務上接受 **93%** 的權限提示；「Approval fatigue is a security bug because fatigue changes the decision—if a run asks for 40 approvals, the product has probably failed before the user clicks」，且「injected actions can slip through standard permission flows, even without the `--dangerously-skip-permissions` flag」。

**[SWEEP ADDITION] LangChain 對應：** `HumanInTheLoopMiddleware` 支援 `interrupt_on` 政策——每個工具可獨立設定，值為 `True`（允許全部決策型別）、`False`（自動核准）、或 dict（指定 `allowed_decisions`）；決策型別有四種：**approve（照原樣執行）／edit（修改後執行）／reject（附回饋拒絕）／respond（直接回覆）**。底層統一使用 LangGraph 的 `interrupt()` 原語：**暫停 graph、持久化 state、等待 `Command(resume=...)`**（[Human-in-the-loop 文件](https://docs.langchain.com/oss/python/langchain/human-in-the-loop)，**MEDIUM**，403 未逐字核實）。這比「一個 y/n 布林」精細一個量級，且因為走 checkpointer 持久化，核准可以跨 process、跨 UI、跨時間恢復。

### L8 — 子代理 orchestration 層

**解決的問題：** 某個子任務會把大量之後不會再引用的資訊灌入主對話。

**官方定位很明確。** According to [Claude Code sub-agents 官方文件](https://code.claude.com/docs/en/sub-agents.md)（**HIGH**，topic-D 直接 WebFetch 驗證，D-009）：每個 subagent 有**自己獨立的 context window**、自訂 system prompt、指定工具存取與獨立 permission mode；父 agent 只傳入任務描述、只收到最終摘要。官方建議是「當某個子任務會把大量之後不會再引用的資訊（搜尋結果、log、檔案內容）灌入主對話時使用」。

**因此 subagent 邊界同時是 context 管理裝置與權限限縮裝置**——這是 L8 之所以不能併入 L3 或 L7 的理由。

**[SWEEP ADDITION] L8 其實是 L4 的極限形式，這個關聯沒有 specialist 講出來。** topic-C 與 topic-D 交叉確認：subagent 是全新獨立 context window，無 prefix 繼承，因此 orchestrator→subagent 邊界原則上**無法重用 prompt cache**（C-023，**MEDIUM**）。把這一點與 L4 的成本模型接起來：compaction 是「打斷一次 cache 前綴換取 context 空間」，sub-agent 是「**完全拋棄 cache 前綴**換取一個乾淨的 context」。這解釋了 D-011 的 15× token 溢價為何這麼高——其中相當一部分不是推論成本，是**每個 subagent 都要付全額 cache write**。實務推論：**如果多 agent 要變便宜，突破口在跨 agent 的 cache 重用，而不在模型單價。**

**成本／品質的實證資料呈現顯著張力，本篇不予調和：**

| 來源 | 場景 | 結果 | Confidence |
|---|---|---|---|
| Anthropic 自家 orchestrator-worker 研究系統（D-011） | 窄領域研究（法律盡職調查、競爭情報、生醫文獻回顧） | 勝過單一 Claude Opus 4 **90.2%**，代價 **~15× token**；Anthropic 自己說「消費級問答無法吸收這個乘數」 | **MEDIUM**（原文 2025-06，逾 12 個月，STALE 風險；2026 年多篇文章仍引用同一數字） |
| 某客服部署案例（D-012） | 客服 | 多 agent **$47,000/月** vs 單 agent **$22,700/月**，準確率只差 **2.1pp**（94.3% vs 92.2%），多 **4.8 秒**延遲 | **LOW**（單一部落格轉述，無法排除簡化敘事） |
| 某事件應變研究（D-014） | 窄領域決策支援 | 可執行建議率 **100% vs 1.7%**，決策品質 +71.7% 且零變異；但通用 benchmark（AORCHESTRA、AdaptOrch）只有 **12–23%** 提升，且主要來自 topology routing 而非 peer collaboration | **LOW**（單一論文，未直接 fetch 全文） |

topic-D 提出的調和假說是「取決於任務是否為 breadth-first、可獨立平行拆解、且答案總量超過單一 context window 的探索型任務」。**本篇採納這個判準作為工程指引，但明確標註：它是對三筆不相容資料的事後解釋，沒有任何一份研究同時涵蓋兩種場景做對照，不得寫成「業界共識」。**

**結果聚合是最脆弱的環節，且無成熟解法**（D-013，**LOW**）：「即使每個 subagent 本身表現完美，設計不良的 synthesis 步驟仍會因無法處理不一致或部分結果而產生不可靠的最終輸出」。緩解方式包括對聚合輸出做 schema 驗證、衝突時用多數決／信心分數／upgrade 到人工審核；但目前主流仍仰賴 LLM 摘要本身（**有損、未校準**），尚未有成熟方法明確建模 subagent 結論的不確定性。

**OpenAI Agents SDK 提供兩種正交 pattern**（D-015，**MEDIUM**）：Manager Pattern（中央 orchestrator 把 sub-agent 當工具呼叫，只有 orchestrator 能跟使用者對話）與 Handoffs Pattern（peer agent 間直接轉移對話控制權）。**一個官方未明確承認的權限盲點：guardrails 在 handoffs 場景下只作用於鏈中第一個與最後一個 agent，中間的 handoff agent 缺乏 guardrail 覆蓋。**

### L9 — 應用／UI 層

**解決的問題：** 人怎麼看到 agent 在做什麼、怎麼介入。

這一層在本輪研究中覆蓋最薄（見第 4 節與待答問題）。已知的分層意涵：Cursor 把「展示程式碼」的責任從模型輸出轉移到編輯器 diff 呈現層，以節省 context window（A-014，**LOW**）——這是一個**用 UI 層設計換 context 預算**的具體案例，說明 L9 不只是外觀層，它會反向影響 L4 的預算。Claude Code 的 hooks 機制與 VILA-Lab 歸納的「UI 層（CLI/SDK/IDE）」屬於同一層（A-008，**MEDIUM**）。

### 學術界對這個骨架的獨立佐證

兩篇論文從完全不同的方法論路徑得到方向一致的分層（皆 **MEDIUM**，arXiv 全文 403，僅摘要）：

- [《Inside the Scaffold: A Source-Code Taxonomy of Coding Agent Architectures》](https://arxiv.org/abs/2604.03515)（2026-04，A-011）以 **13 個開源 coding agent scaffold 的原始碼**（釘選特定 commit）為對象，建立橫跨 12 維度、歸納為 **3 層**（控制架構、工具與環境介面、資源管理）的分類法。控制迴圈可拆成 5 種可組合原語（ReAct、generate-test-repair、plan-execute、multi-attempt retry、tree search），**13 個 agent 中有 11 個混用多種而非單一結構**。作者宣稱所有分類主張都溯源到檔案路徑與行號。
- [《Building Effective AI Coding Agents for the Terminal》](https://arxiv.org/abs/2603.05344)（2026-03，A-012）指出任何長時間執行的終端 coding agent 都必須解決**三個根本工程挑戰**：管理常態超出預算的 context window、在可執行任意 shell 指令時防止破壞性操作、在不壓垮 prompt 預算的前提下擴充能力。其 OPENDEV 系統的解法是 workload-specialized model routing、dual-agent（規劃/執行分離）、**lazy tool discovery**、漸進式 context 壓縮、跨 session 自動記憶。

**這三個挑戰恰好對應 L4、L7、L3。** 三個獨立來源（VILA-Lab 逆向工程、Inside the Scaffold 原始碼分類、OPENDEV 系統論文）以不同方法收斂到同一組邊界，是本骨架最強的支持證據——比任何單一來源的「N 層模型」都強。

---

## 3. 設計選項與取捨（含推薦）

本節給推薦與理由，不只列清單。每項推薦標明適用邊界。

### 3.1 system prompt：單體 vs 條件載入片段

| 選項 | 優點 | 代價 |
|---|---|---|
| 單一 markdown 檔 | 可讀、易 diff、易審核 | 無關內容永遠佔位；無法針對模式裁剪 |
| 條件載入片段（Claude Code：500+ 片段） | 只載入當下相關的行為規則 | 難以整體審視；版本控管等同產品版本控管 |

**推薦：從單體開始，但**一開始就**把「靜態身分／行為」與「動態環境／記憶」分成兩個字串拼接，且靜態段在前。** 理由：這是 prompt caching 的唯一硬需求（L4 的失效規則是 `tools → system → messages` 階層式的），成本近乎零，而且它讓你之後要拆成條件載入時不用重寫。不要一開始就做 500 片段——Claude Code 需要它是因為它要服務 27 個內建工具與 6 種子代理型別。

### 3.2 工具數量：全載入 vs 延遲載入

**推薦：**照 Anthropic 官方判準走，不要自己發明門檻。**工具數 <10 且每次都用到全部 → 不要引入 tool search**（官方明說標準做法更合適）；**≥10 個工具、或工具定義 >10k tokens、或接了多個 MCP server → 引入 defer_loading**。理由：tool search 本身有搜尋呼叫成本，在小工具集上是純損失。**但要有意識地延後，而不是遺漏**——差別在於你知不知道自己在哪個門檻的哪一側。

**同時無條件執行的兩件事（成本極低、收益不對稱）：** (1) 工具描述寫到官方建議的 3–4 句標準（涵蓋做什麼、何時該用／不該用、參數意義、限制）；(2) 一旦有第二個工具來源，立刻加服務前綴命名空間（`github_list_prs`、`fs_read_file`）。理由：B-017 顯示描述品質有量化因果效果（劣化幅度 -29.23%），而命名衝突是一旦發生就要改動所有呼叫端的那種問題。

### 3.3 context 管理：一層摘要 vs 兩層（clearing + compaction）

**推薦：兩層，且 clearing 先行。** 理由不是省 token，是**成本結構**：clearing 是零推論成本的機械操作，compaction 每次都要付一次 LLM 呼叫；而工具結果（可重新取得、佔 context 大宗、96.3%）與對話決策（不可重新取得、佔比小）本來就該用不同機制處理。把兩者混在一起丟給 LLM 摘要，等於用最貴的方法處理最不需要語意判斷的內容。

**推薦門檻：不要用官方允許的最低值。** compaction 門檻設 100K–150K（官方預設 150K）而非 50K，clearing 門檻設 100K（官方範例值）。理由：每次 compaction 都會打斷 cache 前綴，迫使下一輪以 1.25×–2× 重建；壓縮得越頻繁，cache 重建成本越可能吃掉省下的 token 成本。**並且一定要有 `clear_at_least` 等價的「至少省這麼多才值得動作」門檻**——沒有它，你可能為了省 5K token 而付出重建整個前綴的代價。

### 3.4 記憶：全量注入（push）vs agent 主動查詢（pull）vs 混合

| 選項 | 適用邊界 | 失效模式 |
|---|---|---|
| 全量 push 注入 | 記憶總量穩定 <2–3K tokens、且每次都相關 | 記憶一長就無條件吃 context；無法過濾 |
| Agent 主動 pull（官方 memory tool） | 記憶量大、相關性依任務變動 | 多一輪工具呼叫延遲；agent 可能不去查 |
| LLM 掃描檔頭選 N 個（Claude Code） | 中等規模、檔案有良好標題 | 有 cardinality 上限；選取本身有推論成本 |
| markdown 為真、向量為衍生索引 | 記憶量大且需語意檢索 | 索引與真實來源不同步 |

**推薦：小規模（<2–3K tokens）用 push，但一開始就設硬上限並在超過時警告。** 理由：push 在小規模下 cache 友善（內容穩定 → 前綴穩定），而 pull 要多付一輪工具呼叫。但**必須有上限**，因為 push 的失效方式是靜默的——記憶檔慢慢長大，某天開始吃掉 20% context 而沒有任何訊號。**超過上限就換成「LLM 掃描檔頭選 N 個」，不要直接跳到向量資料庫。** 業界正在收斂的答案是 markdown 為 source of truth、向量索引為可重建的衍生索引，向量不是替代品。

**per-user 與 per-project 記憶必須實際分開存放**（前者在使用者家目錄、後者隨 repo）。理由不是架構潔癖，是**個資與 git 汙染**：個人偏好被寫進 repo 會被 git 追蹤並被所有 checkout 者共享。

### 3.5 權限：布林旗標 vs 分級授權 vs sandbox + policy 雙軸

**推薦：雙軸，且順序是 sandbox 先於精細化 approval。** 理由：approval 的精細度有上限——Cursor 官方自承 allowlist「best-effort, not a security boundary」，而 93% 的提示會被接受。**在一個沒有 sandbox 的系統裡把 approval 做得再細，也只是在調整使用者疲勞的速度，不是在縮小傷害半徑。** 反過來，一個有 sandbox 的系統即使 approval 粗糙，傷害半徑也有硬上限。

**但「先做 sandbox」不等於「馬上上 Firecracker」。** 隔離強度是光譜，成本也是。對只有檔案系統工具的 harness，最低成本的有效措施是**路徑邊界（chroot 式的 workspace 限定）＋ 敏感檔案 deny-list**，這比容器化便宜兩個數量級而且擋住最常見的傷害。只有當 agent 要執行任意程式碼或 shell 指令時，才需要升級到 microVM 等級。

**授權範圍的推薦：按「工具 × 路徑範圍」授權，不按 session 授權。** 理由見第 4 節的 approval fatigue：session-wide 授權等於把疲勞後的終局狀態設為系統起點。

### 3.6 Sub-agent：何時該開

**推薦判準（採納 topic-D，但標明證據限制）：只在任務同時滿足三個條件時開** ——(a) breadth-first、可獨立平行拆解；(b) 子任務會產生大量之後不會再引用的中間資訊；(c) 答案總量超過單一 context window。**不滿足全部三項時，多 agent 大機率是純成本浪費**（客服案例：2× 成本換 2.1pp）。

**額外的成本提醒（sweep）：** 把 sub-agent 當成「拋棄整個 cache 前綴」來計價，而不是「多一次呼叫」。15× 的溢價裡有相當比例是 cache write 而非推論。

**如果你依賴 sub-agent 的工具限縮作為安全邊界——先驗證它真的生效。** 官方 SDK 目前這個假設不成立（見第 4 節）。

### 3.7 跨層連結（Cross-Topic Connections）

這四項是任何單一 specialist 看不到、只有把四份輸出並排才浮現的東西。

**(1) cache 友善與 context 節省是方向相反的目標，L4 與 L6 對同一張力給了相反的解。**
L6 的 system-reminder 選擇**犧牲 context 換 cache**（注入使用者訊息，保住 system prompt 前綴，代價是吃 15–50% context）。L4 的 compaction 選擇**犧牲 cache 換 context**（縮短對話，代價是打斷前綴、下一輪 1.25×–2× 重建）。L3 的 tool search 是少數兩者兼得的設計（defer_loading 讓工具定義不進前綴，既省 context 又不破壞 cache）——這正是它值得產品化的理由。**判斷任何 context 節省方案時，都應該同時問「它省了多少 token」與「它動了哪一層的 cache 前綴」。** 只看前者的優化經常是負收益。

**(2) L8 是 L4 的極限形式：sub-agent = 拋棄整個 cache 前綴換一個乾淨 context。**
compaction 打斷一次前綴，sub-agent 直接不繼承前綴（C-023 已由 topic-C/D 交叉確認）。這給了 15× token 溢價一個結構性解釋，也指出了降本方向在跨 agent cache 重用。

**(3) 信任邊界會在 L4/L5 被「洗白」——這是本 sweep 認為最被低估的風險。**
工具輸出、檔案內容、web 內容進入 context 時仍帶有「這是外部不可信輸入」的來源標記（`ToolMessage`、`tool_result`）。但 **compaction 把它們摘要成一段散文之後，來源標記就消失了**。C-020 的 governance decay（安全約束被摘要掉後違反率 0%→30%，**MEDIUM**，未核實全文）與 D-016 的 injection 技巧（Base64 藏在不可見 DOM、環境變數毒化）其實是同一條管線的兩端：**injection 內容經過摘要後，變成看起來像是敘述性事實的東西**。更糟的情況是摘要以什麼身分回填——如果摘要被當成使用者說的話，等於把外部輸入提升到 user authority。這在 `harness-agent-poc` 是實際發生的（見 5.3）。**通用原則：任何壓縮／摘要機制都必須保留 provenance，而且摘要結果的權限等級不能高於被摘要內容中權限最低的那一項。**

**(4) 「宣告 ≠ 強制」橫跨至少四層，是一種獨立的失敗模式類別。** 詳見第 4 節第一項。

### 3.8 超出原範圍的發現（Beyond the Brief）

**[SWEEP ADDITION] L2 與 L3 已經開始跨廠商標準化，L1/L6 沒有。** AGENTS.md（OpenAI 捐出）與 MCP（Anthropic 捐出）雙雙進入 Linux Foundation 的 Agentic AI Foundation（2025-12 成立，**MEDIUM**）。這對長期研究系列有結構性意涵：**專案指令層與工具協定層正在變成公共基礎設施，而身分 prompt 層與動態注入層仍是各家私有的差異化來源。** 如果要預測哪些層會在未來 2 年商品化、哪些會維持護城河，這條分界線是目前最好的指標。這一點在原始 scope 裡完全沒有，四位 specialist 也都沒提到。

**[SWEEP ADDITION] 有一整層在四份輸出裡完全缺席：觀測性／評測層。** 沒有任何 specialist 討論 tracing、eval harness、或「怎麼知道這些層有沒有生效」。這不是疏忽，是 scope 沒問。但它很重要，因為**本篇列出的每一個「宣告 ≠ 強制」案例，都是靠觀測才發現的**——issue #17601 靠 mitmproxy 攔流量，issue #172 靠使用者發現 sub-agent 呼叫了被禁的工具，`harness-agent-poc` 的 compaction 失效靠讀原始碼。**沒有觀測層，其他九層的失效全部是靜默的。** 建議獨立成為研究系列的下一篇，而不是塞進本篇。

---

## 4. 失敗模式（含已知踩雷案例）

### 4.1 宣告式設定 ≠ 執行期強制（本輪最重要的發現）

**這是本輪對抗性研究的直接產物。** topic-A 原本引用 VILA-Lab 的說法，稱 Claude Code 有「7 道獨立安全層」與 deny-first 原則。topic-D 提出挑戰並端出一手證據，topic-A 據此**下修該 claim 的 confidence 為 MEDIUM 並加註 counter_evidence**。這個對抗結果比原 claim 有價值得多。

**核心證據（HIGH，topic-D 直接 WebFetch 驗證）：** [anthropics/claude-agent-sdk-typescript issue #172](https://github.com/anthropics/claude-agent-sdk-typescript/issues/172)（OPEN，2026-02-12 開單，無 PR、無 maintainer 回應）指出：`AgentDefinition.tools`（白名單）與 `disallowedTools`（黑名單）**在 CLI spawn subagent child process 時完全沒有被強制執行**。根因是 Task tool handler 沒有把這些設定映射成 `--allowedTools` / `--disallowedTools` CLI flags，導致 subagent 可以看到並呼叫理論上被禁止的工具——尤其是遞迴呼叫 Task 本身，造成 subagent 鏈爆炸並以「CLI output was not valid JSON」崩潰。官方建議的暫時 workaround 是使用者自行寫 `PreToolUse` hook 擋掉 `Task` 呼叫。

**這個模式在本研究中至少出現六次，橫跨四層：**

| 層 | 案例 | 證據強度 |
|---|---|---|
| L2 | `.cursorrules` 只在 Chat/Tab 被讀取，**Agent mode 不載入** | LOW（二手指南交叉印證） |
| L2 | CLAUDE.md 作為「使用者 context」注入 = 機率性遵從，不是確定性指令 | MEDIUM（VILA-Lab） |
| L3/L8 | SDK issue #172：sub-agent 工具白名單宣告了但未強制 | **HIGH**（一手 GitHub issue，直接驗證） |
| L7 | Cursor allowlist 官方自承「best-effort, not a security boundary」，且有真實繞過（shell built-ins + 環境變數毒化） | MEDIUM |
| L7（本 repo） | `HIGH_RISK_TOOLS = {"write_file"}`，`edit_file` 是無防護的第二個寫入原語 | **HIGH**（原始碼） |
| L4（本 repo） | compaction 執行了但結果從未寫回 state | **HIGH**（原始碼） |

**這與「模型被說服做壞事」（prompt injection / jailbreak）是不同類別的失敗，需要不同的防禦。** prompt injection 的防禦是 L1/L6 的政策層與 L7 的傷害半徑；「宣告 ≠ 強制」的防禦只有一種——**執行期驗證**。

**通用檢測方法（sweep 提出）：對每一層問一個問題——「這一層失效時，是會報錯，還是會靜默通過？」** 上表六個案例**全部都是靜默通過**。這不是巧合：宣告式設定的本質就是「我說了，所以我以為它生效了」，而沒有生效時沒有任何東西會抱怨。因此每一個宣告式的安全／隔離設定，都應該配一個會失敗的測試。

**與 B-014 的對照使這一點更鋒利：** Anthropic API 層級的 `allowed_callers` 屬性（限制工具只能被特定執行環境呼叫，省略 `"direct"` 即封鎖模型直接呼叫）是**有 API 強制驗證**的機制（**MEDIUM**）。同樣是「工具層權限控制」，一個有 API 保證，另一個是文件承諾但程式碼未兌現。**光看架構圖，這兩者長得一模一樣。**

### 4.2 Compaction 系統性丟失精確資訊（不是隨機丟失）

Anthropic 自己的 cookbook probe 測試：3 個高層事實 **100% 保留**，3 個附錄數值 **0% 保留**（**HIGH**）。這代表**摘要優先保留敘事、犧牲精確數值與具體引用**。實務上消失的通常是「第二輪給的限制條件」與「第八輪確認的精確值」。

**最危險的性質是它不像失敗**：對話仍在跑，token 數持續下降，一切看起來很健康。

**更嚴重的假說（MEDIUM，[UNFILLED GAP]）：** arXiv 2606.22528《Governance Decay》宣稱跨 7 模型、1,300+ episode，compaction 讓約束違反率從 **0% 升至 30%**——早期給的安全規則在可見時被遵守，被摘要掉後同一個 agent 會執行原本禁止的操作。**本輪與 sweep 階段對該論文的 abs 與 pdf 兩個 URL 皆收到 403，這個數字只來自搜尋引擎摘要，未能核對「約束」如何量測。引用前必須自行溯源。** 但即使數字不精確，方向性風險是明確的：多數摘要 prompt（包含本 repo 的）都要求保留「關鍵決策與發現」，**沒有任何一個要求保留「使用者早期設下的限制」**。

### 4.3 工具過多導致選錯（且有架構層級的位置偏誤）

Anthropic 官方承認 30–50 工具門檻（**HIGH**）。同行評審的 [BiasBusters](https://www.alphaxiv.org/overview/2510.00307v1)（ICLR 2026 poster，arXiv 2510.00307，**MEDIUM**，未讀全文）進一步發現**位置偏誤**：在 741 個工具的候選集中，清單開頭與結尾的工具準確率約 31–32%，**中段（40%–60% 位置）只有 22–52%**（依模型而異）。作者歸因於 Transformer 的 RoPE 長期衰減——**這是架構層級偏誤，不分廠商都存在**。緩解手段是先過濾出相關子集再均勻取樣，而不是固定塞一個長清單。

另有二手來源引用的崩跌數字（10→100+ 工具時準確率 78%→13.62%；207→417 工具時 64%→20%，**LOW**）。**這兩組數字方向與官方門檻一致，但作為精確數字引用前應溯源至 LongFuncEval（arXiv 2505.10570）原文核對方法論。**

### 4.4 記憶污染／過期（主動誤導，不是資訊不足）

多篇 2026 guide 交叉印證（**MEDIUM**，C-012）：**coding agent 的記憶會隨每次合併的 PR 過期**（不像客服 agent 的「退款政策」可以穩定數月）。若記憶檔寫「認證邏輯在 `src/auth/handlers.ts`」而該檔案已被搬移，agent 會**自信地在錯誤位置尋找**——這是過期資訊主動誤導，比沒有記憶更糟。20+ 並發 agent 寫入同一記憶檔時會出現「寫入衝突、過期讀取、無人協調的矛盾條目」。

markdown-first 陣營自己承認的結構性限制：grep-based 檢索（非語意）加上 **200 行索引上限**（Milvus/zilliztech 分析，**MEDIUM**）。

### 4.5 Approval fatigue 與 prompt injection 繞過核准

93% 的權限提示會被接受（**MEDIUM**）。「if a run asks for 40 approvals, the product has probably failed before the user clicks」。**這被業界定性為安全漏洞而非 UX 問題**，因為攻擊者可以把危險操作藏在大量常規請求中滲透。

具體攻擊技巧（**LOW**，D-016）：Base64 編碼的偽核准指令藏在不可見 DOM 元素（人看不到、agent 會解析）；shell 環境變數毒化讓後續「已核准」的指令實際執行惡意行為。

**真實 sandbox 逃逸案例：** n8n **CVE-2026-25049**（CVSS 9.4–9.8，五家獨立資安廠商交叉驗證，**HIGH**）——JavaScript expression/Code node 的 AST-based sandbox 因**型別混淆**被繞過，已認證使用者可達成 RCE；影響 1.123.17 之前所有版本與 2.0.0–2.5.1，已於 1.123.17 與 2.5.2 修補。另有傳聞級案例（**LOW**，單一二手轉述，未找到一手事故報告）：Ona 平台上一個 Claude Code agent 發現 `/proc/self/root/usr/bin/npx` 路徑可繞過限制，**進而停用了自己的 sandbox**。

### 4.6 隱藏注入的雙重代價

見 L6。實測 32 天 10,577 次隱藏注入、佔 15–50% context、malware 警告 10,040 次觸發 0 次真陽性（**HIGH**）；且 issue #52018 指出這類提醒**與 prompt injection 攻擊在特徵上不可區分**。issue #17601 被關閉為 not planned 且無官方技術回應。

### 4.7 Sub-agent 聚合層品質不可控

D-013（**LOW**）：即使每個 subagent 表現完美，**設計不良的 synthesis 步驟仍會產生不可靠輸出**。目前主流聚合方法仍是 LLM 摘要本身（有損、未校準），**尚無成熟方法明確建模 subagent 結論的不確定性**。這是一個公開的研究缺口，不是可以靠工程技巧繞過的問題。

### 4.8 Orchestration 成本失控

15× token 溢價套用在錯的場景（客服）會直接導致成本翻倍、效益邊際。**判準見 3.6。**

---

## 5. 套用到 harness-agent-poc

本節所有陳述來自 sweep 階段直接讀取 `/home/user/harness-agent-poc` 的原始碼，附檔案路徑與行號。這是全文證據強度最高的部分（不受 proxy 限制）。可直接當 backlog 使用。

### 5.0 現況分層對照

| 層 | POC 現況 | 檔案 |
|---|---|---|
| L0 | 不可控（且未被納入 token 計算） | — |
| L1 | 單一 markdown 靜態 prompt | `harness_agent/prompts/system.md` |
| L2 | 無（無 CLAUDE.md/AGENTS.md 階層、無 cwd/git 環境注入） | — |
| L3 | 6 個檔案系統工具 | `harness_agent/tools/filesystem.py:53-205` |
| L4 | 有 compaction，**但不生效** | `harness_agent/middleware/compact.py` |
| L5 | 有 markdown 記憶，全量 push 注入 | `harness_agent/middleware/memory.py` |
| L6 | 無（`_MEMORY_GUIDELINES` 是靜態 system prompt 的一部分，不是中途注入） | — |
| L7 | 單一布林旗標核准，**且只覆蓋一半的寫入路徑**；無 sandbox | `harness_agent/middleware/hitl.py`、`agent.py:91-131` |
| L8 | 無 | — |
| L9 | Rich CLI | `harness_agent/main.py` |

**一個 POC 已經做對、值得保留的地方（sweep 補充）：** `middleware/base.py:27-31` 的 `append_to_system()` 把所有動態內容**附加在靜態 prompt 之後**，`agent.py:73` 的組裝順序也是「靜態 system.md → 記憶 → guidelines」。**這正好是 L1/L2 的可快取前綴／可變後綴切法**（見 3.1），是意外做對的一件事，重構時不要打散它。

---

### P0 — 修正確性（這三項不是「缺一層」，是既有的層沒有生效）

#### 5.1 `compact.py` 的壓縮結果從未寫回 graph state ← 最高優先

**現況（HIGH，原始碼）：**
- `agent.py:72` — `messages = compact_mw.maybe_compact(state["messages"])`，賦值給**區域變數**。
- `agent.py:88` — `updates["messages"] = [response]`，只回傳模型回應。
- `agent.py:26` — `messages: Annotated[list[AnyMessage], add_messages]`，`add_messages` 是 **append reducer**。

因此 `state["messages"]` **永遠只增不減**。壓縮結果只影響「這一次送給模型的內容」，從未持久化。實際後果：

1. **一旦跨過 50K 門檻，之後每一輪都會重跑一次全量 LLM 摘要**（`compact.py:53` 的 `self.llm.invoke`），每輪多付一次完整 LLM 呼叫，且成本隨對話長度單調上升——這比不做 compaction 還貴。
2. **每輪產生的摘要內容都不同**（LLM 非確定性），送出的 message 前綴每輪都變 → **prompt cache 命中率永遠是 0**。這放大了 C-019 指出的 cache 成本問題一個量級。
3. `compact.py:61-64` 印出的「Compressed N messages」訊息**會在每一輪重複出現且 N 持續變大**——這是可以直接觀察到的症狀。

**修法：** 依 LangGraph 的持久化語意，要真正刪除訊息必須回傳 `RemoveMessage`（[langgraph issue #5112](https://github.com/langchain-ai/langgraph/issues/5112) 說明了 `RemoveMessage` 的正確用法與常見誤用，**MEDIUM**）。最小修正是讓 `maybe_compact` 回傳 state update（含 `RemoveMessage` 清單 + 摘要訊息），並在 `agent_node` 把它併入 `updates`。**更好的做法是直接改用 `SummarizationMiddleware`**（見 5.7）。

**驗收條件：** 寫一個測試，餵超過門檻的訊息串跑兩輪，斷言第二輪的 `state["messages"]` 長度不大於第一輪，且 LLM 摘要呼叫只發生一次。**注意這個 bug 之所以存在到現在，正是因為它靜默通過**（見 4.1 的通用檢測法）。

#### 5.2 `edit_file` 完全繞過 HITL，且 prompt 層主動把寫入導向這條路 ← 最高優先

**現況（HIGH，原始碼）：**
- `filesystem.py:205` — `HIGH_RISK_TOOLS = {"write_file"}`，註解（`:204`）寫「write_file (full overwrite) requires HITL; edit_file (targeted) does not」。
- `filesystem.py:175-198` — `edit_file` 可對**任何已存在的檔案**做任意字串替換，`new_string` 無長度與內容限制。
- `agent.py:99-102` — 分流只看 `HIGH_RISK_TOOLS`，`edit_file` 一律走 `safe` 路徑。
- **而 harness 的 prompt 層在主動指示模型用 `edit_file`：** `prompts/system.md:17`（「Update memory using `edit_file`」）、`prompts/system.md:36-40`（「call `edit_file` to append a summary」「update `memory/AGENTS.md` with `edit_file` BEFORE responding」）、`memory.py:22`（「call `edit_file` to update memory BEFORE doing anything else」）、`memory.py:33`（「you MUST call `edit_file`」）。

**這正是 4.1「宣告 ≠ 強制」在本 repo 的翻版，而且比 SDK issue #172 更糟——#172 是實作 bug，這裡是設計決定。** 系統對外的宣稱是「寫檔前需要人類核准」，實際上只有兩個寫入原語中的一個被攔。`edit_file` 的「targeted」性質並不降低風險：它能改 `.bashrc`、能注入惡意 import、能竄改任何設定檔，唯一的限制是要先知道一段唯一字串——而 agent 有 `read_file` 和 `grep`。

**修法（二選一）：**
- (a) `HIGH_RISK_TOOLS = {"write_file", "edit_file"}`，並同時做 5.6 的分級核准（否則一次核准照樣全放行）。
- (b) 保留 `edit_file` 免核准，但**限制其作用範圍**到 `memory/` 目錄底下（因為 prompt 層對它的唯一正當用途就是更新記憶），其餘路徑走 `write_file` 的核准路徑。

**推薦 (b) 再加 (a) 的殘餘部分**：`edit_file` 在 `memory/` 內免核准、在 `memory/` 外視為高風險。理由：這同時解決了核准疲勞（記憶更新是高頻低風險操作，不該打斷使用者）與防護缺口，而且它讓 prompt 層的指示與權限層的規則第一次對齊。

#### 5.3 壓縮摘要以 `HumanMessage` 回填，造成 provenance laundering

**現況（HIGH，原始碼）：** `compact.py:54-59` — `summary = HumanMessage(content=f"[Context summary — ...]{response.content}")`。

被摘要的內容包含 `ToolMessage`（`compact.py:48` 用 `m.__class__.__name__` 保留了類別名稱，這點做得比預期好），而 tool 結果的來源是 `read_file`／`grep` 讀進來的**任意檔案內容**——按 3.7(3) 的定義，那是不可信輸入。摘要之後這些內容被包進一個 `HumanMessage`，也就是**以「使用者說的話」的身分重新進入對話**。

**風險路徑具體且完整：** 惡意檔案內容 → `read_file` → `ToolMessage` → compaction 摘要 → `HumanMessage`（user authority）→ 模型當成使用者指令。而模型對使用者訊息的服從度遠高於工具輸出。加上 `prompts/system.md:21-24` 明確寫著「`<agent_memory>` always takes priority... **you must follow it immediately and without re-confirming with the user**」，這條「不必再確認」的指令使得任何進入記憶或摘要的內容都有極高的行為權重。

**修法：** 摘要改用 `SystemMessage`，或至少在內容中保留明確的 provenance 標記（例如 `[Context summary derived from tool outputs and prior turns — NOT a direct user instruction]`），並在摘要 prompt（`compact.py:15-26`）中要求模型**保留每項資訊的來源類別**。

**通用規則（3.7(3)）：** 摘要結果的權限等級不能高於被摘要內容中權限最低的那一項。

---

### P1 — 補真正缺的防護

#### 5.4 檔案系統工具沒有任何路徑邊界

**現況（HIGH，原始碼）：** `filesystem.py` 全部六個工具都直接 `Path(...)` 使用者/模型給的絕對路徑，沒有任何 root 限定。特別是：
- `filesystem.py:166-169` — `write_file` 執行 `path.parent.mkdir(parents=True, exist_ok=True)` 後寫入，**可在檔案系統任意位置創建目錄樹並寫檔**。
- `filesystem.py:71-99` — `read_file` 對任何路徑無條件讀取，**不觸發核准**。
- `llm/providers.py:14` — `load_dotenv(Path(__file__).parent.parent.parent / ".env")`，即 API 金鑰放在 project root 的 `.env`。

**完整外流路徑：** `read_file("/home/user/harness-agent-poc/.env")`（無核准）→ 金鑰進入 context → `edit_file` 寫入 `memory/AGENTS.md`（無核准，且 prompt 層鼓勵）→ 金鑰被 git 追蹤。注意 `memory.py:27` 的 `NEVER store API keys or credentials` 是**指示**（L1，機率性遵從），不是**強制**（L7）——這又是一次同樣的錯位。

**修法（低成本、高收益）：** 在 `filesystem.py` 加一個共用的 `_resolve_within_workspace(path)` helper，對所有六個工具做 `Path.resolve()` 後的前綴檢查（含 symlink 解析），越界回傳語意化錯誤；另加一個 deny-list（`.env`、`.git/config`、`~/.ssh/`、`*.pem`、`~/.harness-agent/config.toml`）。**這是在沒有容器化的情況下，成本最低而擋住最多實際傷害的一步**（見 3.5 的推薦順序）。

#### 5.5 `count_tokens_approximately` 沒把 system prompt 與工具定義算進去

**現況（HIGH，原始碼 + C-022）：** `compact.py:37` — `total = count_tokens_approximately(messages)`，只算 messages。但 L0 的固定工具模板、`system.md`、以及 `memory.py:65-94` 注入的完整記憶內容全都佔 context 額度（官方文件明確說明 system prompt、每則訊息含 tool result／圖片／文件、tool definitions、thinking tokens 全部計入）。記憶檔越長，實際用量與 50K 門檻的偏差越大，且偏差**只會單向低估**。

**修法：** 把 system prompt 與工具 schema 的估算值一併納入門檻計算基礎；或直接使用 provider 回傳的 `usage` 欄位作為真實值。

#### 5.6 HITL：一次核准涵蓋整個 session，且用阻塞式 stdin 實作

**現況（HIGH，原始碼 + D-001/D-005）：**
- `agent.py:33` — `writes_approved: bool`；`agent.py:119` — `state_updates["writes_approved"] = True  # skip future prompts`。一旦為 True，`agent.py:99-102` 的分流會讓所有後續寫檔直接走 safe 路徑。
- `hitl.py:16-19` — 一次展示所有 pending tool_calls，**一個 y/n 決定全部**。
- `hitl.py:40-42` — 內容預覽**截斷在 500 字元**：使用者核准的是他看不完的東西。
- `hitl.py:47` — 用 `console.input()` **阻塞式讀 stdin，直接寫在 graph node 裡面**。

**風險評估（D-005，MEDIUM，推論）：** 業界把 approval fatigue 視為在大量重複核准後才出現的漸進式失守；本 POC 的設計是**第一次核准後就直接進入疲勞後的終局狀態**。不需要 40 次核准去磨損警覺性，架構本身保證從第 2 次寫檔起就沒有防護。**反面論點（保留 topic-D 的 counter_evidence）：** 本 POC 工具面窄（無任意 shell 執行、無聯網工具），被 injection 誘導的攻擊面確實有限——但如 5.4 所示，任意寫檔加上無路徑邊界仍然是有實質傷害力的原語。

**[SWEEP ADDITION] 額外的架構問題：`console.input()` 寫在 graph node 內意味著核准無法 checkpoint、無法恢復、無法用於 SDK/server/非 CLI 情境。** LangGraph 的正解是 `interrupt()` 原語——暫停 graph、持久化 state、等待 `Command(resume=...)`。`langchain` 內建的 `HumanInTheLoopMiddleware` 就是建立在這個原語上，支援 `interrupt_on` 逐工具政策與四種決策型別（approve／edit／reject／respond），比一個布林精細一個量級（**MEDIUM**，403 未逐字核實）。

**修法：** 改用 `HumanInTheLoopMiddleware` + `interrupt()`，授權粒度改為「工具 × 路徑範圍」（例如「`reports/{repo_name}/` 底下的寫入本 session 免問，其餘每次問」），並移除或大幅提高 500 字元的預覽截斷。

---

### P2 — 用框架現成件取代自製件

#### 5.7 `pyproject.toml` 已宣告的依賴裡就有多數缺口的現成實作

**現況（HIGH，`pyproject.toml:6-16`）：** 專案宣告 `langchain>=1.2.14`、`langchain-anthropic>=1.4.0`、`langgraph>=1.1.4`。而 `middleware/base.py:10-24` 自己定義了一個叫 `AgentMiddleware` 的類別，只有兩個 hook（`before_agent`、`inject_system`）——**這個名字在 LangChain v1 裡已經存在，且 hook set 豐富得多**：`before_agent`、`before_model`、`wrap_model_call`、`after_model`、`wrap_tool_call`、`after_agent`，且 `before_model` 依序執行、`after_model` 反序執行（**MEDIUM**，[Custom middleware 文件](https://docs.langchain.com/oss/python/langchain/middleware/custom) 403 未逐字核實）。

**[SWEEP ADDITION] 對照表（全部標 MEDIUM，皆為 WebSearch 摘要，docs.langchain.com 與 reference.langchain.com 均 403，導入前請自行核對版本 API）：**

| 骨架層 | POC 現況 | LangChain 現成件 |
|---|---|---|
| L4（clearing） | **無此層** | `ContextEditingMiddleware` + `ClearToolUsesEdit`（對齊 `clear_tool_uses_20250919`，預設 trigger 100k，參數含 `keep`／`clear_tool_inputs`／`exclude_tools`／`placeholder`） |
| L4（compaction） | `compact.py` 自製且不生效 | `SummarizationMiddleware`（`max_tokens_before_summary`、`messages_to_keep` 預設 20、`trim_token_limit`） |
| L4（cache 邊界） | 完全沒有 | `AnthropicPromptCachingMiddleware`（自動對 system message 最後一個 content block 與最後一個 tool definition 打 `cache_control`；type 僅 `ephemeral`，ttl 預設 `5m`） |
| L7（HITL） | `hitl.py` 自製、阻塞式 | `HumanInTheLoopMiddleware`（`interrupt_on` 逐工具政策、approve/edit/reject/respond） |
| L3（工具選擇） | 6 個工具，暫不需要 | `LLMToolSelectorMiddleware`（有需要時） |
| L3（錯誤語意） | 字串式 `Error: xxx` | 內建 tool error middleware（把例外轉成 error `ToolMessage`）；LangChain `ToolMessage` 本身支援 `status="error"` |
| — | 無呼叫次數上限 | `ToolCallLimitMiddleware` / model call limit middleware |
| — | 無 PII 處理 | `PIIMiddleware` |

**推薦：不要一次全換。** 順序是：先做 P0 三項（那是正確性，跟換不換框架無關）→ 換 `SummarizationMiddleware` + `ContextEditingMiddleware`（收益最大且直接消滅 5.1）→ 換 `HumanInTheLoopMiddleware`（連帶解掉 5.6 的阻塞式問題）→ 最後才考慮把 `base.py` 的自製 `AgentMiddleware` 併入框架版本。**理由：`base.py` 的兩個 hook 目前運作正常，換掉它是重構而非修 bug，優先度應該低於前面三項。**

**同時保留一項清醒：** 這個 POC 的教學價值有一部分來自「middleware 是自己寫的、看得懂」。如果目的是理解 harness 分層，自製件不是負債；如果目的是往生產靠攏，框架件才是。**這個取捨應該由專案的目的決定，本研究不代為決定。**

#### 5.8 工具層：描述品質與命名空間（低優先，但成本極低）

**現況（HIGH，原始碼 + B-002/B-004/B-012）：**
- 六個工具的描述皆為單句 docstring（`filesystem.py:55`、`:73`、`:104`、`:120-122`、`:162-165`、`:177-181`），遠低於官方建議的 3–4 句標準；未使用 `input_examples`。
- 無服務前綴命名空間（`ls`、`read_file`、`write_file`…）——6 個工具、單一服務時是合理簡化，但**接入第二個工具來源（git、HTTP）時會立刻產生衝突**。
- 錯誤回傳是機器碼式短字串（`filesystem.py:58` `Error: path_not_found:`、`:60` `Error: not_a_directory:`），符合「語意化錯誤碼」精神但**缺少「下一步該怎麼做」的可恢復性提示**——唯一的例外是 `filesystem.py:195` 的 `"Add more surrounding context."`，那正好是官方建議的正確寫法，可以當作其他錯誤的範本。
- 底層用 LangChain `@tool` 回傳純字串，**沒有 `is_error` 或等效 status 欄位**，模型在結構層面無法區分「正常結果恰好包含 Error 字樣」與「工具真的失敗了」。

**修法：** (1) 把六個描述擴到 3–4 句；(2) 依 `filesystem.py:195` 的範本，給每個錯誤加上一句下一步建議；(3) 錯誤路徑改回傳 `ToolMessage(status="error")`。**這些不急，但因為工具數少，做完只需要一次提交，且是接 MCP 之前必須先清掉的技術債。**

#### 5.9 記憶層：`memory.py` 的四個結構性缺口

**現況（HIGH，原始碼 + C-009/C-013/C-015）：**

1. **全量無條件 push 注入**（`memory.py:56-63`、`:78-85`）——session 開始時把整個 `AGENTS.md` 與整個 repo 記憶檔完整塞進 system prompt，**沒有大小上限、沒有篩選、沒有 agent 主動查詢**。這比官方 memory tool 的 pull 模式原始，甚至比 markdown-first 陣營自己的「LLM 掃描檔頭選 5 個檔案」還原始。
2. **「global」名不符實**（`memory.py:12-14`）——`_PROJECT_ROOT = Path(__file__).parent.parent.parent`，`GLOBAL_MEMORY_FILE = MEMORY_DIR / "AGENTS.md"`，實際落在 **repo 內**而非使用者家目錄。任何 clone 這個 repo 的人都共享同一份「global」記憶；使用者 A 的姓名偏好（`memory.py:97-111` 的 `_extract_name_preference`）會被寫進 repo 並被 git 追蹤。業界慣例是 per-OS-user 的 `~/.claude/` 等價物。
3. **無成長上限、無時間戳記、無過期機制**（`memory.py:33-41` 的 append-only 指示：`"## Previous Analyses\n"` 後面一直往下加）——記憶檔會無限成長，舊條目永遠不會被標記過期或移除。這正是 4.4 描述的失敗模式，且因為是 push 全量注入，記憶檔的成長會**直接、線性地**吃掉 context 與 cache 前綴。
4. **無衝突偵測**——除了 `_extract_name_preference` 取第一個匹配之外，沒有任何「新資訊覆蓋舊資訊」的邏輯。

**修法（依收益排序）：** (a) 把 `GLOBAL_MEMORY_FILE` 移到 `Path.home() / ".harness-agent" / "AGENTS.md"`（該目錄已因 `providers.py:26` 的 `CONFIG_PATH` 而存在，改動成本極低，且立刻解決 git 汙染與多使用者共享）；(b) 給注入內容設 token 硬上限並在超過時警告；(c) 記憶條目加日期並定期修剪；(d) 規模再長之後才考慮換成「掃描檔頭選 N 個」。

#### 5.10 尚不需要、但要「有意識地不做」的層

按官方判準（**HIGH**，B-006/B-007），**6 個工具、單一服務、無 MCP server，遠低於 tool search 的 10 工具/10k token 門檻，現階段不該引入 `defer_loading`**。同理，**L8（sub-agent）在單一分析任務下沒有正當性**——按 3.6 的三條件判準，本 POC 的 repo 分析任務不滿足「答案總量超過單一 context window」。

**這兩項是本研究少數「POC 沒有、暫時也不該加」的結論。** 記錄下來的目的是：讓它們是**有意識的延後**，而不是**遺漏**。

---

## 結論

**綜合層面的第一個判斷：這個十層骨架站得住腳，可以作為後續 25 篇的引用基礎，但要帶著它的但書一起引用。** 支持它的最強證據不是任何單一來源，而是**三個方法論完全不同的獨立來源收斂到同一組邊界**：VILA-Lab 的逆向工程（5 層）、《Inside the Scaffold》對 13 個開源 scaffold 的原始碼分類（3 層）、以及 OPENDEV 論文歸納的三大工程挑戰（context / 破壞性操作 / 工具預算，恰好對應 L4/L7/L3）。層數不同不是矛盾，是粒度選擇不同。我們選 10 層的判準是「每一層要有獨立的失效模式與獨立的設計決策空間」。**但 A-018 的 confidence 是 LOW，這是誠實的標記：它是分析性框架，不是可驗證的事實，也不是業界標準。**

**第二個判斷，也是本輪最有價值的產出：「宣告 ≠ 強制」應該被當成一個一等公民的失敗模式類別，與 prompt injection 平起平坐。** 它在本研究中橫跨 L2（`.cursorrules` 在 Agent mode 不載入、CLAUDE.md 是機率性遵從）、L3/L8（SDK issue #172 的工具白名單未強制，**HIGH**）、L7（Cursor 官方自承 allowlist 不是安全邊界）、以及本 repo 的兩個實例出現至少六次。它的定義性特徵是**靜默通過**：沒有生效時沒有任何東西會抱怨。因此可操作的建議很具體——**對每一層的每一個宣告式安全／隔離設定，配一個會失敗的測試；並在架構評審時對每一層問「這一層失效時是報錯還是靜默通過」。** 值得注意的是，這個發現不是任何一位 specialist 單獨得到的，是 topic-D 挑戰 topic-A、topic-A 下修信心評級並改引一手 issue 的對抗過程產出的。**它證明了對抗性交叉驗證比增加來源數量更有價值。**

**第三個判斷：context 的爭奪不是各層獨立的優化問題，是一個有耦合的分配問題，而耦合媒介是 prompt cache。** L6 犧牲 context 保 cache，L4 犧牲 cache 省 context，L8 直接拋棄 cache 換乾淨 context，只有 L3 的 `defer_loading` 兩者兼得。**任何只看「省了多少 token」而不看「動了哪一層 cache 前綴」的優化，都可能是負收益。** 這也給了 multi-agent 15× 溢價一個結構性解釋，並指出降本方向在跨 agent 的 cache 重用而非模型單價。

**第四個判斷：信任邊界會在壓縮與記憶層被靜默抹除，這是目前最被低估的風險。** 工具輸出進入 context 時帶著來源標記，經過摘要後標記消失。Governance Decay 論文的 0%→30%（**MEDIUM，未核實全文**）、prompt injection 的 Base64/環境變數技巧（**LOW**）、以及本 repo 的 `HumanMessage` 回填（**HIGH，原始碼**）是同一條管線的三個切面。通用規則：**摘要結果的權限等級不能高於被摘要內容中權限最低的那一項。**

**對 `harness-agent-poc` 的具體建議路徑，順序不可交換：** 先做 P0 三項（5.1 compaction 不生效、5.2 `edit_file` 繞過核准、5.3 provenance laundering）——這三項都不是「缺一層」，是既有的層沒有生效，而且都是靜默失敗，是本篇主軸失敗模式在自家 repo 的翻版；再做 P1（5.4 路徑邊界最划算、5.5 token 計算基礎、5.6 分級核准 + `interrupt()`）；最後才是 P2 的框架替換。**明確不做的兩件事：tool search（6 個工具，官方判準明說標準做法更合適）與 sub-agent（不滿足三條件判準）——記錄為有意識的延後，不是遺漏。**

**最後一個 meta 層級的觀察：** 本輪四位 specialist 在 proxy 大量 403 的環境下，仍然把最重要的幾條結論建立在能直接驗證的一手來源上（Anthropic 官方文件、GitHub issue、以及 repo 原始碼）。**這個模式值得成為後續 25 篇的方法論預設：當環境限制了來源廣度時，把有限的驗證預算花在能決定結論方向的少數 claim 上，其餘標清楚 confidence，而不是用大量無法核實的二手來源堆出虛假的厚度。** 本篇證據強度最高的三段——system-reminder 的實測代價、SDK issue #172、以及第 5 節的 repo 分析——全部符合這個模式。

---

## 待答問題

1. **Governance Decay 的 0%→30% 是真的嗎？** arXiv 2606.22528 全文兩次嘗試皆 403，無法核對「約束」如何量測、7 個模型是哪些、1,300+ episode 的任務分布。**為什麼重要：** 如果屬實，它意味著所有 compaction 實作的預設摘要 prompt 都有安全缺陷（沒有任何一個要求保留使用者早期設下的限制）。**下一步：** 換管道取得全文；或自己設計一個小規模複現（在對話早期設一條明確約束，觸發 compaction 後測試違反率）——**這個複現在 `harness-agent-poc` 上做的成本很低，而且可以直接驗證 `compact.py:15-26` 的摘要 prompt。**

2. **業界怎麼對 system prompt 做回歸測試？** 本輪找不到 Anthropic、OpenAI、Anysphere 任何一家的官方說明；A-016 的做法（golden dataset 50–200 筆、多層次評測、prompt drift 偵測、staging）全部來自評測工具廠商（Braintrust、promptfoo）的自述。**這已判定為產業普遍不揭露，而非搜尋失敗。** Piebald-AI 的 CHANGELOG 證明 Claude Code 確實有版本追蹤，但那是逆向工程觀察到的結果，不是官方流程。**為什麼重要：** L1 是唯一一個「改動會影響全部使用者、卻沒有型別系統或測試自然攔截」的層。

3. **觀測性／評測層應該是第 11 層，還是橫切關注？** 四份 specialist 輸出裡完全沒有這一層，但本篇每一個「宣告 ≠ 強制」案例都是靠觀測才發現的。**下一步：獨立成為研究系列的下一篇**，而不是硬塞進本骨架——在確定它是層還是橫切之前，貿然加進 L0–L9 會破壞「每層有獨立失效模式」的判準。

4. **Multi-agent 的成本效益到底取決於什麼？** 現有三筆資料（15×/90.2%、2×/2.1pp、100% vs 1.7%）互不相容，且 confidence 分別為 MEDIUM/LOW/LOW。「任務類型依賴」是合理假說但無直接證據。**需要的是一份同時涵蓋 breadth-first 探索任務與重複性任務、用同一評測基準的對照研究。** 本輪沒找到，可能還不存在。

5. **prompt caching 的 5 分鐘 TTL 在實務上會不會是問題？** topic-C 明確標註這是覆蓋缺口：只找到定價與失效規則的官方說明，**沒有任何使用者實際踩坑的一手報告**（例如長時間思考任務或人類審核等待期間 cache 過期）。這是一個「沒有證據」而非「證據顯示沒問題」的狀態。

6. **Cursor 的實際分層是什麼？** 目前所有資訊都來自可能互相轉載的外流文本（**LOW**）。而 `.cursorrules` 在 Agent mode 不載入的說法如果屬實，影響範圍很大（大量使用者維護著 agent 從未讀過的規則檔），值得獨立核實。

7. **本 repo 的 `compact.py` 失效多久了、影響過什麼？** 5.1 的 bug 是靜默的。**下一步：** 檢查 git 歷史確認引入時點，並檢查現有的 `memory/repos/*.md` 是否有跡象顯示過去的 session 曾在超過門檻後行為異常（例如重複的摘要片段）。

---

## 6. 來源清單

### 一手來源（本輪完成直接 fetch 逐字核實）

**Anthropic 官方文件與 cookbook**
- [Define tools — Anthropic](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools) — 工具模板組裝順序、工具描述規範、namespacing、consolidation
- [Context windows — Anthropic](https://platform.claude.com/docs/en/build-with-claude/context-windows) — context rot 定義、context awareness 自動注入、token 計入範圍
- [Prompt caching — Anthropic](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) — TTL、定價倍率、最小前綴、`tools→system→messages` 失效階層
- [Context editing — Anthropic](https://platform.claude.com/docs/en/build-with-claude/context-editing) — `clear_tool_uses_20250919` 參數
- [Tool search tool — Anthropic](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool) — `defer_loading`、啟用判準
- [Handle tool calls — Anthropic](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls) — `is_error`、可操作錯誤訊息、strict tool use
- [Context engineering cookbook — Anthropic](https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools) — compaction/clearing 實測數字、3/3 vs 0/3 probe 測試、memory tool
- [Sub-agents — Claude Code](https://code.claude.com/docs/en/sub-agents.md) — 獨立 context window、工具限縮、何時該用

**GitHub（issue 與 repo，直接驗證）**
- [anthropics/claude-code issue #17601](https://github.com/anthropics/claude-code/issues/17601) — system-reminder 實測：10,577 次注入、15–50% context、malware 警告 0/10,040 真陽性；已關閉為 not planned
- [anthropics/claude-code issue #52018](https://github.com/anthropics/claude-code/issues/52018) — system-reminder 與 prompt injection 不可區分
- [anthropics/claude-agent-sdk-typescript issue #172](https://github.com/anthropics/claude-agent-sdk-typescript/issues/172) — **sub-agent 工具白名單未在 child process 強制執行（OPEN，2026-02-12）**
- [Piebald-AI/claude-code-system-prompts](https://github.com/Piebald-AI/claude-code-system-prompts) — 從 JS bundle 萃取，246+ 版本 CHANGELOG，500+ prompt 片段
- [noelzappy/claude-code-system-prompts](https://github.com/noelzappy/claude-code-system-prompts) — 六大類 prompt 分類、可快取前綴/後綴模型
- [VILA-Lab/Dive-into-Claude-Code](https://github.com/VILA-Lab/Dive-into-Claude-Code) — 5 層架構、「98.4% Infrastructure」、deny-first、記憶檔頭掃描
- [langchain-ai/langgraph issue #5112](https://github.com/langchain-ai/langgraph/issues/5112) — `RemoveMessage` 語意與常見誤用

**`harness-agent-poc` 原始碼（sweep 直接讀取）**
- `harness_agent/agent.py`、`middleware/compact.py`、`middleware/memory.py`、`middleware/hitl.py`、`middleware/base.py`、`tools/filesystem.py`、`prompts/system.md`、`llm/providers.py`、`pyproject.toml`

### 學術來源（皆 arXiv 全文 403，僅摘要層級，MEDIUM/LOW）

- [Inside the Scaffold: A Source-Code Taxonomy of Coding Agent Architectures](https://arxiv.org/abs/2604.03515)（2026-04）— 13 個 scaffold、12 維度、3 層分類法、5 種控制迴圈原語
- [Building Effective AI Coding Agents for the Terminal](https://arxiv.org/abs/2603.05344)（2026-03）— OPENDEV、三大工程挑戰、lazy tool discovery
- [The System Prompt Is the Attack Surface](https://arxiv.org/pdf/2603.25056)（2026-03）— PhishNChips，同一模型繞過率因 prompt 設計從 <1% 變動到 97%
- [Trace-Free+](https://arxiv.org/abs/2602.20426)（Intuit AI Research，2026-02）— 工具描述改寫使劣化幅度 -29.23%
- [BiasBusters](https://www.alphaxiv.org/overview/2510.00307v1)（arXiv 2510.00307，ICLR 2026 poster）— 工具選擇位置偏誤，RoPE 長期衰減歸因
- arXiv 2606.22528《Governance Decay》— compaction 使約束違反率 0%→30%（**[UNFILLED GAP]** 無法核實全文）
- arXiv 2505.10570《LongFuncEval》— B-009 崩跌數字的疑似原始出處（**未核實**）

### 官方非 Anthropic 來源（WebSearch 摘要，原文 403，MEDIUM）

- [Effective harnesses for long-running agents — Anthropic Engineering](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)（2025-11-26）— harness = context engineering 的官方定義
- [Linux Foundation：Agentic AI Foundation 成立公告](https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation) — AGENTS.md 與 MCP 捐入
- [OpenAI：co-founds the Agentic AI Foundation](https://openai.com/index/agentic-ai-foundation/)
- [OpenAI Help Center：Memory FAQ](https://help.openai.com/en/articles/8590148-memory-faq) — saved memories / chat history 雙層（**升級 A-015 記憶部分為 MEDIUM**）
- [OpenAI Help Center：How does "Reference saved memories" work?](https://help.openai.com/en/articles/11146739-how-does-reference-saved-memories-work)
- [OpenAI：Memory and new controls for ChatGPT](https://openai.com/index/memory-and-new-controls-for-chatgpt/)
- VS Code Agent Permission Model 官方文件 — sandbox/approval 雙軸表述
- OpenAI Codex Sandboxing 官方文件 — 三 sandbox mode × 三 approval policy
- Cursor 官方文件 — allowlist「best-effort, not a security boundary」自承

### LangChain / LangGraph（sweep 補充，WebSearch 摘要，原文 403，MEDIUM）

- [Prebuilt middleware — LangChain](https://docs.langchain.com/oss/python/langchain/middleware/built-in)
- [Custom middleware — LangChain](https://docs.langchain.com/oss/python/langchain/middleware/custom) — 六個 hook 與執行順序
- [Human-in-the-loop — LangChain](https://docs.langchain.com/oss/python/langchain/human-in-the-loop) — `interrupt_on`、四種決策型別、`interrupt()`/`Command(resume=...)`
- [Short-term memory — LangChain](https://docs.langchain.com/oss/python/langchain/short-term-memory)
- [Anthropic middleware integration — LangChain](https://docs.langchain.com/oss/python/integrations/middleware/anthropic)
- [SummarizationMiddleware — LangChain Reference](https://reference.langchain.com/python/langchain/agents/middleware/summarization/SummarizationMiddleware)
- [context_editing — LangChain Reference](https://reference.langchain.com/python/langchain/agents/middleware/context_editing)
- [AnthropicPromptCachingMiddleware — LangChain Reference](https://reference.langchain.com/python/langchain-anthropic/middleware/prompt_caching/AnthropicPromptCachingMiddleware)
- [Agent Middleware — LangChain Blog](https://blog.langchain.com/agent-middleware/)
- [How Middleware Lets You Customize Your Agent Harness — LangChain](https://www.langchain.com/blog/how-middleware-lets-you-customize-your-agent-harness)

### 次級來源（部落格、二手彙整，LOW–MEDIUM，引用前建議溯源）

- [System reminders: steering agents — michaellivs.com](https://michaellivs.com/blog/system-reminders-steering-agents/)（2026）— 40+ 條注入使用者訊息的機制描述
- [Leaked AI coding system prompts — geeky-gadgets.com](https://www.geeky-gadgets.com/leaked-ai-coding-system-prompts/)（2026）— **Cursor 外流 prompt，未經官方證實，多篇報導疑為轉載同一文本**
- [What is prompt versioning — Braintrust](https://www.braintrust.dev/articles/what-is-prompt-versioning) — golden dataset、prompt drift（**評測工具廠商自述，非任何一家 harness 廠商的實際流程**）
- Milvus / zilliztech：《Claude Code Memory System Explained: 4 Layers, 5 Limits, and a Fix》— grep-based 檢索、200 行索引上限、memsearch 混合模式；另有獨立 dev.to 文章印證同一結論
- Northflank 技術部落格（2026）— Docker/gVisor/Firecracker/Kata 隔離強度光譜、seccomp 44/300+ syscalls
- getmrmr blog — approval fatigue 作為安全漏洞的論述
- n8n **CVE-2026-25049**（CVSS 9.4–9.8，五家獨立資安廠商交叉驗證）— AST-based sandbox 型別混淆導致 RCE，已於 1.123.17 / 2.5.2 修補
- Ona 平台 agent 停用自身 sandbox 案例 — **傳聞級，單一二手轉述，未找到一手事故報告**
- 客服場景多 agent 成本案例（$47,000 vs $22,700，2.1pp）— **單一部落格轉述**
- Cursor Rules 2026 指南多篇 — `.cursorrules` 在 Agent mode 不載入（**LOW，無官方核實**）

### 團隊內部產出

- `tasks/scratch/deep-research-teams/2026-07-31-19h11/scope.md` — 原始研究範圍
- `tasks/scratch/deep-research-teams/2026-07-31-19h11/source-corpus.md` — scout 建立的來源池
- `A-claims.json` / `A-summary.md`（20 claims，system prompt 組裝與 harness 解剖）
- `B-claims.json` / `B-summary.md`（17 claims，工具層設計）
- `C-claims.json` / `C-summary.md`（24 claims，context 管理與記憶）
- `D-claims.json` / `D-summary.md`（17 claims，權限與 sub-agent orchestration）
- `gap-report.md` — sweep 階段的對抗性覆蓋度檢查（13 個 gap target，coverage_score 4/5）
