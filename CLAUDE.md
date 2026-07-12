# pump-radar — 15m 布林帶波段啟動偵測追蹤器

## 定位（不可漂移）
- **偵測追蹤器，不是交易系統**。訊號不是買賣依據——樣本內基準 net_24h 為負（docs/DETECTOR_PREREG.md）。
- 升級為交易 bot 的唯一路徑 = 預登記判準達標（forward ≥100 筆且 net_24h mean>0、勝率>50%），屆時另行預登記，禁直接沿用偵測參數。
- 與 crypto-pulse / quant-trading / SwingPulse **獨立**，不共用 code；方法論教訓見 README「前身」段。

## 紅線（承襲 crypto-pulse）
- `detector.py` 的 `PARAMS` 已預登記鎖死；改任一值＝v2，需重開預登記＋重算樣本內基準，不得只改數字不改文件。
- 計分口徑（進場=次根開盤、頭條=net_24h 含 0.2% 費）寫死在 score_signals.py 與預登記文件，兩處必須一致。
- journal 是 append-only 事實紀錄，不利數據照留。
- **不做次根方向預測**：15m 動能方向已被 DirProbe 92k 樣本證偽（~46%），別重蹈。

## 架構
- 純 Python + ccxt（公開行情，無 API key）+ pandas，**不用 freqtrade**（無交易需求）。
- live 模式 = sh 迴圈每 60s 喚起 `pump_detect.py` 單趟（crash-safe）；只處理已收盤 K 棒（最後一根未收盤，抓完即丟）。
- 偵測邏輯只住在 `detector.py`，live/回放共用——改邏輯絕不能只改其中一邊。
- 狀態檔 `logs/.pump_state.json`（last_seen / cooldown_until，ISO 字串直接比大小）。
- **每日結果日報**（2026-07-12 起）：sidecar 容器 `pump-radar-pulse`（sh 迴圈 25 分）喚起
  `daily_pulse_dispatch.py`，台北 09:00 邊界＋marker 補發語意（同 crypto-pulse digest 教訓），
  聚合 24h 新訊號＋剛滿 24h 的結算成績 → dispatch[daily-pulse] →
  `.github/workflows/claude-daily-pulse.yml` Claude 寫 ≤10 行日報推 Discord。
  安靜日（無新訊號且無新結算）NAS 端直接跳過。已回報結算列記於 `logs/.daily_pulse_state.json`
  防重複。repo secrets 需 `CLAUDE_CODE_OAUTH_TOKEN` + `DISCORD_WEBHOOK_URL`。
  日報兼任 **crypto-pulse 重啟哨兵**（radar 停播後接手）：每日算 BTC 4h align_share(42)，
  連續達標天數記在 state；燈亮/熄/滿 30 天（重啟條款達標）即使安靜日也強制發報。
- **訊息「漲跌展望」行**由 `stats_engine.py` 供給：同型訊號歷史分佈（ret_24h 分位數＋MFE/MAE），
  forward 滿 24h 自動計分入池（快取 `logs/.scored_forward.tsv`）、滾動 120 天窗、每日重算
  （`logs/.grade_stats.json`，失敗退回上次/種子）。**是分佈不是方向預測**；計分函式與
  score_signals 共用不得分岔；p25~p75 覆蓋率校準檢查已預登記（DETECTOR_PREREG）。
  種子 `data/insample_scored.tsv` 是樣本內 235 筆的計分明細，動它=動基準，別碰。

## 部署（Synology NAS，同 crypto-pulse 模式）
- Portainer git-stack 指向本 repo `main`；push 後手動 Pull and redeploy。
- 雷（實踩過）：redeploy 帶 `pullImage=false`（本地 build image）；env 是**整組替換**，先 GET 原 Env 帶回再加新值；urllib 發 Discord webhook 必帶 `User-Agent`（Cloudflare 擋預設 UA 回 403）。
- bind mount 只有 logs：`/volume1/docker/pump-radar/logs` ↔ `/app/logs`。

## 驗證指令
```bash
# 回放（本機 feather 或 ccxt）→ 計分
python scripts/replay.py --pairs BTC/USDT,ETH/USDT,ADA/USDT,SOL/USDT --data-dir <feather目錄> > /tmp/j.jsonl
python scripts/score_signals.py --journal /tmp/j.jsonl --data-dir <feather目錄>
```
