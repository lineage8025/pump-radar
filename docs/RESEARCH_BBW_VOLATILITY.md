> 建立於 2026-08-01。**本文件是文獻調研，不構成已採納的方法論**——不改動
> `scripts/detector.py`、不改動任何預登記文件。目的是替 `docs/RND_BACKLOG.md`
> 「方向一 Phase 0」的核心假設找一手依據：**「當下 `bbw_pct` 低 ⇒ 未來 T 小時最大振幅
> 分佈可預測」**。

# BBW 壓縮 → 後續實現波動：文獻調研

## TL;DR

文獻**不支持**「壓縮之後傾向爆發」這個方向性直覺，反而支持相反的短期效應：
波動有**持續性**（GARCH／volatility clustering），低波動之後短期內傾向**續**低波動，
不是傾向轉高。John Bollinger 本人的一手文字也**沒有**明講「squeeze 之後必噴出」，
官方頁面對「之後會怎樣」幾乎留白，唯一講清楚的一手警語反而是「head fake」——
提醒使用者第一次假突破常常方向相反且很快回頭。

真正支持「極端壓縮終將回歸」的機制不是「壓縮→爆發」的直覺反轉，而是**波動的均值回歸**：
GARCH 類模型的變異數是「短期持續、長期回歸不條件均值」，兩者不矛盾。這代表 Phase 0
問的問題本身沒有錯（振幅分位數 vs 波動狀態是可以量的），但**理論上該預期的訊號來源
是「均值回歸的力道隨壓縮極端程度而增強」，不是「壓縮本身就是爆發的觸發器」**——
這兩個敘事在 Phase 0 的實證結果上可能長得很像，但因果解讀不同，寫報告時要分清楚。

加密貨幣專屬、同儕審查、直接測「布林帶壓縮預測後續振幅」的一手文獻**找不到**。
Crypto 波動聚集的 GARCH 文獻很多，但沒人一手驗證過 BBW squeeze 這個具體度量在
15m 頻率上的區別力。這是本次調研最大的缺口，Phase 0 因此是名副其實的「原創驗證」，
不是「複現既有結果」。

---

## 一、BBW / Squeeze 的原始定義出處

### 1.1 BandWidth 定義

Bollinger 官方頁面對 BandWidth 的定義：

> "BandWidth tells us how wide the Bollinger Bands are. The raw width is normalized
> using the middle band. Using the default parameters BandWidth is four times the
> coefficient of variation."
— [Bollinger Bands Explained / Bollinger Band Rules, bollingerbands.com](https://www.bollingerbands.com/bollinger-band-rules)

公式（StockCharts ChartSchool，內容轉錄自 Bollinger 的公開教材，非他本人逐字撰寫，
但為業界公認的官方定義複製版）：

```
BandWidth = (Upper Band − Lower Band) / Middle Band        （× 100 表示成百分比）
```
— [Bollinger BandWidth, ChartSchool](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/bollinger-bandwidth)

**對照 `detector.py:32`**：`df["bbw"] = (df["bb_upper"] - df["bb_lower"]) / mid`，`mid` 是
20 期 SMA（`bb_window=20`），`bb_std=2.0`。這就是 Bollinger 定義的 BandWidth 本身
（未乘 100，純比例），口徑一致，沒有魔改。

### 1.2 「The Squeeze」

Bollinger 自己的頁面對 squeeze 只有一句話，**沒有展開「之後會怎樣」**：

> "Its most popular use is to identify 'The Squeeze', but is also useful in identifying
> trend changes..."
— [bollingerbands.com/bollinger-band-rules](https://www.bollingerbands.com/bollinger-band-rules)

「squeeze = BandWidth 創 6 個月新低」這個具體門檻定義，是 StockCharts ChartSchool 的
教材化描述，非 Bollinger 本人在其官網逐字寫下的規則：

> "Squeeze means a stock's BandWidth is at its narrowest (lowest %) in 6 months."
— [Bollinger Band Squeeze, ChartSchool](https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/bollinger-band-squeeze)

**誠實註記**：這條「6 個月」門檻本身沒有一手統計驗證出處——它是 Bollinger 教材裡
的**經驗法則**，不是回測結果。`detector.py` 用的是 30 天滾動百分位（`bbw_pct_window=2880`
根 15m）＋ ≤25% 分位（`squeeze_pct=0.25`），窗口與門檻都跟原始「6 個月」定義**不同**，
是專案自訂參數，不能拿 Bollinger 的權威性去背書這組數字本身的有效性——這點文件裡
必須說清楚，避免「因為 Bollinger 說過 squeeze 有效，所以我們的 25%/30 天版本也有效」
的邏輯跳躍。

**「之後會發生什麼」是否有方向性宣稱？** 沒有一手文字明講「squeeze 之後必然噴出」。
ChartSchool 的措辭是條件式、方向留白：

> "The direction depends on the subsequent band break." / 初次突破有時會失敗，
> 訊號並非全部可靠。
— [Bollinger BandWidth, ChartSchool](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/bollinger-bandwidth)

即使是「壓縮之後常接大波動」這種常見講法，也多半是二手部落格轉述、非本次調研在
Bollinger 一手文字裡直接驗證到的逐字宣稱——**這點必須降級標注**：本文件**未能**在
bollingerbands.com 一手頁面上找到「squeeze 之後波動必將擴張」的逐字宣稱，只找到
「squeeze 常用來識別即將到來的波動」這種較弱、無方向、無機率數字的措辭。

### 1.3 Head Fake——Bollinger 自己最明確的一手警語

這是本節找到**最強**的一手證據，直接反駁「squeeze → 順向噴出」的天真讀法。

Bollinger 本人 X/Twitter 帳號（@bbands）原文：

> "A Head Fake is a rapid reversal in price direction that most often occurs after
> a Squeeze, usually on high volume and at a Bollinger Band."
— [John Bollinger, @bbands, X/Twitter](https://x.com/bbands/status/737772755412606977)
（本次調研 WebFetch 直接抓取該頁遭 403，逐字內容取自搜尋引擎索引摘要，未能重新驗證
原頁面仍存在該逐字文字——嚴格說屬「搜尋引擎快取轉述」而非親眼讀到原頁，予以註記。）

書中原文（*Bollinger on Bollinger Bands*, p.121），由第三方作者逐字轉錄並標明頁碼：

> "Traders beware! There is a trick to The Squeeze, an odd turning of the wheel that
> you need to be aware of, the head fake."
— 轉引自 [Arthur Hill, "A BB Breakout or the Dreaded Head Fake?", StockCharts/TrendInvestorPro, 2020](https://articles.stockcharts.com/article/articles-chartwatchers-2020-07-a-bb-breakout-or-the-dreaded-h-684)

**降級註記**：本文件未直接取得《Bollinger on Bollinger Bands》原書頁面 121 的掃描或
原文，此句是第三方作者（Arthur Hill）逐字轉錄並標頁碼——可信度高但**非一手**，
按規則降級為「有頁碼依據的二手轉述」。

**這條的意義對 Phase 0 很關鍵**：Bollinger 本人明講的是「壓縮後第一次突破常常是假的、
方向會反轉」，這跟「壓縮後振幅會放大」**不衝突**（head fake 本身就是一次振幅事件，
只是方向騙人）——但也**不支持**「壓縮後第一根突破就代表趨勢確立」。這與 pump-radar
`CLAUDE.md` 的紅線「不做次根方向預測」剛好呼應：Bollinger 自己的觀察也指向「方向
在噴出當下不可信」，只是他討論的是「突破當根」，pump-radar 討論的是「突破根之後的
未來走勢」，層次略有不同，不能直接等同。

---

## 二、學術證據：波動聚集（volatility clustering）——與直覺相反的部分

### 2.1 現象最早的一手表述

「大變動後接大變動、小變動後接小變動」這個觀察，最早的一手學術表述通常追溯到：

> Mandelbrot, B. (1963). "The Variation of Certain Speculative Prices."
> *The Journal of Business*, 36(4), 394–419.

**降級註記**：本次調研查得到期刊卷期（Vol. 36, pp. 394-419），但未能取得該文全文，
逐字的「large changes tend to be followed by large changes...small by small」措辭
是後續文獻（含 Cont 2001／2007）對 Mandelbrot 觀察的標準轉述，本文件**未能直接讀到
1963 年原文裡的逐字句子**，屬於「經廣泛引用但未親自核對原文逐字」。

### 2.2 ARCH — Engle (1982)

> Engle, R.F. (1982). "Autoregressive Conditional Heteroscedasticity with Estimates
> of the Variance of United Kingdom Inflation." *Econometrica*, 50(4), 987–1007.
> DOI 對應期刊頁：[econometricsociety.org](https://www.econometricsociety.org/publications/econometrica/1982/07/01/autoregressive-conditional-heteroscedasticity-estimates)

摘要核心論點（經多個索引來源交叉確認的標準轉述，原文在 JSTOR/Econometric Society
頁面回應 402 付費牆，**本文件未能直接讀到 JSTOR 全文摘要頁**，以下為學界廣泛複誦的
摘要文字，降級標注）：

> ARCH processes are mean zero, serially uncorrelated processes with nonconstant
> variances conditional on the past, but constant unconditional variances. For such
> processes, the recent past gives information about the one-period forecast variance.

**這句話是本文件最重要的一句**：ARCH／GARCH 講的是「條件變異數」隨時間變動且
可由近期資料預測，但**序列本身（報酬）是序列不相關的**——也就是說，波動可預測不等於
報酬（方向）可預測。這與 pump-radar 的紅線「不做方向預測」完全相容，也是 Phase 0
「只問振幅、不問方向」設計正確的理論基礎。

### 2.3 GARCH — Bollerslev (1986)

> Bollerslev, T. (1986). "Generalized Autoregressive Conditional Heteroskedasticity."
> *Journal of Econometrics*, 31(3), 307–327. DOI:
> [10.1016/0304-4076(86)90063-1](https://doi.org/10.1016/0304-4076(86)90063-1)

本文件直接從作者本人 Duke 大學個人頁面抓取原始 PDF
（[public.econ.duke.edu/~boller/Published_Papers/joe_86.pdf](https://public.econ.duke.edu/~boller/Published_Papers/joe_86.pdf)，
確認為原始已發表版本），但自動化文字擷取工具對該掃描版 PDF 解析失敗，**未能逐字引用
內文**，僅能確認：GARCH 將 ARCH 的條件變異數方程式一般化，加入落後條件變異數項本身
（不只是落後平方殘差），使變異數具備更長的記憶／持續性；論文以英國通膨不確定性為
實證例子。

### 2.4 長記憶性——Ding, Granger & Engle (1993)

> Ding, Z., Granger, C.W.J., & Engle, R.F. (1993). "A Long Memory Property of Stock
> Market Returns and a New Model." *Journal of Empirical Finance*, 1(1), 83–106.

摘要核心發現（經多個索引來源交叉確認）：

> 絕對報酬之間的自相關遠高於報酬本身的自相關；`|r_t|^d` 這種冪次轉換在 `d≈1` 時
> 自相關在很長的落後期都維持顯著（即「長記憶」）。

**與 Phase 0 的直接關聯**：這篇是「壓縮之後短期內傾向續壓縮」最硬的證據——如果波動
的自相關結構在幾十、幾百期之後都還顯著，代表**當下低 `bbw_pct` 對「緊接著的未來」
最強的預測方向是「還是低」，不是「反轉成高」**。Phase 0 若只看短 T（1h/4h），
歷史上這個效應方向大機率跟直覺（壓縮預示噴出）相反；只有在較長 T（例如 24h 甚至
更長）、且壓縮已經處於歷史極端分位（比如 <5%）時，波動的均值回歸力才可能開始
壓過短期持續性，讓「振幅擴大」的訊號浮現。**這是 Phase 0 分桶設計必須內建的張力**，
見第五節建議。

### 2.5 波動聚集的標準教材表述——Cont (2001)

> Cont, R. (2001). "Empirical Properties of Asset Returns: Stylized Facts and
> Statistical Issues." *Quantitative Finance*, 1(2), 223–236.
> IOP 頁面：[iopscience.iop.org](https://iopscience.iop.org/article/10.1088/1469-7688/1/2/304/meta)

本文件嘗試直接抓取作者本人網站 PDF（`rama.cont.perso.math.cnrs.fr/pdf/empirical.pdf`）
但因憑證主機名不符（TLS 憑證只涵蓋 `*.perso.math.cnrs.fr`，非確切主機名）擷取失敗，
**未能讀到原文逐字內容**，僅能確認此文是「波動聚集」（volatility clustering）與其他
資產報酬統計特徵（肥尾、無報酬自相關但有絕對值/平方值自相關等）的標準教材級整理，
被廣泛引用為 GARCH 文獻對「stylized facts」的權威彙整之一。

---

## 三、學術證據：低波動之後真的會爆發嗎？——Range Estimator 文獻

Phase 0 用的度量是 `(max(high) − min(low)) / close`，這正是學界「high-low range
estimator」家族的簡化版。以下是這條線的一手（或接近一手）出處：

### 3.1 Parkinson (1980) — 極值法的原始出處

> Parkinson, M. (1980). "The Extreme Value Method for Estimating the Variance of
> the Rate of Return." *The Journal of Business*, 53(1), 61–65.
> [IDEAS/RePEc 條目](https://ideas.repec.org/a/ucp/jnlbus/v53y1980i1p61-65.html)（該頁
> 註明 "No abstract is available for this item"）

**降級註記**：本文件**未能取得原文**（JSTOR 付費牆，CME Group 鏡像 PDF 兩次請求皆
逾時），RePEc 索引頁本身也沒有摘要。以下公式是金融計量教材（包含後續 Yang-Zhang
2000 論文在自己正文中對 Parkinson 估計量的公式化複誦）廣泛重製的版本，**非本文件
直接從 Parkinson 原文核對**：

```
σ²_Parkinson = (1 / (4·n·ln2)) · Σ [ln(High_i / Low_i)]²
```

已知假設（同樣是教材級共識，非本文件核對原文後確認）：連續採樣（continuous sampling）、
幾何布朗運動、零漂移（zero drift）。**不處理跳空（overnight/inter-bar gap）**，
對離散採樣（例如固定用 15m K 棒的 high/low 而非真正連續路徑）會有效率損失，
且採樣頻率越低（K 棒越粗），對真實路徑極值的低估越嚴重。

### 3.2 Garman-Klass (1980) — 加入開高低收

> Garman, M.B. & Klass, M.J. (1980). "On the Estimation of Security Price
> Volatilities from Historical Data." *The Journal of Business*, 53(1), 67–78.
> [IDEAS/RePEc 條目](https://ideas.repec.org/a/ucp/jnlbus/v53y1980i1p67-78.html)

**降級註記**：同樣**未能取得原文全文**（RePEc 頁面摘要僅一句「Shows various methods
of estimating volatility from historical data」，多個 PDF 鏡像連結回傳 404/403）。
已知此文在 Parkinson 基礎上加入開盤與收盤價，效率優於純 high-low 估計量，但仍假設
連續採樣、無跳空、無買賣價差（bid-ask bounce）雜訊——這些假設在低流動性時段或
低量交易對（相對於 pump-radar 掃描的部分中小市值幣種）容易被違反。

### 3.3 Yang-Zhang (2000) — Drift-independent，處理跳空

> Yang, D. & Zhang, Q. (2000). "Drift-Independent Volatility Estimation Based on
> High, Low, Open, and Close Prices." *The Journal of Business*, 73(3), 477–492.
> 作者本人 SSRN 版本：[papers.ssrn.com/abstract_id=229190](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=229190)

摘要（取自作者本人 SSRN 貼文頁，較前兩篇更接近一手）：新估計量結合隔夜跳空報酬與
Rogers-Satchell 型態的日內估計量，具備三個特性：**連續極限下無偏**、**不受漂移項
影響**、**能正確處理開盤跳空**，且在同類「無偏＋漂移獨立」估計量中變異數最小。

**與 Phase 0 的關聯**：這篇論文的存在本身就是一個警訊——它是專門為了修正 Parkinson
與 Garman-Klass **對跳空不敏感、對漂移項敏感**的缺陷而寫的。pump-radar Phase 0 打算用
的 `(max(high)-min(low))/close` 是最原始、未修正的 Parkinson 型態極值法，**沒有做
跳空修正、也沒有做漂移修正**——在 15m 幣圈資料上，跨日缺口不是主要問題（幣圈 24h
交易，K 棒間 gap 通常很小），但「漂移項」在單邊行情裡可能被 A 級訊號本身觸發的走勢
汙染（Parkinson 估計量假設零漂移，若價格在觀察窗內強力單邊上漲，range 會系統性
高估波動而非中性反映）。

### 3.4 Regime switching / 波動的持續 vs 均值回歸——兩因子結構

> Alizadeh, S., Brandt, M.W., & Diebold, F.X. (2002). "Range-Based Estimation of
> Stochastic Volatility Models." *The Journal of Finance*, 57(3), 1047–1091.
> DOI: [10.1111/1540-6261.00454](https://doi.org/10.1111/1540-6261.00454)；
> 作者本人頁面 PDF：[sas.upenn.edu/~fdiebold](https://www.sas.upenn.edu/~fdiebold/papers/paper33/final.pdf)

本文件從作者（Diebold）本人賓大頁面抓到已發表版本 PDF，但該檔是掃描影像格式
（JBIG2 編碼），自動化文字擷取失敗，**未能逐字核對內文**。可確認的元資料與經索引
交叉確認的核心發現：論文主張 range-based 波動代理量效率高、近似高斯分布、
對市場微結構雜訊穩健；用該方法檢驗匯率日波動動態，發現證據指向**雙因子結構——
一個高度持續（persistent）的因子＋一個快速均值回歸（mean-reverting）的因子**。

**這正是解開本節張力的關鍵**：波動同時具備「短期持續」與「較長期均值回歸」兩種力量，
不是二選一。GARCH 的「持續性」講的是「相鄰時段之間高度相關」（第二節），這條「雙因子」
文獻講的是「除了持續性之外，還有一股把波動拉回長期均值的力」。**壓縮狀態離長期均值
越遠（分位數越極端），均值回歸力越強**；這代表如果 Phase 0 真的能量出「壓縮 → 後續
振幅擴大」的訊號，理論上更可能出現在**極端分位（如 <10%）而非普通低分位（25%~50%）**，
且更可能在**較長 T**（例如 24h）而非短 T（1h）才顯現，因為均值回歸本身需要時間展開，
而持續性在短窗支配。

> Hamilton, J.D. (1989). "A New Approach to the Economic Analysis of Nonstationary
> Time Series and the Business Cycle." *Econometrica*, 57(2), 357–384.

僅列為背景引用：Markov regime-switching 模型的奠基文獻，本文件**未深入其波動應用**，
只用來標注「波動狀態存在離散 regime、且 regime 轉換本身可被建模」這個大方向確有
紮實的計量文獻支撐，但未針對此文做逐字核對（付費牆／未進一步追蹤），列為背景參考
而非直接支持 Phase 0 假設的證據。

---

## 四、加密貨幣市場的特殊性

### 4.1 Crypto 波動聚集：文獻很多，但都不是「BBW squeeze → 振幅」這個具體命題

Crypto 的 GARCH 系文獻確實存在且量大，例如：

> "Predicting the Volatility of Cryptocurrencies' Returns Using High-Frequency
> Data: A Comparative Analysis of GARCH, EGARCH, IGARCH, GJR-GARCH, LRE, and HAR
> Models." *Journal of Risk and Financial Management*, 14(4), 90 (MDPI, 開放取用期刊)。
> [mdpi.com/2227-7072/14/4/90](https://www.mdpi.com/2227-7072/14/4/90)

**降級註記**：本文件嘗試直接抓取該 MDPI 開放取用頁面遭 403 阻擋，**未能讀到全文或
摘要**，僅能確認標題、期刊（MDPI JRFM，同儕審查、開放取用）與大致主題（12 種加密
貨幣、5 分鐘高頻報酬、比較多種 GARCH 家族模型）。此文屬 crypto GARCH 波動聚集的
同儕審查一手文獻，但本文件未親自核對其對「壓縮→後續振幅」的具體結論。

其餘檢索到的相關同儕審查文獻（均只讀到標題/索引摘要，**未逐一核對全文**，因此不
展開細節，僅列存在性）：

- Springer *Future Business Journal*（開放取用期刊）"Volatility dynamics of
  cryptocurrencies: a comparative analysis using GARCH-family models"（2025）——
  嘗試直接抓取遭該站認證跳轉阻擋，未讀到內容。
- ScienceDirect "A hybrid model for intraday volatility prediction in Bitcoin
  markets"（2025）——摘要頁 403，未讀到內容。

### 4.2 Bollinger Bands 策略在 crypto 上的實證：找不到高品質一手來源

本次調研**找不到**同儕審查期刊、直接測試「BBW squeeze 預測後續振幅」這個具體命題
在加密貨幣市場（更遑論 15m 頻率）上的一手研究。唯一貼近題目的是：

> Arda, E. (2025). "Bollinger Bands under Varying Market Regimes: A Comparative
> Study of Breakout and Mean-Reversion Strategies in BTC/USDT." SSRN Working Paper.
> [papers.ssrn.com/abstract_id=5775962](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5775962)

**明確降級**：這是 **SSRN 上未經同儕審查的工作論文**（2025 年 12 月），不是期刊
發表；本文件直接抓取該頁遭 403，內容僅來自搜尋引擎的索引摘要，**完全未核對全文**、
未確認作者機構、未確認樣本期間與統計方法的嚴謹度。索引摘要顯示其比較的是「突破 vs
均值回歸」策略在不同市場 regime（牛市／派發階段）下的表現，**這是策略層面的比較，
不是「squeeze 本身對振幅有無區別力」的統計檢定**，命題不完全對應 Phase 0 要問的
問題。**不應該當作 Phase 0 假設的證據使用**，只能當作「業界有人在關注類似問題」的
線索。

**誠實結論**：加密貨幣 BBW squeeze 的一手同儕審查證據**查不到**。Phase 0 因此是
在填補一個真實的文獻空白，不是複現已知結果——這既是風險（沒有先驗可以校準期待）
也是機會（如果做出乾淨結果，是原創發現）。

---

## 五、對 Phase 0 設計的具體建議

1. **分桶要覆蓋極端分位，不能只切 25/50/75**。第三節的「雙因子」論點指向：如果
   「壓縮→振幅擴大」訊號存在，最可能出現在最極端的低分位（例如 `bbw_pct < 0.05` 或
   `<0.10`），而非 `detector.py` 現用的 `squeeze_pct=0.25`。Phase 0 的分桶表建議至少
   切到 `<5%` 這一檔獨立看，不要跟 `10%~25%` 的桶混在一起——用 25% 當門檻可能把
   均值回歸訊號稀釋到看不見。

2. **T 要覆蓋到夠長**。GARCH 短期持續性（第二節）意味著短 T（1h、可能 4h）的振幅
   分佈在低 `bbw_pct` 分桶上大機率是**更窄**而非更寬（持續壓縮）；只有 T 拉長到
   24h 以上，均值回歸力才有機會顯現成「振幅擴大」。若 Phase 0 只看 1h/4h/24h 三檔，
   務必把「1h/4h 結果符合『持續壓縮』」也當作**正常、預期內**的結果來報告，不要
   誤讀成「假設被推翻」——真正的檢定戰場是 24h 那一檔。

3. **對照組要交叉：不只是「當下 bbw_pct 分桶」，還要對照「同分桶但排除量能異常前置」**。
   `detector.py` 的 `event` 同時吃了 `squeeze_before` 與 `vol_z`；Phase 0 若要單獨
   驗證 `bbw_pct` 的區別力，分桶時最好跟 `event`/`vol_z` 解耦，否則量能訊號的效果
   可能被誤記到 BBW 頭上。

4. **振幅估計量要老實承認是簡化版 Parkinson，且未做漂移修正**。第三節指出 Yang-Zhang
   之所以存在，就是因為 Parkinson／Garman-Klass 對漂移項敏感——如果 `bbw_pct` 低的
   時段剛好也是趨勢明確（非橫盤）的時段，`(max-min)/close` 會系統性偏高，把「有方向
   的趨勢延續」誤記成「振幅擴大」，這其實正是網格交易最怕的情境（方向一 RND_BACKLOG
   的核心風險）。若資源允許，Phase 0 可以額外算一版 Yang-Zhang 或至少 Garman-Klass
   估計量做交叉驗證，觀察簡化版與修正版的結論是否一致；若不一致，要老實寫出來，
   不能只挑對故事有利的那個。

5. **採樣頻率的偏誤要寫進限制**。第三節范圍估計量的教材共識是：離散採樣（15m K 棒）
   相對真實連續路徑會低估真實極值，且流動性越薄（小市值幣種、非主流時段），
   K 棒內真實高低點被觸及但未被記錄的機率越高——這對 pump-radar 掃描的中小市值標的
   是實質風險。若條件允許，建議挑 1-2 檔大市值標的（BTC/ETH）與 1-2 檔平時掃到的
   中小市值標的分開跑 Phase 0，看看振幅分佈的區別力是否因流動性而系統性不同；
   若只跑一組聚合結果，至少要在文件裡承認這個混淆變數存在。

6. **avoid look-ahead 的具體檢查清單**（沿用 `detector.py` 既有的「前一根」設計原則）：
   - `bbw_pct` 分桶必須用**訊號觸發那一刻已知**的值（即 `shift(1)` 或更早），不能用
     未來已收盤但當下還沒發生的窗口資料回填百分位分母；`detector.py:36-39` 目前的
     `rolling().rank(pct=True)` 已經是「只排當前值」且用 `shift(1)` 做壓縮判定，
     Phase 0 若復用 `add_indicators` 這條邏輯不會有前視問題，但若自己另外算一套
     百分位（例如全樣本一次算完再切訓練/測試）就會犯規，务必比照現有寫法。
   - 振幅計算的視窗 `T` 必須從分桶當根**之後**開始算（不含當根自己），且不能讓
     `T` 視窗跨越到下一次 `bbw_pct` 取樣點導致同一段資料被算兩次而虛增樣本獨立性
     ——這與 `DETECTOR_PREREG.md` 已預登記的「同 4h 窗僅計首發」去叢集邏輯是同一個
     坑，Phase 0 要嘛沿用同一套去叢集規則，要嘛在文件裡明講沒做、樣本並非獨立。

---

## 六、未解問題／查不到的東西

- **Bollinger 本人是否在一手文字裡明講「squeeze 之後波動擴張的機率/幅度」的具體數字**：
  查不到。他的公開文字（官網、書摘轉引）在方向與機率上都是定性、留白的，沒有可引用
  的量化宣稱。
- **Parkinson (1980) / Garman-Klass (1980) 原文全文**：兩次都被付費牆或逾時擋下，
  本文件對這兩篇的公式與假設描述**全部是教材複誦，非親自核對原文**，降級處理。
- **Bollerslev (1986) / Cont (2001) / Alizadeh-Brandt-Diebold (2002) 的原文逐字內容**：
  三篇都成功定位到作者本人網站或已發表 PDF（一手來源確實存在），但自動化擷取工具
  對掃描版/憑證異常的檔案處理失敗，**未能逐字引用內文**，僅能確認文獻存在、
  DOI／卷期正確、以及經多方索引交叉確認的核心論點方向。
- **加密貨幣市場專屬、同儕審查、直接檢定「BBW squeeze 對後續振幅有無區別力」的一手
  論文**：找不到。這是本次調研最大的空白，也是 Phase 0 存在的理由——它填補的是一個
  真實的文獻缺口，不是重複驗證。
- **crypto 24/7 交易對「波動聚集」與傳統市場（有開盤/收盤跳空）文獻結論是否完全
  可直接套用**：本次調研沒有找到專門討論「24h 連續交易 vs 有隔夜缺口市場」對
  GARCH／range estimator 假設影響差異的一手文獻，只能合理推論（跳空問題較小、
  但連續交易可能弱化「隔夜資訊累積」這個 GARCH 常見的解釋機制），未經一手驗證，
  不應當成定論。

---

## 參考文獻

**Bollinger BandWidth / Squeeze（一手或最接近一手）**
- [Bollinger Bands Explained / Bollinger Band Rules, bollingerbands.com](https://www.bollingerbands.com/bollinger-band-rules)
- [Bollinger BandWidth, ChartSchool / StockCharts](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/bollinger-bandwidth)
- [Bollinger Band Squeeze, ChartSchool / StockCharts](https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/bollinger-band-squeeze)
- [John Bollinger, @bbands, X/Twitter，head fake 定義](https://x.com/bbands/status/737772755412606977)（搜尋引擎索引摘要，未能重新驗證原頁）
- Bollinger, J. *Bollinger on Bollinger Bands*, p.121（head fake 段落，經 [Arthur Hill, StockCharts/TrendInvestorPro, 2020](https://articles.stockcharts.com/article/articles-chartwatchers-2020-07-a-bb-breakout-or-the-dreaded-h-684) 逐字轉錄）

**波動聚集 / GARCH 系文獻**
- Mandelbrot, B. (1963). "The Variation of Certain Speculative Prices." *The Journal of Business*, 36(4), 394–419.（未取得全文）
- Engle, R.F. (1982). "Autoregressive Conditional Heteroscedasticity with Estimates of the Variance of United Kingdom Inflation." *Econometrica*, 50(4), 987–1007. [econometricsociety.org](https://www.econometricsociety.org/publications/econometrica/1982/07/01/autoregressive-conditional-heteroscedasticity-estimates)（摘要付費牆，逐字句轉引自索引來源）
- Bollerslev, T. (1986). "Generalized Autoregressive Conditional Heteroskedasticity." *Journal of Econometrics*, 31(3), 307–327. DOI: [10.1016/0304-4076(86)90063-1](https://doi.org/10.1016/0304-4076(86)90063-1)。作者本人 PDF：[public.econ.duke.edu/~boller/Published_Papers/joe_86.pdf](https://public.econ.duke.edu/~boller/Published_Papers/joe_86.pdf)
- Ding, Z., Granger, C.W.J., & Engle, R.F. (1993). "A Long Memory Property of Stock Market Returns and a New Model." *Journal of Empirical Finance*, 1(1), 83–106.
- Cont, R. (2001). "Empirical Properties of Asset Returns: Stylized Facts and Statistical Issues." *Quantitative Finance*, 1(2), 223–236. [iopscience.iop.org](https://iopscience.iop.org/article/10.1088/1469-7688/1/2/304/meta)（作者本人 PDF 連結因憑證問題無法擷取）

**Range Estimator / Regime Switching**
- Parkinson, M. (1980). "The Extreme Value Method for Estimating the Variance of the Rate of Return." *The Journal of Business*, 53(1), 61–65.（未取得全文，無公開摘要）
- Garman, M.B. & Klass, M.J. (1980). "On the Estimation of Security Price Volatilities from Historical Data." *The Journal of Business*, 53(1), 67–78.（未取得全文）
- Yang, D. & Zhang, Q. (2000). "Drift-Independent Volatility Estimation Based on High, Low, Open, and Close Prices." *The Journal of Business*, 73(3), 477–492. 作者 SSRN 版本：[papers.ssrn.com/abstract_id=229190](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=229190)
- Alizadeh, S., Brandt, M.W., & Diebold, F.X. (2002). "Range-Based Estimation of Stochastic Volatility Models." *The Journal of Finance*, 57(3), 1047–1091. DOI: [10.1111/1540-6261.00454](https://doi.org/10.1111/1540-6261.00454)。作者本人 PDF：[sas.upenn.edu/~fdiebold/papers/paper33/final.pdf](https://www.sas.upenn.edu/~fdiebold/papers/paper33/final.pdf)（掃描檔，未能擷取逐字內容）
- Hamilton, J.D. (1989). "A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle." *Econometrica*, 57(2), 357–384.（僅列為背景，未深入核對）

**加密貨幣**
- "Predicting the Volatility of Cryptocurrencies' Returns Using High-Frequency Data: A Comparative Analysis of GARCH, EGARCH, IGARCH, GJR-GARCH, LRE, and HAR Models." *Journal of Risk and Financial Management*, 14(4), 90. [mdpi.com/2227-7072/14/4/90](https://www.mdpi.com/2227-7072/14/4/90)（抓取遭 403，僅存在性與標題已確認）
- Arda, E. (2025). "Bollinger Bands under Varying Market Regimes: A Comparative Study of Breakout and Mean-Reversion Strategies in BTC/USDT." SSRN Working Paper（**未經同儕審查**）. [papers.ssrn.com/abstract_id=5775962](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5775962)（抓取遭 403，僅搜尋引擎索引摘要）

**Repo 內部參照**
- `/home/michael/pump-radar/CLAUDE.md`
- `/home/michael/pump-radar/docs/RND_BACKLOG.md`
- `/home/michael/pump-radar/docs/RESEARCH_GRID_MECHANICS.md`
- `/home/michael/pump-radar/scripts/detector.py`（`PARAMS`、`add_indicators`，2026-08-01 讀取版本）
