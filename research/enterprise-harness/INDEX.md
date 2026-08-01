# Enterprise Harness 研究索引

自動產出的研究報告總表。每輪 Routine 完成後會在這裡追加一列。

| # | 主題 | 報告 | 深度 | 產出時間 |
|---|------|------|------|----------|
| 01 | Harness 解剖學（L0–L9 分層骨架） | [`01-harness-anatomy.md`](reports/01-harness-anatomy.md) | shallow | 2026-07-31 |

深度標記：
- `shallow` — 只跑了一輪 web pipeline，結論待驗證
- `deep` — 跑過深化 pass 或交叉比對過多個來源
- `applied` — 結論已經落到 `harness_agent/` 的實作或設計文件裡

## 完整證據鏈

每份報告的原始產出（scope、來源池、各 specialist 的 claims JSON 與 summary、sweep 的 gap report）
保存在 `archive/<報告 slug>/`。報告正文的每條論點都可以回溯到對應的 claim，claim 帶 source_url、
發布日期與 confidence 標記。要質疑報告的任何結論，從 archive 查起。

## 已知限制

本執行環境的對外 HTTPS 走 agent proxy，多數非 Anthropic 官方網域的直接 WebFetch 會被 403 擋下。
因此非官方來源的論點多數只透過搜尋摘要間接取得。**閱讀報告時務必先讀該報告開頭的「方法論限制」**，
並以 confidence 標記校準每條論點的可信度。
