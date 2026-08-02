"""Q1'''（run 6，2026-08-02）：Yang-Zhang / Garman-Klass 交叉驗證 Q1 主效應。

授權來源：`research/program.md` §4.1（2026-08-02 人類裁決，YZ/GK 交叉驗證放行）。
四條約束照做：
 1. **只准這兩個具名估計量，各跑一次**——不掃估計量家族。
 2. **主結果永遠是凍結網格那版**（Parkinson-type range，直接沿用 run1/run5 的 ORIG 數字，
    本檔不重跑）；GK/YZ 只進限制段作交叉驗證。
 3. **兩者不一致 → 結論記 inconclusive**，不得挑對敘事有利的那個。
 4. **只換振幅公式**——分桶／T／窗口／標的／去叢集口徑全部沿用 §4 凍結網格，一律不動。

窗口：ORIG 主窗口 2025-01-01~2026-06-30（與 run1/run5 同一段），暖機月 2024-12。
標的：docker-compose 10 PAIRS（同 §4）。

公式（`docs/RESEARCH_BBW_VOLATILITY.md` §3.2/3.3 教材複誦版）：

Garman-Klass 單根變異數：
    gk_t = 0.5 * ln(H_t/L_t)^2 - (2*ln2 - 1) * ln(C_t/O_t)^2
窗口（n 根，t=1..n 為訊號根之後的 K 棒）加總（零自相關假設下變異數可加）：
    sigma_GK_window = sqrt(max(sum(gk_t), 0))

Yang-Zhang（window 版，n 根樣本估「單根」變異數再乘 n 還原成窗口尺度）：
    o_1 = ln(O_1 / close_0)                     close_0 = 訊號根收盤（既有 amplitude() 的 close 錨點）
    o_t = ln(O_t / C_{t-1})  for t=2..n
    c_t = ln(C_t / O_t)      for t=1..n
    rs_t = ln(H_t/C_t)*ln(H_t/O_t) + ln(L_t/C_t)*ln(L_t/O_t)   for t=1..n
    V_o = sample_var(o_1..o_n, ddof=1); V_c = sample_var(c_1..c_n, ddof=1); V_rs = mean(rs_1..rs_n)
    k = 0.34 / (1.34 + (n+1)/(n-1))
    sigma2_perbar_YZ = V_o + k*V_c + (1-k)*V_rs
    sigma_YZ_window = sqrt(n * max(sigma2_perbar_YZ, 0))
n=4 時 (n+1)/(n-1) 有效；n>=4 恆成立（本網格最短 T=1h=4 根），不需另外 guard n<=1。

兩者輸出皆為「log 報酬尺度的窗口波動」，與主結果的簡單百分比 range 尺度不同，
不能跨估計量比較絕對數值——只能比較「最低桶 vs 最高桶」這個相對差距的方向與顯著性，
這正是 §4.1 交叉驗證要問的問題（估計量選擇是否動搖 Q1 的方向性結論）。

用法：
  python 2026-08-02_q1triple_yz_gk_crossval.py --fetch-only   # 只暖快取
  python 2026-08-02_q1triple_yz_gk_crossval.py                # 全分析
"""

import argparse
import sys
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from detector import add_indicators, PARAMS  # noqa: E402
from fetch_klines import fetch_month, to_candles, months  # noqa: E402

PAIRS = [
    "BTC/USDT", "ETH/USDT", "ADA/USDT", "SOL/USDT", "XRP/USDT",
    "DOGE/USDT", "BNB/USDT", "LINK/USDT", "LTC/USDT", "AVAX/USDT",
]
FETCH_START, FETCH_END = "2024-12", "2026-06"  # 2024-12 暖機（滿足 30 天 bbw_pct 窗）
WINDOW_START, WINDOW_END = "2025-01-01", "2026-06-30"  # ORIG，與 run1/run5 同段
OUT_DIR = Path("/tmp/kl_q1triple")

# 凍結網格（program.md §4），不得增刪
BUCKETS = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.25), (0.25, 0.50), (0.50, 0.75), (0.75, 1.0)]
HORIZONS = {"1h": 4, "4h": 16, "12h": 48, "24h": 96}
MAX_T_BARS = max(HORIZONS.values())

N_BOOT = 2000
SEED = 20260802606  # 與 run1~5 的 SEED 不同數字，避免子種子巧合碰撞；仍是確定性常數
STEM = Path(__file__).with_suffix("").as_posix()
LN2 = np.log(2)


# ---------------------------------------------------------------- 資料

def load_pair(pair: str) -> pd.DataFrame:
    cache = OUT_DIR / f"{pair.replace('/', '_')}-15m.feather"
    if cache.exists():
        return pd.read_feather(cache)
    symbol = pair.replace("/", "")
    parts = []
    for m in months(FETCH_START, FETCH_END):
        raw = fetch_month(symbol, m, "15m")
        if raw is not None and len(raw):
            parts.append(to_candles(raw))
    candles = (pd.concat(parts, ignore_index=True)
               .drop_duplicates(subset="date")
               .sort_values("date")
               .reset_index(drop=True))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    candles.to_feather(cache)
    print(f"[fetch] {pair}: {len(candles)} 根 15m "
          f"({candles['date'].iloc[0]} ~ {candles['date'].iloc[-1]})", file=sys.stderr, flush=True)
    return candles


def sub_seed(*parts) -> int:
    return SEED + zlib.crc32("|".join(str(x) for x in parts).encode()) % 100000


def bucket_of(p):
    if pd.isna(p):
        return None
    for i, (lo, hi) in enumerate(BUCKETS):
        is_last = i == len(BUCKETS) - 1
        if (lo <= p <= hi) if is_last else (lo <= p < hi):
            return (lo, hi)
    return None


def bucket_label(b) -> str:
    lo, hi = b
    return f"[{lo:.2f},{hi:.2f}]" if hi == 1.0 else f"[{lo:.2f},{hi:.2f})"


# ---------------------------------------------------------------- 振幅／波動估計量

def amp_range(window: pd.DataFrame, close0: float) -> float:
    """主結果的估計量（本檔不用來產生主結果，只留著核對用）。"""
    return (window["high"].max() - window["low"].min()) / close0


def amp_gk(window: pd.DataFrame) -> float:
    h, l, o, c = window["high"].to_numpy(), window["low"].to_numpy(), \
        window["open"].to_numpy(), window["close"].to_numpy()
    gk = 0.5 * np.log(h / l) ** 2 - (2 * LN2 - 1) * np.log(c / o) ** 2
    total = float(np.sum(gk))
    return float(np.sqrt(max(total, 0.0)))


def amp_yz(window: pd.DataFrame, close0: float) -> float:
    n = len(window)
    h, l, o, c = window["high"].to_numpy(), window["low"].to_numpy(), \
        window["open"].to_numpy(), window["close"].to_numpy()
    prev_close = np.concatenate([[close0], c[:-1]])
    o_ret = np.log(o / prev_close)
    c_ret = np.log(c / o)
    rs = np.log(h / c) * np.log(h / o) + np.log(l / c) * np.log(l / o)
    V_o = float(np.var(o_ret, ddof=1))
    V_c = float(np.var(c_ret, ddof=1))
    V_rs = float(np.mean(rs))
    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    sigma2_perbar = V_o + k * V_c + (1 - k) * V_rs
    return float(np.sqrt(n * max(sigma2_perbar, 0.0)))


# ---------------------------------------------------------------- 取樣（去叢集口徑與 run1/run5 逐行同義）

def q1_samples(df: pd.DataFrame, pair: str, start_ts, end_ts):
    rows = []
    mask = (df["date"] >= start_ts) & (df["date"] < end_ts) & df["bbw_pct"].notna()
    idxs = df.index[mask].tolist()
    next_allowed = -1
    n_considered = 0
    for i in idxs:
        n_considered += 1
        if i < next_allowed:
            continue
        if i + MAX_T_BARS >= len(df):
            continue
        bkt = bucket_of(float(df.at[i, "bbw_pct"]))
        if bkt is None:
            continue
        close0 = float(df.at[i, "close"])
        row = {"pair": pair, "ts": df.at[i, "date"], "bucket": bkt}
        for name, bars in HORIZONS.items():
            win = df.iloc[i + 1: i + 1 + bars]
            row[f"gk_{name}"] = amp_gk(win)
            row[f"yz_{name}"] = amp_yz(win, close0)
        rows.append(row)
        next_allowed = i + MAX_T_BARS
    print(f"  [decluster] {pair}: 候選列 {n_considered} -> 採樣 {len(rows)}",
          file=sys.stderr, flush=True)
    return rows


# ---------------------------------------------------------------- bootstrap（方法同 Q1'）

def _weeks(sub: pd.DataFrame, col):
    return sub.groupby("week")[col].apply(lambda s: s.to_numpy()).to_numpy(dtype=object)


def block_boot_diff(a_df, b_df, q, rng, col, n_boot=N_BOOT):
    a_w, b_w = _weeks(a_df, col), _weeks(b_df, col)
    diffs = np.empty(n_boot)
    for k in range(n_boot):
        a_pick = rng.integers(0, len(a_w), size=len(a_w))
        b_pick = rng.integers(0, len(b_w), size=len(b_w))
        diffs[k] = (np.quantile(np.concatenate([b_w[i] for i in b_pick]), q)
                    - np.quantile(np.concatenate([a_w[i] for i in a_pick]), q))
    return diffs


def add_week(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["week"] = pd.to_datetime(df["ts"]).dt.tz_convert("UTC").dt.strftime("%G-W%V")
    return df


# ---------------------------------------------------------------- 報表

def grid_table(sdf: pd.DataFrame, estimator: str) -> pd.DataFrame:
    rows = []
    for b in BUCKETS:
        sub = sdf[sdf["bucket"] == b]
        line = {"estimator": estimator, "bucket": bucket_label(b), "n": len(sub)}
        for name in HORIZONS:
            s = sub[f"{estimator}_{name}"].dropna()
            if len(s) == 0:
                line[f"{name}_p50"] = line[f"{name}_p80"] = line[f"{name}_p95"] = None
                continue
            # log-return 尺度數值很小，乘 100 轉成「百分比等價」尺度方便閱讀比較
            line[f"{name}_p50"] = round(float(s.quantile(0.50)) * 100, 4)
            line[f"{name}_p80"] = round(float(s.quantile(0.80)) * 100, 4)
            line[f"{name}_p95"] = round(float(s.quantile(0.95)) * 100, 4)
        rows.append(line)
    return pd.DataFrame(rows)


def lowhigh_ci(sdf: pd.DataFrame, estimator: str) -> pd.DataFrame:
    lo_df = add_week(sdf[sdf["bucket"] == BUCKETS[0]])
    hi_df = add_week(sdf[sdf["bucket"] == BUCKETS[-1]])
    out = []
    for name in HORIZONS:
        col = f"{estimator}_{name}"
        row = {"estimator": estimator, "T": name, "n_lo": len(lo_df), "n_hi": len(hi_df)}
        if len(lo_df) < 30 or len(hi_df) < 30:
            row.update({"p80_lo": None, "p80_hi": None, "diff_p80": None,
                        "ci_lo": None, "ci_hi": None})
            out.append(row)
            continue
        p80_lo = float(lo_df[col].quantile(0.80)) * 100
        p80_hi = float(hi_df[col].quantile(0.80)) * 100
        rng = np.random.default_rng(sub_seed(estimator, name))
        d = block_boot_diff(lo_df, hi_df, 0.80, rng, col=col) * 100
        ci = np.quantile(d, [0.025, 0.975])
        row.update({"p80_lo": round(p80_lo, 4), "p80_hi": round(p80_hi, 4),
                    "diff_p80": round(p80_hi - p80_lo, 4),
                    "ci_lo": round(float(ci[0]), 4), "ci_hi": round(float(ci[1]), 4)})
        out.append(row)
    return pd.DataFrame(out)


# ---------------------------------------------------------------- 主流程

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch-only", action="store_true")
    args = ap.parse_args()

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)

    prepared = {}
    coverage = []
    for pair in PAIRS:
        candles = load_pair(pair)
        df = add_indicators(candles, PARAMS)
        prepared[pair] = df
        coverage.append({
            "pair": pair, "bars": len(df),
            "first": str(df["date"].iloc[0]), "last": str(df["date"].iloc[-1]),
            "n_bbw_null": int(df["bbw_pct"].isna().sum()),
        })
    cov = pd.DataFrame(coverage)
    print("\n=== 資料覆蓋（抓取 2024-12~2026-06，含暖機月）===")
    print(cov.to_string(index=False))
    cov.to_csv(f"{STEM}_coverage.tsv", sep="\t", index=False)
    if args.fetch_only:
        return

    start_ts = pd.Timestamp(WINDOW_START, tz="UTC")
    end_ts = pd.Timestamp(WINDOW_END, tz="UTC") + pd.Timedelta(days=1)

    srows = []
    for pair in PAIRS:
        srows += q1_samples(prepared[pair], pair, start_ts, end_ts)
    sdf = pd.DataFrame(srows)
    print(f"\n[Q1'''] ORIG 窗口（{WINDOW_START}~{WINDOW_END}）去叢集後總採樣 n={len(sdf)}")
    sdf_out = sdf.copy()
    sdf_out["bucket"] = sdf_out["bucket"].apply(bucket_label)
    sdf_out.to_csv(f"{STEM}_samples.tsv", sep="\t", index=False)

    grids, cis = [], []
    for est in ("gk", "yz"):
        t = grid_table(sdf, est)
        print(f"\n--- [{est.upper()}] 六分桶 × T 波動估計量分位數（%等價尺度，每格附 n）---")
        print(t.to_string(index=False))
        grids.append(t)

        c = lowhigh_ci(sdf, est)
        print(f"\n--- [{est.upper()}] 最低桶 vs 最高桶差距（逐週區塊 bootstrap {N_BOOT} 次）---")
        print(c.to_string(index=False))
        cis.append(c)

    pd.concat(grids).to_csv(f"{STEM}_grid.tsv", sep="\t", index=False)
    pd.concat(cis).to_csv(f"{STEM}_lowhigh_ci.tsv", sep="\t", index=False)

    print("\n" + "=" * 100)
    print("### GK vs YZ 對照（24h 最低桶 vs 最高桶差距，含 0？）")
    both = pd.concat(cis)
    both_24h = both[both["T"] == "24h"]
    print(both_24h.to_string(index=False))


if __name__ == "__main__":
    main()
