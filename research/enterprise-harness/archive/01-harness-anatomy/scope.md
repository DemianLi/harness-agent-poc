# Scope — Harness 架構分層（Backlog 01）

## Research Question

在 Claude Code、ChatGPT、Cursor 這類正式上線的 agent harness 裡，模型與使用者之間實際存在哪些架構層？
涵蓋 system prompt 組裝與分層、工具層設計、context window 管理、記憶系統、權限控制、sub-agent orchestration。
每層要說明：解決什麼問題、業界具體做法差異、失敗模式。

## Project Context

本研究服務於 `harness-agent-poc`（Python + LangChain/LangGraph 的 harness POC，已有 memory / compact /
HITL 三個 middleware）。目標是找出「企業級 harness」相對於這個 POC 缺了哪些層，以及每層的業界標準做法。
產出會成為長期研究系列的第一篇，後續 25 個主題會引用它，因此**分層的切法要站得住腳**。

## Source-type constraints

優先 primary source：官方文件（Claude Code docs、OpenAI/Anthropic 工程部落格、MCP spec）、
維護良好的 OSS repo、實際逆向工程紀錄。次級來源要標註。少於 3 個佐證來源的論點要標 confidence。
**快速變動領域**：2026 年的 LLM 工具生態，超過 6 個月的來源視為可能過期，除非有近期來源佐證。

## Cross-cutting themes

- **Context 是稀缺資源**：每一層（prompt、工具定義、記憶、sub-agent 回傳）都在搶同一個 context window，
  各層的設計取捨最終都會回到「這值不值得佔 token」。
- **信任邊界**：工具輸出、檔案內容、web 內容都是不可信輸入，權限層與 prompt 層對此的責任怎麼劃分。
- **狀態放哪**：prompt 內 vs. 檔案 vs. 外部儲存，是分層差異的主軸。

---

## Topic A — System prompt 組裝與分層 + harness 整體解剖

**Effort: deep**

Focus questions:
1. 正式產品的 system prompt 實際由哪些片段組合而成（靜態基底、環境資訊、工具說明、使用者偏好、
   專案層 CLAUDE.md/AGENTS.md、動態注入的 reminder）？各段的注入時機與優先序為何？
2. Claude Code、ChatGPT、Cursor 三者在 prompt 分層上最大的差異是什麼？
3. system-reminder 這類「對話中途注入」的機制解決什麼問題，代價是什麼？
4. prompt 改動如何做版本控管與回歸測試？業界有無公開做法？

Suggested queries:
- `system prompt architecture LLM agent`
- `Claude Code system prompt leaked analysis`
- `CLAUDE.md AGENTS.md project instructions`
- `system reminder injection agent`
- `system prompt versioning regression testing` （對抗性）
- `system prompt bloat problems` （對抗性）

## Topic B — 工具層設計

**Effort: deep**

Focus questions:
1. 好的 tool schema 長什麼樣？命名、描述、參數設計對模型呼叫正確率的影響有無實證？
2. 工具數量變多時 context 爆炸怎麼解（tool search / deferred tools / namespacing / 動態載入）？
   MCP 生態在企業規模下的具體問題是什麼？
3. 工具錯誤該怎麼回傳給模型才有用（錯誤語意、可恢復性、重試提示）？
4. 失敗模式：工具描述誤導、參數幻覺、工具過多導致選錯。

Suggested queries:
- `tool schema design LLM function calling`
- `MCP tool search context`
- `too many tools LLM accuracy`
- `function calling error handling agent`
- `MCP limitations problems` （對抗性）
- `tool use failure modes LLM` （對抗性）

## Topic C — Context window 管理 + 記憶系統

**Effort: deep**

Focus questions:
1. compaction / auto-summarization 實際怎麼實作？觸發門檻、保留什麼、丟什麼？
2. prompt caching 如何改變 context 管理的成本模型？什麼操作會讓 cache 失效？
3. 記憶系統：可編輯 Markdown 記憶檔 vs. 向量檢索，各自適用邊界？per-user 與 per-project 記憶怎麼分？
4. 失敗模式：compaction 丟掉關鍵資訊、記憶污染、記憶與現況衝突。

Suggested queries:
- `context window management agent compaction`
- `prompt caching cost model Anthropic`
- `agent memory architecture markdown vs vector`
- `context rot long context degradation`
- `context compaction loses information` （對抗性）
- `agent memory problems stale` （對抗性）

## Topic D — 權限控制 + Sub-agent orchestration

**Effort: moderate**

Focus questions:
1. 權限模型有哪些設計（approval mode、allowlist、危險操作分級、沙箱）？一次授權的範圍該多大？
2. sandbox 的實作選項與取捨（container / gVisor / seccomp / 網路 egress 政策）？
3. sub-agent 何時該開、何時不該開？context 隔離帶來什麼好處與什麼損失？結果怎麼聚合？
4. 失敗模式：授權疲勞導致全部放行、sub-agent 回傳品質不可控、orchestration 成本失控。

Suggested queries:
- `agent permission model approval sandbox`
- `Claude Code permission modes allowlist`
- `subagent orchestration context isolation`
- `multi-agent LLM cost overhead`
- `agent sandbox escape risk` （對抗性）
- `multi-agent systems worse than single agent` （對抗性）
