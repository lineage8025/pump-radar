"""Q2''（run 5，2026-08-02）：延長窗口重跑 Q1（Phase 0 振幅網格）與 Q2'（event 分桶配對），
外加時期分層（2023-01~2024-12 vs 2025-01~2026-06）。

授權來源：`research/backlog.md` Q2''（2026-08-02 人類裁決放行並登記窗口）
＋ `research/program.md` §4.2「窗口延長協定」。四條約束照做：
 1. **全網格重跑**——六分桶 × T(1/4/12/24h) 全部重算，不是只補 n 不足的兩桶。
 2. **原窗口（2025-01-01~2026-06-30）仍是主結果**，延長版並列且標明是事後延長。
 3. **時期分層**：P1=2023-01-01~2024-12-31 與 P2=2025-01-01~2026-06-30（P2 即原窗口）
    兩段獨立重算並比較——直接對上 run1 最強反駁第 1／3 點（宏觀 regime 混淆）。
 4. 窗口已先寫進 backlog.md 才跑；分桶／T／度量／去叢集／標的一律不動
    （凍結網格 `research/program.md` §4）。

資料管線：`research/fetch_klines.py`（唯讀）的 `fetch_month` + `to_candles`。
PR #4 合併後 `to_candles()` 由 main() 逐月呼叫、單位判斷只吃該月自己的 open_time，
run1~3 在探針內自行複製 `month_to_candles` 的繞法**不再需要**（backlog Q2'' 註記），
本檔直接 import 原檔的 `to_candles` 逐月套用。

抓取範圍 2022-12 ~ 2026-06：2022-12 是暖機月（`bbw_pct_window=2880`＝30 天、
`min_periods=960`＝10 天），分析窗起點 2023-01-01 之前必須有滿月資料，
且探針一律丟棄 `bbw_pct` 為 null 的列（不當 0 處理）。

用法：
  python 2026-08-02_q2doubleprime_extended_window.py --fetch-only   # 只暖快取
  python 2026-08-02_q2doubleprime_extended_window.py                # 全分析
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
FETCH_START, FETCH_END = "2022-12", "2026-06"
OUT_DIR = Path("/tmp/kl_q2pp")

# 三個分析窗（起含、迄含）。P2 與 ORIG 是同一段：原窗口本身就是時期分層的後段。
WINDOWS = [
    ("ORIG", "2025-01-01", "2026-06-30", "原窗口（主結果，run1/run3 已跑，本次重現）"),
    ("EXT", "2023-01-01", "2026-06-30", "延長窗口（事後延長，並列呈現）"),
    ("P1", "2023-01-01", "2024-12-31", "時期分層前段（新增期）"),
]

# 凍結網格（program.md §4），不得增刪
BUCKETS = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.25), (0.25, 0.50), (0.50, 0.75), (0.75, 1.0)]
HORIZONS = {"1h": 4, "4h": 16, "12h": 48, "24h": 96}
MAX_T_BARS = max(HORIZONS.values())  # 96 根＝24h，同時是去叢集的最小間隔
T_24H_BARS = 96

N_BOOT = 2000
SEED = 20260802
STEM = Path(__file__).with_suffix("").as_posix()


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
            parts.append(to_candles(raw))  # 逐月套用＝PR#4 後的正確單位判斷
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
    """確定性子種子：Python 的 str hash 每個 process 隨機化，不能拿來當種子。"""
    return SEED + zlib.crc32("|".join(str(x) for x in parts).encode()) % 100000


def bucket_of(p):
    """[lo,hi) 左閉右開，僅最後一桶 [0.75,1.0] 兩端皆閉（凍結網格 §4 原文）。"""
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


def amplitude(window: pd.DataFrame, close: float) -> float:
    return (window["high"].max() - window["low"].min()) / close


# ---------------------------------------------------------------- 取樣（與 run1/run3 逐行同義）

def q1_samples(df: pd.DataFrame, pair: str, start_ts, end_ts, verbose=True):
    """Q1 母體：分析窗內、bbw_pct 非 null、去叢集（取樣點間隔 >= 96 根）的時點。"""
    rows = []
    mask = (df["date"] >= start_ts) & (df["date"] < end_ts) & df["bbw_pct"].notna()
    idxs = df.index[mask].tolist()
    next_allowed = -1
    n_considered = 0
    for i in idxs:
        n_considered += 1
        if i < next_allowed:
            continue
        if i + MAX_T_BARS >= len(df):   # 右尾截斷會系統性壓低振幅，整筆排除
            continue
        bkt = bucket_of(float(df.at[i, "bbw_pct"]))
        if bkt is None:
            continue
        close = float(df.at[i, "close"])
        row = {"pair": pair, "ts": df.at[i, "date"], "bucket": bkt}
        for name, bars in HORIZONS.items():
            row[f"amp_{name}"] = amplitude(df.iloc[i + 1: i + 1 + bars], close)
        rows.append(row)
        next_allowed = i + MAX_T_BARS
    if verbose:
        print(f"  [decluster] {pair}: 候選列 {n_considered} -> 採樣 {len(rows)}",
              file=sys.stderr, flush=True)
    return rows


def event_rows(df: pd.DataFrame, pair: str, start_ts, end_ts):
    """event 端：同標的 cooldown（16 根）套在全序列上，再依分析窗過濾（與 run2/run3 同序）。"""
    rows = []
    cooldown_until = -1
    for i in df.index[df["event"]]:
        if i <= cooldown_until:
            continue
        cooldown_until = i + PARAMS["cooldown_bars"]
        ts = df.at[i, "date"]
        if not (start_ts <= ts < end_ts):
            continue
        if i + T_24H_BARS >= len(df):
            continue
        close = float(df.at[i, "close"])
        rows.append({
            "pair": pair, "ts": ts, "grade": df.at[i, "grade"],
            "bbw_pct_now": float(df.at[i, "bbw_pct"]) if pd.notna(df.at[i, "bbw_pct"]) else None,
            "amp_24h": amplitude(df.iloc[i + 1: i + 1 + T_24H_BARS], close),
        })
    return rows


# ---------------------------------------------------------------- bootstrap（沿用 Q1'/Q2' 方法）

def _weeks(sub: pd.DataFrame, col="amp_24h"):
    return sub.groupby("week")[col].apply(lambda s: s.to_numpy()).to_numpy(dtype=object)


def block_boot_diff(a_df, b_df, q, rng, col="amp_24h", n_boot=N_BOOT):
    """b - a 的逐週區塊 bootstrap（週為區塊，兩組各自獨立重抽），回傳 diffs 陣列。"""
    a_w, b_w = _weeks(a_df, col), _weeks(b_df, col)
    diffs = np.empty(n_boot)
    for k in range(n_boot):
        a_pick = rng.integers(0, len(a_w), size=len(a_w))
        b_pick = rng.integers(0, len(b_w), size=len(b_w))
        diffs[k] = (np.quantile(np.concatenate([b_w[i] for i in b_pick]), q)
                    - np.quantile(np.concatenate([a_w[i] for i in a_pick]), q))
    return diffs


def stratified_pooled_diff(event_df, random_df, buckets_used, rng, n_boot=N_BOOT):
    """跨桶合併：各桶事件數為固定權重（權重不重抽），桶內逐週區塊 bootstrap p80 差距。"""
    weights = {b: len(event_df[event_df["bucket"] == b]) for b in buckets_used}
    total_w = sum(weights.values())
    per_bucket = {b: (_weeks(event_df[event_df["bucket"] == b]),
                      _weeks(random_df[random_df["bucket"] == b])) for b in buckets_used}
    diffs = np.empty(n_boot)
    for k in range(n_boot):
        acc = 0.0
        for b in buckets_used:
            e_w, r_w = per_bucket[b]
            e_s = np.concatenate([e_w[i] for i in rng.integers(0, len(e_w), size=len(e_w))])
            r_s = np.concatenate([r_w[i] for i in rng.integers(0, len(r_w), size=len(r_w))])
            acc += weights[b] * (np.quantile(e_s, 0.80) - np.quantile(r_s, 0.80))
        diffs[k] = acc / total_w
    return diffs


def add_week(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["week"] = pd.to_datetime(df["ts"]).dt.tz_convert("UTC").dt.strftime("%G-W%V")
    return df


# ---------------------------------------------------------------- 報表

def q1_table(sdf: pd.DataFrame, tag: str) -> pd.DataFrame:
    rows = []
    for b in BUCKETS:
        sub = sdf[sdf["bucket"] == b]
        line = {"window": tag, "bucket": bucket_label(b), "n": len(sub)}
        for name in HORIZONS:
            s = sub[f"amp_{name}"].dropna()
            if len(s) == 0:
                line[f"{name}_p50"] = line[f"{name}_p80"] = line[f"{name}_p95"] = None
                continue
            line[f"{name}_p50"] = round(float(s.quantile(0.50)) * 100, 3)
            line[f"{name}_p80"] = round(float(s.quantile(0.80)) * 100, 3)
            line[f"{name}_p95"] = round(float(s.quantile(0.95)) * 100, 3)
        rows.append(line)
    return pd.DataFrame(rows)


def q1_lowhigh_ci(sdf: pd.DataFrame, tag: str) -> pd.DataFrame:
    """最低桶 vs 最高桶的分位數差距（逐週區塊 bootstrap）。
    24h 是 §4 預登記的檢定戰場；1h/4h/12h 同屬凍結網格，一併報以免事後挑 T。"""
    lo_df = add_week(sdf[sdf["bucket"] == BUCKETS[0]])
    hi_df = add_week(sdf[sdf["bucket"] == BUCKETS[-1]])
    out = []
    for name in HORIZONS:
        col = f"amp_{name}"
        row = {"window": tag, "T": name, "n_lo": len(lo_df), "n_hi": len(hi_df)}
        if len(lo_df) < 30 or len(hi_df) < 30:
            row.update({"p80_lo": None, "p80_hi": None, "diff_p80": None,
                        "ci_lo": None, "ci_hi": None})
            out.append(row)
            continue
        p80_lo = float(lo_df[col].quantile(0.80)) * 100
        p80_hi = float(hi_df[col].quantile(0.80)) * 100
        rng = np.random.default_rng(sub_seed(tag, name))
        d = block_boot_diff(lo_df, hi_df, 0.80, rng, col=col) * 100
        ci = np.quantile(d, [0.025, 0.975])
        row.update({"p80_lo": round(p80_lo, 3), "p80_hi": round(p80_hi, 3),
                    "diff_p80": round(p80_hi - p80_lo, 3),
                    "ci_lo": round(float(ci[0]), 3), "ci_hi": round(float(ci[1]), 3)})
        out.append(row)
    return pd.DataFrame(out)


def q2prime_table(events: pd.DataFrame, randoms: pd.DataFrame, tag: str):
    """Q2' 分桶配對表 + 跨桶合併 + A 級合併。回傳 (bucket_table_df, pooled_rows)。"""
    e_all, r_all = add_week(events), add_week(randoms)
    rows = []
    for b in BUCKETS:
        e_sub, r_sub = e_all[e_all["bucket"] == b], r_all[r_all["bucket"] == b]
        n_e, n_r = len(e_sub), len(r_sub)
        line = {"window": tag, "bucket": bucket_label(b), "n_event": n_e,
                "n_A": int((e_sub["grade"] == "A").sum()) if n_e else 0,
                "n_B": int((e_sub["grade"] == "B").sum()) if n_e else 0,
                "n_random": n_r}
        if n_e == 0 or n_r == 0:
            line.update({"event_p80": None, "random_p80": None, "diff_p80": None,
                         "ci_lo": None, "ci_hi": None, "note": "無樣本"})
            rows.append(line)
            continue
        e_p80 = float(e_sub["amp_24h"].quantile(0.80)) * 100
        r_p80 = float(r_sub["amp_24h"].quantile(0.80)) * 100
        line["event_p80"] = round(e_p80, 3)
        line["random_p80"] = round(r_p80, 3)
        line["diff_p80"] = round(e_p80 - r_p80, 3)
        if n_e < 30:
            line.update({"ci_lo": None, "ci_hi": None, "note": "n<30 樣本不足，不判定"})
        else:
            rng = np.random.default_rng(sub_seed(tag, b))
            d = block_boot_diff(r_sub, e_sub, 0.80, rng) * 100
            ci = np.quantile(d, [0.025, 0.975])
            line.update({"ci_lo": round(float(ci[0]), 3), "ci_hi": round(float(ci[1]), 3),
                         "note": ""})
        rows.append(line)

    pooled = []
    for label, esrc in (("全事件", e_all), ("A 級", e_all[e_all["grade"] == "A"])):
        used = [b for b in BUCKETS if len(esrc[esrc["bucket"] == b]) >= 30]
        dropped = [bucket_label(b) for b in BUCKETS if b not in used]
        if not used:
            pooled.append({"window": tag, "subset": label, "buckets_used": "無（皆 n<30）",
                           "n_event": len(esrc), "point": None, "ci_lo": None, "ci_hi": None,
                           "dropped": ",".join(dropped)})
            continue
        w = [len(esrc[esrc["bucket"] == b]) for b in used]
        pts = [(float(esrc[esrc["bucket"] == b]["amp_24h"].quantile(0.80))
                - float(r_all[r_all["bucket"] == b]["amp_24h"].quantile(0.80))) * 100 for b in used]
        point = sum(wi * pi for wi, pi in zip(w, pts)) / sum(w)
        rng = np.random.default_rng(sub_seed(tag, label))
        d = stratified_pooled_diff(esrc, r_all, used, rng) * 100
        ci = np.quantile(d, [0.025, 0.975])
        pooled.append({"window": tag, "subset": label,
                       "buckets_used": " ".join(bucket_label(b) for b in used),
                       "n_event": sum(w), "point": round(point, 3),
                       "ci_lo": round(float(ci[0]), 3), "ci_hi": round(float(ci[1]), 3),
                       "dropped": ",".join(dropped)})
    return pd.DataFrame(rows), pd.DataFrame(pooled)


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
            "n_event_raw": int(df["event"].sum()),
        })
    cov = pd.DataFrame(coverage)
    print("\n=== 資料覆蓋（抓取 2022-12~2026-06，含暖機月）===")
    print(cov.to_string(index=False))
    cov.to_csv(f"{STEM}_coverage.tsv", sep="\t", index=False)
    if args.fetch_only:
        return

    q1_tables, q1_cis, q2_tables, q2_pooled = [], [], [], []
    summary_pool = {}

    for tag, start, end, desc in WINDOWS:
        start_ts = pd.Timestamp(start, tz="UTC")
        end_ts = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
        print("\n" + "=" * 100)
        print(f"### 窗口 {tag}：{start} ~ {end}　{desc}")

        srows, erows = [], []
        for pair in PAIRS:
            df = prepared[pair]
            srows += q1_samples(df, pair, start_ts, end_ts)
            erows += event_rows(df, pair, start_ts, end_ts)
        sdf = pd.DataFrame(srows)
        print(f"[Q1] 去叢集後總採樣 n={len(sdf)}")

        ev = pd.DataFrame(erows).sort_values("ts").reset_index(drop=True)
        n_null = int(ev["bbw_pct_now"].isna().sum())
        ev = ev.dropna(subset=["bbw_pct_now"]).reset_index(drop=True)
        ev["win4h"] = ev["ts"].dt.floor("4h")
        ev_d = ev.drop_duplicates(subset="win4h", keep="first").reset_index(drop=True)
        ev_d["bucket"] = ev_d["bbw_pct_now"].apply(bucket_of)
        n_nobkt = int(ev_d["bucket"].isna().sum())
        ev_d = ev_d.dropna(subset=["bucket"]).reset_index(drop=True)
        print(f"[Q2'] event 原始（同標的 cooldown）n={len(ev) + n_null}，bbw_pct null 丟棄 {n_null}，"
              f"跨標的 4h 窗去重後 n={len(ev_d)}（A={int((ev_d.grade=='A').sum())}/"
              f"B={int((ev_d.grade=='B').sum())}），桶外丟棄 {n_nobkt}")

        t = q1_table(sdf, tag)
        print(f"\n--- [{tag}] Q1 凍結網格：bbw_pct 六分桶 × T 振幅分位數（%，每格附 n）---")
        print(t.to_string(index=False))
        q1_tables.append(t)

        c = q1_lowhigh_ci(sdf, tag)
        print(f"\n--- [{tag}] Q1 最低桶 vs 最高桶 p80 差距（逐週區塊 bootstrap {N_BOOT} 次）---")
        print(c.to_string(index=False))
        q1_cis.append(c)

        bt, pl = q2prime_table(ev_d, sdf, tag)
        print(f"\n--- [{tag}] Q2' event（觸發當下 bbw_pct 分桶）vs 同桶隨機時點，24h 振幅 p80 ---")
        print(bt.to_string(index=False))
        print(f"\n--- [{tag}] Q2' 跨桶合併（僅 n_event>=30 的桶，事件數加權）---")
        print(pl.to_string(index=False))
        q2_tables.append(bt)
        q2_pooled.append(pl)

        sdf_out = sdf.copy()
        sdf_out["bucket"] = sdf_out["bucket"].apply(bucket_label)
        sdf_out.to_csv(f"{STEM}_samples_{tag}.tsv", sep="\t", index=False)
        ev_out = ev_d.copy()
        ev_out["bucket"] = ev_out["bucket"].apply(bucket_label)
        ev_out.to_csv(f"{STEM}_events_{tag}.tsv", sep="\t", index=False)
        summary_pool[tag] = (len(sdf), len(ev_d))

    pd.concat(q1_tables).to_csv(f"{STEM}_q1_grid.tsv", sep="\t", index=False)
    pd.concat(q1_cis).to_csv(f"{STEM}_q1_lowhigh_ci.tsv", sep="\t", index=False)
    pd.concat(q2_tables).to_csv(f"{STEM}_q2_buckets.tsv", sep="\t", index=False)
    pd.concat(q2_pooled).to_csv(f"{STEM}_q2_pooled.tsv", sep="\t", index=False)

    print("\n" + "=" * 100)
    print("### 時期分層對照（P1=2023-01~2024-12 新增期　vs　ORIG/P2=2025-01~2026-06 原窗口）")
    print("\n[Q1 效應] 最低桶 vs 最高桶 p80 差距，逐窗逐 T：")
    print(pd.concat(q1_cis).to_string(index=False))
    print("\n[Q2' 效應] 跨桶合併：")
    print(pd.concat(q2_pooled).to_string(index=False))
    print("\n[樣本規模] " + "  ".join(f"{k}: Q1 n={v[0]}, event n={v[1]}" for k, v in summary_pool.items()))


if __name__ == "__main__":
    main()
