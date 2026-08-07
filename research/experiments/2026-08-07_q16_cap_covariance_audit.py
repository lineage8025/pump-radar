#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Q16 / run22 — audit：Q10 頭條數字 `cap = ΔR × E[A+B]` 的「上界」宣稱覆核。

背景
----
`docs/RND_BACKLOG.md` 方向二把可捕獲報酬換算登記為

    可捕獲報酬 ≈ ΔR × E[A + B]          （明文：「這是上界，不是策略收益」）

run8 照這個字面公式算出全網格最大 0.0886%，據此判 `weakens`（結局②）。
run13（Q13）與 run18（Q14）兩輪稽核驗的都是「照這個公式算，數字對不對」，
**沒有人驗過這個公式是不是它自稱的那個東西**。

疑點（純算術）
--------------
`ΔR × E[A+B]` 是**平均數的乘積**（marginal means）。逐 episode 的對應量是

    cap_pair = E[ ΔR_i · amp_i ]
             = E[ΔR_i]·E[amp_i] + Cov(ΔR_i, amp_i)
             = cap_prod          + Cov

其中 `ΔR_i·amp_i = max(A,B)_i − R_flip,i·amp_i`，即該 episode 相對隨機符號翻轉
基準的「主導側超額行程」。**Cov 這一項從未被計算過。**
有理由預期 Cov > 0（整段漂移大的 episode 同時有大 amp 與高 R_act），
若如此則預登記公式**低估**可捕獲報酬，Q10 的否定結論比宣稱的更不安全。

本腳本只做這件事，不新增任何分桶／T／標的／窗口，[cells=0]（audit 車道）。

輸入
----
`research/experiments/2026-08-05_q10_shape_samples.tsv`（run8 產出，已 commit）
`research/experiments/2026-08-05_q10_shape_grid.tsv`  （run8 產出，用於逐位元對拍）

用法
----
    python3 2026-08-07_q16_cap_covariance_audit.py --self-test
    python3 2026-08-07_q16_cap_covariance_audit.py --boot 20000 --out-prefix <prefix>
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, "2026-08-05_q10_shape_samples.tsv")
GRID = os.path.join(HERE, "2026-08-05_q10_shape_grid.tsv")

# 凍結網格（一字沿用 research/program.md §4 / RND_BACKLOG 方向二，不得增刪）
BUCKET_LABELS = [
    "[0,0.05)", "[0.05,0.10)", "[0.10,0.25)",
    "[0.25,0.50)", "[0.50,0.75)", "[0.75,1.0]",
]
T_HOURS = [1, 4, 12, 24]
N_CELLS = len(BUCKET_LABELS) * len(T_HOURS)   # 24
ALPHA_ADJ = 0.05 / N_CELLS                    # ≈ 0.00208（方向二累計 M=24）

# 預登記門檻（TRADEABILITY_PREREG.md §3.3）與兩個更寬鬆的敏感度版本
THRESH_PREREG = 0.28   # 2 × 來回成本 0.14%
THRESH_NOSLIP = 0.20   # 滑價歸零：2 × (2 × taker 0.05%)
THRESH_BARE = 0.10     # 再拿掉 2 倍餘裕：來回 taker only


# ----------------------------------------------------------------------------
# 核心統計
# ----------------------------------------------------------------------------
def cell_stats(dr, amp):
    """回傳 (cap_prod, cap_pair, cov, corr)。單位為比例（非 %）。"""
    n = len(dr)
    cap_prod = float(dr.mean()) * float(amp.mean())
    cap_pair = float((dr * amp).mean())
    cov = cap_pair - cap_prod          # ＝ 母體共變數（用 /n 而非 /(n-1)）
    if n < 2 or dr.std() == 0 or amp.std() == 0:
        corr = float("nan")
    else:
        corr = float(np.corrcoef(dr, amp)[0, 1])
    return cap_prod, cap_pair, cov, corr


def week_aggregates(week_ids, dr, amp):
    """把 episode 依 ISO 週聚成塊，回傳 block bootstrap 需要的每週小計。"""
    uniq, inv = np.unique(week_ids, return_inverse=True)
    k = len(uniq)
    s_n = np.bincount(inv, minlength=k).astype(np.float64)
    s_dr = np.bincount(inv, weights=dr, minlength=k)
    s_amp = np.bincount(inv, weights=amp, minlength=k)
    s_prod = np.bincount(inv, weights=dr * amp, minlength=k)
    return s_n, s_dr, s_amp, s_prod


def block_bootstrap(s_n, s_dr, s_amp, s_prod, boot, rng):
    """逐 ISO 週 block bootstrap（沿用 run8 預登記口徑）。

    回傳 (cap_prod_boot, cap_pair_boot)，皆為長度 boot 的陣列（比例單位）。
    """
    k = len(s_n)
    idx = rng.integers(0, k, size=(boot, k))
    tot_n = s_n[idx].sum(axis=1)
    tot_dr = s_dr[idx].sum(axis=1)
    tot_amp = s_amp[idx].sum(axis=1)
    tot_prod = s_prod[idx].sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        cap_prod = (tot_dr / tot_n) * (tot_amp / tot_n)
        cap_pair = tot_prod / tot_n
    return cap_prod, cap_pair


def ci(arr, alpha):
    lo = float(np.nanpercentile(arr, 100.0 * alpha / 2.0))
    hi = float(np.nanpercentile(arr, 100.0 * (1.0 - alpha / 2.0)))
    return lo, hi


# ----------------------------------------------------------------------------
# self-test（合成資料，已知答案）
# ----------------------------------------------------------------------------
def self_test():
    ok = True
    rng = np.random.default_rng(20260807)

    # 1) 零共變數：dr 與 amp 獨立 ⇒ cap_pair ≈ cap_prod
    n = 200000
    dr = rng.normal(0.01, 0.05, n)
    amp = rng.gamma(3.0, 0.02, n)
    cp, cpair, cov, corr = cell_stats(dr, amp)
    print(f"[test1] 獨立情形 cov={cov:.3e} corr={corr:+.4f} (應 ≈0)")
    ok &= abs(cov) < 1e-5 and abs(corr) < 0.02

    # 2) 已知正共變數：dr = a + b*amp ⇒ Cov = b*Var(amp)
    b = 0.5
    amp2 = rng.gamma(3.0, 0.02, n)
    dr2 = 0.01 + b * amp2
    cp2, cpair2, cov2, corr2 = cell_stats(dr2, amp2)
    expect = b * float(amp2.var())
    print(f"[test2] 線性情形 cov={cov2:.6e} 期望={expect:.6e} corr={corr2:+.4f} (應 =1)")
    ok &= abs(cov2 - expect) < 1e-12 and abs(corr2 - 1.0) < 1e-12

    # 3) 恆等式 cap_pair = cap_prod + cov（浮點層級）
    ok &= abs((cp2 + cov2) - cpair2) < 1e-15
    print(f"[test3] 恆等式 |cap_prod+cov−cap_pair| = {abs((cp2+cov2)-cpair2):.3e}")

    # 4) 逐 episode 恆等式 ΔR_i·amp_i = max(A,B)_i − R_flip,i·amp_i
    #    （用 R_act 定義直接驗：R_act·amp = max(A,B)）
    A = rng.gamma(2.0, 0.01, 1000)
    B = rng.gamma(2.0, 0.01, 1000)
    ampx = A + B
    ract = np.maximum(A, B) / ampx
    rflip = rng.uniform(0.6, 0.9, 1000)
    lhs = (ract - rflip) * ampx
    rhs = np.maximum(A, B) - rflip * ampx
    d4 = float(np.max(np.abs(lhs - rhs)))
    print(f"[test4] 逐episode恆等式 max|Δ| = {d4:.3e}")
    ok &= d4 < 1e-15

    # 5) block bootstrap 在單一大週塊、boot 足量時應收斂到點估計
    wid = np.array(["W%02d" % (i % 50) for i in range(n)])
    s_n, s_dr, s_amp, s_prod = week_aggregates(wid, dr, amp)
    bp, bpair = block_bootstrap(s_n, s_dr, s_amp, s_prod, 2000,
                                np.random.default_rng(7))
    d5 = abs(float(np.mean(bpair)) - cpair)
    print(f"[test5] bootstrap均值 vs 點估計 |Δ| = {d5:.3e}")
    ok &= d5 < 1e-4

    # 6) 符號翻轉不變性（TRADEABILITY_PREREG §1.3）：A↔B 互換後 R、amp、
    #    因而 ΔR·amp 逐位元不變
    ract_m = np.maximum(B, A) / (B + A)
    d6 = float(np.max(np.abs(ract_m - ract)))
    print(f"[test6] A↔B互換後 R_act max|Δ| = {d6:.3e} (§1.3 鏡射不變性)")
    ok &= d6 == 0.0

    print("SELF-TEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--boot", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=20260807)
    ap.add_argument("--out-prefix", default=os.path.join(HERE, "2026-08-07_q16"))
    args = ap.parse_args()

    if args.self_test:
        sys.exit(self_test())

    df = pd.read_csv(SAMPLES, sep="\t")
    grid8 = pd.read_csv(GRID, sep="\t")
    print(f"samples: {len(df)} 列, {df['pair'].nunique()} 標的, "
          f"{df['iso'].nunique()} ISO 週")

    rng = np.random.default_rng(args.seed)
    rows = []
    for bi, blab in enumerate(BUCKET_LABELS):
        sub = df[df["bucket"] == bi]
        for T in T_HOURS:
            dr = sub[f"dR_{T}"].to_numpy(dtype=np.float64)
            drm = sub[f"dRm_{T}"].to_numpy(dtype=np.float64)
            amp = sub[f"amp_{T}"].to_numpy(dtype=np.float64)
            wid = sub["iso"].to_numpy()
            n = len(dr)

            cap_prod, cap_pair, cov, corr = cell_stats(dr, amp)
            # 鏡射版（run8 §1.3 第二種量法，只用來取保守者，不另計格位）
            capm_prod, capm_pair, covm, _ = cell_stats(drm, amp)

            s_n, s_dr, s_amp, s_prod = week_aggregates(wid, dr, amp)
            bprod, bpair = block_bootstrap(s_n, s_dr, s_amp, s_prod,
                                           args.boot, rng)
            lo95, hi95 = ci(bpair, 0.05)
            loADJ, hiADJ = ci(bpair, ALPHA_ADJ)
            lo95p, hi95p = ci(bprod, 0.05)
            loADJp, hiADJp = ci(bprod, ALPHA_ADJ)

            # 與 run8 grid.tsv 對拍（cap_prod 應逐位元重現）
            g = grid8[(grid8["bucket"] == blab) & (grid8["T_h"] == T)]
            run8_cap = float(g["cap_pct"].iloc[0]) if len(g) else float("nan")
            run8_n = int(g["n"].iloc[0]) if len(g) else -1

            rows.append(dict(
                bucket=blab, T_h=T, n=n, run8_n=run8_n,
                dR_mean=float(dr.mean()), amp_mean_pct=float(amp.mean()) * 100.0,
                cap_prod_pct=cap_prod * 100.0,
                run8_cap_pct=run8_cap,
                cap_prod_vs_run8=cap_prod * 100.0 - run8_cap,
                cap_pair_pct=cap_pair * 100.0,
                cov_pct=cov * 100.0,
                ratio_pair_over_prod=(cap_pair / cap_prod) if cap_prod != 0 else float("nan"),
                corr_dR_amp=corr,
                capm_pair_pct=capm_pair * 100.0,
                cap_pair_consv_pct=min(cap_pair, capm_pair) * 100.0,
                pair_lo95_pct=lo95 * 100.0, pair_hi95_pct=hi95 * 100.0,
                pair_loADJ_pct=loADJ * 100.0, pair_hiADJ_pct=hiADJ * 100.0,
                prod_lo95_pct=lo95p * 100.0, prod_hi95_pct=hi95p * 100.0,
                prod_loADJ_pct=loADJp * 100.0, prod_hiADJ_pct=hiADJp * 100.0,
                n_weeks=len(s_n),
            ))

    out = pd.DataFrame(rows)
    tsv = f"{args.out_prefix}_cap_covariance.tsv"
    out.to_csv(tsv, sep="\t", index=False, float_format="%.10g")
    print(f"\n寫出 {tsv}")

    # ---- 對拍 ----
    d = np.max(np.abs(out["cap_prod_vs_run8"].to_numpy()))
    print(f"\n[對拍] cap_prod vs run8 grid.tsv cap_pct: max|Δ| = {d:.3e} (pp)")
    print(f"[對拍] n 與 run8 一致: {bool((out['n'] == out['run8_n']).all())}")

    # ---- 主表 ----
    print("\n=== 24 格：乘積式 vs 逐 episode 配對式（單位 %）===")
    print(f"{'bucket':<14}{'T':>4}{'n':>6}{'cap_prod':>11}{'cap_pair':>11}"
          f"{'cov':>11}{'pair/prod':>11}{'corr':>9}")
    for _, r in out.iterrows():
        print(f"{r['bucket']:<14}{int(r['T_h']):>4}{int(r['n']):>6}"
              f"{r['cap_prod_pct']:>11.4f}{r['cap_pair_pct']:>11.4f}"
              f"{r['cov_pct']:>11.4f}{r['ratio_pair_over_prod']:>11.3f}"
              f"{r['corr_dR_amp']:>9.4f}")

    # ---- 判定 ----
    print("\n=== 判定：三個門檻 vs 配對式 cap ===")
    for name, col in [("點估計 cap_pair", "cap_pair_pct"),
                      ("未調整 95% CI 上界", "pair_hi95_pct"),
                      ("Bonferroni 調整 CI 上界", "pair_hiADJ_pct")]:
        m = float(out[col].max())
        arg = out.loc[out[col].idxmax()]
        print(f"{name:<28} 全網格最大 = {m:+.4f}%  @ {arg['bucket']} × T={int(arg['T_h'])}h"
              f"   | vs 0.28%: {'打不過' if m < THRESH_PREREG else '★超過'}"
              f"  vs 0.20%: {'打不過' if m < THRESH_NOSLIP else '★超過'}"
              f"  vs 0.10%: {'打不過' if m < THRESH_BARE else '★超過'}")

    # run8 對照
    print(f"\n[run8 原版] cap_prod 全網格最大 = {float(out['cap_prod_pct'].max()):+.4f}%，"
          f"調整後 CI 上界最大 = {float(out['prod_hiADJ_pct'].max()):+.4f}%")
    print(f"[本輪 配對版] cap_pair 全網格最大 = {float(out['cap_pair_pct'].max()):+.4f}%，"
          f"調整後 CI 上界最大 = {float(out['pair_hiADJ_pct'].max()):+.4f}%")
    print(f"\ncov 為正的格數: {int((out['cov_pct'] > 0).sum())}/24；"
          f"corr(ΔR,amp) 為正的格數: {int((out['corr_dR_amp'] > 0).sum())}/24")
    print(f"cov 絕對值最大 = {float(out['cov_pct'].abs().max()):.4f}pp")


if __name__ == "__main__":
    main()
