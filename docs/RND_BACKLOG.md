# 待研發方向（R&D Backlog）

> 建立於 2026-07-31。本文件記錄**尚未立案**的研究方向與其判準。
> 列在這裡 ≠ 已採納；每條都附 kill criteria，數據不支持就收攤。

## 定位紅線（先講清楚，避免文件躺久了漂移）

pump-radar 本體定位不變：**15m 布林帶波段啟動的偵測追蹤器，不是交易系統**。
本文件裡的方向若涉及交易，一律走「另行預登記」路徑，**禁止沿用 `scripts/detector.py` 的
`PARAMS` 任何值**（CLAUDE.md 紅線原文）。

## 目錄邊界（由 build 強制，不靠自制力）

```
pump-radar/
├─ scripts/     ← 部署內容。Dockerfile 有 COPY，改動即上線
├─ data/        ← 部署內容。Dockerfile 有 COPY
├─ docs/        ← 文件
└─ research/    ← 研究程式碼。Dockerfile 【沒有】COPY，永不進容器
   ├─ program.md      ← autoresearch 憲章（對 agent 唯讀）
   ├─ backlog.md      ← 問題積壓清單（agent 唯一可直接編輯的協定檔）
   ├─ LEDGER.tsv      ← 運行帳本（append-only）
   ├─ fetch_klines.py ← 資料管線：data.binance.vision → feather（對 agent 唯讀）
   ├─ log/            ← 研究日誌（agent 可寫）
   └─ experiments/    ← 探針程式碼（agent 可寫；失敗的也留著）
```

2026-08-01 起這條線由 **autoresearch 迴圈**執行（`.github/workflows/claude-autoresearch.yml`，
手動觸發）。可寫路徑白名單由 workflow 的 guard step 機器強制，不靠自制力——
細節見 `research/program.md` §3 與 `CLAUDE.md`「自主研究迴圈」段。

三條邊界：

| 邊界 | 規則 |
|---|---|
| **部署** | `research/` 不在 Dockerfile 的 COPY 清單；live 路徑（`pump_detect.py` / `daily_pulse_dispatch.py`）**永不 import** `research/` 下的任何東西 |
| **參數** | 研究方向各自持有 PARAMS 與預登記文件，與 `detector.py` 完全獨立 |
| **憑證** | 研究階段全離線，只吃歷史 feather；本 repo 永不出現任何交易所 API key |

`research/` 可以單向 `from scripts.detector import add_indicators`（唯讀複用指標計算），
但反向依賴一律禁止。

---

# 方向一：網格交易可行性調研

**狀態**：調研中（未立案）
**技術參考**：`docs/RESEARCH_GRID_MECHANICS.md`
**建立日**：2026-07-31

## 為什麼跟 BBW 偵測器相關

方向相反，**狀態變數相同**。`detector.py` 的核心是 `bbw_pct`（BBW 在 30 天窗的百分位）：

| | pump-radar 現行用法 | 網格用法 |
|---|---|---|
| `bbw_pct` 低（壓縮） | 「準備爆發」的前置條件 → 標 A 級 | **黃金運行期**（區間震盪吃格差） |
| 放量突破上軌（`event`） | 訊號觸發，開始追蹤 | **關機訊號**，波動爆發＝網格死亡 |
| 需要的預測 | 無（禁方向預測） | 也不需要方向——**只需要振幅** |

**關鍵**：網格的存亡與方向無關，只與「持倉期間價格會不會走出區間寬度 W」有關。
這完全繞開「不做次根方向預測」的紅線，因為它問的是**波動幅度分佈**，不是方向。

而這個分佈 pump-radar 已經在算了——`score_signals.py` 的 MFE/MAE 就是振幅。
`DETECTOR_PREREG.md` 現有數字翻成網格語言：

> 訊號觸發後 24h，區間下緣放在 −1.4%（A 級 MAE 中位）的網格約有一半機率被打穿；
> 放在 −3% 的約有 14%（A 級）／26%（B 級）機率被打穿。

## Phase 0 — 用現有資料回答「區間該多寬」

**這是整條線 CP 值最高的一步，且完全在現有能力圈內，不需要任何交易基礎建設。**

要回答的問題：

> 給定當下 `bbw_pct = p`，未來 T 小時內的最大振幅
> `(max(high) − min(low)) / close` 的分位數分佈是什麼？

- 產出：`research/experiments/` 下的探針（估 ~120 行），複用 `scripts/detector.py` 的
  `add_indicators`，吃 `research/fetch_klines.py` 抓下來的 feather 目錄
- 輸出：一張 `bbw_pct 分桶 × T(1/4/12/24h)` 的振幅分位數表（p50/p80/p95，每格附 n）
- **不動 `detector.py` 一個字**
- **分桶／T／度量／去叢集口徑已凍結**在 `research/program.md` §4（先於結果寫死，防事後挑分桶）；
  分析窗口與標的登記在 `research/backlog.md` 的 Q1。文獻依據見 `docs/RESEARCH_BBW_VOLATILITY.md`
  ——特別注意它的提醒：**短 T（1h/4h）低分桶「振幅更小」是 GARCH 持續性下的預期結果**，
  不是假設被推翻，真正的檢定戰場在 24h 那一檔。

**驗收**：能明確讀出「壓縮狀態下，區間放多寬才有 80% 機率撐過 T 小時」。
若 `bbw_pct` 對後續振幅**無區別力**（各分桶分佈重疊），整條線直接終止——
因為那代表網格區間根本無法事前定寬，只能碰運氣。

## Phase 0.5 — 反向驗證：現行 event 是不是好的網格 kill-switch

比較「`event` 觸發後 24h 振幅」vs「隨機時點 24h 振幅」的分佈。

- 資料：`data/insample_scored.tsv`（235 筆種子）+ feather 全量作為對照組
- 若前者顯著大於後者 → 偵測器是一個**經過驗證的波動爆發預警**

**這與「追價期望為負」不衝突**：kill-switch 不需要方向，只需要振幅。
這也是現有數據唯一支持得起的新敘述，且不觸碰任何紅線。

> 誠實註記：此檢驗的對照組取樣需避開事件叢集（同一 4h 窗多標的齊發），
> 沿用 `DETECTOR_PREREG.md` 已預登記的「同 4h 窗僅計首發」去叢集視角。

## Phase 1 — 撮合回放器（Phase 0 結果支持才做）

- 抄 `grid.js` 的 77 行策略本體 + `ex/paper.js:220-260` 的撮合與扣費邏輯
- 吃 15m OHLCV，掃參數空間：區間寬度 × 格數 × 出區間策略（close / recover）
- **頭條指標必須是淨損益分佈，不是勝率、不是完成格數**
  （網格勝率天然接近 100%，用勝率驗證等同沒驗證——見 DirProbe 教訓）
- 必須扣手續費；必須修掉原專案「回收階梯成交計入完成格數」的口徑錯誤

## Phase 2 — 預登記（Phase 1 樣本內基準為正才做）

另寫預登記文件，鎖死參數與計分口徑，開跑 forward。
**禁止沿用 pump-radar 的任何參數或判準。**

## Kill criteria（預先寫死）

| 階段 | 終止條件 |
|---|---|
| Phase 0 | `bbw_pct` 分桶對後續振幅無區別力 → 終止 |
| Phase 1 | 樣本內淨期望為負 → **照實記錄後收攤，不做參數搜尋救活** |

## AI 的位置（預先寫死，避免後面手癢）

下單 / 補單 / 對帳**永遠純規則**；LLM 只能碰敘述層（日報、告警）。
理由不是 AI 不夠聰明，是 **LLM 決策不可回放、不可預登記**——
同樣輸入下次給不同答案，永遠算不出樣本內基準，也就永遠無法判定有沒有 edge。
詳見 `RESEARCH_GRID_MECHANICS.md` 第六節。

---

# 方向二：（待填）

<!-- 新方向照上面格式加：狀態 / 動機 / 階段 / kill criteria -->
