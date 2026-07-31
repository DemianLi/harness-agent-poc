# Enterprise Harness 研究待辦清單

目標：搞清楚要做出一個像 Claude chat / Claude Code 那樣的 **企業級 agent harness**，
在架構、工程、營運、合規上分別需要什麼；並把每個結論收斂成可以套用到本 repo
（`harness_agent/`）的具體做法。

## 運作方式

- 每 2 小時一輪，由 Routine 喚起一個雲端 session。
- 每輪從下面挑 **第一個未完成（`[ ]`）** 的主題，跑 `/deep-research web`，
  產出一份報告到 `research/enterprise-harness/reports/NN-slug.md`。
- 完成後把該項改成 `[x]`，補上報告連結，更新 `INDEX.md`，commit 並 push。
- 清單跑完後，改為「深化模式」：回頭挑 `INDEX.md` 裡標記 `depth: shallow`
  的報告做第二輪深挖，或針對新出現的技術補充。

## 每份報告的必備結構

1. **問題定義** — 這個面向在企業級 harness 裡具體要解決什麼
2. **業界做法** — 至少 3 個真實系統的做法，附來源連結
3. **設計選項與取捨** — 不只列清單，要給推薦與理由
4. **失敗模式** — 這塊做壞會怎樣，有哪些已知踩雷案例
5. **套用到 harness-agent-poc** — 對照本 repo 現況（middleware / tools / memory），
   指出差距與下一步可落地的改動
6. **來源清單** — 全部連結

---

## 第一階段：核心架構

- [ ] 01 — Harness 解剖學：模型與使用者之間到底有哪幾層（system prompt、tools、context、memory、permission、orchestration）
- [ ] 02 — System prompt 架構：組裝、分層、版本控管、A/B 與 regression
- [ ] 03 — 工具層設計：tool schema 設計原則、工具數量爆炸的解法（tool search / deferred tools）、錯誤回傳語意
- [ ] 04 — Context window 管理：compaction、摘要策略、何時該檢索而非塞入、prompt caching 的成本模型
- [ ] 05 — 記憶系統：短期 vs 長期、per-user vs per-project、可編輯 Markdown 記憶 vs 向量庫的取捨
- [ ] 06 — Sub-agent 與 agent teams：fan-out 策略、context 隔離、結果聚合、何時不該開 sub-agent
- [ ] 07 — 串流與即時互動 UX：SSE / token streaming、部分工具結果、中斷與轉向（steering）、可恢復串流

## 第二階段：企業級基礎建設

- [ ] 08 — 權限與 HITL：approval mode、allowlist、危險操作分級、一次授權的範圍該多大
- [ ] 09 — 沙箱與程式碼執行隔離：container / gVisor / Firecracker、檔案系統與 egress 政策
- [ ] 10 — 多租戶隔離：資料、金鑰、執行環境、成本歸屬
- [ ] 11 — 認證授權：SSO / SAML / SCIM、RBAC、組織層級政策與 managed settings
- [ ] 12 — 資料治理：保留期限、PII 偵測與遮蔽、資料落地（residency）、zero-data-retention
- [ ] 13 — 合規：SOC 2、ISO 27001、HIPAA/BAA、EU AI Act 對 agent 產品的實際要求
- [ ] 14 — 稽核與可觀測性：trace/span 模型、OpenTelemetry GenAI 慣例、要記什麼才查得動事故

## 第三階段：品質、成本、可靠度

- [ ] 15 — 評測與回歸測試：agent harness 要怎麼測、eval 資料集怎麼建、如何避免 prompt 改動造成靜默退化
- [ ] 16 — 安全層：prompt injection 防禦、不可信內容邊界、輸出過濾、分類器堆疊
- [ ] 17 — 成本控制：token 計帳、預算與限流、快取命中率、模型路由降級
- [ ] 18 — 多模型與多供應商抽象：fallback、能力差異吸收、供應商鎖定的解法
- [ ] 19 — 可靠度：重試與冪等、長任務續跑、佇列與背景工作、部分失敗的回報

## 第四階段：產品面與交付

- [ ] 20 — 檔案與產出物：上傳、artifact 渲染、CSP 與沙箱化預覽、產物版本
- [ ] 21 — 連接器與 MCP：server 目錄、OAuth 流程、企業規模下的工具授權範圍控制
- [ ] 22 — 聊天前端架構：虛擬化訊息串、樂觀更新、斷線續傳、多裝置同步
- [ ] 23 — 企業知識庫整合：RAG 的實際邊界、權限感知檢索（ACL-aware retrieval）
- [ ] 24 — 部署拓樸：SaaS / VPC / on-prem / 氣隙、Bedrock 與 Vertex 的差異
- [ ] 25 — 管理後台：用量分析、席次管理、政策主控台、給 IT 的可視性
- [ ] 26 — 競品拆解：Claude Code、ChatGPT Enterprise、Glean、Dust、以及主流開源 harness 的架構對照
