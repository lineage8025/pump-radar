"""Q1'' 大小市值分層穩健性覆核（run 4，承接 run1/run2/run3 誘惑清單「大小市值標的分開看」，
`docs/RESEARCH_BBW_VOLATILITY.md` §5 建議 5：10 標的合併計算，流動性系統差異
（BTC/ETH vs LTC/AVAX 等）造成的 range 低估程度未拆解）。

本檔**不換分桶、不換 T、不換度量、不換窗口、不重新抓資料**——唯讀複用 run1 已產出的
2026-08-01_phase0_bbw_amplitude_samples.tsv（10 標的、2025-01-01~2026-06-30、去叢集後
n=5450），只是把既有樣本依 pair 切成兩個市值分層子集，各自重算 Q1 的核心比較
（24h p80，最低桶 vs 最高桶，逐週區塊 bootstrap，方法與 2026-08-01_q1prime_block_bootstrap.py
完全一致）。這是 Q1 結論的分層穩健性覆核，非新增分桶/T/度量，不受 program.md §5
frontier 兩階段閘門管轄——與 Q1' 的定性相同（Q1' 換重抽單位、本檔換樣本分層，
皆未動 §4 凍結網格任何一項）。

分層依市值粗分兩組（backlog.md Q1'' 登記）：
- large：BTC/USDT, ETH/USDT（唯二市值破千億美元等級，流動性顯著優於其餘 8 標的）
- other：ADA/SOL/XRP/DOGE/BNB/LINK/LTC/AVAX/USDT（其餘 8 標的）
二分而非細分多層，是因為細分會讓部分桶×組合的 n 更快跌破 30，本次以「能不能維持
Q1 方向」為主要問題，不追求標的層級的精細歸因。
"""

from pathlib import Path

import numpy as np
import pandas as pd

SAMPLES_PATH = Path(__file__).parent / "2026-08-01_phase0_bbw_amplitude_samples.tsv"
LOWEST_BUCKET = "(0.0, 0.05)"
HIGHEST_BUCKET = "(0.75, 1.0)"
N_BOOT = 2000
SEED = 20260801

LARGE_CAP = {"BTC/USDT", "ETH/USDT"}


def block_bootstrap_quantile_diff(lo_df: pd.DataFrame, hi_df: pd.DataFrame, q: float, rng) -> np.ndarray:
    """對兩個互斥子集各自做『逐週區塊』重抽，回傳 N_BOOT 個 (hi_q - lo_q) 差距。
    方法與 2026-08-01_q1prime_block_bootstrap.py 完全一致（一字不改複製過來，避免分岔）。"""
    lo_weeks = lo_df.groupby("week")["amp_24h"].apply(lambda s: s.to_numpy())
    hi_weeks = hi_df.groupby("week")["amp_24h"].apply(lambda s: s.to_numpy())
    lo_week_arr = lo_weeks.to_numpy(dtype=object)
    hi_week_arr = hi_weeks.to_numpy(dtype=object)
    n_lo_weeks = len(lo_week_arr)
    n_hi_weeks = len(hi_week_arr)

    diffs = np.empty(N_BOOT)
    for b in range(N_BOOT):
        lo_pick = rng.integers(0, n_lo_weeks, size=n_lo_weeks)
        hi_pick = rng.integers(0, n_hi_weeks, size=n_hi_weeks)
        lo_sample = np.concatenate([lo_week_arr[i] for i in lo_pick])
        hi_sample = np.concatenate([hi_week_arr[i] for i in hi_pick])
        diffs[b] = np.quantile(hi_sample, q) - np.quantile(lo_sample, q)
    return diffs


def run_group(df: pd.DataFrame, label: str, seed: int, rows_out: list) -> None:
    lo_df = df[df["bucket"] == LOWEST_BUCKET]
    hi_df = df[df["bucket"] == HIGHEST_BUCKET]
    n_lo, n_hi = len(lo_df), len(hi_df)
    print(f"\n--- 分層={label} ---")
    print(f"最低桶 {LOWEST_BUCKET}: n={n_lo}, 涵蓋 {lo_df['week'].nunique()} 個 ISO 週")
    print(f"最高桶 {HIGHEST_BUCKET}: n={n_hi}, 涵蓋 {hi_df['week'].nunique()} 個 ISO 週")

    if n_lo < 30 or n_hi < 30:
        print(f"[樣本不足] 最低桶或最高桶 n<30（門檻見 program.md §5.1），僅列點估計不計 CI 或標註不足採信")

    rng = np.random.default_rng(seed)
    point_p80 = np.quantile(hi_df["amp_24h"], 0.80) - np.quantile(lo_df["amp_24h"], 0.80)
    ci_lo = ci_hi = None
    if n_lo >= 2 and n_hi >= 2:
        diffs_p80 = block_bootstrap_quantile_diff(lo_df, hi_df, 0.80, rng)
        ci_lo, ci_hi = np.quantile(diffs_p80, [0.025, 0.975])
        print(f"24h p80 差距（最高桶−最低桶）點估計 = {point_p80*100:+.3f}pp, "
              f"95% CI [{ci_lo*100:+.3f}, {ci_hi*100:+.3f}]pp"
              f"{'（n<30，僅供參考）' if (n_lo < 30 or n_hi < 30) else ''}")
    else:
        print(f"24h p80 差距點估計 = {point_p80*100:+.3f}pp（n 太小，無法 bootstrap）")

    # 六桶全覽（24h only，主戰場），每桶附 n，讓讀者自行核對單調性是否在分層內維持
    print(f"\n{label} 六桶 24h 振幅分位數：")
    for bkt in ["(0.0, 0.05)", "(0.05, 0.1)", "(0.1, 0.25)", "(0.25, 0.5)", "(0.5, 0.75)", "(0.75, 1.0)"]:
        sub = df[df["bucket"] == bkt]
        n = len(sub)
        if n == 0:
            print(f"  {bkt}: n=0")
            continue
        p50 = float(sub["amp_24h"].quantile(0.50)) * 100
        p80 = float(sub["amp_24h"].quantile(0.80)) * 100
        p95 = float(sub["amp_24h"].quantile(0.95)) * 100
        flag = "" if n >= 30 else "（n<30）"
        print(f"  {bkt}: n={n}{flag}  p50={p50:.3f}%  p80={p80:.3f}%  p95={p95:.3f}%")
        rows_out.append({
            "group": label, "bucket": bkt, "n": n,
            "p50_24h": round(p50, 3), "p80_24h": round(p80, 3), "p95_24h": round(p95, 3),
        })
    rows_out.append({
        "group": label, "bucket": "lo_vs_hi_gap_p80", "n": f"{n_lo}/{n_hi}",
        "p50_24h": None,
        "p80_24h": round(point_p80 * 100, 3),
        "p95_24h": f"CI[{ci_lo*100:+.3f},{ci_hi*100:+.3f}]" if ci_lo is not None else "n/a",
    })


def main() -> None:
    df = pd.read_csv(SAMPLES_PATH, sep="\t", parse_dates=["ts"])
    df["week"] = df["ts"].dt.tz_convert("UTC").dt.strftime("%G-W%V")

    large_df = df[df["pair"].isin(LARGE_CAP)].copy()
    other_df = df[~df["pair"].isin(LARGE_CAP)].copy()
    print(f"分層前總 n={len(df)}；large(BTC/ETH) n={len(large_df)}；other(8標的) n={len(other_df)}")
    assert len(large_df) + len(other_df) == len(df), "分層切割遺漏樣本"

    rows_out = []
    run_group(large_df, "large(BTC,ETH)", SEED, rows_out)
    run_group(other_df, "other(8標的)", SEED + 1, rows_out)

    print("\n=== 對照：run1 全體 10 標的合併結果（供對比） ===")
    print("點估計 = +2.760pp, 95% CI [+2.138, +3.464]pp（來源：research/log/2026-08-01.md run1）")
    print("Q1' 逐週區塊 bootstrap（全體 10 標的）: 95% CI [+1.457, +4.112]pp（來源：run2）")

    out_path = Path(__file__).with_suffix("").as_posix() + "_result_table.tsv"
    pd.DataFrame(rows_out).to_csv(out_path, sep="\t", index=False)
    print(f"\n[write] 結果表已存至 {out_path}")


if __name__ == "__main__":
    main()
