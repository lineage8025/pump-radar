# pump-radar — 15m 布林帶波段啟動偵測追蹤器

## 定位（不可漂移）
- **偵測追蹤器，不是交易系統**。訊號不是買賣依據——樣本內基準 net_24h 為負（docs/DETECTOR_PREREG.md）。
- 升級為交易 bot 的唯一路徑 = 預登記判準達標（forward ≥100 筆且 net_24h mean>0、勝率>50%），屆時另行預登記，禁直接沿用偵測參數。
- **【2026-08-08 結算：判準未達成，定位降為純測量儀器】**（`docs/DETECTOR_PREREG.md`「結算」段）
  n=100 三個分級 net_24h mean 皆為負（A −0.348%／B −0.052%／全體 −0.170%），
  **毛報酬 +0.030% ≈ 0，虧損幾乎全部來自 0.2% 來回費**。三個 CI 皆含 0 ⇒ 是**未達標不是已證偽**。
  三項衍生結論（引用時必須一併帶上）：
  - **A/B 分級樣本外反轉**（樣本內 A 優於 B，forward 相反），且「A 級跌更少」的主張未存活
    （重挫尾巴 11% vs 25% → forward 兩級皆 18%）⇒ **分級不得用於挑訊號或調部位**。
  - **出場規則救不了**：21 格對稱 bracket 中性期望全負。恆等式 `(+x−0.2)/2+(−x−0.2)/2 = −0.2%`
    ——x 被消掉只剩費用。不對稱出場＝方向賭注，已由符號翻轉檢定不受理（TRADEABILITY_PREREG §1.4）。
  - **逐則 Discord 推播已關閉**（`SIGNAL_DISCORD` 預設 0），資料照常累積、日報保留。
    下次回顧設在 n≈400（約 2026-12），不再逐日追蹤。
- **交易化階段（2026-08-05~08-08）已結束，三條路線全部收攤**：方向一網格 kill criteria 觸發（Q8）、
  方向二振幅形狀經濟門檻差一個數量級（Q10，三重驗證）、偵測器本身判準未達（本段）。
  autoresearch 排程已於 2026-08-08 自我到期，不續。**唯一量到有實體的是資金費率 carry
  （Binance 10 標的 gross +7.53%/年），但那是 carry 不是 alpha，且必須另開 repo——本 repo 永不放 API key。**
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

## 自主研究迴圈（autoresearch，2026-08-01 起）
- `.github/workflows/claude-autoresearch.yml`，**每 2 小時一輪的排程班**（12 輪/天，每奇數 UTC 小時 :25＝台北 09:25/11:25/…/07:25）＋隨時可手動 `workflow_dispatch`（可帶 `focus`）。設計借自 karpathy/autoresearch 的 program.md 模式。
- **排程是自我啟停的**：GitHub cron 沒有「從某天跑到某天」，所以用 env `SCHEDULE_FROM` / `SCHEDULE_UNTIL`（台北日期，兩端含當日）＋第一個 gate step 控制——過早或過期都幾秒內跳過、不喚醒 agent，不必靠人記得去 Enable/Disable。**目前設 `2026-08-06`~`2026-08-08`＝每 2 小時制的 36 輪試跑期**；要續跑就改 `SCHEDULE_UNTIL`。手動觸發不受此限。
- **交易化階段（2026-08-05 起）**：目標擴大為「找出能真實交易的方向與策略」，新增位階高於 program.md 的 `docs/TRADEABILITY_PREREG.md`——①紅線 4 的精確化界定（人類簽署）＋可機械判定的**符號翻轉檢定**；②**假設預算**（LEDGER summary 以 `[cells=N]` 開頭）與 Bonferroni 族系錯誤率調整；③**holdout 封存**（研究只准用 2023-01-01~2025-06-30，2025-07-01 之後禁讀，guard step 掃 `experiments/` 新增行的 `--start/--end` 參數）；④五關升級判準，agent 權限上限是關 3、**不得自行宣告策略可用**。研究方向見 `docs/RND_BACKLOG.md` 方向二（振幅形狀／可捕獲趨勢比 R，backlog Q10）與方向三（aggTrades 逐筆校準，Q11）。
- 排程雷：①`schedule` 事件的 `github.actor` 不保證是 repo owner，觸發者閘要加 `github.event_name == 'schedule'` 否則靜默不執行；②cron 分鐘錯開整點（整點負載高易延遲/丟棄）；③間隔 90 分鐘＝job timeout 上限，避免撞 `concurrency` 佇列被頂掉；④gate 算台北日期要用 python3 zoneinfo，`TZ=Asia/Taipei date` 在缺 tzdata 的環境會悄悄退回 UTC 而差一天。
- Actions 分鐘數不計費（public repo 用標準 GitHub-hosted runner 免費），**唯一成本是 Claude 訂閱額度**。
- **夜間班節流**（program.md §2.1）：一晚 4 輪但 backlog 工作量遠少於 4 輪，沒事做的輪次規定寫 `status=blocked` 後結束，禁止重跑已完成探針或換角度重切同一份數據充數——帳本連續 `blocked` 是「backlog 空了」的訊號，補題或關排程由人決定。
- **與 crypto-pulse 版的關鍵差異**：forward journal 在 NAS、日報只推 Discord 不留存，**CI 拿不到 forward 證據**，所以主業不是覆盤 forward，而是**執行 `docs/RND_BACKLOG.md` 的離線探針**——資料由 `research/fetch_klines.py` 從 data.binance.vision 抓（**不用 ccxt**：美國 runner 打 api.binance.com 會 451），全程無 API key。
- 協定 `research/program.md`（對 agent 唯讀）、積壓清單 `research/backlog.md`（agent 唯一可直接編輯的協定檔）、人格 `.claude/agents/researcher.md`、帳本 `research/LEDGER.tsv`（append-only）。
- **Phase 0 凍結網格**寫死在 program.md §4（六分桶 × T=1/4/12/24h × p50/p80/p95），**先於結果**登記，防事後挑分桶；分析窗口與標的登記在 `research/backlog.md` 的 Q1。
- **機器強制**：workflow guard step 檢查 agent push 的路徑白名單（僅 `research/log/`、`research/experiments/`、`LEDGER.tsv`、`backlog.md` 四處）與 LEDGER byte-prefix append-only，越界自動 revert＋Discord 告警＋job fail；另有 failure 通知防無聲跳過。`scripts/`、`data/`、`docs/`、預登記文件對 agent 一律唯讀。
- `research/` **不在 Dockerfile 的 COPY 清單**（只 COPY `scripts/ data/`），永不進容器；`scripts/` 反向 import `research/` 一律禁止。

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
