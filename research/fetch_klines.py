"""從 data.binance.vision 抓 15m 月度 K 線，落成 score_signals.load_candles 吃得下的 feather。

為什麼不用 ccxt：GitHub 的美國 runner 打 api.binance.com 會吃 HTTP 451（crypto-pulse 實踩），
而 data.binance.vision 是靜態 CDN、不受地域封鎖，且月度 zip 一次抓一整月遠快於分頁 REST。

用法：
  python research/fetch_klines.py --pairs BTC/USDT,ETH/USDT --start 2025-01 --end 2025-06 --out-dir /tmp/kl

輸出檔名與欄位刻意對齊 scripts/score_signals.py 的 load_candles()：
  <PAIR>-15m.feather（PAIR 的 / 換成 _），欄位 date(UTC tz-aware)/open/high/low/close/volume。
因此抓完的目錄可直接餵給 replay.py / score_signals.py 的 --data-dir。

本檔是研究基礎設施，對 autoresearch agent **唯讀**（不在 program.md 的可寫白名單內）：
資料管線出錯要人來修，不能讓迴圈自己改抓數據的方式——否則「數據不對」與「結論不對」
會糾纏成無法歸因的一團。
"""

import argparse
import io
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

BASE = "https://data.binance.vision/data/spot/monthly/klines"
# Binance K 線 CSV 的 12 欄（無論有無 header 都是這個順序）
COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "count",
    "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]
UA = "pump-radar-research/1.0"


def months(start: str, end: str) -> list[str]:
    """展開 YYYY-MM 區間（含頭含尾）。"""
    y0, m0 = (int(x) for x in start.split("-"))
    y1, m1 = (int(x) for x in end.split("-"))
    out, y, m = [], y0, m0
    while (y, m) <= (y1, m1):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def fetch_month(symbol: str, month: str, interval: str = "15m") -> pd.DataFrame | None:
    """抓單月 zip；404（該月尚未產出或標的當時未上市）回 None，其餘網路錯誤往上拋。"""
    url = f"{BASE}/{symbol}/{interval}/{symbol}-{interval}-{month}.zip"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            blob = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"  [skip] {symbol} {month} 無資料（404）", file=sys.stderr)
            return None
        raise

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = zf.namelist()[0]
        raw = zf.read(name).decode("utf-8")

    # Binance 2025 起在部分資料集加了 header 行，舊檔沒有——用第一格是不是數字來判，
    # 不要靠日期猜（同一標的不同月份可能不一致）。
    first = raw.split("\n", 1)[0].split(",")[0].strip()
    header = 0 if not first.lstrip("-").isdigit() else None
    df = pd.read_csv(io.StringIO(raw), header=header, names=None if header == 0 else COLS)
    if header == 0:
        df.columns = COLS[: len(df.columns)]
    return df


def to_candles(df: pd.DataFrame) -> pd.DataFrame:
    """轉成 load_candles() 的欄位規格。時間單位靠數量級判 ms/µs——Binance 2025 起
    部分資料改用微秒，寫死 unit='ms' 會把 2025 年的 K 線解析成西元 57000 年。"""
    ts = pd.to_numeric(df["open_time"])
    unit = "us" if ts.iloc[0] > 1e14 else "ms"
    out = pd.DataFrame({
        "date": pd.to_datetime(ts, unit=unit, utc=True),
        "open": pd.to_numeric(df["open"]),
        "high": pd.to_numeric(df["high"]),
        "low": pd.to_numeric(df["low"]),
        "close": pd.to_numeric(df["close"]),
        "volume": pd.to_numeric(df["volume"]),
    })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", required=True, help="逗號分隔，如 BTC/USDT,ETH/USDT")
    ap.add_argument("--start", required=True, help="起始月 YYYY-MM（含）")
    ap.add_argument("--end", default=None, help="結束月 YYYY-MM（含），預設為上個月")
    ap.add_argument("--interval", default="15m")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    if args.end is None:
        today = date.today()
        args.end = f"{today.year:04d}-{today.month - 1:02d}" if today.month > 1 \
            else f"{today.year - 1:04d}-12"

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mlist = months(args.start, args.end)
    rc = 0

    for pair in [p.strip() for p in args.pairs.split(",") if p.strip()]:
        symbol = pair.replace("/", "")
        parts = []
        for m in mlist:
            got = fetch_month(symbol, m, args.interval)
            if got is not None and len(got):
                parts.append(to_candles(got))
        if not parts:
            print(f"[warn] {pair} 一個月都沒抓到，跳過", file=sys.stderr)
            rc = 1
            continue

        candles = pd.concat(parts, ignore_index=True)
        # 月度檔理論上不重疊，但 Binance 偶有邊界重複；去重後嚴格升冪，供 detector 的 rolling 用
        candles = (candles.drop_duplicates(subset="date")
                          .sort_values("date")
                          .reset_index(drop=True))
        path = out_dir / f"{pair.replace('/', '_')}-{args.interval}.feather"
        candles.to_feather(path)
        span = f"{candles['date'].iloc[0]:%Y-%m-%d} ~ {candles['date'].iloc[-1]:%Y-%m-%d}"
        print(f"[ok] {pair}: {len(candles)} 根 {args.interval}（{span}）→ {path}")

    return rc


if __name__ == "__main__":
    sys.exit(main())
