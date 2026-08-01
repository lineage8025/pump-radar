# backlog.md — 問題積壓清單與 frontier 登記簿

> 本檔是研究迴圈中 **agent 唯一可直接編輯的協定檔**（更新問題狀態、登記/結案 frontier 方向）。
> 憲章本體 `research/program.md`、人格檔 `.claude/agents/researcher.md`、
> 資料管線 `research/fetch_klines.py` 對 agent 唯讀，改動只能開 PR。

狀態標記：`open` / `watching`（等數據或等前置）/ `closed`（寫明結論與日期，移到底部「已結案」段）。

## 問題清單

- **Q2 `probe` open**（2026-08-01 解封，原 watching 等 Q1）— **Phase 0.5：現行 `event` 是不是好的波動爆發預警。**
  比較「`event` 觸發後 24h 振幅」vs「隨機時點 24h 振幅」的分佈。
  對照組取樣需避開事件叢集，沿用 `docs/DETECTOR_PREREG.md` 已預登記的「同 4h 窗僅計首發」視角。
  注意：這與「追價期望為負」不衝突——kill-switch 不需要方向，只需要振幅。
  但**不得**因此改寫偵測器的定位敘述（那是人類的事）。
  **2026-08-01 run 1 提醒**：Q1 發現 `bbw_pct` 低（壓縮）對應的是「24h 振幅更小」而非更大
  （見 `research/log/2026-08-01.md`），`event` 的 A 級門檻正是「觸發前壓縮」——執行 Q2 時
  這個前置條件對振幅可能是負向貢獻，若 `event` 後振幅仍大於隨機時點，貢獻大概率來自
  `vol_z≥3.0` 放量條件而非壓縮本身，解讀時要把這個拆解寫清楚，不能只看表面比較。

- **Q1'** `probe` open（2026-08-01 新增，承接 Q1 最強反駁）— **Phase 0 結果的 block bootstrap
  穩健性覆核。** `research/log/2026-08-01.md` 的最強反駁指出：逐樣本 bootstrap 可能因跨標的
  同期相關（宏觀 regime 齊漲跌）系統性低估 CI 寬度，5450 筆「獨立樣本」的有效自由度可能遠
  小於表面值。用同一份既有結果（`research/experiments/2026-08-01_phase0_bbw_amplitude_samples.tsv`）
  改用按週或按標的分塊的 block bootstrap 重估最低桶 vs 最高桶 24h p80 差距的 CI，
  若下界仍 >0 → Q1 結論穩健，補記 ledger；若下界 ≤0 → Q1 結論需降級為「未證實」，
  同樣補記 ledger 並回頭更新 `research/log/2026-08-01.md` 的狀態註記（append 方式，不得
  刪改原文）。**這不是「換分桶/換T重跑」，是同一分析的穩健性覆核，不受 frontier 兩階段
  閘門限制**——沿用同一份凍結網格與同一批樣本，只改重抽方法。

- **Q3 `audit` closed（2026-08-01）** — 樣本內基準可重算性：**完全重算一致，無差異**。
  見「已結案」段。

- **Q4 `tooling` open** — **forward 證據盲點。** 本迴圈在 CI 內看不到任何 forward 數據
  （journal 在 NAS、日報只推 Discord 不留存）。提案：讓 `daily_pulse_dispatch.py` 的 payload
  額外存成一個 issue（或讓 `claude-daily-pulse.yml` 開 issue 存檔），使迴圈能覆盤 forward 進度。
  **只開 PR 提案，不得自行實作上線**——那條路徑是 production。

- **Q5 `lit` watching** — 承接 `docs/RESEARCH_BBW_VOLATILITY.md` §6 的缺口：
  加密貨幣專屬、同儕審查、直接檢定「BBW squeeze 對後續振幅有無區別力」的一手論文**查不到**。
  若日後出現，更新情報即可；**不因外部論文而改動 §4 凍結網格或 kill criteria**。

非 frontier 的新問題（probe/audit/lit/tooling）直接寫進上表即可；
新研究**方向**（相當於 `docs/RND_BACKLOG.md` 的「方向二」）走 `program.md` §5 兩階段立案閘門。

## Frontier 方向登記簿

每個方向編永久 ID（F1、F2…）。登記時寫入「進行中」表；淘汰後移入「已淘汰」表，
**同一機制的方向不得換皮重跑**（換皮＝只調參數/時距/指標外觀）。
本質差異論證必須同時對照 `CLAUDE.md` 紅線、`docs/RND_BACKLOG.md` 既有方向與本表。

### 進行中

| ID | 方向（機制一句話） | 階段 | 登記 commit / issue | 日期 |
|---|---|---|---|---|
| — | — | — | — | — |

### 已淘汰

| ID | 方向（機制一句話） | 淘汰證據（ledger/日誌連結） | 日期 |
|---|---|---|---|
| — | — | — | — |

## 已結案

- **Q1**（closed 2026-08-01）— Phase 0：`bbw_pct` 對後續振幅有無區別力。
  結論：**有區別力**（六分桶在 4 個 T 上單調遞增，24h 檔最低桶 vs 最高桶 p80 差距
  bootstrap 95% CI [+2.14,+3.46]pp，下界 >0），未觸發 kill criteria。方向與「壓縮後爆發」
  直覺相反——是波動持續性主導、非均值回歸反轉。**信賴區間穩健性未覆核**（見最強反駁，
  已開 Q1' 承接）。詳見 `research/log/2026-08-01.md`、
  `research/experiments/2026-08-01_phase0_bbw_amplitude.py`。
- **Q3**（closed 2026-08-01）— 樣本內基準可重算性：`data/insample_scored.tsv` 235 筆逐筆重算，
  與 `docs/DETECTOR_PREREG.md` 引用的原 4 標的基準（n=102/107 事件）與全 10 標的分級分佈表
  （n=235）**全部數字完全相符，無差異**。詳見
  `research/experiments/2026-08-01_q3_audit_insample.py`。
