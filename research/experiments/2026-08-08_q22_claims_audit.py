#!/usr/bin/env python3
"""Q22 — CLAUDE.md 2026-08-08「結算」段中與 Q10 有關之宣稱的內部一致性稽核。

車道 audit，[cells=0]：本腳本**不計算任何新的分桶 × T × 參數組合**，
只讀 run8 已凍結的 24 格輸出表（`2026-08-05_q10_shape_grid.tsv`）並做算術核對。
方向二累計格位數 M 維持 24，不因本輪增加。

檢查項：
  A. 「經濟門檻差一個數量級」——對 cap 點估計與 CI 上界兩種讀法各自檢定。
  B. cap = dR x E[A+B] 由原始欄位重算，對 run8 自己寫下的 cap_pct 欄逐格比對。
  C. 三個成本門檻版本（0.28% 預登記 / 0.20% 滑價歸零 / 0.10% 去餘裕）的比值表。

資料窗口：不抓取任何新資料。輸入是 run8 的產物，其窗口為
2023-01-01~2025-06-30（暖機 2022-12），未觸碰 TRADEABILITY_PREREG §4 封存段。
"""
import math
import pathlib

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
GRID = HERE / "2026-08-05_q10_shape_grid.tsv"
OUT = HERE / "2026-08-08_q22_claims_audit.tsv"

# TRADEABILITY_PREREG.md §3.3 預登記門檻，以及 run8 日誌 §10 反駁 3 用過的兩個變體
THRESHOLDS = {
    "prereg_0.28": 0.28,   # 2 x 來回總成本 0.14%
    "zero_slip_0.20": 0.20,  # 滑價歸零：2 x 2 x taker 0.05%
    "no_margin_0.10": 0.10,  # 再拿掉 2 倍餘裕
}

def main() -> None:
    g = pd.read_csv(GRID, sep="\t")
    assert len(g) == 24, f"凍結網格應為 24 格，實得 {len(g)}"

    # --- B. cap 由原始欄位重算，對 run8 自己的 cap_pct 欄比對 -------------
    cap_recomputed = g["dR"] * g["amp_mean_pct"]
    max_abs_diff = float((cap_recomputed - g["cap_pct"]).abs().max())

    rows = []
    cap_max = float(g["cap_pct"].max())
    cap_max_cell = g.loc[g["cap_pct"].idxmax()]
    hiadj_max = float(g["cap_hiADJ_pct"].max())
    hiadj_max_cell = g.loc[g["cap_hiADJ_pct"].idxmax()]
    hi95_max = float(g["cap_hi95_pct"].max())

    # --- A/C. 三個門檻 x 三種讀法的比值 -----------------------------------
    readings = {
        "cap_point_max": cap_max,          # 點估計（run8 頭條數字）
        "cap_hi95_max": hi95_max,          # 未調整 95% CI 上界
        "cap_hiADJ_max": hiadj_max,        # Bonferroni 調整後 CI 上界（最保守）
    }
    for rname, rval in readings.items():
        for tname, tval in THRESHOLDS.items():
            ratio = tval / rval
            rows.append({
                "reading": rname,
                "reading_pct": round(rval, 6),
                "threshold": tname,
                "threshold_pct": tval,
                "ratio_threshold_over_cap": round(ratio, 4),
                "log10_ratio": round(math.log10(ratio), 4),
                "is_one_order_of_magnitude": bool(ratio >= 10.0),
            })

    out = pd.DataFrame(rows)
    out.to_csv(OUT, sep="\t", index=False)

    print("=== B. cap 欄重算核對（dR x amp_mean_pct vs run8 的 cap_pct 欄）===")
    print(f"24 格 max|Δ| = {max_abs_diff:.3e} pp")
    print()
    print("=== A. 全網格最大值（run8 凍結 24 格）===")
    print(f"cap 點估計最大      : {cap_max:.4f}%  @ {cap_max_cell['bucket']} x {int(cap_max_cell['T_h'])}h (n={int(cap_max_cell['n'])})")
    print(f"cap 未調整 CI 上界最大: {hi95_max:.4f}%")
    print(f"cap 調整後 CI 上界最大: {hiadj_max:.4f}%  @ {hiadj_max_cell['bucket']} x {int(hiadj_max_cell['T_h'])}h")
    print()
    print("=== C. 門檻 / cap 比值（>=10 才叫「差一個數量級」）===")
    print(out.to_string(index=False))
    print()
    print("=== 附：24 格 cap 點估計降序前 5（供人工覆核）===")
    top = g.sort_values("cap_pct", ascending=False)[
        ["bucket", "T_h", "n", "dR", "amp_mean_pct", "cap_pct", "cap_hiADJ_pct"]
    ].head(5)
    print(top.to_string(index=False))
    print(f"\n輸出：{OUT}")


if __name__ == "__main__":
    main()
