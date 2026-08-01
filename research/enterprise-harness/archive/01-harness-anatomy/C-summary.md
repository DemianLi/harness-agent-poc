# Topic: Context window 管理 + 記憶系統

## Key Findings

- **官方 compaction 門檻遠高於 POC 現況。** Anthropic 官方 `compact_20260112` compaction 功能的預設觸發門檻是 150K tokens、最低可設 50K；而 harness-agent-poc 的 `compact.py` 把門檻寫死在 50,000 tokens——剛好卡在官方允許的最低值，代表 POC 目前壓縮得比業界建議預設值頻繁得多。（[platform.claude.com/cookbook](https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools), 2026-03-20）
- **業界的 context 管理是兩層設計，POC 只有一層。** Anthropic 把「機械式 tool-result clearing」(`clear_tool_uses_20250919`，零推論成本、只清空可重新取得的工具輸出) 和「LLM 摘要 compaction」(`compact_20260112`，處理對話語意) 明確分成兩個獨立機制，可以疊加使用。POC 的 `compact.py` 沒有 clearing 這一層，把工具結果和對話決策混在一起丟給 LLM 摘要，且摘要前還會把每則訊息硬截斷到 300 字元。
- **Compaction 系統性地丟失『晦澀細節』，不是隨機丟失。** Anthropic 自己的 cookbook 示範：3 個高層事實 100% 保留，但 3 個具體數值（附錄表格數字）0% 保留。更嚴重的是一篇 2026-06 arXiv 論文（未能核對全文，僅搜尋摘要，信心 MEDIUM）宣稱 compaction 會讓「治理性約束」被靜默抹除，跨 7 模型/1,300+ episode 使約束違反率從 0% 升至 30%。
- **Prompt caching 讓「縮短對話」不再等於「省錢」。** 快取內容仍完整佔用 context window（不會因便宜就不算 token），但打斷快取前綴（例如觸發 compaction）意味著下一輪要用 1.25x-2x 價格重建快取。POC 的 `compact.py` 完全沒有這個成本模型概念——每次 compaction 都無條件打斷快取，也沒有「至少清多少才划算」的門檻。
- **業界 2026 年出現明確的『markdown-first』記憶趨勢，但這是 trade-off 不是免費午餐**（此點經 topic-A 挑戰後修正表述）：Claude Code / Manus / OpenClaw 都用 markdown 檔案而非向量資料庫作記憶主體，理由是可檢視/可 diff/git-native；但代價是需要額外的選擇機制（LLM 掃描檔頭選檔案，或 grep-based 檢索），且有 200 行索引上限等擴展性瓶頸，業界正收斂到「markdown 為 source of truth、向量索引為可重建的衍生索引（cache）」的混合模式。POC 的 `memory.py` 是純粹的『全量無條件注入』，連 markdown-first 陣營的『選擇性讀取』都沒有做到。

## Detailed Findings

### 1. Compaction / auto-summarization 實作細節

根據 Anthropic 官方 cookbook（platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools，2026-03-20，官方一手來源），Anthropic 的 server-side compaction（`compact_20260112`）觸發門檻最低 50K、預設 150K tokens，透過 `trigger: {"type": "input_tokens", "value": THRESHOLD}` 設定，且 `instructions` 參數可完全覆寫預設摘要 prompt。實測案例中一個 335,279 tokens 的研究對話在觸發 compaction 後被壓成約 2,783 tokens 的摘要（peak context 從 335,279 降到 169,164，約 50% 減少）。

更關鍵的是**保留/丟棄的模式**：同一份 cookbook 用具體 probe 測試——3 個「高層次事實」（例如 C. elegans 壽命中位數 18 天）100% 被保留；但 3 個「晦澀細節」（附錄表格裡的 I-squared 值 61、效應量 55、PhenoAge 比值 0.72）0% 被保留。這不是隨機遺失，而是系統性地優先保留敘事性摘要、犧牲精確數值/具體引用。這與 WebSearch 找到的多篇 2026 業界文章描述一致：「消失的通常是第二輪給的限制條件、第八輪確認的精確值」，而且「失敗看起來不像失敗——對話仍在跑，token 數持續下降」。

一篇 2026 年 6 月的 arXiv 論文（"Governance Decay: How Context Compaction Silently Erases Safety Constraints in Long-Horizon LLM Agents"，2606.22528）提出更嚴重的說法：跨 7 個模型、1,300+ episode，compaction 讓約束違反率從 0% 升到 30%——早期給的『安全規則/治理約束』在可見時被遵守，但被摘要掉後同一個 agent 之後會執行原本禁止的操作。**[STALE/UNVERIFIED SOURCE 標註]**：本研究的 WebFetch 對 arxiv.org/abs 與 /pdf 兩個 URL 皆收到 403，這個數字只來自搜尋引擎摘要，未能核對論文原文的方法論定義（例如「約束」怎麼量測），信心設為 MEDIUM。但如果屬實，這對 harness-agent-poc 有直接意義：`compact.py` 的摘要 prompt 只要求保留「關鍵決策與發現、已探索的檔案、待辦事項」，並未特別要求保留「使用者早期設下的限制/規則」，理論上存在同樣的治理衰減風險。

**另一個獨立機制：Tool-Result Clearing**（`clear_tool_uses_20250919`，官方 cookbook 驗證）是跟 compaction 平行、更廉價的一層：純機械式地把舊的 `tool_result` 內容替換成 `"[cleared to save context]"`，但保留 `tool_use` 呼叫記錄；零推論成本；可設定 `keep`（保留最近 N 個工具結果）、`exclude_tools`（排除特定工具，例如 memory tool，不被清除）。實測：335,279 tokens → 173,137 tokens（48% 減少）。topic-B（peer）提供另一組數字：128,740 → 43,060 tokens（67% 減少，keep=1）。這代表 Anthropic 官方設計是**兩層**：先用零成本的機械清除（clearing）處理可重新取得的工具輸出，再用有成本的 LLM 摘要（compaction）處理真正需要語意壓縮的對話。

**對照 harness-agent-poc 的 `compact.py`**：只有一個路徑——`maybe_compact()` 在超過 50K tokens 時，把除了最後 10 則訊息外的所有訊息（不分是工具結果還是對話）都截斷到 300 字元、串接成一段文字，丟給 LLM 做單次摘要。這與官方標準做法有三個明確落差：(1) 沒有 tool-result clearing 這個零成本前置層；(2) 摘要前的 300 字元硬截斷，比 LLM 摘要本身更粗暴地丟資訊——任何完整檔案內容或長 tool result 的尾端直接被砍掉，LLM 根本看不到；(3) 門檻設在業界建議的最低值。

### 2. Prompt caching 如何改變成本模型

根據 Anthropic 官方文件（platform.claude.com/docs/en/build-with-claude/prompt-caching，官方一手來源）：
- **TTL**：預設 5 分鐘 (ephemeral)，可付費延長到 1 小時；快取在 TTL 內每次被讀取都會免費刷新。
- **定價倍率**：5 分鐘 cache write = 1.25x 基礎 input 價；1 小時 cache write = 2x；cache read = 0.1x（即只收 10% 原價）。
- **最小可快取前綴長度**依模型而異：512～4,096 tokens 不等（Opus 5 最低 512，Haiku 4.5 需 4,096）；短於此長度無法被快取，且不會報錯，只能靠 `cache_creation_input_tokens`/`cache_read_input_tokens` 是否出現來驗證。
- **失效規則是階層式的**：`tools → system → messages`。改工具定義會讓三層全失效；改 web search/citations/speed 設定會讓 system+messages 失效；改 `tool_choice` 或圖片只會讓 messages 失效。任何對已快取內容的修改都會產生不同前綴 hash，強制重建 cache。

最重要的概念性發現（官方文件明確陳述）：**「快取的 prompt 前綴仍然完整佔用 context window：prompt caching 改變的是你付多少錢，不是它算不算 token。」** 這代表 context 管理決策不再只是「token 數多寡」的單一維度，而是「打斷快取前綴的代價」這個第二維度——過早或過度頻繁的 compaction 即使降低了 token 數，也可能因為打斷快取前綴、強迫下一輪以 1.25x-2x 價格重建快取而**提高**實際成本。這正是官方 `clear_tool_uses_20250919` 提供 `clear_at_least` 參數（至少清除多少 tokens 才值得動作）的設計理由。

**[CONNECTS TO: Topic B]** — topic-B（peer）補充了一個直接互補的細節：Tool Search Tool 的 `defer_loading: true` 讓工具定義不進入 system prompt 前綴、直到被搜尋到才展開，因此**工具庫變大不會使 prompt cache 失效**（因為沒進前綴）。這與本研究的 cache-invalidation 階層規則是同一個機制的兩面：topic-B 講的是「怎麼避免落入 tools 層」，我講的是「一旦落入某層，怎麼算失效範圍」。

**POC 現況（`compact.py`）完全沒有這個成本模型**：沒有任何 `cache_control`、`cache_read_input_tokens` 相關邏輯；`COMPACT_THRESHOLD` 是純 token 數門檻，跟「打斷快取的代價」無關；每次 compaction 都無條件地用一個全新的 summary `HumanMessage` 取代舊訊息，這必然打斷任何既有快取前綴，卻沒有評估這個代價是否划算。

**[CONNECTS TO: Topic A]** — Anthropic 的 context awareness 機制（Sonnet 5/4.6、Haiku 4.5 自動啟用，Opus 4.7+/Fable 5/Mythos 5 則需手動設定 beta task budgets）會在每個請求的 system prompt 注入 `<budget:token_budget>200000</budget:token_budget>`，並在每次 tool call 後注入 `<system_warning>Token usage: X/Y remaining</system_warning>`。這是開發者無法關閉、API 自動注入的系統提示片段，性質上更接近 topic-A 負責的「system-reminder 注入」而非本研究的手動配置項——已通知 topic-A 並得到其確認補充（model-dependent 的細節）。

### 3. 記憶系統：可編輯 Markdown 檔 vs. 向量檢索

Anthropic 官方 memory tool（`memory_20250818`）是**agent 主動 pull** 的模式：protocol 明確要求「先看 `/memories` 目錄再做任何事」，支援 view/create/str_replace/insert/delete/rename 六種操作，內建路徑穿越防護。跨 session 的實測效益很明顯：沒有記憶時 Session 2 要重讀 4 份文件（~108K tokens）；有記憶時只需載入一份 ~3K tokens 的摘要檔。

業界 2026 年出現明確的「markdown-first」趨勢：多篇獨立 DEV Community / Medium 文章（交叉印證）指出 Claude Code、Manus、OpenClaw 等高流量正式產品都用純 markdown 而非向量資料庫作記憶主體，理由是檔案可檢視、可 diff、可攜、git-native；Claude Code v2.1.33（2026年2月）甚至讓每個 subagent 都有專屬的 markdown memory frontmatter。

**但這不是無條件的勝利**——topic-A（peer）在此提出了直接挑戰，我接受並修正表述：VILA-Lab 的 "Dive into Claude Code" 分析（topic-A 引用，本研究未直接查證，故列為 peer-corroborated MEDIUM）顯示 Claude Code 實際做法是「LLM 掃描 memory 檔案標頭、最多選 5 個相關檔案，無 embedding、無向量相似度」——這仍然需要一個選擇機制，只是用 LLM 呼叫成本取代向量基礎設施成本，不是真正免費。獨立地，Milvus/zilliztech 部落格（"Claude Code Memory System Explained: 4 Layers, 5 Limits, and a Fix"）給出更具體的量化限制：grep-based 檢索（甚至不是 LLM 掃描）加上 200 行索引上限，兩者共同造成「專案歷史累積後」的擴展性瓶頸；同標題被另一篇獨立 dev.to 文章印證（"Claude Code's Memory: 4 Layers of Complexity, Still Just Grep and a 200-Line Cap"）。**業界正在收斂到的模式是「markdown 為 source of truth、向量索引（如 Milvus/memsearch 的做法）為可隨時從 .md 重建的衍生索引」**——不是二選一，而是分層：markdown 負責可信度與可攜性，索引負責檢索效率。

**Per-user vs per-project 記憶怎麼分**：業界慣例（WebSearch 交叉驗證多篇 2026 guide）是三層：Global（`~/.claude/`，跨所有專案，個人偏好）、Project（隨 repo 走，團隊共享）、Auto Memory（每個 git repo 一個獨立目錄，例如 `~/.claude/projects/<project>/memory/`，agent 自動記筆記）。優先序：System instructions > Global CLAUDE.md > Project CLAUDE.md > CLAUDE.local.md > Auto memory > 對話歷史 > 已壓縮摘要。

**POC 的 `memory.py` 對照**：兩個明確落差。(1) **推 vs 拉**——`memory.py` 是無條件全量注入（session 開始時把整個 AGENTS.md + 整個 repo 記憶檔塞進 system prompt），沒有任何篩選/大小上限/agent 主動查詢，這與官方 memory tool 的「agent 主動 view、選擇性讀取」相反，甚至比 markdown-first 陣營自己的「LLM 掃描選 5 個檔案」還原始。(2) **「global」名不符實**——`GLOBAL_MEMORY_FILE` 實際存在 `_PROJECT_ROOT/memory/AGENTS.md`（相對於程式碼所在的 repo），而不是使用者家目錄；這其實是「第二個專案層級檔案」，任何複製這個 repo 的人都共享同一份「global」記憶，跟業界慣例的「per-OS-user、與 repo 無關」不同——多使用者情境下，使用者 A 的姓名偏好等個人化設定會被寫進 repo 並被所有人共用、被 git 追蹤。

### 4. 失敗模式

- **Compaction 丟掉關鍵資訊**：見上述「3/3 vs 0/3」的具體證據，以及 Governance Decay 論文的治理衰減假說（MEDIUM confidence，未核對全文）。
- **記憶污染/過期（staleness/poisoning）**：多篇 2026 guide（HackerNoon 等，交叉印證）指出「coding agent 的記憶會隨每次合併的 PR 過期」，若記憶檔說「認證邏輯在 src/auth/handlers.ts」而該檔案被搬移，agent 會自信地在錯誤位置找——這是「過期資訊主動誤導」而非單純資訊不足。20+ 並發 agent 寫入同一記憶檔會出現「寫入衝突、過期讀取、無人協調的矛盾條目」。`memory.py` 對此完全沒有防護：無行數上限、無時間戳記、無過期機制，append-only 的更新指示意味著記憶檔會無限成長，舊條目永遠不會被標記過期或移除。
- **Context rot**：Anthropic 官方文件本身承認「token 數增加，準確率與回憶能力下降」，並將此列為 context 管理的核心動機（而非邊緣案例）。Zylos Research 2026 調查（WebSearch 摘要，未直接查證全文，故信心 MEDIUM）稱 65% 的 2025 企業 AI 失敗源於推理過程中的 context degradation，而非單純 token 超限——如果屬實，這意味著「多壓縮一點」不必然更安全，因為壓縮本身也是一種 context 操作，可能引入新的 rot/資訊損失。
- **[CONNECTS TO: Topic D]**：topic-D（peer，直接 WebFetch 驗證 code.claude.com/docs/en/sub-agents.md）指出 subagent 執行在完全獨立的 context window，父子之間不共享 conversation prefix，因此 orchestrator→subagent 邊界原則上是 prompt-cache miss（我方 cost model 應假設如此，本研究未直接查證此一手來源，信心 MEDIUM，僅轉引 peer 驗證結果）。topic-D 也指出一個已確認的 GitHub open issue（anthropics/claude-agent-sdk-typescript#172，本研究未直接查證，信心 LOW，僅轉引）：sub-agent 的工具權限白名單在 child process 層級未被強制執行。合併來看，這代表『宣告式的隔離設計（context 隔離、memory 隔離、tool 權限隔離）』在文件層面講得很乾淨，但至少兩處（工具權限強制、memory 跨 agent 同步）目前沒有 runtime 機制真正兜住。

## Investigation Log

- **From corpus：** 使用 corpus 來源 #1（context windows 官方文件）、#2（context engineering cookbook）、#12/#26（prompt caching，corpus 標記 PARTIAL，改用官方 prompt-caching 文件直接驗證）、#13/#14（markdown-first 記憶，corpus 標記 accessible 但實際 WebFetch 回 403，改用 WebSearch 取得摘要）、#15（memweave，未直接查證，時間有限跳過）、#25（Beyond Similarity 論文，corpus 標記 PARTIAL，未查證，跳過）、#28（Zylos memory architectures，corpus 標記 PARTIAL，用 WebSearch 摘要間接引用）。
- **Supplementary searches：** "context compaction loses information agent failure mode 2026"、"markdown-first agent memory vs vector database Claude Code Manus 2026"、"Claude Code memory system 4 layers 5 limits markdown fix Milvus memsearch"、"AGENTS.md OR CLAUDE.md memory pollution stale conflict codebase drift"、"Claude Code memory per-user global vs per-project CLAUDE.md scope hierarchy 2026"。
- **Discarded：** dev.to codingsimba/whoffagents 兩篇 markdown-first 原始文章、Milvus blog、harmix blog、getunblocked.com、arxiv 2606.22528 全文——皆回傳 403（proxy block），改用 WebSearch 摘要作為次級來源，並在對應 claim 中標註信心等級與未核對全文的限制。
- **Contradictions debated：** 與 topic-A 就「markdown 記憶是否『完勝』向量資料庫」進行辯論——topic-A 主張這是有上限的選擇機制（LLM 掃描選 5 檔）而非免費解法，本研究接受並將 C-010 改為 trade-off 表述，同時用 Milvus 來源（C-011）獨立佐證擴展性瓶頸確實存在。
- **Peer findings incorporated：** topic-A（VILA-Lab 記憶檔頭掃描機制、context-awareness 的 model-dependent 細節）；topic-B（clear_tool_uses_20250919 的官方參數細節與實測數字、tool search tool 的 defer_loading 與 cache 穩定性關聯）；topic-D（subagent 獨立 context window 導致跨邊界 cache miss、GitHub issue #172 工具權限未強制執行）。
- **Adversarial search results：** 找到 Governance Decay 論文（compaction 使治理約束違反率 0%→30%，但未能核對全文）、markdown 記憶的 staleness/poisoning/多 agent 衝突問題、Milvus 部落格對 markdown-first 陣營自己承認的 5 個結構性限制（grep-based 檢索、200 行上限）。
- **Challenges issued：** 無主動發起對 topic-A/B/D 具體 claim 的直接反駁挑戰（本研究收到 topic-A 的挑戰並回應，屬於「被挑戰」而非「發起挑戰」）；但在協調訊息中對 topic-B 提出一個查證請求（cookbook 範例的 trigger 預設值 30K vs topic-B 引用的 100K，建議雙方各自對照官方文件確認實際 API 預設值——此為潛在數字落差，未及在時限內解決，列入 Unresolved）。
- **Challenges received：** topic-A 對「markdown 完勝向量資料庫」提出 CHALLENGE，本研究已接受並修正 claim 表述（C-010），標記為 [CONTESTED→RESOLVED]。

## Unresolved

- **Governance Decay 論文（arXiv 2606.22528）的 30% 約束違反率數字未經全文核對**——本研究的 WebFetch 對該論文全文（abs 與 pdf 兩個 URL）皆遭 403 阻擋，僅能引用搜尋引擎摘要。建議 sweep 階段標記為 [UNVERIFIED — 僅搜尋摘要，未核對原文方法論]。
- **`clear_tool_uses_20250919` 的實際 API 預設 trigger 值**：本研究引用的 cookbook 範例顯示 trigger 範例值 30K-50K，但 topic-B 引用的訊息中提到「預設100K tokens」——雙方都是引用同一份 cookbook 的不同範例段落，未能在時限內查證官方 API 文件的實際預設值（cookbook 範例可能不等於 API 預設）。建議 sweep 或後續查證 platform.claude.com/docs/en/build-with-claude/context-editing 的正式 API 參數表。
- **VILA-Lab "Dive into Claude Code" 的原文**未被本研究直接查證（僅透過 topic-A 轉述），若需要更高信心應直接 WebFetch 該 repo。
- **memweave（corpus 來源 #15）與 Beyond Similarity 論文（corpus 來源 #25）**因時間限制未深入查證，可能包含與本研究記憶失敗模式相關的額外證據，屬覆蓋缺口。
- **本研究未找到任何直接批評『prompt caching TTL 機制本身』的一手來源**（例如 TTL 5 分鐘是否對長時間思考任務造成實務問題）——僅有定價與失效規則的說明文件，缺乏使用者實際踩坑的一手報告，這是本主題的覆蓋缺口，明確標註為缺口而非「沒有問題」。
