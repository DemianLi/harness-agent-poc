# Topic: System prompt 組裝與分層 + harness 整體解剖

## Key Findings

- **Anthropic API 本身就有固定的組裝順序**：帶 `tools` 參數的請求會被自動包成「固定工具說明 → 工具 JSON Schema → 使用者 system prompt → 工具設定」的模板，且 Sonnet 5/4.6/4.5、Haiku 4.5 會被自動注入 `<budget:token_budget>` 與 `<system_warning>` 標籤——這代表「system prompt 組裝」不是從 Claude Code 才開始，而是從 API 契約層就已經分層了（A-001、A-002，皆為官方文件並經本人直接 WebFetch 逐字核實）。
- **Claude Code 的 system-reminder 機制是「注入使用者訊息，不是注入 system prompt」**，目的是保留 prompt cache，代價是使用者看不到，且被社群質疑與 prompt injection 難以區分；一名研究者的實測（GitHub issue #17601）指出 32 天內超過 1 萬次隱藏注入，消耗 15-50% context window，且針對「檔案是否為 malware」的警告 100% 為偽陽性（A-003、A-004）——這是本研究找到的最扎實的「代價」證據。
- **Claude Code 的 system prompt 不是單一字串，而是 500+ 條件載入片段**，分成 Core Identity / Orchestration / Specialized Agents / Security / Utilities / Context Management 六大類，採「可全域快取的靜態前綴 + session 專屬動態後綴」設計，記憶依 enterprise→user→project→local 五層優先序注入（A-005、A-006、A-007）。
- **業界對「harness 整體分層」已有多套獨立提出但方向收斂的模型**：VILA-Lab 的 5 層（UI / Agent Loop / Permission / Tools&Extensions / State&Persistence，核心論點「98.4% 是基礎設施」）、學術論文 Inside the Scaffold 的 3 層（控制架構 / 工具環境介面 / 資源管理）、OPENDEV 論文的三大工程挑戰（context / 破壞性操作防護 / 工具預算）彼此不衝突，本研究據此整合出一套 10 層骨架（A-018）。
- **Cursor 與 ChatGPT 的分層資訊來源品質明顯弱於 Claude Code**：Cursor 只有「外流」部落格文章（非官方證實），ChatGPT 的分層描述來自第三方記憶工具廠商部落格，兩者皆標為 LOW confidence，這是本主題一個明確的覆蓋缺口（見 Unresolved）。

## Detailed Findings

### 1. 正式產品的 system prompt 由哪些片段組成、注入時機為何

從最底層往上看，system prompt 的組裝其實分好幾層，而且不是從 Claude Code 這類 harness 才開始：

**API 契約層（L0）**：According to [Anthropic 官方文件](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)（2026），只要請求帶 `tools` 參數，API 就會自動組出固定模板：「你有一組工具可用」的說明 + 格式化指示 → 工具的 JSON Schema 定義 → **使用者自訂的 system prompt** → 工具設定（`tool_choice` 等）。這代表在最底層，工具說明就已經被放在使用者自訂 system prompt「之前」——這一點對 Topic B 的工具層設計很關鍵，因為工具描述的 token 成本是計入這個固定前綴，而非「附加」的（此發現由 topic-B 獨立發現並轉發，我以 WebFetch 直接驗證原文逐字相符，見 A-001）。同一層還有一個開發者完全不能控制的自動注入：According to [context-windows 文件](https://platform.claude.com/docs/en/build-with-claude/context-windows)，Sonnet 5/4.6/4.5 與 Haiku 4.5 每次請求的 system prompt 都會被塞入 `<budget:token_budget>200000</budget:token_budget>`，每次工具呼叫後再塞入 `<system_warning>Token usage: X/Y remaining</system_warning>`——文件明講「你永遠不用自己送這些標籤，API 會注入」（A-002；此發現由 topic-C 獨立發現並轉發，我已直接核實原文）。值得注意的是 Opus 4.7 以後的 Opus 模型、Fable 5、Mythos 5 反而**不會**收到這組自動注入，改成要開發者自己設定的 beta 版 task budgets——同一家公司在不同模型線上對「自動注入 vs 開發者顯式控制」做了不同選擇，這本身就是分層設計的取捨案例。

**靜態身分/行為層（L1）+ 環境與專案層（L2）**：According to [noelzappy/claude-code-system-prompts](https://github.com/noelzappy/claude-code-system-prompts)（2026，逆向工程/行為觀察）、[Piebald-AI/claude-code-system-prompts](https://github.com/Piebald-AI/claude-code-system-prompts)（2026-07-24，直接從編譯後 JS bundle 萃取字串），Claude Code 的 system prompt 由 500+ 個條件載入片段組成，歸為六類：Core Identity、Orchestration（多工作者 4 階段流程）、Specialized Agents（verification/exploration/agent-creation/terminal）、Security & Permissions（2 階段安全分類器）、Utilities（session 搜尋、記憶選取、進度摘要）、Context Management（壓縮、session 回顧）。組裝上採「globally cacheable prefix（靜態身分/行為）+ session-specific suffix（動態環境細節、記憶內容、model overrides）」——這正是為了配合 prompt caching：只要前綴不變就能重複命中快取，環境資訊（cwd、git status、日期）等易變內容則放到後綴，不拖累快取命中率（A-006）。CLAUDE.md/AGENTS.md 這類專案層記憶注入依 enterprise config → user global → project shared → project rules → local private config 五層優先序疊加，支援巢狀 `@include`（最大深度 5）。VILA-Lab 的獨立分析（[Dive-into-Claude-Code](https://github.com/VILA-Lab/Dive-into-Claude-Code)）給出方向一致但層數略有出入的說法：「4-level CLAUDE.md hierarchy (managed, user, project, local)」，並強調一個關鍵區分——CLAUDE.md 等專案指令是作為「使用者 context（機率性遵從）」注入，而非放進「system prompt（確定性）」，這解釋了為什麼專案層規則有時會被模型「忽略」：它從架構上就不是「指令」層級，是「建議」層級（A-009）。

Piebald-AI 的 CHANGELOG（追蹤 v2.0.14 以來 246+ 個版本）顯示每次 Claude Code 版本更新都會動到多個 prompt 片段——這代表「system prompt 版本控管」在 Claude Code 這樣的產品裡，實質上等同於「產品版本控管」的一部分，而不是獨立的 prompt-ops 流程（A-007，[CONNECTS TO: 這對本研究聚焦問題 4 是重要背景，但沒有找到 Anthropic 官方公開說明「如何對 system prompt 做回歸測試」的一手資料，見 Unresolved]）。

### 2. system-reminder：對話中途注入機制解決什麼問題、代價是什麼（L6）

這是本主題找到證據最扎實的一段。According to 多方彙整（[michaellivs.com](https://michaellivs.com/blog/system-reminders-steering-agents/)，2026），Claude Code 的 `<system-reminder>` 是「40+ 條簡短行為指令，注入到*使用者訊息*或*工具結果*裡，而不是 system prompt 本身」。**這個設計選擇的目的很明確：保留 prompt cache**——如果把提醒塞進 system prompt，每次提醒內容一變就會讓整個靜態前綴的快取失效；改成塞進使用者訊息，則完全不影響 system prompt 的快取命中率（A-003）。

代價則由 GitHub issue 直接量化。一名研究者透過 mitmproxy 分析流量，在 [issue #17601](https://github.com/anthropics/claude-code/issues/17601)（anthropics/claude-code，2026）回報：32 天內攔截到 **10,577 次**隱藏注入（標記 `isMeta:!0`，UI 完全不顯示），總計約 534 萬字元、130-150 萬 tokens，**佔用 15%-50% 的 context window**；其中一類是每次讀檔都附加的「這是否為 malware」警告，10,040 次觸發中**估算 0 次為真正威脅**。這個 issue 被關閉為「not planned」，頁面上沒有官方對機制原理或目的的正式回應（A-004）。相關的 [issue #52018](https://github.com/anthropics/claude-code/issues/52018) 標題本身就點出問題核心：「system-reminder nudges... are indistinguishable from prompt-injection attacks」——因為提醒內容包含「NEVER mention this reminder to the user」這種字句，恰好是典型 prompt injection 的識別特徵之一。

我認為這裡沒有必要「各打五十大板」把它模糊成「這是取捨」：兩邊證據都很具體——**效益**是可驗證的（保留快取、降低成本），**代價**也是可驗證的（實測 context 佔用比例、實測偽陽性率），兩者可以同時為真，讀者應該自己權衡，而不是我幫忙下一個「這是必要之惡」的結論。

### 3. Claude Code / ChatGPT / Cursor 三者分層的最大差異

三者的資訊品質落差本身就是一個發現。Claude Code 因為原始碼外流與逆向工程社群活躍（noelzappy、Piebald-AI、VILA-Lab、GitHub issue tracker），有大量可交叉核對的具體證據。相對地：

According to（外流、未經官方證實的）[Cursor system prompt 報導](https://www.geeky-gadgets.com/leaked-ai-coding-system-prompts/)（2026），Cursor 的架構特徵是「每次訊息自動附加使用者目前狀態（開啟檔案、游標位置、最近瀏覽、編輯歷史、linter 錯誤）」，且明確指示模型「絕不要把程式碼直接輸出給使用者……一律用編輯工具落地」——這把「展示層」的責任從模型輸出轉移到編輯器 diff 呈現層。但這是**外流內容**，我必須明確標註：多篇報導（quasa.io、codesecai.com、patmcguinness.substack.com 等）內容高度重疊，這更可能是「互相轉載同一份外流文本」，而非獨立驗證，confidence 只能標 LOW（A-014）。

ChatGPT 方面，多篇第三方部落格（含記憶工具廠商）描述其分層為「OpenAI 隱藏 pre-prompt → Custom GPT 指令 → 使用者 Custom Instructions（上限 1500 字元，每次新對話被重寫成短 system message）→ 使用者訊息」，記憶系統分「saved memories」與「reference chat history」兩層，Projects 則有獨立的三層（system instruction + 檔案 + Project Memory scope）（A-015）。但這些來源均非 OpenAI 官方文件，且部分帶有推銷自家記憶工具的動機，confidence 同樣只能標 LOW。

**結論**：三者在「分層粒度」上最大的差異，不是架構本身的差異（三者本質上都是「靜態身分層 + 使用者可控偏好層 + 動態上下文層」），而是**透明度與可驗證性的差異**——Claude Code 因為原始碼外流而被逆向工程到片段等級並可交叉比對版本演進；Cursor 只有零星外流；ChatGPT 完全依賴官方模糊帶過的產品文案與第三方猜測。這個「透明度落差」本身就該寫進最終報告，而不只是「三者架構差不多」這種淺層結論。

### 4. prompt 版本控管與回歸測試

According to [Braintrust 的 prompt versioning 文章](https://www.braintrust.dev/articles/what-is-prompt-versioning)（2026）與相關 promptfoo 文章，業界共通做法是：把 prompt 當程式碼版本控管、用 50-200 筆涵蓋核心/邊界/對抗情境的「golden dataset」做多層次評測、比對歷史基準分數偵測「prompt drift」、上線前先過 staging（A-016）。**但這是評測工具廠商（Braintrust、promptfoo）自己的說法**，我沒有找到 Anthropic、OpenAI、Cursor（Anysphere）任何一家官方公開說明「自家 system prompt 如何做版本控管與回歸測試」的一手資料——這是本聚焦問題最明確的覆蓋缺口，應在 Unresolved 中標註，而不是假裝已經回答。Piebald-AI 的 CHANGELOG（A-007）雖然證明 Claude Code 確實有版本追蹤，但那是「逆向工程觀察到的結果」，不是「官方說明的流程」。

### 5. 整合骨架（本研究的額外交付）

本研究額外負責提出一套站得住腳、供後續 25 篇引用的分層模型（完整內容見 A-018）。依據多個獨立來源交叉比對（VILA-Lab 5 層、Inside the Scaffold 3 層、OPENDEV 三大挑戰、noelzappy 可快取前綴/後綴模型、Anthropic 官方 harness=context engineering 定義），整合為 **10 層**：

L0 模型 API 契約層（固定工具模板、context-awareness 自動注入，開發者不可修改）→ L1 靜態身分/行為層（可全域快取前綴）→ L2 環境與專案上下文層（CLAUDE.md 階層、環境資訊，可變後綴）→ L3 工具層（schema、MCP，Topic B 負責）→ L4 context window 管理層（compaction、cache 邊界，Topic C 負責）→ L5 長期記憶層（跨 session 持久化，Topic C 負責，與 L4 差異在於「本輪工作記憶」vs「跨對話長期記憶」）→ L6 對話中途動態注入層（system-reminder、system_warning，注入使用者訊息而非 system prompt）→ L7 權限/sandbox 層（deny-first、傷害半徑控制，Topic D 負責）→ L8 子代理 orchestration 層（task 分派、context 隔離，Topic D 負責）→ L9 應用/UI 層（CLI/SDK/IDE、hooks）。

與 topic-D 交叉驗證後達成一個重要邊界共識：**L1/L6（政策/說服層，本主題負責）與 L7（傷害半徑層，Topic D 負責）是 defense-in-depth 關係，不是互斥**——L1/L6 處理「模型會不會被說服去做壞事」，L7 處理「就算模型被說服了，實際能造成多大傷害」。這兩層的失效模式也不同：L1/L6 失效是 prompt injection/jailbreak，L7 失效是 approval fatigue 或白名單未被實際強制（topic-D 以 [anthropics/claude-agent-sdk-typescript issue #172](https://github.com/anthropics/claude-agent-sdk-typescript/issues/172) 證實後者確有實例，見 A-020）。這個「宣告式設定 vs 執行期實際強制」的落差，本身就該列入整份研究的失敗模式清單——**架構圖上畫的分層，不等於程式碼裡實際強制的分層**。

[CONNECTS TO: Topic D — 骨架 L7/L8 的邊界劃分與 defense-in-depth 共識已於訊息中確認]
[CONNECTS TO: Topic C — 骨架 L4/L5 的區分（工作記憶 vs 長期記憶）建議 Topic C 在其輸出中明確採用或反駁這個切法]
[CONNECTS TO: Topic B — 骨架 L0/L3 的邊界（API 固定工具模板 vs 工具層可控設計空間）建議 Topic B 核對]

### harness-agent-poc 缺口初步比對

依專案背景描述，harness-agent-poc 目前的 memory / compact / HITL 三個 middleware 大致對應到 L5（記憶）、L4（context 管理）、L7（僅涵蓋人機核准部分）。初步比對顯示可能缺少：L1/L2 的可快取前綴/可變後綴分離設計、L6 對話中途動態注入層、L3 工具層的延遲載入/數量控管、L8 子代理 orchestration（A-019）。**這只是基於專案背景文字描述的定性推論，我沒有讀取 harness-agent-poc 的實際原始碼**（任務範圍不允許，也超出網路研究範疇），建議 sweep agent 或熟悉專案程式碼的角色複核。

## Investigation Log

- **From corpus：** 使用 #3（arxiv 2603.25056，system prompt attack surface）、#4（Medium Claude Code prompt architecture，實際被 403 擋下，改用 noelzappy/Piebald 替代）、#5（noelzappy repo，高度使用）、#6（dbreunig blog，被 403 擋下，改用 WebSearch 摘要 + 找到 mindstudio/kotrotsos 等替代來源）、#7（LPCI 論文，因時間限制未深入，判斷與 system-reminder 議題方向重疊但非本次核心）、#19（Inside the Scaffold，經 WebSearch 取得摘要）、#22（Arbiter interference detection，因時間限制未深入）、#30（Code as Agent Harness，因時間限制未深入，改用更直接相關的 arxiv 2603.05344 與 Anthropic 官方 harness 部落格）。
- **Supplementary searches：** "Piebald-AI claude-code system prompt reverse engineering"、"Cursor system prompt leaked rules"、"ChatGPT system prompt layers custom instructions"、"system-reminder Claude Code injection mechanism"、"system prompt version control regression testing"、"Inside the Scaffold taxonomy"、"Building Effective AI Coding Agents for the Terminal"、"Anthropic Effective harnesses for long-running agents"。
- **Discarded：** #4 Medium 文章（付費牆，僅取得標題與摘要，未列入正式 claims）；多篇 SEO 特徵明顯的「Cursor leaked prompt」文章互相轉載同一份文本，僅取其中一篇作為 LOW confidence 來源，不重複列為多方佐證。
- **Contradictions debated：** 與 topic-D 就 VILA-Lab「7層安全防護/deny-first」說法是否過度簡化進行討論——topic-D 提出 GitHub issue #172 的執行期落差證據，雙方同意將該 claim 下修為 MEDIUM confidence 並附上但書（見 A-010、A-020），非各打五十大板，而是明確標註「宣稱 vs 實際強制」的落差為獨立發現。
- **Peer findings incorporated：** 採納 topic-B 的 API 工具層固定模板發現（並自行核實，見 A-001）；採納 topic-C 的 context-awareness 自動注入標籤發現（並自行核實，見 A-002）；採納並回應 topic-D 的 defense-in-depth 分工提案（見整合骨架章節）。
- **Adversarial search results：** GitHub issue #17601、#52018（anthropics/claude-code）提供了 system-reminder 機制最扎實的「代價」證據（context 佔用、偽陽性率、透明度爭議）；GitHub issue #172（claude-agent-sdk-typescript）提供了「權限分層宣稱 vs 實際強制」落差的具體案例。
- **Challenges issued：** 對 topic-C 的「markdown 完勝 vector DB」說法提出挑戰（過度概化風險：LLM header-scan 有 cardinality 上限、選取機制本身有推論成本），topic-C 已接受並改為「trade-off」框架呈現，並補充 Milvus/zilliztech 的產業佐證（RESOLVED，非我方 claims，供讀者參照 topic-C 輸出）。
- **Challenges received：** topic-D 對 A-010（VILA-Lab「7層安全防護」）提出挑戰，已達成共識：下修 confidence 為 MEDIUM 並附上 GitHub issue #172 的執行期落差證據（見 A-010、A-020，已 RESOLVED）。

## Unresolved

- **[覆蓋缺口]** 未找到 Anthropic、OpenAI、Cursor（Anysphere）任一家官方公開說明「自家 system prompt 如何做版本控管與回歸測試」的一手資料；A-016 的做法來自評測工具廠商（Braintrust、promptfoo），屬產業常規但非特定公司自證。
- **[STALE/未核實]** A-013（Anthropic「Effective harnesses for long-running agents」部落格）因官方頁面被 proxy 擋下 403，只透過 WebSearch 對第三方鏡像頁面的彙整取得內容，未能逐字核實原文，建議 sweep agent 若需要精確引用字句應另尋管道核實。
- **[LOW confidence，來源品質弱]** Cursor（A-014）與 ChatGPT（A-015）的分層描述皆僅來自外流內容/第三方部落格，非官方文件，建議在最終報告中明確標註「相對 Claude Code 資訊透明度低很多」這個落差本身，而非假裝三者資訊對等。
- **[未完全解決]** A-010（VILA-Lab「7 層安全防護、deny-first」）與 A-020（SDK 執行期落差）之間的關係已達成「應同時呈現、不可單獨引用 7 層數字」的共識，但兩個 claim 各自的 confidence 已個別標註，讀者仍需留意這是「兩份非官方來源的交叉討論」，不等於官方對此有明確立場。
- **[整合骨架本身的限制]** A-018 的 10 層骨架是研究者對多個不同層數（3/5/10）模型的整合選擇，不是業界公認的單一標準；不同來源對「層與層邊界該畫在哪」本來就有分歧（例如記憶 vs context 管理是否該分開、子代理是否算獨立一層還是工具層的特例），後續 25 篇研究引用時應視為「一個站得住腳但非唯一正確」的參考框架。
