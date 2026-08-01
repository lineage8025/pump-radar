"""Q2'（run 3，backlog.md 2026-08-01 新增，承接 run2 Q2 最強反駁第 1 點）：
`bbw_pct` 分層配對版 Q2。

run2 的 Q2 直接比較「event（去重後）24h 振幅」vs「Q1 全樣本隨機時點 24h 振幅」，
發現整體無顯著差異（p80 差距 CI 含 0）。但最強反駁指出：這個比較沒有控制事件
觸發當下的 `bbw_pct` 分佈——B 級事件（`bbw_pct.shift(1)>0.25`）的 `bbw_pct` 底色
本來就偏高，依 run1 Q1（`bbw_pct` 越高、24h 振幅越大），這會讓 B 級事件「應該」
振幅偏高；觀察到的「無顯著差異」可能是兩股方向相反的力量（`bbw_pct` 底色 vs
`event` 條件本身）互相抵消，不是 `event` 真的沒有資訊量。

本檔把每筆 event 依其**觸發當根自身**（未 shift，與 run1 Q1 的 bucket_of() 用同一顆
row 的 bbw_pct 是同一個「當下」定義）配對到 `research/program.md` §4 凍結的六分桶，
只跟同一分桶內的 Q1 隨機時點子集比較 24h 振幅，藉此把 `vol_z`/突破條件的獨立貢獻
從 `bbw_pct` 底色中分離出來。**不是新方向、不換分桶/T/標的/窗口**，只是換一種
配對方式重新解讀已有的 event/隨機資料，backlog.md 已將此列為非 frontier 的 Q2 承接題，
不受 §5 frontier 兩階段閘門管轄。

資料來源：
- event 端：重新抓取 10 標的 `2024-12~2026-06`（`/tmp` 快取隨環境重啟清空），
  用 `fetch_klines.fetch_month()`（唯讀，未改動）+ 本檔複製 run1/run2 已用過的
  逐月 ms/µs 單位繞法（`to_candles()` 原檔用整批第一筆 open_time 判斷單位，
  跨 2024-12(ms)->2025-01(µs) 邊界會誤判，繞法與 run1/run2 完全相同）。
  事件偵測/分級/cooldown/跨標的 4h 窗去重完全複用 `detector.add_indicators`/`PARAMS`
  與 run2 `2026-08-01_q2_phase05_event_kill_switch.py` 的邏輯，一字不動；唯一新增
  是額外記錄每筆事件觸發當根自身的 `bbw_pct`（`df.at[i, "bbw_pct"]`，非 shift(1)）。
- 隨機時點端：唯讀複用 run1 `2026-08-01_phase0_bbw_amplitude_samples.tsv`
  （10 標的、2025-01-01~2026-06-30、去叢集後 n=5450，欄位已含 bucket 與 amp_24h），
  不重新抓資料、不重新定義隨機基準。

方法：對六個凍結分桶各自算「該桶內 event p80 vs 該桶內隨機時點 p80」的差距，
以及用事件數加權（僅採 n>=30 的桶）算一個跨桶合併估計，逐週區塊 bootstrap
（沿用 Q1'/Q2 已用過的方法）取 CI。
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
T_24H_BARS = 96
RANDOM_POOL_PATH = Path(__file__).parent / "2026-08-01_phase0_bbw_amplitude_samples.tsv"
N_BOOT = 2000
SEED = 20260801

# 凍結網格 program.md §4，與 run1 Q1 bucket_of() 完全一致
BUCKETS = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.25), (0.25, 0.50), (0.50, 0.75), (0.75, 1.0)]


def bucket_of(p: float):
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


def month_to_candles(raw: pd.DataFrame) -> pd.DataFrame:
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
    cache = OUT_DIR / f"{pair.replace('/', '_')}-15m.feather"
    if cache.exists():
        return pd.read_feather(cache)
    symbol = pair.replace("/", "")
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


def raw_event_indices(df: pd.DataFrame) -> list:
    cooldown_until = -1
    idxs = []
    for i in df.index[df["event"]]:
        if i <= cooldown_until:
            continue
        cooldown_until = i + PARAMS["cooldown_bars"]
        idxs.append(i)
    return idxs


def amplitude(window: pd.DataFrame, close: float) -> float:
    return (window["high"].max() - window["low"].min()) / close


def block_bootstrap_quantile_diff(a_df, b_df, q, rng, n_boot=N_BOOT):
    """b - a 的逐週區塊 bootstrap（沿用 Q1'/Q2 方法）。a=隨機時點, b=event。"""
    a_weeks = a_df.groupby("week")["amp_24h"].apply(lambda s: s.to_numpy()).to_numpy(dtype=object)
    b_weeks = b_df.groupby("week")["amp_24h"].apply(lambda s: s.to_numpy()).to_numpy(dtype=object)
    diffs = np.empty(n_boot)
    for k in range(n_boot):
        a_pick = rng.integers(0, len(a_weeks), size=len(a_weeks))
        b_pick = rng.integers(0, len(b_weeks), size=len(b_weeks))
        a_sample = np.concatenate([a_weeks[i] for i in a_pick])
        b_sample = np.concatenate([b_weeks[i] for i in b_pick])
        diffs[k] = np.quantile(b_sample, q) - np.quantile(a_sample, q)
    return diffs


def stratified_pooled_diff(event_df, random_df, buckets_used, rng, n_boot=N_BOOT):
    """跨桶合併估計：以各桶事件數為固定權重，逐週區塊 bootstrap 各桶內 p80 後加權平均。
    權重本身不重抽（只重抽各桶內的樣本），避免多引入一個與研究問題無關的變異來源。"""
    weights = {b: len(event_df[event_df["bucket"] == b]) for b in buckets_used}
    total_w = sum(weights.values())
    diffs = np.empty(n_boot)
    # 預先把各桶依週分組，重複利用
    per_bucket = {}
    for b in buckets_used:
        e_sub = event_df[event_df["bucket"] == b]
        r_sub = random_df[random_df["bucket"] == b]
        e_weeks = e_sub.groupby("week")["amp_24h"].apply(lambda s: s.to_numpy()).to_numpy(dtype=object)
        r_weeks = r_sub.groupby("week")["amp_24h"].apply(lambda s: s.to_numpy()).to_numpy(dtype=object)
        per_bucket[b] = (e_weeks, r_weeks)
    for k in range(n_boot):
        acc = 0.0
        for b in buckets_used:
            e_weeks, r_weeks = per_bucket[b]
            e_pick = rng.integers(0, len(e_weeks), size=len(e_weeks))
            r_pick = rng.integers(0, len(r_weeks), size=len(r_weeks))
            e_sample = np.concatenate([e_weeks[i] for i in e_pick])
            r_sample = np.concatenate([r_weeks[i] for i in r_pick])
            d = np.quantile(e_sample, 0.80) - np.quantile(r_sample, 0.80)
            acc += weights[b] * d
        diffs[k] = acc / total_w
    return diffs


def main() -> None:
    start_ts = pd.Timestamp(ANALYSIS_START, tz="UTC")
    end_ts = pd.Timestamp(ANALYSIS_END, tz="UTC") + pd.Timedelta(days=1)

    raw_rows = []
    for pair in PAIRS:
        candles = load_pair(pair)
        df = add_indicators(candles, PARAMS)
        for i in raw_event_indices(df):
            ts = df.at[i, "date"]
            if not (start_ts <= ts < end_ts):
                continue
            if i + T_24H_BARS >= len(df):
                continue
            close = float(df.at[i, "close"])
            window = df.iloc[i + 1: i + 1 + T_24H_BARS]
            raw_rows.append({
                "pair": pair, "ts": ts, "grade": df.at[i, "grade"],
                "bbw_pct_now": float(df.at[i, "bbw_pct"]) if pd.notna(df.at[i, "bbw_pct"]) else None,
                "amp_24h": amplitude(window, close),
            })
        n_events_this_pair = sum(1 for r in raw_rows if r["pair"] == pair)
        print(f"[events] {pair}: {n_events_this_pair} 筆（cooldown 已套用，右尾截斷已排除）",
              file=sys.stderr)

    events_raw = pd.DataFrame(raw_rows).sort_values("ts").reset_index(drop=True)
    n_null_bbw = events_raw["bbw_pct_now"].isna().sum()
    print(f"\n=== 原始事件數（同標的 cooldown）n={len(events_raw)}，"
          f"其中 bbw_pct_now 為 null（暖機不足，丟棄）n={n_null_bbw} ===")
    events_raw = events_raw.dropna(subset=["bbw_pct_now"]).reset_index(drop=True)

    # 跨標的「同一 4h 窗僅計首發」去叢集（與 run2 Q2 同一視角）
    events_raw["win4h"] = events_raw["ts"].dt.floor("4h")
    events_dedup = events_raw.drop_duplicates(subset="win4h", keep="first").reset_index(drop=True)
    print(f"跨標的 4h 窗去重後 n={len(events_dedup)}"
          f"（原始 {len(events_raw)} -> 去重 {len(events_dedup)}，"
          f"重複率 {(1 - len(events_dedup)/len(events_raw))*100:.1f}%）")
    print(f"A 級 n={len(events_dedup[events_dedup.grade=='A'])}  "
          f"B 級 n={len(events_dedup[events_dedup.grade=='B'])}")

    events_dedup["bucket"] = events_dedup["bbw_pct_now"].apply(bucket_of)
    n_bucket_none = events_dedup["bucket"].isna().sum()
    if n_bucket_none:
        print(f"[警告] {n_bucket_none} 筆事件 bbw_pct_now 落在凍結網格 6 桶邊界外"
              f"（理論上不應發生，bucket_of 已含首尾兩端），予以丟棄。")
    events_dedup = events_dedup.dropna(subset=["bucket"]).reset_index(drop=True)

    events_dedup.to_csv(Path(__file__).with_suffix("").as_posix() + "_events.tsv", sep="\t", index=False)

    random_df = pd.read_csv(RANDOM_POOL_PATH, sep="\t", parse_dates=["ts"])
    random_df["week"] = random_df["ts"].dt.tz_convert("UTC").dt.strftime("%G-W%V")
    # samples.tsv 的 bucket 欄位是字串化的 tuple repr（如 "(0.0, 0.05)"），用同一個 BUCKETS 表對應
    bucket_str_to_tuple = {str(b): b for b in BUCKETS}
    random_df["bucket"] = random_df["bucket"].map(bucket_str_to_tuple)
    events_dedup["week"] = pd.to_datetime(events_dedup["ts"]).dt.tz_convert("UTC").dt.strftime("%G-W%V")

    rng = np.random.default_rng(SEED)

    print("\n" + "=" * 78)
    print("=== 分桶配對表：event（觸發當下 bbw_pct 所在桶）vs 同桶隨機時點，24h 振幅 ===")
    rows_out = []
    for b in BUCKETS:
        e_sub = events_dedup[events_dedup["bucket"] == b]
        r_sub = random_df[random_df["bucket"] == b]
        n_e, n_r = len(e_sub), len(r_sub)
        if n_e == 0:
            print(f"\n[{bucket_label(b)}] event n=0，該桶無事件落入，無法比較。")
            rows_out.append({"bucket": bucket_label(b), "n_event": 0, "n_event_A": 0, "n_event_B": 0,
                              "n_random": n_r, "event_p80": None, "random_p80": None,
                              "diff_p80": None, "ci_lo": None, "ci_hi": None})
            continue
        e_p50 = e_sub["amp_24h"].quantile(0.50) * 100
        e_p80 = e_sub["amp_24h"].quantile(0.80) * 100
        r_p50 = r_sub["amp_24h"].quantile(0.50) * 100
        r_p80 = r_sub["amp_24h"].quantile(0.80) * 100
        n_a = int((e_sub["grade"] == "A").sum())
        n_b = int((e_sub["grade"] == "B").sum())
        print(f"\n[{bucket_label(b)}] event n={n_e}(A={n_a}/B={n_b})  隨機 n={n_r}")
        print(f"  event  24h p50={e_p50:.3f}%  p80={e_p80:.3f}%")
        print(f"  隨機   24h p50={r_p50:.3f}%  p80={r_p80:.3f}%")
        diff = e_p80 - r_p80
        if n_e < 30:
            print(f"  [n<30，以下差距與 CI 僅供參考，不得判定有/無區別力] 差距(event-隨機)={diff:+.3f}pp")
            rows_out.append({"bucket": bucket_label(b), "n_event": n_e, "n_event_A": n_a, "n_event_B": n_b,
                              "n_random": n_r, "event_p80": round(e_p80, 3), "random_p80": round(r_p80, 3),
                              "diff_p80": round(diff, 3), "ci_lo": None, "ci_hi": None})
            continue
        diffs = block_bootstrap_quantile_diff(r_sub, e_sub, 0.80, rng) * 100
        ci = np.quantile(diffs, [0.025, 0.975])
        print(f"  差距(event-隨機) p80 點估計={diff:+.3f}pp, 逐週區塊 bootstrap 95% CI "
              f"[{ci[0]:+.3f}, {ci[1]:+.3f}]pp")
        rows_out.append({"bucket": bucket_label(b), "n_event": n_e, "n_event_A": n_a, "n_event_B": n_b,
                          "n_random": n_r, "event_p80": round(e_p80, 3), "random_p80": round(r_p80, 3),
                          "diff_p80": round(diff, 3), "ci_lo": round(ci[0], 3), "ci_hi": round(ci[1], 3)})

    out_df = pd.DataFrame(rows_out)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    print("\n" + out_df.to_string(index=False))
    out_df.to_csv(Path(__file__).with_suffix("").as_posix() + "_bucket_table.tsv", sep="\t", index=False)

    print("\n" + "=" * 78)
    print("=== 跨桶合併估計（僅採 n_event>=30 的桶，以各桶事件數加權，逐週區塊 bootstrap）===")
    buckets_used = [b for b in BUCKETS if len(events_dedup[events_dedup["bucket"] == b]) >= 30]
    dropped = [bucket_label(b) for b in BUCKETS if b not in buckets_used]
    if dropped:
        print(f"以下桶因 event n<30 被排除在合併估計外（該桶結果只在上表個別參考）：{dropped}")
    if len(buckets_used) == 0:
        print("所有桶 event n 皆 <30，無法計算合併估計。")
    else:
        n_used = sum(len(events_dedup[events_dedup["bucket"] == b]) for b in buckets_used)
        point_diffs = []
        for b in buckets_used:
            e_sub = events_dedup[events_dedup["bucket"] == b]
            r_sub = random_df[random_df["bucket"] == b]
            point_diffs.append((e_sub["amp_24h"].quantile(0.80) - r_sub["amp_24h"].quantile(0.80)) * 100)
        weights = [len(events_dedup[events_dedup["bucket"] == b]) for b in buckets_used]
        point = sum(w * d for w, d in zip(weights, point_diffs)) / sum(weights)
        diffs = stratified_pooled_diff(events_dedup, random_df, buckets_used, np.random.default_rng(SEED + 1)) * 100
        ci = np.quantile(diffs, [0.025, 0.975])
        print(f"合併採用桶：{[bucket_label(b) for b in buckets_used]}，合併 event n={n_used}")
        print(f"跨桶加權 p80 差距(event-隨機) 點估計={point:+.3f}pp, 逐週區塊 bootstrap 95% CI "
              f"[{ci[0]:+.3f}, {ci[1]:+.3f}]pp")

    print("\n" + "=" * 78)
    print("=== 同一分桶配對，只看 A 級事件（壓縮後爆發）vs 同桶隨機時點 ===")
    a_events = events_dedup[events_dedup["grade"] == "A"]
    a_buckets_used = [b for b in BUCKETS if len(a_events[a_events["bucket"] == b]) >= 30]
    a_dropped = [bucket_label(b) for b in BUCKETS if b not in a_buckets_used]
    print(f"A 級事件分桶分佈：{a_events['bucket'].apply(bucket_label).value_counts().to_dict()}")
    if a_dropped:
        print(f"以下桶因 A 級 event n<30 被排除在合併估計外：{a_dropped}")
    if len(a_buckets_used) == 0:
        print("A 級事件在所有桶的 n 皆 <30，無法計算合併估計，僅供上面分佈參考。")
    else:
        n_a_used = sum(len(a_events[a_events["bucket"] == b]) for b in a_buckets_used)
        a_point_diffs = []
        for b in a_buckets_used:
            e_sub = a_events[a_events["bucket"] == b]
            r_sub = random_df[random_df["bucket"] == b]
            a_point_diffs.append((e_sub["amp_24h"].quantile(0.80) - r_sub["amp_24h"].quantile(0.80)) * 100)
        a_weights = [len(a_events[a_events["bucket"] == b]) for b in a_buckets_used]
        a_point = sum(w * d for w, d in zip(a_weights, a_point_diffs)) / sum(a_weights)
        a_diffs = stratified_pooled_diff(a_events, random_df, a_buckets_used, np.random.default_rng(SEED + 2)) * 100
        a_ci = np.quantile(a_diffs, [0.025, 0.975])
        print(f"合併採用桶：{[bucket_label(b) for b in a_buckets_used]}，合併 A 級 event n={n_a_used}")
        print(f"A 級跨桶加權 p80 差距(event-隨機) 點估計={a_point:+.3f}pp, 逐週區塊 bootstrap 95% CI "
              f"[{a_ci[0]:+.3f}, {a_ci[1]:+.3f}]pp")


if __name__ == "__main__":
    main()
