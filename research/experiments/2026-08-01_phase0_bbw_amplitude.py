"""Phase 0 探針（Q1，2026-08-01 run 1）：bbw_pct 六分桶 x T(1/4/12/24h) 振幅分位數表。

網格凍結於 research/program.md §4，本檔不得增刪分桶或 T。標的與窗口登記於
research/backlog.md Q1（10 PAIRS，分析窗 2025-01-01~2026-06-30，暖機月 2024-12）。

已知資料管線 bug（research/fetch_klines.py 對 agent 唯讀，不得修改，僅能繞過使用）：
`to_candles()` 只用整批 concat 後的第一筆 open_time 判斷 ms/us 單位；Binance 從
2025-01 起把 monthly klines 的時間戳從 ms 換成 us，但暖機月 2024-12 仍是 ms。
一次抓「2024-12~2026-06」整段會把 2025 年之後全部誤判成 ms，日期解析成西元 58000 年
（本次運行實測 BTCUSDT 2024-12 open_time=13 位數(ms)，2025-01 起 open_time=16 位數(us)）。
繞法：本檔只呼叫 fetch_klines.fetch_month()（未改動、逐月抓 raw csv），
自己在本檔內逐月套用單位判斷再 concat——不修改 fetch_klines.py 本身，
且抓取來源／方式與原檔完全一致（同一個 data.binance.vision 月度 zip）。
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from detector import add_indicators, PARAMS  # noqa: E402
from fetch_klines import fetch_month, months  # noqa: E402

PAIRS = [
    "BTC/USDT", "ETH/USDT", "ADA/USDT", "SOL/USDT", "XRP/USDT",
    "DOGE/USDT", "BNB/USDT", "LINK/USDT", "LTC/USDT", "AVAX/USDT",
]
FETCH_START, FETCH_END = "2024-12", "2026-06"
ANALYSIS_START, ANALYSIS_END = "2025-01-01", "2026-06-30"
OUT_DIR = Path("/tmp/kl_phase0")

BUCKETS = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.25), (0.25, 0.50), (0.50, 0.75), (0.75, 1.0)]
HORIZONS = {"1h": 4, "4h": 16, "12h": 48, "24h": 96}
MAX_T_BARS = max(HORIZONS.values())  # 96 = 24h,去叢集間隔門檻


def month_to_candles(raw: pd.DataFrame) -> pd.DataFrame:
    """單月版 to_candles：單位判斷只吃該月自己的 open_time，不受其他月污染。"""
    ts = pd.to_numeric(raw["open_time"])
    unit = "us" if ts.iloc[0] > 1e14 else "ms"
    return pd.DataFrame({
        "date": pd.to_datetime(ts, unit=unit, utc=True),
        "open": pd.to_numeric(raw["open"]),
        "high": pd.to_numeric(raw["high"]),
        "low": pd.to_numeric(raw["low"]),
        "close": pd.to_numeric(raw["close"]),
        "volume": pd.to_numeric(raw["volume"]),
    })


def load_pair(pair: str) -> pd.DataFrame:
    symbol = pair.replace("/", "")
    cache = OUT_DIR / f"{pair.replace('/', '_')}-15m.feather"
    if cache.exists():
        return pd.read_feather(cache)
    parts = []
    for m in months(FETCH_START, FETCH_END):
        raw = fetch_month(symbol, m, "15m")
        if raw is not None and len(raw):
            parts.append(month_to_candles(raw))
    candles = (pd.concat(parts, ignore_index=True)
               .drop_duplicates(subset="date")
               .sort_values("date")
               .reset_index(drop=True))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    candles.to_feather(cache)
    print(f"[fetch] {pair}: {len(candles)} 根 15m "
          f"({candles['date'].iloc[0]} ~ {candles['date'].iloc[-1]})", file=sys.stderr)
    return candles


def bucket_of(p: float):
    """[lo,hi) 左閉右開，僅最後一桶 [0.75,1.0] 兩端皆閉（凍結網格 program.md §4 原文）。"""
    for i, (lo, hi) in enumerate(BUCKETS):
        is_last = i == len(BUCKETS) - 1
        if (lo <= p <= hi) if is_last else (lo <= p < hi):
            return (lo, hi)
    return None


def amplitude(window: pd.DataFrame, close: float) -> float:
    return (window["high"].max() - window["low"].min()) / close


def main() -> None:
    start_ts = pd.Timestamp(ANALYSIS_START, tz="UTC")
    end_ts = pd.Timestamp(ANALYSIS_END, tz="UTC") + pd.Timedelta(days=1)

    samples = []  # dicts: pair, ts, bucket, amp_1h, amp_4h, amp_12h, amp_24h
    for pair in PAIRS:
        candles = load_pair(pair)
        df = add_indicators(candles, PARAMS)
        # 分析窗切片；bbw_pct null 一律丟棄(不當0)
        mask = (df["date"] >= start_ts) & (df["date"] < end_ts) & df["bbw_pct"].notna()
        idxs = df.index[mask].tolist()

        next_allowed = -1
        n_considered = 0
        n_sampled = 0
        for i in idxs:
            n_considered += 1
            if i < next_allowed:
                continue
            # 需要 i 之後還有完整 24h(96 根) 窗才能採樣（否則右尾截斷會系統性偏誤振幅）
            if i + MAX_T_BARS >= len(df):
                continue
            bkt = bucket_of(float(df.at[i, "bbw_pct"]))
            if bkt is None:
                continue
            close = float(df.at[i, "close"])
            row = {"pair": pair, "ts": df.at[i, "date"], "bucket": bkt}
            for name, bars in HORIZONS.items():
                window = df.iloc[i + 1: i + 1 + bars]
                row[f"amp_{name}"] = amplitude(window, close)
            samples.append(row)
            n_sampled += 1
            next_allowed = i + MAX_T_BARS
        print(f"[decluster] {pair}: 候選列 {n_considered} -> 去叢集後採樣 {n_sampled}", file=sys.stderr)

    sdf = pd.DataFrame(samples)
    sdf.to_csv(Path(__file__).with_suffix("").as_posix() + "_samples.tsv", sep="\t", index=False)
    print(f"\n=== 總採樣數 n={len(sdf)}（去叢集後，跨 10 標的）===")

    print("\n=== 結果表：bbw_pct 分桶 x T 振幅分位數（p50/p80/p95, n）===")
    rows_out = []
    for lo, hi in BUCKETS:
        sub = sdf[sdf["bucket"] == (lo, hi)]
        n = len(sub)
        line = {"bucket": f"[{lo:.2f},{hi:.2f}]" if hi == 1.0 else f"[{lo:.2f},{hi:.2f})", "n": n}
        for name in HORIZONS:
            s = sub[f"amp_{name}"].dropna()
            if len(s) == 0:
                line[f"{name}_p50"] = line[f"{name}_p80"] = line[f"{name}_p95"] = None
                continue
            line[f"{name}_p50"] = round(float(s.quantile(0.50)) * 100, 3)
            line[f"{name}_p80"] = round(float(s.quantile(0.80)) * 100, 3)
            line[f"{name}_p95"] = round(float(s.quantile(0.95)) * 100, 3)
        rows_out.append(line)

    out_df = pd.DataFrame(rows_out)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    print(out_df.to_string(index=False))
    out_df.to_csv(Path(__file__).with_suffix("").as_posix() + "_result_table.tsv", sep="\t", index=False)

    # 24h 是主戰場：對「最低桶 <5%」vs「最高桶 75~100%」的 p80 差距做 percentile bootstrap CI
    print("\n=== 24h p80 差距 bootstrap 95% CI（最低桶 vs 最高桶，2000 次重抽）===")
    rng = np.random.default_rng(20260801)
    lo_s = sdf.loc[sdf["bucket"] == BUCKETS[0], "amp_24h"].dropna().to_numpy()
    hi_s = sdf.loc[sdf["bucket"] == BUCKETS[-1], "amp_24h"].dropna().to_numpy()
    print(f"最低桶 n={len(lo_s)}, 最高桶 n={len(hi_s)}")
    if len(lo_s) >= 5 and len(hi_s) >= 5:
        diffs = []
        for _ in range(2000):
            a = rng.choice(lo_s, size=len(lo_s), replace=True)
            b = rng.choice(hi_s, size=len(hi_s), replace=True)
            diffs.append(np.quantile(b, 0.80) - np.quantile(a, 0.80))
        diffs = np.array(diffs)
        ci_lo, ci_hi = np.quantile(diffs, [0.025, 0.975])
        point = np.quantile(hi_s, 0.80) - np.quantile(lo_s, 0.80)
        print(f"點估計(最高桶p80 - 最低桶p80) = {point*100:+.3f}pp, 95% CI [{ci_lo*100:+.3f}, {ci_hi*100:+.3f}]pp")
    else:
        print("樣本不足(n<5)，不計算 CI")


if __name__ == "__main__":
    main()
