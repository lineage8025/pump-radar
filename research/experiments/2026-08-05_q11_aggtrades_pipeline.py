"""Q11 Phase A：aggTrades 逐日下載→聚合→丟棄，產出 1 分鐘粒度摘要 feather。

不落地原始逐筆資料（記憶體內解壓解析，處理完當日立刻丟棄），只 commit 聚合後的摘要
（MB 量級）。摘要欄位設計目的：①重建 intrabar 路徑真值（high/low 何者先到達、
中價穿越次數代理路徑複雜度），供 Phase B 重跑 Q8 頭條格位；②taker buy/sell 量與
價差相關統計，供 Phase C 校準滑價。

用法：
  python research/experiments/2026-08-05_q11_aggtrades_pipeline.py \
      --pairs BTC/USDT,ETH/USDT,SOL/USDT --start 2024-01 --end 2024-03 \
      --out-dir research/experiments/q11_aggtrades

資料源 data.binance.vision/data/spot/daily/aggTrades/<SYMBOL>/<SYMBOL>-aggTrades-<YYYY-MM-DD>.zip。
"""

import argparse
import calendar
import io
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

BASE = "https://data.binance.vision/data/spot/daily/aggTrades"
UA = "pump-radar-research/1.0"
# spot aggTrades 無 header 時的 8 欄；部分較新日期已加 header
COLS = [
    "agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id",
    "transact_time", "is_buyer_maker", "is_best_match",
]


def month_days(month: str) -> list[str]:
    y, m = (int(x) for x in month.split("-"))
    n = calendar.monthrange(y, m)[1]
    return [f"{y:04d}-{m:02d}-{d:02d}" for d in range(1, n + 1)]


def months(start: str, end: str) -> list[str]:
    y0, m0 = (int(x) for x in start.split("-"))
    y1, m1 = (int(x) for x in end.split("-"))
    out, y, m = [], y0, m0
    while (y, m) <= (y1, m1):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def fetch_day(symbol: str, day: str, retries: int = 3) -> pd.DataFrame | None:
    """抓單日 aggTrades zip，回傳解析後 DataFrame；404（未來日期/當時未上市）回 None。"""
    url = f"{BASE}/{symbol}/{symbol}-aggTrades-{day}.zip"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                blob = resp.read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"  [skip] {symbol} {day} 無資料（404）", file=sys.stderr)
                return None
            last_err = e
        except Exception as e:  # noqa: BLE001 — 網路暫時性錯誤重試
            last_err = e
        time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(f"{symbol} {day} 下載失敗（重試 {retries} 次）: {last_err}")

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = zf.namelist()[0]
        raw = zf.read(name)
    del blob

    first = raw.split(b"\n", 1)[0].split(b",")[0].strip()
    header = 0 if not first.lstrip(b"-").isdigit() else None
    df = pd.read_csv(io.BytesIO(raw), header=header,
                      names=None if header == 0 else COLS)
    del raw
    if header == 0:
        df.columns = COLS[: len(df.columns)]
    return df


def aggregate_day(df: pd.DataFrame) -> pd.DataFrame:
    """單日逐筆 → 1 分鐘摘要。輸入須已按 transact_time 遞增（Binance 原始檔本就有序）。"""
    df = df.copy()
    df["price"] = pd.to_numeric(df["price"])
    df["quantity"] = pd.to_numeric(df["quantity"])
    ts = pd.to_numeric(df["transact_time"])
    unit = "us" if ts.iloc[0] > 1e14 else "ms"
    df["minute"] = pd.to_datetime(ts, unit=unit, utc=True).dt.floor("min")
    df["is_buyer_maker"] = df["is_buyer_maker"].astype(str).str.lower().eq("true")
    # taker 買量＝賣方是 maker（is_buyer_maker=True）時，taker 是買方
    df["taker_buy_qty"] = np.where(df["is_buyer_maker"], df["quantity"], 0.0)
    df["taker_sell_qty"] = np.where(df["is_buyer_maker"], 0.0, df["quantity"])

    rows = []
    for minute, g in df.groupby("minute", sort=True):
        price = g["price"].to_numpy()
        qty = g["quantity"].to_numpy()
        hi = price.max()
        lo = price.min()
        hi_idx = int(np.argmax(price))
        lo_idx = int(np.argmin(price))
        mid = (hi + lo) / 2.0
        # 中價穿越次數：價格序列相對 mid 的符號變化次數，代理區間內往返
        sign = np.sign(price - mid)
        sign_nz = sign[sign != 0]
        crossings = int(np.sum(sign_nz[1:] != sign_nz[:-1])) if len(sign_nz) > 1 else 0
        rows.append({
            "minute": minute,
            "open": price[0],
            "high": hi,
            "low": lo,
            "close": price[-1],
            "volume": float(qty.sum()),
            "n_trades": len(g),
            "high_before_low": hi_idx < lo_idx,
            "n_mid_crossings": crossings,
            "taker_buy_volume": float(g["taker_buy_qty"].sum()),
            "taker_sell_volume": float(g["taker_sell_qty"].sum()),
        })
    return pd.DataFrame(rows)


def process_symbol_month(symbol: str, month: str, out_dir: Path,
                          today_str: str) -> dict:
    parts = []
    n_days_ok, n_days_missing = 0, 0
    for day in month_days(month):
        if day >= today_str:
            break  # 未來日期不存在，略過（月末未滿月時）
        df = fetch_day(symbol, day)
        if df is None:
            n_days_missing += 1
            continue
        agg = aggregate_day(df)
        del df
        parts.append(agg)
        n_days_ok += 1
        print(f"  [ok] {symbol} {day}: {len(agg)} 分鐘、原始 {agg['n_trades'].sum()} 筆聚合成交", file=sys.stderr)

    if not parts:
        return {"symbol": symbol, "month": month, "n_days_ok": 0, "n_days_missing": n_days_missing, "n_minutes": 0}

    monthly = pd.concat(parts, ignore_index=True).sort_values("minute").reset_index(drop=True)
    out_path = out_dir / f"{symbol}-aggtrades-1m-{month}.feather"
    monthly.to_feather(out_path)
    return {
        "symbol": symbol, "month": month, "n_days_ok": n_days_ok,
        "n_days_missing": n_days_missing, "n_minutes": len(monthly),
        "path": str(out_path),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--start", required=True, help="YYYY-MM")
    ap.add_argument("--end", required=True, help="YYYY-MM")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    today_str = date.today().isoformat()

    reports = []
    for pair in [p.strip() for p in args.pairs.split(",") if p.strip()]:
        symbol = pair.replace("/", "")
        for month in months(args.start, args.end):
            t0 = time.time()
            rep = process_symbol_month(symbol, month, out_dir, today_str)
            rep["seconds"] = round(time.time() - t0, 1)
            reports.append(rep)
            print(f"[done] {rep}", file=sys.stderr)

    cov = pd.DataFrame(reports)
    cov_path = out_dir / "coverage_report.tsv"
    cov.to_csv(cov_path, sep="\t", index=False)
    print(f"覆蓋率報表寫入 {cov_path}")
    print(cov.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
