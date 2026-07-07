"""訊號誠實計分器（deterministic）：journal 事件 × 15m K 線 → 多時距報酬/MFE/MAE/含費淨損益。

口徑（預登記，見 docs/DETECTOR_PREREG.md）：
- 進場價 = 訊號根「下一根 15m 開盤價」（偵測發生在收盤後，這是最早可成交價；不用訊號根收盤價自欺）。
- 時距：1h/4h/12h/24h（4/16/48/96 根）固定持有報酬；MFE/MAE 取 24h 窗內 high/low 極值。
- 頭條指標：24h 固定持有、扣 0.2% 來回費後的平均淨報酬（僅此一個，其餘皆為診斷用）。

用法：
  python score_signals.py --journal logs/pump_journal.jsonl [--data-dir /path/to/feather] [--pairs BTC/USDT,...]
未給 --data-dir 時透過 ccxt 抓 K 線（需網路）。
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

HORIZONS = {"1h": 4, "4h": 16, "12h": 48, "24h": 96}
FEE_ROUNDTRIP = 0.002  # 現貨 taker 0.1% × 2，寧可高估


def load_candles(pair: str, data_dir: str | None) -> pd.DataFrame:
    if data_dir:
        path = Path(data_dir) / f"{pair.replace('/', '_')}-15m.feather"
        df = pd.read_feather(path)
    else:
        import ccxt

        ex = ccxt.binance()
        rows, since = [], ex.milliseconds() - 35 * 24 * 3600 * 1000  # 35 天，滿足 BBW 30 天回看
        while True:
            batch = ex.fetch_ohlcv(pair, "15m", since=since, limit=1000)
            if not batch:
                break
            rows += batch
            if len(batch) < 1000:
                break
            since = batch[-1][0] + 1
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
        df["date"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.reset_index(drop=True)


def score_event(ev: dict, candles: pd.DataFrame) -> dict | None:
    ts = pd.Timestamp(ev["ts"])
    idx = candles.index[candles["date"] == ts]
    if len(idx) == 0:
        return None
    i = int(idx[0])
    if i + 1 >= len(candles):
        return None  # 訊號太新，還沒有下一根可進場
    entry = float(candles.iloc[i + 1]["open"])
    out = {"ts": ev["ts"], "pair": ev["pair"], "grade": ev.get("grade"), "entry": entry}
    window = candles.iloc[i + 1 : i + 1 + HORIZONS["24h"]]
    out["mfe_24h"] = float(window["high"].max()) / entry - 1
    out["mae_24h"] = float(window["low"].min()) / entry - 1
    for name, bars in HORIZONS.items():
        j = i + 1 + bars - 1
        out[f"ret_{name}"] = (float(candles.iloc[j]["close"]) / entry - 1) if j < len(candles) else None
    if out["ret_24h"] is not None:
        out["net_24h"] = out["ret_24h"] - FEE_ROUNDTRIP
    else:
        out["net_24h"] = None
    return out


def summarize(scored: list[dict]) -> None:
    df = pd.DataFrame(scored)
    print(f"\n事件數 {len(df)}（A 級 {(df['grade'] == 'A').sum()} / B 級 {(df['grade'] == 'B').sum()}）")
    for col in ["ret_1h", "ret_4h", "ret_12h", "ret_24h", "net_24h", "mfe_24h", "mae_24h"]:
        s = df[col].dropna()
        if s.empty:
            continue
        print(f"{col:9s} mean {s.mean()*100:+.2f}%  median {s.median()*100:+.2f}%  "
              f"win {(s > 0).mean()*100:.0f}%  n={len(s)}")
    for g in ["A", "B"]:
        s = df.loc[df["grade"] == g, "net_24h"].dropna()
        if len(s):
            print(f"net_24h[{g}] mean {s.mean()*100:+.2f}%  win {(s > 0).mean()*100:.0f}%  n={len(s)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--journal", required=True)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--tsv", default=None, help="逐事件明細輸出路徑（TSV）")
    args = ap.parse_args()

    events = [json.loads(l) for l in Path(args.journal).read_text().splitlines()
              if l.strip() and json.loads(l).get("event") == "pump_signal"]
    if not events:
        sys.exit("journal 內無 pump_signal 事件")

    scored = []
    for pair in sorted({e["pair"] for e in events}):
        candles = load_candles(pair, args.data_dir)
        for ev in (e for e in events if e["pair"] == pair):
            row = score_event(ev, candles)
            if row:
                scored.append(row)

    if args.tsv:
        pd.DataFrame(scored).to_csv(args.tsv, sep="\t", index=False)
        print(f"明細已寫 {args.tsv}")
    summarize(scored)


if __name__ == "__main__":
    main()
