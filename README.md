# pump-radar

虛擬幣 15m **波段啟動偵測追蹤器**。布林帶（20×2σ）壓縮→放量突破上軌的事件偵測，
Discord 即時通知，每則訊號落 journal，計分器事後誠實對帳。

> **定位聲明**：這是偵測器，不是交易訊號。樣本內基準（2026-05~07，107 事件）顯示
> 「訊號後 24h 含費淨報酬為負」（mean −0.31%，勝率 39%）——與前身專案 crypto-pulse
> 的 DirProbe 結論一致（15m 動能無方向 edge，92k 樣本）。訊號的價值在「即時看見
> 波段正在啟動」，能不能交易由 forward 數據裁決，升級判準已預登記於
> `docs/DETECTOR_PREREG.md`，達標前不建交易 bot。

## 偵測邏輯（v1，參數已鎖）

15m 已收盤 K 棒，全部 AND：

1. 收盤自下而上穿越布林上軌（20 × 2σ）
2. 陽線
3. 量能 z-score ≥ 3（基準 = 前 24h，排除當根）

**A 級** = 觸發前 BBW 百分位（30 天回看）≤ 25%（教科書式壓縮後爆發）；其餘 **B 級**。
同標的 4h 冷卻。標的：BTC/ETH/ADA/SOL（Binance 現貨公開行情，無需 API key）。

驗證：2026-07-06 的盤中 V 型反彈（低點 +5~7%），BTC/ETH/ADA 皆於 15:45 UTC 觸發，
SOL 於 21:00 UTC 觸發。事件頻率全組約 1.6 則/天。

## 結構

```
scripts/
  detector.py        # 偵測核心（純函式；live 與回放共用，避免邏輯分岔）
  pump_detect.py     # live 單趟：ccxt 抓 15m → 偵測 → Discord + journal（sh 迴圈每 60s 喚起）
  replay.py          # 歷史回放 → 事件 jsonl
  score_signals.py   # 計分：journal × K 線 → 1h/4h/12h/24h 報酬、MFE/MAE、含費淨損益
docs/DETECTOR_PREREG.md  # 偵測參數＋計分口徑＋樣本內基準＋升級判準（預登記，鎖死）
docker-compose.yml       # NAS Portainer git-stack 部署（模式同 crypto-pulse）
```

## 本機使用

```bash
pip install ccxt pandas pyarrow

# 歷史回放（無本機資料時自動走 ccxt，抓近 35 天）
python scripts/replay.py --pairs BTC/USDT,ETH/USDT > events.jsonl

# 計分
python scripts/score_signals.py --journal events.jsonl --tsv detail.tsv
```

## NAS 部署

Portainer → Stacks → Add stack → Repository（本 repo、`docker-compose.yml`），
stack env 設 `DISCORD_WEBHOOK_URL`。需先建 `/volume1/docker/pump-radar/logs`（權限可寫）。
journal 累積 ≥100 筆後跑 `score_signals.py` 對 forward 數據結算。

## 前身

[crypto-pulse](https://github.com/lineage8025/crypto-pulse)（2026-07-07 封存）。本專案繼承其
方法論（預登記、誠實計分、forward 為裁判）與教訓（15m 動能方向預測已證偽、urllib 發
Discord 必帶 User-Agent、Portainer redeploy 的 env 整組替換），但 code 完全獨立。
