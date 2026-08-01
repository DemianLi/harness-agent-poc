---
deepening_recommended: false
gap_count: 13
high_severity_gaps: 4
medium_severity_gaps: 7
contested_unresolved: 2
coverage_score: 4
---

# Gap Report: Harness 架構分層（Backlog 01）

Sweep agent 對 A/B/C/D 四位 specialist 共 78 條 claims（A 20 / B 17 / C 24 / D 17）與四份 summary 的對抗性覆蓋度檢查。

## 1. Cross-specialist contradictions

### 1.1 `clear_tool_uses_20250919` 的預設 trigger 值（C 自行標記為未解決）
- C-006 引用官方 cookbook 範例，顯示 trigger 範例值落在 30K–50K。
- topic-B 在協調訊息中稱「預設 100K tokens」。
- **Sweep 判定：部分解決。** LangChain 的 `ContextEditingMiddleware`（`ClearToolUsesEdit` 策略，明確宣稱對齊 Anthropic `clear_tool_uses_20250919`）文件記載預設 trigger 為 **100,000 tokens**；Anthropic 官方 context-editing 文件的標準範例同樣使用 `{"type":"input_tokens","value":100000}`。C 引用的 30K–50K 應為 cookbook 為了在小型 demo 觸發而刻意調低的示範值，非 API 預設。此矛盾判定為「範例值 vs 預設值」的引用層級差異，非真實矛盾。**兩位 specialist 都沒錯，但都各自引用了不完整的證據。**

### 1.2 Multi-agent 的成本效益（D 自行標記，本 sweep 判定不可調和）
- D-011（MEDIUM）：Anthropic orchestrator-worker 研究系統，+90.2% 表現 / 15× token。
- D-012（LOW）：客服場景多 agent 每月 $47,000 vs 單 agent $22,700，準確率只差 2.1pp，多 4.8 秒延遲。
- D-014（LOW）：窄領域事件應變，可執行建議率 100% vs 1.7%。
- **Sweep 判定：不可調和，且必須原樣呈現。** 三筆資料的任務類型、評測基準、confidence 等級都不同（一筆 MEDIUM、兩筆 LOW），沒有任何一份研究同時涵蓋兩種場景做對照。D 提出的「任務類型依賴」是合理的調和假說，但它本身沒有直接證據支持——它是 D 對三筆互不相容資料的事後解釋。最終文件必須把三筆資料並列、標明各自 confidence，並明說「調和假說未經直接驗證」。**不得寫成「業界共識是視任務類型而定」。**

### 1.3 system-reminder 的效益 vs 代價（topic-A 明確拒絕調和）
- 效益（A-003, MEDIUM）：注入使用者訊息而非 system prompt，可完整保留 prompt cache。
- 代價（A-004, HIGH）：實測 32 天 10,577 次注入、佔 15–50% context、malware 警告 10,040 次觸發 0 次真陽性。
- **Sweep 判定：同意 topic-A，維持不調和。** 值得注意的是兩者的 confidence 不對稱——代價側是 HIGH（有 mitmproxy 實測流量），效益側是 MEDIUM（機制推論，Anthropic 未公開說明設計意圖，issue #17601 被關為 not planned 且無官方回應）。**證據較弱的一側恰好是對廠商有利的一側**，這點應在正文標明。

## 2. Low-confidence uncorroborated claims

| Claim | Confidence | 問題 | Sweep 處置 |
|---|---|---|---|
| A-014（Cursor 分層） | LOW | 僅外流文本，多篇報導高度重疊疑為互相轉載 | 補充官方層級證據失敗，但找到獨立佐證（`.cursorrules` 在 Agent mode 不載入），維持 LOW |
| A-015（ChatGPT 分層） | LOW | 第三方部落格，部分帶記憶工具推銷動機 | **部分升級**：記憶雙層（saved memories / chat history）已由 OpenAI Help Center 官方文件證實，可升 MEDIUM；1500 字元上限與「重寫成短 system message」仍為 LOW |
| A-018（10 層骨架） | LOW | 分析性框架，無單一來源可驗證 | 保留 LOW，並在正文明示「這是站得住腳的參考框架，非業界標準」 |
| B-009（78%→13.62%、64%→20%） | LOW | 二手摘要、以訛傳訛風險 | 保留 LOW，方向性引用，不作精確數字引用 |
| C-020（Governance Decay 30%） | MEDIUM | arXiv 全文 403，僅搜尋摘要 | **[UNFILLED GAP]** — 本 sweep 重試仍 403，下修為「僅摘要層級，方法論未核實」 |
| D-007（Ona agent 停用自身 sandbox） | LOW | 單一二手轉述 | 保留 LOW，標為傳聞級 |
| D-012 / D-013 / D-014 / D-016 | LOW | 皆為 WebSearch 摘要重建 | 保留 LOW |

## 3. Contested claims

| Claim | 狀態 | Sweep 評估 |
|---|---|---|
| A-010 / D-017（VILA-Lab「7 層獨立安全防線 / deny-first」） | topic-D 挑戰 → topic-A 下修 MEDIUM 並附 SDK issue #172 為 counter_evidence | **RESOLVED，且結果比原 claim 更有價值。** 這場對抗產出了本輪最重要的發現類別（宣告式權限 ≠ 執行期強制）。最終文件應把「7 層」這個數字降級為背景，把落差本身升級為主要發現。 |
| B-015（`[CONTESTED/待驗證後確認]` 標記未清除） | D-010 已由 topic-D 直接 WebFetch 驗證為真（OPEN，2026-02-12） | **RESOLVED。** B-015 的 CONTESTED 標記應移除，升為與 D-010 同級的 HIGH（一手 GitHub issue 直接驗證）。 |
| C-010（markdown 完勝 vector DB） | topic-A 挑戰 → C 改為 trade-off 表述並補 Milvus 佐證 | RESOLVED，處理得當。 |

## 4. Absent claims（本 sweep 認為最重要的一類）

四位 specialist 的網路研究品質高，但有一整個維度集體缺席：**沒有任何人把 L0–L9 骨架映射到 harness-agent-poc 實際使用的框架（LangChain v1 / LangGraph）上。** A 明說自己沒讀程式碼；B/C/D 讀了 `filesystem.py` / `compact.py` / `memory.py` / `hitl.py` / `agent.py`，但都停在「POC 缺這一層」，沒有問「這一層在 LangChain 裡是不是已經有現成實作」。這使得整份研究對 backlog 的可操作性大打折扣——差別在於「你要自己實作 tool-result clearing」與「你 `pyproject.toml` 已經宣告的 `langchain>=1.2.14` 裡就有 `ContextEditingMiddleware`」。

另外四項 repo 層級的事實，四位 specialist 全部漏掉：

1. **compaction 的結果從未寫回 state**（`agent.py:72` 賦值給區域變數，`agent.py:88` 只回傳 `[response]`，`add_messages` 是 append reducer，沒有用 `RemoveMessage`）。C 花了大量篇幅分析 `compact.py` 的門檻、截斷、cache 成本，卻沒發現這個機制根本不生效。
2. **`edit_file` 完全繞過 HITL**（`filesystem.py:205` `HIGH_RISK_TOOLS = {"write_file"}`），而 `prompts/system.md:17,36-40` 與 `memory.py:22,33` 都在主動指示模型用 `edit_file`。D 說「只有 write_file 觸發核准」但沒推到「所以另一個寫入原語是無防護的，且 prompt 層在鼓勵用它」。
3. **摘要以 `HumanMessage` 回填**（`compact.py:54`），把來自檔案內容/工具輸出的資訊提升到「使用者說的話」這個權限等級——這是 provenance laundering，跟 C-020 的 governance decay、D-016 的 injection 是同一條管線。
4. **檔案系統工具沒有任何路徑邊界**，且 `providers.py:14` 從 project root 載入 `.env`，而 `read_file` 讀 `.env` 完全不需核准。

## 5. Topic coverage balance

- **Topic A（deep）**：覆蓋最紮實，system-reminder 一段是全輪最好的證據鏈。但 focus Q4（prompt 版本控管/回歸測試）實質未答，A 自己誠實標註。
- **Topic B（deep）**：紮實，官方文件比例最高。工具「錯誤語意」一段偏薄（只有 Anthropic 一家的規範，沒有 OpenAI / MCP 的對照）。
- **Topic C（deep）**：篇幅與 claim 數最多（24 條），但有相當比例是 POC gap 分析（C-003/005/007/009/013/015/019/022 共 8 條），純業界研究的密度低於 claim 數暗示的程度。
- **Topic D（moderate）**：以 moderate effort 產出品質最高的單一發現（D-010 一手驗證）。但 sandbox 一節是唯一被明確標為「POC 完全沒有」的層，卻沒有給出「在 Python/LangGraph 情境下最小可行的沙箱化路徑」——缺可操作性。
- **整體不平衡**：L9（應用/UI 層）與 L6（對話中途注入）在 POC 對照上幾乎沒被檢視；「觀測性 / 評測」這一整個橫切關注在四份輸出裡完全不存在。

## Gap Targets

| ID | Severity | Type | Description | Suggested Queries | Sweep 處置 |
|----|----------|------|-------------|-------------------|-----------|
| G1 | HIGH | absent_claim | L0–L9 各層在 LangChain v1 / LangGraph 的現成對應實作完全未被調查，使 backlog 不可操作 | "LangChain prebuilt middleware list", "AgentMiddleware hooks", "ContextEditingMiddleware", "AnthropicPromptCachingMiddleware" | **FILLED**（§2 各層「LangChain 對應」+ §5 backlog） |
| G2 | HIGH | absent_claim | `compact.py` 的壓縮結果從未寫回 graph state，機制實質不生效 | 直接讀 repo + "LangGraph RemoveMessage add_messages reducer" | **FILLED**（一手：repo 程式碼） |
| G3 | HIGH | absent_claim | `edit_file` 繞過 HITL，且 system prompt 與 memory guidelines 主動導向該路徑 | 直接讀 repo | **FILLED** |
| G4 | HIGH | absent_claim | 檔案工具無路徑邊界；`.env` 可被無核准讀取後經 `edit_file` 外流 | 直接讀 repo | **FILLED** |
| G5 | MEDIUM | contradiction | multi-agent 成本效益三筆資料互不相容 | — | **維持不調和**，並列呈現 |
| G6 | MEDIUM | contradiction | `clear_tool_uses` trigger 預設值 30K vs 100K | "clear_tool_uses_20250919 default trigger" | **FILLED**（判定為範例值 vs 預設值，預設 100K） |
| G7 | MEDIUM | uncorroborated | Cursor / ChatGPT 分層僅有 LOW 品質來源 | "OpenAI help center memory", "Cursor AGENTS.md agent mode" | **部分 FILLED**（ChatGPT 記憶層升 MEDIUM；Cursor 仍 LOW，但找到 `.cursorrules` 不載入 Agent mode 的獨立佐證） |
| G8 | MEDIUM | absent_claim | L2/L3 的標準化治理（AGENTS.md 與 MCP 皆已捐入 Linux Foundation AAIF）完全未被提及 | "Agentic AI Foundation AGENTS.md MCP Linux Foundation" | **FILLED** |
| G9 | MEDIUM | absent_claim | HITL 以阻塞式 `console.input()` 實作於 graph node 內，而非 LangGraph `interrupt()` | "LangGraph interrupt Command resume HumanInTheLoopMiddleware" | **FILLED** |
| G10 | MEDIUM | uncorroborated | Governance Decay 論文 0%→30% 數字無法核實全文 | "arXiv 2606.22528" | **[UNFILLED GAP]** — 重試仍 403 |
| G11 | MEDIUM | coverage_imbalance | 無任一廠商官方說明自家 system prompt 的版本控管/回歸測試流程 | "Anthropic system prompt regression testing" | **[UNFILLED GAP]** — 判定為產業普遍不揭露，非搜尋失敗 |
| G12 | MEDIUM | absent_claim | 觀測性 / 評測層（tracing、eval harness）在四份輸出中完全缺席，但它是判斷其他各層是否生效的唯一手段 | "agent observability tracing eval harness" | **部分 FILLED**（列入「超出原範圍的發現」與待答問題，未做深度研究） |
| G13 | LOW | absent_claim | 工具錯誤語意只有 Anthropic 一家規範，缺 OpenAI/MCP 對照 | "OpenAI function calling error handling convention" | **未填補**（低嚴重度，B 的官方來源已足夠支撐建議） |

## Sweep 對是否需要第二輪 deepening 的判斷

**不建議。** 理由：(1) 四個 HIGH gap 全部是 repo 層級事實，由 sweep 直接讀程式碼填補完畢，不需再一輪網路研究；(2) 兩個 UNFILLED gap（G10、G11）都是 proxy 403 或產業不揭露造成，第二輪在同一環境下不會有不同結果；(3) 唯一真正值得再開一輪的是 G12（觀測性/評測層），但它其實是「下一篇研究題目」而非「本篇的洞」——本篇的職責是把分層骨架釘死，觀測性應該獨立成篇。

coverage_score = 4：業界做法覆蓋充分，骨架站得住腳；扣分在 prompt 版本控管無一手來源、觀測性層缺席、Cursor 側證據品質偏弱。
