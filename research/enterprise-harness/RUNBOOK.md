# 自動研究輪次 Runbook

每 2 小時由 Routine 喚起一個全新雲端 session，執行以下流程。
**這份檔案是流程的唯一真實來源**——想調整研究行為，改這裡就好，不必動 Routine 本身。

> **本文件的內容經過 2026-07-31 第一輪實測驗證。** 不要照 deep-research plugin 的
> 官方說明操作，那條路在這個環境走不通，原因見下方「環境限制」。

---

## 環境限制（先讀，否則會浪費一整輪）

deep-research plugin 已安裝且 skill 載得進來，但**它的 driver 在這個 harness 裡跑不起來**：

| 問題 | 實測結果 | 因應 |
|------|----------|------|
| `TeamCreate` / `TeamDelete` 不存在 | plugin driver 宣告需要，ToolSearch 查無此工具 | 不要呼叫 `/deep-research`。用下方手動流程 |
| subagent 沒有 `TaskUpdate` | specialist 明確回報工具不存在 | task 阻塞鏈是裝飾品，狀態由 coordinator 手動維護 |
| 被阻塞的 agent 無法預先存在 | 四個 specialist 都收到 `No agent named 'sweep' is reachable` | sweep 必須等 specialist 全部完成後才 spawn。specialist 的 DONE 訊息會失敗，這是預期行為，不影響結果（sweep 直接讀檔案） |
| 對外 HTTPS 走 agent proxy | 多數非 Anthropic 網域的 WebFetch 回 403 | 非官方來源只能靠 WebSearch 摘要驗證。**每份報告開頭必須寫明這點** |

**唯一不受 proxy 影響的高強度證據來源是 repo 原始碼本身。** 這是為什麼「套用到
harness-agent-poc」那節的證據等級最高——要善用這個不對稱。

### 第一輪實測數據（校準用）

| 階段 | 時間 | token |
|------|------|-------|
| Haiku scout（31 來源） | 2.8 分 | 35K |
| 4 個 Sonnet specialist（平行） | 10.5 分 | 435K |
| Opus sweep | ~11 分 | 未計 |
| **合計** | **約 25 分鐘** | **約 600K** |

**第一輪的 Opus sweep 撞到 session 額度上限被中斷**（主文件已寫完才斷，副本與 advisory 沒寫成）。
這是真實風險，不是意外。下方流程已據此縮編為 **3 個 specialist、天花板 7 分鐘**，目標是
整輪收在 20 分鐘內。

---

## 步驟

### 1. 準備分支

```bash
cd /home/user/harness-agent-poc   # 或該 session 的 clone 路徑
git fetch origin claude/enterprise-claude-chat-research-yrnmzj
git checkout claude/enterprise-claude-chat-research-yrnmzj
git pull origin claude/enterprise-claude-chat-research-yrnmzj
```

**先確認 repo 真的在。** 若目錄不存在，先 clone 再繼續，不要假設環境已經掛好。
若分支不存在，從 `master` 建立。

### 2. 選題

讀 `BACKLOG.md`，取 **第一個 `[ ]` 未完成項目**。

若全部完成 → 進入 **深化模式**：讀 `INDEX.md`，挑一份 `depth: shallow` 的報告，
針對它「失敗模式」與「套用到 harness-agent-poc」兩節做第二輪研究，就地更新該報告，
深度標記升為 `deep`。

**讀第 01 篇報告的 L0–L9 分層骨架**，新報告要掛在這個骨架上，用同一套層號，
不要另創一套分層。如果研究結果顯示骨架該修，那本身就是重要發現，明講。

### 3. 研究（手動 pipeline，不要用 `/deep-research`）

建立 scratch 目錄 `tasks/scratch/research/<run-id>/`，然後：

#### 3a. 寫 scope.md

由你（coordinator）直接判斷，這是判斷工作不外包。內容要有：
- 研究問句（把 backlog 標題展開成具體、可證偽的問句）
- **3 個** topic 分區，每區 3-4 個 focus question
- 每區的建議搜尋詞，**每區至少 1 個對抗性查詢**（"X problems"、"X limitations"、"why not X"）
- 跨 topic 的重疊邊界，明講誰負責什麼（不寫這個一定會產生重複工作）
- 專案脈絡：把 `harness_agent/` 相關檔案的**現況**寫進去（例如「`hitl.py` 目前一次核准
  涵蓋整個 session」），specialist 才能做出有針對性的落差分析

#### 3b. Scout（Haiku）

`subagent_type: deep-research:research-scout`，prompt 模板在
`~/.claude/plugins/cache/claude-community/deep-research/*/pipelines/scout-prompt-template.md`。
天花板 3 分鐘。完成後**由你手動**把它的 task 標成 completed（它自己做不到）。

#### 3c. Specialists（Sonnet ×3，平行 spawn）

`subagent_type: deep-research:research-specialist`，模板在同目錄
`specialist-prompt-template.md`。每個 specialist 的 prompt 必須填入：
- floor 4 分鐘 / **ceiling 7 分鐘** / 至少 5 個來源
- 對應的專案檔案現況（讓它自己去讀原始碼——第一輪這招產出了最有價值的發現）
- 明確的重疊邊界與 peer 名單
- 指示：summary 與 claims 內容用**繁體中文**，技術名詞保留英文
- 預先告知：`sweep` 目前不可達，DONE 訊息送不出去是正常的，寫完檔案就結束

**對抗性挑戰要留著。** 第一輪 topic-D 挑戰 topic-A 的安全防線宣稱、topic-A 下修信心評級，
這是整輪品質最高的一段。不要為了省時間拿掉這個機制。

#### 3d. Sweep（Opus）

**等三個 specialist 全部完成後才 spawn**（不能預先 spawn 被阻塞的 agent）。
`subagent_type: deep-research:research-synthesizer`。prompt 要含：
- 全部 specialist 輸出的檔案路徑
- 報告輸出路徑 `research/enterprise-harness/reports/NN-slug.md`
- 下方「報告必備結構」六節
- 明確指示：**不要抹平矛盾**，來源打架就兩邊都寫、附證據
- 明確指示：**不要 SendMessage 給任何 teammate**（會失敗）
- 明確指示：保留 specialist 的內容，它的工作是評估覆蓋度、補洞、加框架，不是重寫

#### 3e. Fallback

若 subagent 機制整個不可用，**不要中止**——改用 WebSearch + WebFetch 自己跑：
至少 10 個來源、優先官方文件與工程部落格、至少 2 個對抗性查詢，再自行統整。
報告開頭註明使用了 fallback 模式。

### 4. 報告必備結構

輸出到 `research/enterprise-harness/reports/NN-slug.md`（`NN` 用 backlog 編號）：

0. **方法論限制** — 放最前面。這輪哪些來源核實到原文、哪些只有搜尋摘要、哪些填不起來
1. **問題定義**
2. **業界做法** — 至少 3 個真實系統，附來源連結，掛在 L0–L9 骨架上
3. **設計選項與取捨** — 要給推薦與理由，不要只列清單
4. **失敗模式** — 含已知踩雷案例。**「宣告的行為 ≠ 執行時的行為」這類落差要特別突出**
5. **套用到 harness-agent-poc** — 對照本 repo 現況，**必須引用真實檔案路徑與行號**，
   按 P0/P1/P2 分級，每項附**驗收條件**。這節要能直接當 backlog 用
6. **來源清單** — 標註哪些是一手核實、哪些是二手

額外要求：
- **有來源才寫。** 無法佐證的推論明確標為推測。
- 保留每條論點的 confidence（HIGH/MEDIUM/LOW）。
- 版本與日期寫進來（例：「截至 2026-07 的 MCP spec」），因為會被後續輪次引用。
- 繁體中文，技術名詞保留英文。

### 5. 收尾

1. 報告寫到 `reports/NN-slug.md`
2. **證據鏈歸檔**：`cp scratch/* research/enterprise-harness/archive/NN-slug/`
   （scope、source-corpus、各 claims.json 與 summary.md、gap-report）
3. `rm -rf tasks/scratch`
4. `BACKLOG.md` 該項改 `[x]` 並加報告連結
5. `INDEX.md` 追加一列，深度填 `shallow`
6. Commit：`research(NN): <主題>`
7. `git push -u origin claude/enterprise-claude-chat-research-yrnmzj`
   （網路失敗退避重試 2s / 4s / 8s / 16s）
8. **不要開 PR。** 不要推到其他分支。

### 6. 回報

3-5 行：這輪做了哪個主題、最關鍵的 2-3 個發現、有沒有需要人介入的判斷。

---

## 邊界

- 只讀公開資料。不要嘗試取得付費牆後、需登入或非公開的內容。
- 不要改 `harness_agent/` 底下的程式碼。這個 Routine 只產出研究報告，實作改動留給人決定。
  （**發現的 bug 寫進報告第 5 節，不要順手修掉。**）
- **單輪上限約 20 分鐘。** 逼近上限時的取捨順序：
  1. 先砍 specialist 數量（3 → 2），不要砍 sweep
  2. 再砍 specialist 的 ceiling（7 → 5 分）
  3. 最後才減少 topic 涵蓋範圍，並在報告裡明講哪些沒做
  **優先保住「有來源、有結論」的完整段落**，寧可少寫兩節，也不要交出每節都半成品的報告。
- **session 額度是真實風險**（第一輪的 Opus sweep 就是這樣被中斷的）。
  若 sweep 中斷但主文件已寫出，檢查文件完整性——第一輪的主文件其實是完整的，
  只是副本沒寫成。不要因為 agent 回報 failed 就丟掉已經產出的東西。
