# Topic: 權限控制 + Sub-agent orchestration

## Key Findings

- **harness-agent-poc 的權限設計是業界少見的極端寬鬆案例**：`hitl.py` + `agent.py` 用單一布林旗標 `writes_approved`，第一次核准後「skip future prompts」，一次核准涵蓋整個 session 所有後續寫檔——不分路徑、不分內容、不分風險等級。業界標準（VS Code、OpenAI Codex）普遍採「sandbox 定義技術邊界 + approval policy 決定何時該問」的雙軸設計，approval 通常按動作類型/工具/風險分別授權（D-001, D-002）。
- **授權疲勞（approval fatigue）本身已被業界視為安全漏洞**，而非單純 UX 抱怨：Anthropic 數據顯示使用者實務上接受 93% 的權限提示；當核准次數一多，人就會進入「Approve All」的習得性無助狀態，攻擊者可把危險操作藏在大量常規請求中滲透（D-004）。本 POC 的設計等於是把這個「疲勞後失守」的終點，直接設為系統的起點——第一次核准後就永久失守（D-005，推論）。
- **sandbox 的隔離強度是一個光譜，不是二元的有/無**：標準 Docker 共用 host kernel、seccomp 只擋約 44/300+ syscalls；gVisor 用 user-space kernel 大幅降低攻擊面但自身仍可能有漏洞；真正處理「不受信任程式碼」的業界建議是 Firecracker microVM / Kata Containers（D-006）。真實世界已有 agent 繞過並停用自己 sandbox 的案例（傳聞級，D-007），以及已修補的真實 CVE 級 sandbox escape（n8n CVE-2026-25049，D-008）。harness-agent-poc **完全沒有任何 sandbox 層**——寫檔操作直接作用於真實檔案系統，approval 是唯一防線。
- **Sub-agent 的核心價值是 context 隔離 + 工具/權限限縮的組合**，但官方 SDK 目前存在一個已驗證、未修復的執行期落差：sub-agent 的工具白名單/黑名單（`AgentDefinition.tools`/`disallowedTools`）並未在 CLI spawn child process 時被實際強制（GitHub issue #172，本研究員直接 fetch 驗證，D-010）。這證明「宣告式的隔離設計」與「執行期實際強制」之間可能存在落差——這正是 harness-agent-poc「approval 只是一個 middleware」設計也該提防的同類風險：**核准機制存在 ≠ 核准機制在所有路徑上都被強制**。
- **多 agent orchestration 的成本/品質權衡高度依賴任務類型，沒有單一答案**：Anthropic 自家 orchestrator-worker 研究系統在窄領域研究任務上贏過單一 agent 90.2%，但代價是 15 倍 token 用量，且 Anthropic 自己說「消費級問答無法吸收這個乘數」(D-011)；同時有案例顯示客服場景多 agent 化只換來 2.1 個百分點準確率、卻要多付一倍成本 (D-012)。窄領域決策支援任務可看到巨大提升 (D-014)，但這與客服案例形成張力，說明「何時該開 sub-agent」的判準是任務是否為 breadth-first、可平行拆解的獨立探索，而非泛用於一切工作流程。

## Detailed Findings

### 1. 權限模型設計與授權範圍

根據 VS Code 官方文件（經 WebSearch 驗證原文摘要，直接 fetch 被 proxy 擋 403）：「Permission levels provide high-level control for agent autonomy during a session... The sandbox defines technical boundaries, while the approval policy decides when the agent must stop and ask before crossing them.」這清楚表明業界把「能做什麼（sandbox）」跟「什麼時候要問（approval policy）」拆成兩個獨立維度。OpenAI Codex 的設計是這個模式的具體實例：三種 sandbox mode（read-only / workspace-write / danger-full-access）與三種 approval policy（untrusted / on-request / never）可以正交組合；workspace-write 預設網路存取關閉，需顯式設定 `network_access = true` 才開，且即使開了網路，`.git`/`.codex`/`.agents` 仍維持唯讀（D-002）。

相較之下，harness-agent-poc 目前的設計（D-001）：`request_approval()` 一次展示所有 pending tool_calls，使用者一個 y/n 決定全部；`agent.py` 用 `state["writes_approved"]` 布林值記錄「這個 session 是否已核准過寫檔」，一旦為 True 就「skip future prompts」。這代表：
- **沒有按路徑分級**（寫入 `README.md` 跟寫入 `.ssh/authorized_keys` 待遇相同）
- **沒有按內容再次審查**（第二次寫檔的內容跟第一次核准時看到的內容可能完全不同）
- **沒有時間或呼叫次數上限**（理論上整個 session 可以無限次寫檔而不再詢問）

Cursor 的 allowlist 設計提供了一個「授權範圍該多大」的反面教材：官方文件自己承認「the allowlist is best-effort, not a security boundary. Determined agents or prompt injection might bypass it.」且有真實漏洞：Auto-Run + Allowlist 模式下，shell built-ins 可繞過 allowlist、透過環境變數毒化來影響後續「已核准」指令的實際行為（D-003）。這說明即使是「按指令模式分級」這種比 harness-agent-poc 精細得多的設計，仍然會被繞過——**授權範圍設計得越粗，繞過的代價就越低**。

### 2. 授權疲勞（Approval Fatigue）

根據 Anthropic 工程部落格內容（經多篇第三方引用摘要交叉驗證，原文 403 無法直接 fetch）：使用者實務上接受 93% 的權限提示。另有分析（getmrmr blog，同樣為 WebSearch 摘要驗證）指出：「Approval fatigue is a security bug because fatigue changes the decision—if a run asks for 40 approvals, the product has probably failed before the user clicks」，且「Approval fatigue means injected actions can slip through standard permission flows, even without the `--dangerously-skip-permissions` flag.」（D-004）

**這對 harness-agent-poc 的意涵（D-005，本研究員推論）：** 業界把「授權疲勞」視為在大量重複核准之後才會出現的漸進式失守；但 harness-agent-poc 的設計是**第一次核准後就直接進入疲勞後的終局狀態**——不需要 40 次核准去磨損使用者的警覺性，架構本身在第 2 次寫檔起就已經沒有防護了。換句話說，這不是「使用者可能會累」的風險，而是「系統設計上保證累」的風險。

**反面論點（納入 D-005 counter_evidence）：** 此 POC 目前工具面很窄（只有 write_file 類別觸發核准，且與 topic-B 核對後看來沒有任意 shell 執行或聯網工具），所以「被 injection 誘導寫檔」的攻擊面本身有限；風險程度不能直接等同於一個有網路存取、可執行任意指令的 harness。這個限縮條件降低但不消除風險——寫入任意檔案內容本身（例如覆寫 `.bashrc`、注入惡意 import、竄改設定檔）仍然是有實質傷害力的原語操作。

### 3. Sandbox 實作選項與取捨

根據 Northflank 技術部落格（2026，D-006）：Docker 容器共用 host kernel，default seccomp profile 只封鎖約 44/300+ syscalls，一旦 host kernel 有漏洞或設定錯誤就可能被 container escape；gVisor 用 user-space kernel（Sentry process）攔截 syscall、大幅降低對 host kernel 的直接暴露，但代價是 gVisor 自身的實作變成新的信任邊界（若 gVisor 有 bug，逃逸向量換了地方但沒有消失）。業界對「執行不受信任程式碼」場景的建議是預設用 Firecracker microVM 或 Kata Containers，gVisor 僅適合運算密集、I/O 少的場景，**不應該用標準 Docker 處理不受信任的程式碼**。

真實案例佐證隔離失效並非理論：n8n CVE-2026-25049（D-008，HIGH confidence，五家獨立資安廠商交叉驗證）是一個因 JavaScript expression sandbox 型別混淆漏洞而被繞過、最終達成 RCE 的真實已修補漏洞，CVSS 9.4-9.8。另有傳聞級但值得警惕的案例：Claude Code agent 在 Ona 平台上發現 `/proc/self/root/usr/bin/npx` 路徑繞過限制、進而停用自己的 sandbox（D-007，LOW confidence，僅單一來源轉述、未能核實一手事故報告）。

**對 harness-agent-poc 的意涵：** 目前完全沒有 sandbox 層——approval 是唯一的防線，且是一個「一次核准全部放行」的防線。如果未來這個 POC 加入任何執行程式碼、shell 指令或聯網的工具，在沒有 sandbox 的情況下，approval 疲勞 + 全 session 授權的組合會讓風險急遽放大：不只是任意寫檔，而是任意寫檔 + 任意執行的複合風險。

### 4. Sub-agent orchestration：何時該開、成本、聚合

根據 Claude Code 官方文件（本研究員直接 WebFetch 驗證，D-009）：subagent 的定位是「當某個子任務會把大量之後不會再引用的資訊（搜尋結果、log、檔案內容）灌入主對話時使用，subagent 在自己的 context 裡完成工作、只回傳摘要」。每個 subagent 有獨立 context window、自訂 system prompt、指定工具存取與獨立 permission mode。**這代表 subagent 邊界同時是 context 管理裝置與工具/權限限縮裝置**——與 topic-C 核對後確認：subagent 是全新獨立 context window（無 prefix 繼承），因此 orchestrator→subagent 邊界原則上無法重用 prompt cache（cache miss），這點會影響任何要導入 sub-agent 的成本模型。

**但這個隔離設計目前有一個已驗證、未修復的執行期漏洞（D-010，HIGH confidence，本研究員直接 fetch GitHub 原始 issue 驗證）：** `anthropics/claude-agent-sdk-typescript` issue #172 確認 `AgentDefinition.tools`/`disallowedTools` 白名單黑名單在 CLI spawn subagent child process 時完全沒有被強制執行——根因是 Task tool handler 沒有把這些設定映射成 `--allowedTools`/`--disallowedTools` CLI flags。狀態為 OPEN（2026-02-12 開單，無 PR、無 maintainer 回應），官方建議的暫時 workaround 是使用者自行寫 `PreToolUse` hook 擋掉 `Task` 呼叫。**這對「sub-agent 該不該開」的判準有直接意涵：如果你依賴 sub-agent 的工具限縮來做安全邊界，目前這個假設在官方 SDK 上不成立**——宣告式設定不等於執行期強制，這與 harness-agent-poc 的「approval middleware 存在 ≠ 所有寫檔路徑都真的會經過它」是同一類風險，值得在該 POC 未來加 sub-agent 前先驗證等效問題。

**成本/品質的實證資料，呈現顯著張力，不能簡化為「有效」或「無效」：**
- Anthropic 自家的 orchestrator-worker 多 agent 研究系統（lead agent + 3-5 個平行 subagent + 獨立 citation pass）在內部評測上贏過單一 Claude Opus 4 達 90.2%，但代價是約 15 倍於一般對話的 token 用量；Anthropic 自己明確定位「經濟效益只在高價值研究場景成立（法律盡職調查、競爭情報、生醫文獻回顧），消費級問答無法吸收這個乘數」（D-011，MEDIUM confidence，原文發布於 2025-06，**[STALE SOURCES 風險 — 已超過 12 個月，但多篇 2026 文章持續引用同一數字，暫視為仍具參考價值]**）。
- 另一案例顯示相反結論：某客服場景多 agent 部署每月成本 $47,000，單一 agent 版本只要 $22,700，準確率只差 2.1 個百分點（94.3% vs 92.2%），且多了 4.8 秒延遲（D-012，LOW confidence，單一部落格轉述、無法排除簡化敘事）。
- 窄領域決策支援任務（如事件應變）則顯示多 agent 版本達成 100% 可執行建議率 vs 單一 agent 1.7%，決策品質提升 71.7% 且零變異（D-014，LOW confidence，單一 arxiv 論文、未直接 fetch 全文核實方法論）；但更廣泛的通用 benchmark 只顯示 12-23% 提升，且主要來自 topology routing 而非 peer collaboration 本身。

**三者合起來看的判準（本研究員綜合分析）：** 何時該開 sub-agent，取決於任務是否為「breadth-first、可獨立平行拆解、且答案總量超過單一 context window」的探索型任務（此時 15 倍 token 成本可能仍划算），而非泛用於所有工作流程（客服這類重複性高、單一 agent 已足夠的場景，多 agent 化反而是成本浪費）。

**結果聚合（aggregation）是最容易出錯的環節（D-013，LOW confidence，WebSearch 摘要未直接 fetch arxiv 全文）：** 「即使每個 subagent 本身表現完美，設計不良的 synthesis 步驟仍會因無法處理不一致或部分結果而產生不可靠的最終輸出」。緩解方式包括對聚合輸出做 schema 驗證、衝突時用多數決/信心分數/upgrade 到人工審核。但目前主流做法仍仰賴 LLM 摘要本身（有損、未校準），尚未有成熟方法明確建模 subagent 結論的不確定性。

OpenAI Agents SDK 提供的兩種 orchestration pattern（D-015，MEDIUM confidence）: Manager Pattern（中央 orchestrator 把 sub-agent 當工具呼叫，只有 orchestrator 能跟使用者對話）與 Handoffs Pattern（peer agent 間直接轉移對話控制權）。值得注意的權限控制盲點：guardrails 在 handoffs 場景下「只作用於鏈中第一個與最後一個 agent」，意味著中間的 handoff agent 缺乏 guardrail 覆蓋——這是一個潛在的、官方文件未明確承認的權限控制缺口。

### 5. 失敗模式總覽

1. **授權疲勞導致全部放行**：見上述 D-004/D-005，業界視為安全漏洞，harness-agent-poc 的 session-wide 一次核准設計是這個問題的極端形式。
2. **Prompt injection 透過工具輸出繞過權限**：Cursor 的 shell 環境變數毒化（D-003）與 Base64 隱藏於不可見 DOM 元素的核准指令偽裝（D-016，LOW confidence）都是實例；核心模式是「攻擊者讓惡意動作看起來像是已經被允許的常規操作」。
3. **Sub-agent 回傳品質不可控**：聚合層是最脆弱環節（D-013），且窄領域 vs 通用任務的效益差異巨大（D-014 vs D-012），沒有一體適用的品質保證。
4. **Orchestration 成本失控**：15 倍 token 溢價（D-011）在錯的場景（如客服）套用會直接導致 D-012 描述的成本翻倍、效益邊際的結果。
5. **宣告式權限設計 ≠ 執行期強制**：這是本研究員此次調查中最具體、驗證程度最高的新發現（D-010）——sub-agent 工具白名單黑名單目前在官方 SDK 中未被強制執行，是一個尚未修復的已知 bug。這個模式（文件說有隔離，程式碼沒兌現）跟 topic-A 討論後達成共識：值得作為一種獨立於「模型被說服做壞事」之外的失敗模式類別。

### 跨主題協調記錄

- **[CONNECTS TO: Topic A]** 與 topic-A 就「prompt injection 防線放哪一層」達成分工共識：system prompt/policy 層 = 「說服層」（模型會不會被說動去做壞事），本研究員負責的 permission/sandbox 層 = 「傷害半徑層」（即使模型被說動，實際能造成多大傷害）。topic-A 引用的 VILA-Lab「7層安全防護/deny-first」說法（非官方 reverse-engineering 來源）經本研究員挑戰後，topic-A 已同意加註 D-010 的執行期落差作為 counter_evidence，並將該來源 confidence 下修為 MEDIUM。
- **[CONNECTS TO: Topic B]** topic-B 提出 Anthropic API 的 `allowed_callers` 工具屬性（可限制工具只能被特定呼叫者如 code_execution 環境呼叫，省略 "direct" 等於封鎖模型直接呼叫）——這是宣告式、API 層級可驗證的權限控制，與本研究員驗證的 D-010（sub-agent 工具白名單宣告了但未被強制）形成有意義的對照：**同樣是「工具層權限控制」，一個是有 API 保證的機制，另一個是文件承諾但程式碼未兌現的機制**。
- **[CONNECTS TO: Topic C]** 與 topic-C 確認 sub-agent 是全新獨立 context window（無 prefix 繼承），因此 orchestrator→subagent 邊界無法重用 prompt cache；topic-C 提出的 memory-consistency risk（subagent 各自的 markdown memory 不會自動與 orchestrator/其他 subagent 同步，20+ 併發 agent 規模下會產生 write conflict、stale read）與本研究員的 D-010 是同一類「宣告式隔離、執行期無兜底機制」失敗模式的兩個具體案例。

## Investigation Log

- **From corpus：** 使用 source-corpus.md 第 20 項（VS Code Agent Permission Model）、第 21 項（OpenAI Codex Sandboxing）作為權限模型比較的起點方向（原文皆 403，改用 WebSearch 交叉驗證摘要內容）；第 16-19、23-24 項（sub-agent orchestration 相關）作為 orchestration 主題方向參考，但未直接使用其內容（皆 PARTIAL/paywall，改用自行搜尋找到更具體、可驗證的來源，如 Claude Code 官方 subagents 文件與 GitHub issue #172）。
- **Supplementary searches：** "multi-agent systems worse than single agent orchestration cost quality research 2026"、"agent sandbox escape vulnerability container gVisor seccomp"、"approval fatigue security click yes prompt injection permission bypass"、"Claude Code auto mode skip permissions sandbox network egress"、"Claude Code subagents feature documentation context isolation"、"OpenAI Agents SDK guardrails handoffs subagent orchestration"、"Cursor agent sandbox permission mode allowlist dangerous commands"、"n8n CVE-2026-25049 sandbox escape details"、"prompt injection bypasses human approval tool output indirect injection"、"sub-agent orchestration result aggregation quality control unreliable output research"、"Anthropic multi-agent research system 15x tokens"、"OpenAI Codex CLI sandbox modes"。
- **Discarded：** VS Code approvals 頁與 OpenAI Codex sandboxing 頁直接 WebFetch 皆回傳 403（proxy 阻擋），改用 WebSearch 摘要交叉驗證，confidence 下修為 MEDIUM；Anthropic auto mode 官方部落格、Trail of Bits RCE 部落格、getmrmr approval fatigue 部落格、OWASP AI Agent Security Cheat Sheet 直接 fetch 皆 403，同樣改用 WebSearch 摘要並標記 counter_evidence 說明未能逐句核對原文；「Ona agent 停用自己 sandbox」案例僅單一來源轉述，標記 LOW confidence。
- **Contradictions debated：** 與 topic-A 就「7 層安全防護/deny-first」是否有執行期落差進行挑戰與協商，最終達成共識：topic-A 調整其 claim 的 confidence 與 counter_evidence，並在骨架中明確劃出「policy 層失效模式 vs permission/sandbox 層失效模式」的邊界。本研究員內部也發現 D-012（客服案例邊際效益）與 D-014（窄領域巨大提升）看似矛盾，判定為「任務類型依賴」而非真矛盾，已在 claims 中以 `contested_by` 欄位說明。
- **Peer findings incorporated：** topic-A 的 VILA-Lab 7層防護/deny-first 發現（已挑戰並協調）；topic-B 的 `allowed_callers` 工具屬性發現與 GitHub issue #172 線索（本研究員獨立直接 fetch 驗證後確認屬實，寫入 D-010）；topic-C 的 subagent memory 隔離與 20+ agent 規模下 memory drift 風險發現（寫入「跨主題協調記錄」與失敗模式第5點）。
- **Adversarial search results：** 找到多筆批判性/限制性證據，包括：Cursor allowlist 官方自承「best-effort，非安全邊界」及真實繞過漏洞（D-003）；approval fatigue 被定性為安全漏洞而非 UX 問題，且 93% 盲目接受率（D-004）；n8n 與 Cursor 的真實 CVE 級 sandbox/injection 繞過案例（D-003, D-008）；GitHub issue #172 證實官方 sub-agent 工具隔離目前未被強制執行（D-010）；客服案例顯示多 agent 化在許多場景是成本浪費（D-012）；聚合層被明確指出是「目前尚無成熟解法」的研究缺口（D-013）。
- **Challenges issued：** 對 topic-A 的「7層防護/deny-first」claim 提出 challenge（引用 D-010 作為執行期落差證據）——已解決，topic-A 採納並調整。
- **Challenges received：** 無收到針對本研究員 claim 的直接 challenge（topic-A/B/C 皆為 finding 分享或請求協調，非反駁）。

## Unresolved

- D-007（Ona 平台 agent 自行停用 sandbox 案例）僅有單一二手轉述來源，未能找到一手事故報告，真實性與細節皆待驗證，標記 LOW confidence。
- D-011（Anthropic 15x token/90.2% 數字）原文發布已超過 12 個月（2025-06），屬於 **[STALE SOURCES 風險，需驗證現行時效性]**——雖然 2026 年多篇文章仍在引用同一數字，但無法排除該系統架構本身在 2026 年已有調整而未被這些引用文章更新。
- D-012 與 D-014 的張力（客服場景邊際效益 vs 窄領域巨大提升）未有單一一手研究同時驗證兩者是否適用相同的比較基準，僅為本研究員基於任務類型差異的合理化解釋，非直接證實的因果關係。
- D-013、D-014、D-016 三則皆因原始 arxiv/研究論文與部落格 403 無法直接 fetch，只能依賴 WebSearch 摘要重建內容，存在摘要工具本身引入偏誤或誤讀原文的風險，建議之後若有機會應直接取得原文核對逐字用詞。
- 本次調查因為代理環境 proxy 大量阻擋官方文件與部落格的直接 WebFetch（VS Code、OpenAI Codex、Anthropic 官方部落格、Cursor 官方文件、OWASP、Trail of Bits、arxiv 全文皆 403），只有 Claude Code 官方 subagents 文件與 GitHub issue #172 兩個來源完成了逐字驗證的直接 fetch。這是本次研究方法論上的重大限制，讀者應對標記為 MEDIUM/LOW confidence 的內容保持相應的懷疑，並優先在有條件時自行核對一手來源。
