#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Q16 / run22 第三步 — 把第一步的共變數項扣掉第二步量到的 H0 機械性偏差，
看**殘差**還有沒有能力威脅 `TRADEABILITY_PREREG.md` §3.3 的門檻。

⚠ 這是**指示性敏感度分析，不是宣告**。
第二步的 H0 是 iid 常態、無波動聚集、無厚尾、close-only（無 intrabar 高低），
**不是真實資料的校準虛無分佈**。真正校準的作法要拿每次翻轉的 `amp` 重算
`E_flip[R·amp]`，而 run8 的 `samples.tsv` 只存了 `mean(R_flip)`，沒存翻轉的 amp
⇒ 需要重跑 1m 路徑重建（見日誌「下次建議起點」與 backlog Q16）。

本步只回答一個有界的問題：**即使把 H0 偏差用最保守（＝最小）的方式扣，
殘差會不會越過 0.28% / 0.20% / 0.10%？**

用法
    python3 2026-08-07_q16_debias_sensitivity.py
"""

import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REAL = os.path.join(HERE, "2026-08-07_q16_cap_covariance.tsv")
H0 = os.path.join(HERE, "2026-08-07_q16_h0_placebo.tsv")
OUT = os.path.join(HERE, "2026-08-07_q16_debias.tsv")

THRESH = [("預登記 0.28%", 0.28), ("滑價歸零 0.20%", 0.20), ("去餘裕 0.10%", 0.10)]


def main():
    real = pd.read_csv(REAL, sep="\t")
    h0 = pd.read_csv(H0, sep="\t").set_index("T_h")

    # 尺度無關的比較量：cov / E[amp]（＝以「ΔR 當量」表達的共變數）
    real["cov_over_amp"] = real["cov_pct"] / real["amp_mean_pct"]
    real["h0_cov_over_amp"] = real["T_h"].map(h0["cov_over_amp"])
    real["h0_corr"] = real["T_h"].map(h0["corr_dR_amp"])

    # 機械性偏差的指示性估計（同 T 的 H0 比例 × 該格的 amp）
    real["bias_pct"] = real["h0_cov_over_amp"] * real["amp_mean_pct"]
    real["cov_residual_pct"] = real["cov_pct"] - real["bias_pct"]
    real["cap_debias_pct"] = real["cap_prod_pct"] + real["cov_residual_pct"]

    real.to_csv(OUT, sep="\t", index=False, float_format="%.10g")

    print("=== 尺度無關比較：真實 cov/E[amp] vs H0（iid）cov/E[amp] ===")
    print(f"{'bucket':<14}{'T':>4}{'real':>10}{'H0':>10}{'倍數':>8}"
          f"{'real_corr':>11}{'H0_corr':>9}")
    for _, r in real.iterrows():
        print(f"{r['bucket']:<14}{int(r['T_h']):>4}{r['cov_over_amp']:>10.4f}"
              f"{r['h0_cov_over_amp']:>10.4f}"
              f"{r['cov_over_amp'] / r['h0_cov_over_amp']:>8.2f}"
              f"{r['corr_dR_amp']:>11.4f}{r['h0_corr']:>9.4f}")

    print("\n=== 指示性去偏後的 cap（單位 %）===")
    print(f"{'bucket':<14}{'T':>4}{'run8 cap':>10}{'cap_pair':>10}"
          f"{'H0偏差':>9}{'殘差':>9}{'去偏cap':>10}")
    for _, r in real.iterrows():
        print(f"{r['bucket']:<14}{int(r['T_h']):>4}{r['cap_prod_pct']:>10.4f}"
              f"{r['cap_pair_pct']:>10.4f}{r['bias_pct']:>9.4f}"
              f"{r['cov_residual_pct']:>9.4f}{r['cap_debias_pct']:>10.4f}")

    print("\n=== 三個門檻 vs 各版本點估計的全網格最大值 ===")
    variants = [("run8 乘積式（預登記、H0 置中）", "cap_prod_pct"),
                ("配對式（H0 下有正偏，**無效**）", "cap_pair_pct"),
                ("指示性去偏（非宣告）", "cap_debias_pct")]
    for name, col in variants:
        m = float(real[col].max())
        arg = real.loc[real[col].idxmax()]
        flags = "  ".join(
            f"vs {lbl}: {'打不過' if m < v else '★超過'}" for lbl, v in THRESH)
        print(f"{name:<34} max={m:+.4f}% @ {arg['bucket']}×{int(arg['T_h'])}h   {flags}")

    print(f"\n殘差為正的格數: {int((real['cov_residual_pct'] > 0).sum())}/24")
    print(f"真實/H0 倍數範圍: {real['cov_over_amp'].div(real['h0_cov_over_amp']).min():.2f}"
          f" ~ {real['cov_over_amp'].div(real['h0_cov_over_amp']).max():.2f}")
    print(f"\n寫出 {OUT}")


if __name__ == "__main__":
    main()
