# backlog.md — 問題積壓清單與 frontier 登記簿

> 本檔是研究迴圈中 **agent 唯一可直接編輯的協定檔**（更新問題狀態、登記/結案 frontier 方向）。
> 憲章本體 `research/program.md`、人格檔 `.claude/agents/researcher.md`、
> 資料管線 `research/fetch_klines.py` 對 agent 唯讀，改動只能開 PR。

狀態標記：`open` / `watching`（等數據或等前置）/ `closed`（寫明結論與日期，移到底部「已結案」段）。

## 問題清單

- **Q1 `probe` open** — **Phase 0：`bbw_pct` 對後續振幅有無區別力。**
  照 `program.md` §4 的凍結網格跑（六分桶 × T=1/4/12/24h × p50/p80/p95，每格附 n）。
  **分析窗口預登記：2025-01-01 ~ 2026-06-30**（抓資料時起點提前到 `2024-12` 當暖機月，
  丟棄 `bbw_pct` 為 null 的列）；**標的預登記：`docker-compose.yml` 的 10 個 PAIRS**。
  窗口與標的登記於本行，**結果出來後不得為了改善結果而變更**。
  驗收：能明確讀出「壓縮狀態下，區間放多寬才有 80% 機率撐過 T 小時」。
  Kill：若各分桶分佈重疊、24h 檔也無區別力 → 依 `docs/RND_BACKLOG.md` kill criteria **終止方向一**，
  照實記錄，不得改網格重跑。

- **Q2 `probe` watching（等 Q1 完成）** — **Phase 0.5：現行 `event` 是不是好的波動爆發預警。**
  比較「`event` 觸發後 24h 振幅」vs「隨機時點 24h 振幅」的分佈。
  對照組取樣需避開事件叢集，沿用 `docs/DETECTOR_PREREG.md` 已預登記的「同 4h 窗僅計首發」視角。
  注意：這與「追價期望為負」不衝突——kill-switch 不需要方向，只需要振幅。
  但**不得**因此改寫偵測器的定位敘述（那是人類的事）。

- **Q3 `audit` open** — **樣本內基準可重算性。** `docs/DETECTOR_PREREG.md` 引用的樣本內基準
  （net_24h mean、勝率、A/B 級 MAE 中位數）能否用 `data/insample_scored.tsv` 的 235 筆逐筆重算出來？
  對不上就逐項列出差異與可能原因。**只覆核，不修正**——兩份檔案對你都唯讀。

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

（尚無）
