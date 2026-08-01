# backlog.md — 問題積壓清單與 frontier 登記簿

> 本檔是研究迴圈中 **agent 唯一可直接編輯的協定檔**（更新問題狀態、登記/結案 frontier 方向）。
> 憲章本體 `research/program.md`、人格檔 `.claude/agents/researcher.md`、
> 資料管線 `research/fetch_klines.py` 對 agent 唯讀，改動只能開 PR。

狀態標記：`open` / `watching`（等數據或等前置）/ `closed`（寫明結論與日期，移到底部「已結案」段）。

## 問題清單

- **Q2' `probe` open**（2026-08-01 run2 新增，承接 Q2 最強反駁第 1 點）— **bbw_pct 分層
  配對版 Q2。** run2 發現「event vs 隨機時點」整體比較未控制事件當下的 `bbw_pct` 分佈
  （B 級事件的 `bbw_pct` 底色本來就偏高，依 Q1 這本就該讓振幅偏大；A 級要求 `bbw_pct<=0.25`
  底色偏低）。下次應把每筆 event 依其觸發當下 `bbw_pct` 值配對到**同一分桶**的隨機時點
  子集（而非整個 6 桶混合的 Q1 母體）重新比較 24h 振幅，才能把 `vol_z`/突破條件的獨立
  貢獻與 `bbw_pct` 底色分開。詳見 `research/log/2026-08-01.md` Run 2 最強反駁第 1 點。
  **這不是新方向，是 Q2 同一問題的更乾淨版本**，不受 frontier 兩階段閘門限制。

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
- **Q1'**（closed 2026-08-01 run2）— Phase 0 結果的 block bootstrap 穩健性覆核：逐 ISO 週
  區塊重抽後，24h p80 最低桶 vs 最高桶差距 CI 由 [+2.138,+3.464]pp 放寬為
  **[+1.457,+4.112]pp，仍不含 0**。Q1「有區別力」結論穩健，但精確度下降，之後引用
  Q1 CI 時改用本次較寬版本。詳見 `research/log/2026-08-01.md` Run 2、
  `research/experiments/2026-08-01_q1prime_block_bootstrap.py`。
- **Q2**（closed 2026-08-01 run2，未驗證）— Phase 0.5：`event`（去重後 n=791）24h 振幅
  vs 隨機時點（Q1 母體 n=5450）p80 差距 +0.191pp，CI [−0.705,+1.128]pp **含 0**——
  `docs/RND_BACKLOG.md` 的「顯著大於隨機時點→驗證為波動爆發預警」驗收條件**未達成**。
  A 級（n=263）單獨看甚至略負（CI [−1.873,+0.007]pp）；A vs B 差距顯著（CI [+0.621,+2.934]pp
  不含 0）但疑似主要是 `bbw_pct` 分佈差異的機械性重述，非 `vol_z` 條件本身的獨立貢獻。
  **不是「event 完全沒用」的證偽，是本次比較設計無法乾淨拆解 event 的獨立貢獻**——
  承接題見上方 Q2'。詳見 `research/log/2026-08-01.md` Run 2、
  `research/experiments/2026-08-01_q2_phase05_event_kill_switch.py`。
