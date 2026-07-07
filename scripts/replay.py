"""歷史回放：對 feather 或 ccxt 抓的 15m K 線跑 detector，事件輸出 stdout（jsonl）。

用法：
  python replay.py --data-dir /path/to/feather --pairs BTC/USDT,ETH/USDT [--since 2026-05-01]
  python replay.py --pairs BTC/USDT --days 60          # 無本機資料時走 ccxt

回放與 live 用同一份 detector.py，結果可直接餵 score_signals.py。
"""

import argparse
import json
import sys

from detector import add_indicators, iter_events
from score_signals import load_candles


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--since", default=None, help="只輸出此日期（含）之後的事件，ISO 格式")
    args = ap.parse_args()

    for pair in args.pairs.split(","):
        df = add_indicators(load_candles(pair.strip(), args.data_dir))
        for ev in iter_events(df, pair.strip()):
            if args.since and ev["ts"] < args.since:
                continue
            print(json.dumps(ev, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
