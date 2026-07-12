"""pump-radar live 偵測（單趟執行，由外層 sh 迴圈每 60s 喚起——與 crypto-pulse radar 同模式，crash-safe）。

流程：ccxt 抓各標的 15m K 線（分頁補足 BBW 百分位所需 30 天）→ detector 判最新已收盤根
→ 新事件則 Discord 通知＋寫 journal。狀態（已處理 bar、冷卻期）落地 logs/.pump_state.json。

環境變數：
  DISCORD_WEBHOOK_URL   未設則只寫 journal 不通知
  PAIRS                 預設 BTC/USDT,ETH/USDT,ADA/USDT,SOL/USDT
  EXCHANGE              預設 binance（僅用公開行情端點，無需 API key）
"""

import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ccxt
import pandas as pd

import stats_engine
from detector import PARAMS, add_indicators, iter_events

LOG_DIR = Path(os.environ.get("LOG_DIR", "/app/logs"))
JOURNAL = LOG_DIR / "pump_journal.jsonl"
STATE_FILE = LOG_DIR / ".pump_state.json"
SCORED_CACHE = LOG_DIR / ".scored_forward.tsv"
STATS_FILE = LOG_DIR / ".grade_stats.json"
FETCH_BARS = PARAMS["bbw_pct_window"] + PARAMS["bb_window"] + 50
TAIPEI = timezone(timedelta(hours=8))


def fetch_15m(ex, pair: str) -> pd.DataFrame:
    rows, since = [], ex.milliseconds() - FETCH_BARS * 15 * 60 * 1000
    while len(rows) < FETCH_BARS:
        batch = ex.fetch_ohlcv(pair, "15m", since=since, limit=1000)
        if not batch:
            break
        rows += batch
        since = batch[-1][0] + 1
        if len(batch) < 1000:
            break
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.iloc[:-1].reset_index(drop=True)  # 丟掉未收盤的最後一根


def notify_discord(msg: str) -> None:
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        return
    req = urllib.request.Request(
        url,
        data=json.dumps({"content": msg}).encode(),
        headers={
            "Content-Type": "application/json",
            # Cloudflare 擋 urllib 預設 UA（crypto-pulse 2026-07-04 實踩），必須自帶
            "User-Agent": "pump-radar/1.0",
        },
    )
    urllib.request.urlopen(req, timeout=10).read()


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    pairs = [p.strip() for p in os.environ.get(
        "PAIRS",
        "BTC/USDT,ETH/USDT,ADA/USDT,SOL/USDT,XRP/USDT,"
        "DOGE/USDT,BNB/USDT,LINK/USDT,LTC/USDT,AVAX/USDT").split(",")]
    ex = getattr(ccxt, os.environ.get("EXCHANGE", "binance"))()

    for pair in pairs:
        try:
            df = add_indicators(fetch_15m(ex, pair))
        except Exception as e:  # 單一標的失敗不拖垮整趟
            print(f"[pump] {pair} fetch/indicator error: {e}", flush=True)
            continue
        last_bar = df.iloc[-1]
        bar_ts = last_bar["date"].isoformat()
        st = state.setdefault(pair, {"last_seen": "", "cooldown_until": ""})
        if bar_ts <= st["last_seen"]:
            continue  # 這根已處理過
        st["last_seen"] = bar_ts

        if not bool(last_bar["event"]) or bar_ts <= st["cooldown_until"]:
            continue
        ev = next(iter_events(df.iloc[[-1]].reset_index(drop=True), pair))
        ev["ts"] = bar_ts  # iter_events 只看單根，時間以實際 bar 為準
        st["cooldown_until"] = (
            last_bar["date"] + timedelta(minutes=15 * PARAMS["cooldown_bars"])
        ).isoformat()

        with JOURNAL.open("a") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        tpe = last_bar["date"].astimezone(TAIPEI).strftime("%m-%d %H:%M")
        squeeze = "壓縮後爆發" if ev["grade"] == "A" else "放量突破"
        try:
            notify_discord(
                f"🚀 **[{ev['grade']}] {pair}** 15m 波段啟動（{squeeze}）\n"
                f"收盤 {ev['close']:g} 上穿布林上軌 | vol_z={ev['vol_z']} "
                f"bbw_pct={ev['bbw_pct']} | {tpe} 台北\n"
                f"{stats_engine.outlook_line(ev['grade'], stats_engine.load_stats(STATS_FILE))}\n"
                f"-# 歷史分佈隨 forward 自動更新，非方向預測；追漲期望詳分佈，非買賣建議"
            )
        except Exception as e:
            print(f"[pump] discord notify failed: {e}", flush=True)

    STATE_FILE.write_text(json.dumps(state))
    stats_engine.maybe_refresh(JOURNAL, SCORED_CACHE, STATS_FILE)  # 每日一次，失敗不擋主流程
    now = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[pump {now}] cycle ok | pairs={len(pairs)}", flush=True)


if __name__ == "__main__":
    main()
