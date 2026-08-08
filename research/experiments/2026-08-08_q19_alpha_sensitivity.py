"""Q19 附錄（run 28）：Q10 唯一顯著格位對族系格位數 M 的敏感度。

動機是機械的、不是新假設：`docs/TRADEABILITY_PREREG.md` §3.2 明文
「M 只增不減、門檻只緊不鬆」。Q10 在 M=24（α_adj=0.05/24≈0.00208）下有 1 格通過
（`[0.10,0.25)` × 24h），落在 `docs/RND_BACKLOG.md` 方向二預寫的**結局②**。
若日後方向二累計更多格位，同一格會在某個 M 之後失去顯著 ⇒ 24 格全不顯著 ⇒ **結局①**。

⚠ 方向性：本檢查**只可能拿掉顯著性、不可能增加**，因此它只會讓 Q10 的否定結論更強
（結局② → 結局①），不是救活 Q10 的嘗試。經濟裁決（0.0886% < 0.28%）與本檢查無關，
兩種結局都不進 Phase 1。

作法：沿用 run 8 的 `block_boot`（逐 ISO 週 block bootstrap）與其 samples.tsv 的
`dR_24` 欄，只改信心水準。`n_boot=400,000`（run 13 §4.2 實測 20,000 對刀鋒格不 seed 穩定、
400,000 才收斂），三組 seed 併報。

用法：python research/experiments/2026-08-08_q19_alpha_sensitivity.py
"""

import numpy as np
import pandas as pd

SAMPLES = "research/experiments/2026-08-05_q10_shape_samples.tsv"
OUT = "research/experiments/2026-08-08_q19_alpha_sensitivity.tsv"
BUCKET, T_H = 2, 24                 # 頭條格位 [0.10,0.25) × 24h
N_BOOT, CHUNK = 400_000, 50_000
M_LIST = [24, 28, 29, 30, 36, 48, 60, 72, 96, 120]
SEEDS = [20260808, 990017, 424242]


def boot_means(vals, weeks, n_boot, seed):
    uw, inv = np.unique(weeks, return_inverse=True)
    nw = len(uw)
    ssum = np.bincount(inv, weights=vals, minlength=nw)
    scnt = np.bincount(inv, minlength=nw).astype(float)
    rng = np.random.default_rng(seed)
    out = []
    done = 0
    while done < n_boot:
        k = min(CHUNK, n_boot - done)
        idx = rng.integers(0, nw, size=(k, nw))
        out.append(ssum[idx].sum(axis=1) / scnt[idx].sum(axis=1))
        done += k
    return np.concatenate(out), nw


def main() -> int:
    sm = pd.read_csv(SAMPLES, sep="\t")
    sub = sm[sm["bucket"] == BUCKET].reset_index(drop=True)
    dr = sub[f"dR_{T_H}"].to_numpy()
    amp = sub[f"amp_{T_H}"].to_numpy()
    wk = sub["iso"].to_numpy()
    print(f"格位 [0.10,0.25) x {T_H}h：n={len(sub)}，dR 點估計={dr.mean():+.6f}，"
          f"E[A+B]={amp.mean()*100:.4f}%，cap={dr.mean()*amp.mean()*100:.4f}%")

    rows = []
    for seed in SEEDS:
        means, nw = boot_means(dr, wk, N_BOOT, seed)
        for M in M_LIST:
            a = 0.05 / M
            lo, hi = np.quantile(means, [a / 2, 1 - a / 2])
            rows.append({"seed": seed, "n_weeks": nw, "M": M, "alpha_adj": a,
                         "conf_pct": (1 - a) * 100, "dR_lo": lo, "dR_hi": hi,
                         "significant": bool(lo > 0)})
            print(f"  seed={seed} M={M:>4} α={a:.6f} conf={100*(1-a):.4f}%  "
                  f"dR CI=[{lo:+.6f},{hi:+.6f}]  {'顯著' if lo > 0 else '不顯著'}")
    df = pd.DataFrame(rows)
    df.to_csv(OUT, sep="\t", index=False)

    print("\n== 三組 seed 一致的臨界 M（顯著 → 不顯著）==")
    for M in M_LIST:
        s = df[df["M"] == M]["significant"]
        print(f"  M={M:>4}: 顯著 {int(s.sum())}/3 組 seed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
