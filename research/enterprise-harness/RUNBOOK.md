# 自動研究輪次 Runbook

每 2 小時由 Routine 喚起一個全新雲端 session，執行以下流程。
**這份檔案是流程的唯一真實來源**——想調整研究行為，改這裡就好，不必動 Routine 本身。

## 步驟

### 1. 準備分支

```bash
cd /home/user/harness-agent-poc   # 或該 session 的 clone 路徑
git fetch origin claude/enterprise-claude-chat-research-yrnmzj
git checkout claude/enterprise-claude-chat-research-yrnmzj
git pull origin claude/enterprise-claude-chat-research-yrnmzj
```

若分支不存在，從 `master` 建立。

### 2. 選題

讀 `research/enterprise-harness/BACKLOG.md`，取 **第一個 `[ ]` 未完成項目**。

若全部完成 → 進入 **深化模式**：讀 `INDEX.md`，挑一份 `depth: shallow` 的報告，
針對它的「失敗模式」與「套用到 harness-agent-poc」兩節做第二輪研究，就地更新該報告，
並把深度標記升成 `deep`。

### 3. 研究

優先使用已安裝的 plugin：

```
/deep-research web "<把 backlog 標題展開成一個具體的研究問句>"
```

Pipeline A 會用 Haiku scout 蒐集來源、Sonnet specialists 交叉驗證、Opus 統整。
若 plugin 不可用（Agent Teams 未啟用或市集拉取失敗），**不要中止**——
改用 WebSearch + WebFetch 手動跑：至少 10 個來源、優先官方文件與工程部落格，
再自行統整。並在報告開頭註明使用了 fallback 模式。

### 4. 寫報告

輸出到 `research/enterprise-harness/reports/NN-slug.md`（`NN` 用 backlog 的編號）。

必備結構見 `BACKLOG.md` 的「每份報告的必備結構」。額外要求：

- **有來源才寫**。無法佐證的推論要明確標示為推測，不要寫成事實。
- 版本與日期要寫進來（例：「截至 2026-07 的 MCP spec」），因為報告會被之後的輪次引用。
- 「套用到 harness-agent-poc」一節必須引用真實檔案路徑
  （`harness_agent/middleware/compact.py:12` 這種格式），不能空泛。
- 用繁體中文寫，技術名詞保留英文原文。

### 5. 收尾

1. 把 `BACKLOG.md` 該項改成 `[x]`，後面加上報告連結。
2. 在 `INDEX.md` 追加一列，深度填 `shallow`。
3. Commit：`research(NN): <主題>`
4. `git push -u origin claude/enterprise-claude-chat-research-yrnmzj`
   （網路失敗時退避重試 2s / 4s / 8s / 16s）
5. **不要開 PR。** 不要推到其他分支。

### 6. 回報

在 session 結束時用 3-5 行摘要說明：這輪做了哪個主題、最關鍵的 2-3 個發現、
以及有沒有需要人介入的判斷（例如發現 backlog 的假設有誤）。

## 邊界

- 只讀公開資料。不要嘗試取得付費牆後、需登入或非公開的內容。
- 不要改 `harness_agent/` 底下的程式碼——這個 Routine 只負責產出研究報告。
  實作改動留給人決定。
- 單輪若超過 ~40 分鐘仍未收斂，就把已完成的部分寫成報告並註明未竟之處，
  然後正常收尾，不要無限跑下去。
