"""Q1' 穩健性覆核（run 2，承接 Q1 最強反駁第 1 點）。

Q1（research/log/2026-08-01.md）用逐樣本 percentile bootstrap（2000 次，把 5450 筆
「去叢集後」樣本視為互相獨立）算出 24h p80 最低桶 vs 最高桶差距 95% CI [+2.138,+3.464]pp。
最強反駁指出：10 個標的在同一段宏觀 regime（例如全市場齊壓縮/齊放量的那幾週）可能高度
相關地落入相似的桶並產生相關的振幅，逐樣本重抽會把「幾個獨立的宏觀事件」誤當成 5450 個
獨立觀測，系統性低估 CI 寬度。

本檔**不換分桶、不換 T、不換標的、不換窗口**——只把重抽單位從「逐樣本」換成「逐週區塊」，
沿用同一份既有結果 2026-08-01_phase0_bbw_amplitude_samples.tsv（唯讀，不修改）。
這是 backlog.md Q1' 登記的穩健性覆核，非 frontier 兩階段閘門管轄範圍（同一分析、只改
重抽方法），也不是「換分桶/換T重跑」。

方法：block bootstrap by ISO 週——把每筆樣本按 ts 所屬的 ISO 週（跨標的共用同一週曆，
用來捕捉「全市場同週同 regime」的相關性）分組成 block；重抽時整塊週一起抽入或抽出，
塊內樣本的組內相關因此被保留，不會被錯誆成獨立觀測。分別對「最低桶」與「最高桶」的
週集合各自做 block bootstrap（兩桶樣本互斥，各自资抽自己的週塊即可，不需要成對抽樣）。
"""

from pathlib import Path

import numpy as np
import pandas as pd

SAMPLES_PATH = Path(__file__).parent / "2026-08-01_phase0_bbw_amplitude_samples.tsv"
LOWEST_BUCKET = "(0.0, 0.05)"
HIGHEST_BUCKET = "(0.75, 1.0)"
N_BOOT = 2000
SEED = 20260801


def block_bootstrap_quantile_diff(lo_df: pd.DataFrame, hi_df: pd.DataFrame, q: float, rng) -> np.ndarray:
    """對兩個互斥子集各自做『逐週區塊』重抽，回傳 N_BOOT 個 (hi_q - lo_q) 差距。"""
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


def main() -> None:
    df = pd.read_csv(SAMPLES_PATH, sep="\t", parse_dates=["ts"])
    df["week"] = df["ts"].dt.tz_convert("UTC").dt.strftime("%G-W%V")  # ISO 年-週，跨年正確

    lo_df = df[df["bucket"] == LOWEST_BUCKET]
    hi_df = df[df["bucket"] == HIGHEST_BUCKET]
    print(f"最低桶 {LOWEST_BUCKET}: n={len(lo_df)}, 涵蓋 {lo_df['week'].nunique()} 個 ISO 週")
    print(f"最高桶 {HIGHEST_BUCKET}: n={len(hi_df)}, 涵蓋 {hi_df['week'].nunique()} 個 ISO 週")

    # 每週有幾個標的落入該桶，粗略呈現「同週跨標的齊發」的集中程度（佐證最強反駁的前提）
    lo_per_week_pairs = lo_df.groupby("week")["pair"].nunique()
    hi_per_week_pairs = hi_df.groupby("week")["pair"].nunique()
    print(f"\n最低桶每週涉及標的數：mean={lo_per_week_pairs.mean():.2f}, "
          f"median={lo_per_week_pairs.median():.0f}, max={lo_per_week_pairs.max()}")
    print(f"最高桶每週涉及標的數：mean={hi_per_week_pairs.mean():.2f}, "
          f"median={hi_per_week_pairs.median():.0f}, max={hi_per_week_pairs.max()}")

    rng = np.random.default_rng(SEED)

    print(f"\n=== 24h p80 差距：逐週區塊 block bootstrap（{N_BOOT} 次重抽）===")
    diffs_p80 = block_bootstrap_quantile_diff(lo_df, hi_df, 0.80, rng)
    point_p80 = np.quantile(hi_df["amp_24h"], 0.80) - np.quantile(lo_df["amp_24h"], 0.80)
    ci_p80 = np.quantile(diffs_p80, [0.025, 0.975])
    print(f"點估計 = {point_p80*100:+.3f}pp, 95% CI [{ci_p80[0]*100:+.3f}, {ci_p80[1]*100:+.3f}]pp")

    print(f"\n=== 24h p50 差距：逐週區塊 block bootstrap（{N_BOOT} 次重抽，補充視角）===")
    rng2 = np.random.default_rng(SEED + 1)
    diffs_p50 = block_bootstrap_quantile_diff(lo_df, hi_df, 0.50, rng2)
    point_p50 = np.quantile(hi_df["amp_24h"], 0.50) - np.quantile(lo_df["amp_24h"], 0.50)
    ci_p50 = np.quantile(diffs_p50, [0.025, 0.975])
    print(f"點估計 = {point_p50*100:+.3f}pp, 95% CI [{ci_p50[0]*100:+.3f}, {ci_p50[1]*100:+.3f}]pp")

    print("\n=== 對照：原逐樣本 bootstrap（Q1 run1 原始結果，供對比）===")
    print("點估計 = +2.760pp, 95% CI [+2.138, +3.464]pp（來源：research/log/2026-08-01.md）")


if __name__ == "__main__":
    main()
