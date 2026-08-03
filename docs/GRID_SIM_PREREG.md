# 網格 Phase 1 撮合回放預登記（2026-08-03）

> 規則承襲 `DETECTOR_PREREG.md`：**參數自此鎖死**，不得在同段資料回頭調參後宣稱有效；
> 計分口徑先寫死，結果照實累積，不利數據照寫。
>
> 本文件於**任何回放結果產生之前**寫成並 commit。時序判準見 `research/program.md` §4.1。

## 定位

執行 `docs/RND_BACKLOG.md` **方向一 Phase 1「撮合回放器」**。要回答的唯一問題：

> 區間半幅 `W` × 槓桿 `L` × 出區間策略下，持有 `T` 天的**淨損益分佈**是什麼？何時被強平？

**這不是交易系統，也不是把 pump-radar 變成交易 bot。** pump-radar 本體定位不變（15m 布林帶波段啟動的偵測追蹤器）。本文件與 `scripts/detector.py` 的 `PARAMS` **完全獨立**，禁止沿用其任何值。

## 前置閘門（已通過）

`RND_BACKLOG.md` 規定「Phase 1 需 Phase 0 結果支持才做」。`research/LEDGER.tsv`：

- run 1 / 2 / 4 / 6 對 Q1（`bbw_pct` 對後續振幅有無區別力）判 `supports`
- run 6 以 Yang-Zhang／Garman-Klass 交叉驗證主效應，三估計量同向（+2.155 / +2.171 / +2.760 pp，CI 皆不含 0）

閘門通過，Phase 1 得以執行。

> 註：Phase 0.5（Q2 系列，`event` 是否為波動爆發預警）四輪判 `weakens`／未證實。
> **本 Phase 1 不使用 `event` 作為任何開關或條件**，故不受該結論影響。

## 外部起因（照實記錄動機來源）

第三方 repo `beibei030/classic-grid`（2026-08-02 開源）的出廠設定：±4.6% 區間、80 格、30x 槓桿、`marginFrac 0.7`、**無停損無回撤上限**。其 `EQUITY = 800` 為寫死常數（`src/config.ts:18`，無 env 出口）。該設定在下方凍結網格中是一個**具名格位**，不是本研究的唯一目標。

---

## 一、凍結網格（先於任何結果寫死，防事後挑格位）

**以下軸與值是預登記的，回放器必須照跑，不得增刪。**

| 軸 | 值 | 備註 |
|---|---|---|
| 區間半幅 `W` | 1.5, 3, **4.6**, 7, 10（%） | 4.6 = classic-grid 出廠 |
| 格數 `N` | 40, **80** | 80 = 出廠 |
| 槓桿 `L` | 3, 5, 10, 15, **30** | 30 = 出廠 |
| 出區間策略 | **hold**, close, recover | hold = classic-grid 實際行為 |
| 持有期 `T` | 1d, 7d, 30d | |
| 維持保證金率 | **2.0%**（主）、0.5%（穩健性） | 2% 來源：classic-grid `src/venues/risex.ts:162` `maintenanceMarginBps: 200` |
| maker 費率（單邊） | **1.1bp**（主）、0bp、5bp（穩健性） | 1.1bp：`officialStats.ts:213` Decibel `feeMaker:0.00011`；0bp：同檔 Extended；5bp：`config.ts:29` 的保守預檢值 |
| `marginFrac` | **固定 0.7**，不開軸 | 與 `L` 同為線性縮放。報告一律附「實效曝險 = 0.7 × L」 |
| `skipBand` | **固定 0.25 × spacing** | classic-grid `config.ts:33` |
| 模式 | **固定 neutral** | classic-grid `config.ts:33`；不掃 long/short |

**標的與窗口**（登記後不得為改善結果而變更）：

- 標的：`docker-compose.yml` 的 10 個 PAIRS —
  BTC/ETH/ADA/SOL/XRP/DOGE/BNB/LINK/LTC/AVAX（皆 /USDT）
- 窗口：**2023-01-01 ~ 2026-06-30**（與 Q2'' 延長窗口一致）
- 粒度：**1m K 線**

**錨點取樣**：每 24h 一個錨點，且**必須涵蓋全部 24 個 UTC 小時**。

> 這是刻意不重蹈 `program.md` §4「已知限制②」——Phase 0 的去叢集實作為「索引 +96 根」貪婪步進，
> 使取樣點退化成每標的每天同一 UTC 時刻。本 Phase 1 的錨點以標的為單位輪替起始小時，
> 確保相位均勻。`T > 1d` 時 episode 必然重疊，**故 CI 一律用逐 ISO 週 block bootstrap**
> （沿用 Q1' run2 既有作法），不得用假設獨立的標準誤。

---

## 二、策略定義（移植自 classic-grid `src/grid.ts`）

等同 `docs/RESEARCH_GRID_MECHANICS.md` 第一節記錄的 77 行三函式。**回放器不得加入任何原策略沒有的邏輯**（不得加趨勢過濾、不得加動態調寬、不得加停損——那些是別的研究）。

1. **鋪格**：`spacing = 2W / N`；`levels[i] = mid − W + i × spacing`，`i = 0..N`
2. **初始鋪單**：現價下方掛買、上方掛賣；`|level − price| < 0.25 × spacing` 的格位跳過
3. **成交後補單（唯一狀態轉移）**：
   - 買單於 level `i` 成交 → 於 level `i+1` 掛賣（`i+1 > N` 則不補）
   - 賣單於 level `i` 成交 → 於 level `i−1` 掛買（`i−1 < 0` 則不補）

**部位規模**（照 classic-grid `config.ts:102-104` 原式）：

```
notional = equity × marginFrac × L
sizeBase = notional / (N × mid)
```

單邊全數成交時淨部位名義 = `equity × marginFrac × L / 2`。出廠設定（L=30, marginFrac=0.7）下 = **10.5 × equity**。

### 必須實作的不變式（違反即 raise，不容默默通過）

出自 `RESEARCH_GRID_MECHANICS.md` 第二節，該文以實戰教訓標註：

- **① 一格最多一張掛單**
- **② 絕不重新鋪開倉單**（該文標為「最致命的一條」）——網格只由「成交 → 補反向腿」的鏈維持；任何在已成交格位重開同向單的行為 = 單向庫存無限累積 = 爆倉
- **③ 開倉腿／平倉腿分開對待**

---

## 三、撮合模型與假設（先寫死，事後不得改）

### Intrabar 路徑

1m 內採單調路徑：`close ≥ open` 時走 `open→low→high→close`，否則走 `open→high→low→close`。
**兩種序各跑一次**，差異作為敏感度寫入結果表。

### 成交判定

價格觸及格位即視為成交（全額、無滑價）。

> **已知偏誤，方向明確**：真實 post-only 掛單有排隊，碰價未必成交。
> 因此本模型**系統性高估格差收入**。強平判定只看價格極值，**不受此偏誤影響**。
> ⇒ 對「該用多少槓桿」的結論是**安全方向的偏誤**（真實只會更差）；
> 對「網格賺不賺錢」的結論則**偏樂觀**，不得反向解讀。

### 出區間策略

價格離開 `[mid−W, mid+W]` 後：

| 策略 | 行為 |
|---|---|
| `hold` | 不做任何事，掛單留在場上（**classic-grid 實際行為**） |
| `close` | 於出界價全部平倉並撤單，episode 結束 |
| `recover` | 撤掉開倉腿，只保留 reduce-only 階梯等回調分批減倉；**只減不加、不自動止損** |

### 強平判定

```
equity_t = equity_0 + realized_t + unrealized_t − fees_t
強平 ⟺ equity_t ≤ maintenance_rate × |position_t × price_t|
```

強平即 episode 終止，該 episode 記為權益歸零（`equity_multiple = 0`）。

### 未計入的成本（照實列，不得事後補救當作優點）

- **funding**：資料用現貨（見限制段），永續資金費率**完全未計入**。中性網格會累積方向性庫存，funding 是真實成本。
- 滑價、部分成交、交易所停機、下單被拒、API 限流。

---

## 四、度量與頭條指標

**頭條指標（`RND_BACKLOG.md` 原文，不得更動）**：

> **淨損益分佈**。不是勝率、不是完成格數。

理由已預先寫死：網格勝率天然接近 100%，用勝率驗證等同沒驗證（DirProbe 教訓）。

具體定義：`net_return = equity_T / equity_0 − 1`，回報 **mean / median / p5 / p25 / p75 / p95**，每格附 n 與 block bootstrap CI。

**次要指標**：

- `P(強平 | W, N, L, 策略, T)`
- 最大回撤分佈（episode 內 equity 自峰值最大跌幅）
- **損益三分拆解**：格差收入 / 庫存未實現損益 / 手續費——三者相加須等於 net_return，作為帳目自洽檢查

---

## 五、Kill criteria（`RND_BACKLOG.md` 已預寫，本文件照抄鎖死）

| 條件 | 動作 |
|---|---|
| 樣本內淨期望為負 | **照實記錄後收攤，不做參數搜尋救活** |

補充鎖死：若僅**部分格位**淨期望為正，不得單獨挑出該格位宣稱有效——必須整張表照登，並明確標示「這是 50 格掃描的結果，最佳格位的表現含選擇偏誤」。

---

## 六、已知限制（結果出來前先寫，免得事後編故事）

1. **現貨代理永續**。`research/fetch_klines.py` 的 `BASE` 指向 `data/spot/monthly/klines`，且該檔對研究迴圈唯讀、本次不動。沿用現貨是為與 Phase 0 母體一致；代價是 funding 未計入、且永續的插針深度通常大於現貨 ⇒ **對爆倉風險偏樂觀**。
2. **碰價即成交**高估格差收入（見三之偏誤段）。
3. **Intrabar 路徑為假設**，非真實 tick 序。雙序敏感度可界定範圍，但不能消除。
4. **標的為 CEX 主流幣**，classic-grid 實際跑的是新生 perp DEX（Extended/RISEx/Decibel/N1/Phoenix），**流動性更薄、插針更深** ⇒ 同樣對爆倉風險偏樂觀。
5. **Episode 重疊**（T > 1d），樣本非獨立，故 CI 用 block bootstrap；即便如此，有效樣本數低於名目 n。
6. **窗口涵蓋特定市場週期**（2023-01~2026-06），結論不保證外推到未見過的 regime。

以上 1、2、4 三條**方向一致：全部讓模擬結果比真實更樂觀**。因此若模擬結論是「會爆」，真實只會更早爆；若模擬結論是「賺錢」，**不得直接採信**。

---

## 七、本 Phase 明令不做的事

- 不動 `scripts/` 任何檔案、不動 `data/`、不動 `detector.py` 一個字
- 不動 `research/fetch_klines.py`、`research/program.md`（研究迴圈的唯讀協定檔）
- 不掃本文件未登記的軸；想加軸＝改網格，須另行預登記
- 不用 LLM 做任何下單／補單／參數決策（`RND_BACKLOG.md` 已預先寫死：
  下單永遠純規則，理由是 LLM 決策不可回放、不可預登記）
- 結果為負時不做參數搜尋救活
