"""Q2（Phase 0.5，run 2，backlog.md 已解封）：現行 `event`（detector.py 觸發條件）
是不是好的「波動爆發預警」——比較 event 觸發後 24h 振幅 vs 隨機時點 24h 振幅。

方法論提醒（backlog.md Q2 附註，2026-08-01 run1 Q1 發現後補記）：Q1 已證實
`bbw_pct` 低（壓縮）對應的是「24h 振幅更小」而非更大。`event` 的 A 級門檻正是
「觸發前一根 bbw_pct<=25%（壓縮）」，若壓縮本身對振幅是負向貢獻，A 級事件單獨看
振幅可能不會贏過隨機時點；`event` 若整體仍贏過隨機時點，貢獻大概率來自
`vol_z>=3.0` 放量條件而非壓縮本身。本檔因此把 A/B 級分開報告，不只看整體。

隨機時點基準**直接複用 run1 Q1 的既有樣本**（2026-08-01_phase0_bbw_amplitude_samples.tsv，
5450 筆，10 標的、同一分析窗 2025-01-01~2026-06-30、同一去叢集規則 `>=96` 根間隔、
未條件於任何 bucket——本身就是「隨機時點」母體），不重新定義隨機基準，確保口徑一致。
唯讀該檔，不修改。

`event`/`grade` 判定完全複用 `scripts/detector.py` 的 `add_indicators`/`PARAMS`，
本檔不改動偵測邏輯一個字。cooldown（同標的 16 根內不重複觸發）沿用 detector 既有規則，
另外套用 DETECTOR_PREREG.md 已預登記的「同一 4h 窗僅計首發」跨標的去叢集視角
（多標的同刻齊發時只算最早一筆）作為主結果；去重前的原始事件數同時回報供對照。

資料抓取沿用 run1 相同的 fetch_klines.py bug 繞法（該檔對本迴圈唯讀，未改動）：
`to_candles()` 以整批第一筆 open_time 判斷 ms/us 單位，跨 2024-12(ms)->2025-01(us) 邊界
會誤判，故逐月自行判斷單位再 concat。
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
    """複製 detector.iter_events 的 cooldown 邏輯，額外保留整數 index（iter_events 本身不回傳）。"""
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
    """b - a 的逐週區塊 bootstrap（沿用 Q1' 方法），a/b 各自的樣本互斥。"""
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


def report_vs_random(label: str, sub_df: pd.DataFrame, random_df: pd.DataFrame, rng) -> None:
    n = len(sub_df)
    if n < 5:
        print(f"\n[{label}] n={n}（<5，樣本不足，無統計意義，不計算 CI/分位數）")
        return
    p50 = sub_df["amp_24h"].quantile(0.50) * 100
    p80 = sub_df["amp_24h"].quantile(0.80) * 100
    rp50 = random_df["amp_24h"].quantile(0.50) * 100
    rp80 = random_df["amp_24h"].quantile(0.80) * 100
    print(f"\n[{label}] n={n}  24h p50={p50:.3f}%  p80={p80:.3f}%  "
          f"（隨機時點對照 n={len(random_df)}: p50={rp50:.3f}% p80={rp80:.3f}%）")
    if n < 30:
        print(f"[{label}] n<30，以下 CI 僅供參考，不得判定有/無區別力。")
    diffs = block_bootstrap_quantile_diff(random_df, sub_df, 0.80, rng)
    ci = np.quantile(diffs, [0.025, 0.975])
    point = p80 - rp80
    print(f"[{label}] p80 差距(vs 隨機) 點估計={point:+.3f}pp, "
          f"逐週區塊 bootstrap 95% CI [{ci[0]:+.3f}, {ci[1]:+.3f}]pp")


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
                continue  # 右尾截斷，需完整 24h 前瞻窗
            close = float(df.at[i, "close"])
            window = df.iloc[i + 1: i + 1 + T_24H_BARS]
            raw_rows.append({
                "pair": pair, "ts": ts, "grade": df.at[i, "grade"],
                "vol_z": float(df.at[i, "vol_z"]),
                "amp_24h": amplitude(window, close),
            })
        n_events_this_pair = sum(1 for r in raw_rows if r["pair"] == pair)
        print(f"[events] {pair}: {n_events_this_pair} 筆（cooldown 已套用，右尾截斷已排除）",
              file=sys.stderr)

    events_raw = pd.DataFrame(raw_rows).sort_values("ts").reset_index(drop=True)
    print(f"\n=== 原始事件數（僅同標的 cooldown，未做跨標的 4h 窗去重）n={len(events_raw)} ===")
    print(f"A 級 n={len(events_raw[events_raw.grade=='A'])}  "
          f"B 級 n={len(events_raw[events_raw.grade=='B'])}")

    # 跨標的「同一 4h 窗僅計首發」去叢集（DETECTOR_PREREG.md 已預登記視角）
    events_raw["win4h"] = events_raw["ts"].dt.floor("4h")
    events_dedup = events_raw.drop_duplicates(subset="win4h", keep="first").reset_index(drop=True)
    print(f"\n=== 跨標的 4h 窗去重後 n={len(events_dedup)}"
          f"（原始 {len(events_raw)} -> 去重 {len(events_dedup)}，"
          f"重複率 {(1 - len(events_dedup)/len(events_raw))*100:.1f}%）===")
    print(f"A 級 n={len(events_dedup[events_dedup.grade=='A'])}  "
          f"B 級 n={len(events_dedup[events_dedup.grade=='B'])}")

    events_dedup.to_csv(Path(__file__).with_suffix("").as_posix() + "_events.tsv", sep="\t", index=False)

    random_df = pd.read_csv(RANDOM_POOL_PATH, sep="\t", parse_dates=["ts"])
    random_df["week"] = random_df["ts"].dt.tz_convert("UTC").dt.strftime("%G-W%V")
    events_dedup["week"] = pd.to_datetime(events_dedup["ts"]).dt.tz_convert("UTC").dt.strftime("%G-W%V")

    rng = np.random.default_rng(SEED)
    print("\n" + "=" * 70)
    print("=== 主結果：event(去重後,全部) vs 隨機時點（Q1 run1 母體,n=5450）===")
    report_vs_random("event-all(dedup)", events_dedup, random_df, rng)

    print("\n=== 拆解：A 級（壓縮後爆發）vs 隨機時點 ===")
    report_vs_random("event-A(dedup)", events_dedup[events_dedup.grade == "A"], random_df, rng)

    print("\n=== 拆解：B 級（無壓縮前置）vs 隨機時點 ===")
    report_vs_random("event-B(dedup)", events_dedup[events_dedup.grade == "B"], random_df, rng)

    print("\n=== A 級 vs B 級 直接比較（驗證『壓縮本身是否拖累振幅』的假設）===")
    a_sub = events_dedup[events_dedup.grade == "A"]
    b_sub = events_dedup[events_dedup.grade == "B"]
    if len(a_sub) >= 5 and len(b_sub) >= 5:
        a_p80 = a_sub["amp_24h"].quantile(0.80) * 100
        b_p80 = b_sub["amp_24h"].quantile(0.80) * 100
        print(f"A 級(n={len(a_sub)}) p80={a_p80:.3f}%  B 級(n={len(b_sub)}) p80={b_p80:.3f}%  "
              f"差距(A-B)={a_p80-b_p80:+.3f}pp")
        if len(a_sub) < 30 or len(b_sub) < 30:
            print("其中一級 n<30，此差距僅供參考，不判定有無區別力。")
    else:
        print(f"A 級 n={len(a_sub)} 或 B 級 n={len(b_sub)} <5，樣本不足，無統計意義。")


if __name__ == "__main__":
    main()
