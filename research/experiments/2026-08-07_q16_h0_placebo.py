#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Q16 / run22 第二步 — **對自己的發現做證偽**：
`E[ΔR_i · amp_i]` 這個統計量，在虛無假設 H0（報酬符號可交換）下期望值是不是 0？

為什麼要問
----------
第一步（`2026-08-07_q16_cap_covariance_audit.py`）量到 `Cov(ΔR_i, amp_i)` 在
凍結網格 24 格**全為正**，而且量級大於 run8 的乘積式點估計本身。
表面上這像是「預登記公式低估了可捕獲報酬」。

但在下結論之前必須先排除一個機械性解釋：

    ΔR_i = R_act,i − mean_flip(R)   對符號抽取而言是**中心化**的（H0 下 E=0），
    這正是 run8 的隨機化檢定有效的原因。
    但 amp_i = A_i + B_i **本身也是符號序列的函數**——
    固定 |r_i| 序列時，符號一致（趨勢）的實現值 range 大，
    符號來回（震盪）的實現值 range 小。
    ⇒ 在**同一個 episode 的翻轉系綜內**，R 與 amp 就已經正相關。
    ⇒ 因此 E[ΔR_i · amp_i] 在 H0 下**不是 0，而是正的**。

若如此，`cap_pair` 是一個在 H0 下就有正偏的統計量，
第一步量到的共變數**不是可捕獲的東西**，預登記的乘積式才是正確的那一個。

作法
----
純合成 iid 常態報酬（H0 為真，定義上沒有任何可捕獲結構），
完整重現 run8 的量法：每個 episode 對同一條 |r| 序列做 200 次隨機符號翻轉，
`ΔR = R_act − mean(R_flip)`，再算 `Cov(ΔR_i, amp_i)` 與 `corr(ΔR_i, amp_i)`。

若合成 H0 下的 `corr` 與真實資料（0.094 ~ 0.273）同量級 ⇒ 機械性偽影，證偽第一步的表象。

用法
----
    python3 2026-08-07_q16_h0_placebo.py --episodes 2000 --flips 200
"""

import argparse
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))

# 對應凍結網格的四個 T（1m 根數）
T_STEPS = {1: 60, 4: 240, 12: 720, 24: 1440}


def r_and_amp_from_paths(cum):
    """cum: (m, L) 對數累積路徑（相對 P0=0）。回傳 (R, amp)。

    沿用 run8 §4 決定 3：A/B 在價格空間，A = exp(max)−1、B = 1−exp(min)，
    並依定義夾在 ≥0（run8 的 A/B 夾零處理）。
    """
    mx = np.maximum(cum.max(axis=1), 0.0)
    mn = np.minimum(cum.min(axis=1), 0.0)
    A = np.exp(mx) - 1.0
    B = 1.0 - np.exp(mn)
    amp = A + B
    R = np.where(amp > 0, np.maximum(A, B) / np.where(amp > 0, amp, 1.0), 1.0)
    return R, amp


def run_h0(n_ep, L, flips, sigma, rng, batch=25):
    """回傳每個 episode 的 (R_act, amp_act, R_flip_mean)。"""
    R_act = np.empty(n_ep)
    amp_act = np.empty(n_ep)
    R_flip = np.empty(n_ep)

    done = 0
    while done < n_ep:
        b = min(batch, n_ep - done)
        # |r| 序列（H0：符號與大小獨立）
        r = rng.normal(0.0, sigma, size=(b, L))
        cum = np.cumsum(r, axis=1)
        Ra, aa = r_and_amp_from_paths(cum)
        R_act[done:done + b] = Ra
        amp_act[done:done + b] = aa

        absr = np.abs(r).astype(np.float32)
        for j in range(b):
            eps = rng.integers(0, 2, size=(flips, L)).astype(np.float32) * 2.0 - 1.0
            cf = np.cumsum(eps * absr[j][None, :], axis=1)
            Rf, _ = r_and_amp_from_paths(cf.astype(np.float64))
            R_flip[done + j] = Rf.mean()
        done += b
    return R_act, amp_act, R_flip


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=2000)
    ap.add_argument("--flips", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20260807)
    ap.add_argument("--out", default=os.path.join(HERE, "2026-08-07_q16_h0_placebo.tsv"))
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    rows = []
    for T, L in T_STEPS.items():
        # sigma 取成讓 24h 振幅落在真實資料量級（~5%），純為可比性，不影響 corr
        sigma = 0.05 / (1.6 * np.sqrt(1440))
        Ra, amp, Rf = run_h0(args.episodes, L, args.flips, sigma, rng)
        dR = Ra - Rf
        cov = float((dR * amp).mean() - dR.mean() * amp.mean())
        corr = float(np.corrcoef(dR, amp)[0, 1])
        cap_prod = float(dR.mean() * amp.mean())
        cap_pair = float((dR * amp).mean())
        # H0 下 ΔR 的標準誤（用來確認 ΔR 本身確實 ≈0）
        se_dr = float(dR.std(ddof=1) / np.sqrt(len(dR)))
        rows.append(dict(
            T_h=T, L_steps=L, n_ep=args.episodes, flips=args.flips,
            dR_mean=float(dR.mean()), dR_se=se_dr, dR_z=float(dR.mean() / se_dr),
            amp_mean_pct=float(amp.mean()) * 100.0,
            cap_prod_pct=cap_prod * 100.0,
            cap_pair_pct=cap_pair * 100.0,
            cov_pct=cov * 100.0,
            corr_dR_amp=corr,
            cov_over_amp=cov / float(amp.mean()),
        ))
        print(f"T={T:>2}h L={L:>4}  ΔR={dR.mean():+.5f} (z={dR.mean()/se_dr:+.2f})  "
              f"amp={amp.mean()*100:.3f}%  cap_prod={cap_prod*100:+.4f}%  "
              f"cap_pair={cap_pair*100:+.4f}%  cov={cov*100:+.4f}pp  "
              f"corr={corr:+.4f}  cov/amp={cov/amp.mean():+.5f}")

    out = pd.DataFrame(rows)
    out.to_csv(args.out, sep="\t", index=False, float_format="%.10g")
    print(f"\n寫出 {args.out}")
    print("\n判讀：H0 為真（iid、無任何可捕獲結構）。")
    print("  若 ΔR ≈ 0 但 cov / corr 明顯 > 0 ⇒ `E[ΔR·amp]` 在 H0 下有正偏，")
    print("  ⇒ 第一步量到的共變數是機械性偽影，預登記的乘積式才是正確的統計量。")


if __name__ == "__main__":
    main()
