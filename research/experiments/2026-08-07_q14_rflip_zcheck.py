#!/usr/bin/env python3
"""Q14 附屬分析：逐格 `R_flip` 差異（本輪 3 seed 平均 − run 8 單一 seed）的統計檢查。

為什麼需要這一支：run18 日誌 §6 預先寫死的判準是「逐格 |R_flip 差| 落在 4 × se_MC 內」，
但那個 `se_MC` 只涵蓋**我自己 3 個 seed 平均**的蒙地卡羅誤差，
**漏掉了 run 8 自己那一個 seed 的蒙地卡羅誤差**——而後者是兩者中較大的一項
（單一 seed 的誤差 ≈ 3 seed 平均的 √3 倍）。判準寫得太緊，這是我的規格錯誤，照實修正並雙報。

正確的比較誤差：`sd(diff) = sqrt(se_mine² + se_run8²)`，
其中 `se_run8 = sd_ep/√n`、`se_mine = sd_ep/√(3n)`，`sd_ep` ＝逐 episode 的
`R_flip` 蒙地卡羅標準差（由本輪 3 個 seed 的逐 episode 值估計，
每個 episode 只有 2 個自由度，但在格位內對數百~數千個 episode 匯總後非常精確）。
"""

import math
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
MC = HERE / "2026-08-07_q14_rflip_mc.tsv"
OUT = HERE / "2026-08-07_q14_rflip_zcheck.tsv"

T_HOURS = [1, 4, 12, 24]
SEED_COLS = ["pcg6420260807", "pcg64990017", "philox424242"]
BUCKET_LABELS = ["[0,0.05)", "[0.05,0.10)", "[0.10,0.25)", "[0.25,0.50)",
                 "[0.50,0.75)", "[0.75,1.0]"]

mc = pd.read_csv(MC, sep="\t")
rows = []
for b in range(6):
    sub = mc[mc["bucket"] == b]
    for th in T_HOURS:
        vals = np.stack([sub[f"R_flip_{c}_{th}"].to_numpy() for c in SEED_COLS])
        # 逐 episode 的 seed 間變異數（ddof=1，2 自由度）→ 格位內平均後得 sd_ep²
        var_ep = vals.var(axis=0, ddof=1)
        sd_ep = math.sqrt(var_ep.mean())
        n = len(sub)
        se_mine = sd_ep / math.sqrt(3 * n)
        se_run8 = sd_ep / math.sqrt(n)
        diff = float(vals.mean(axis=0).mean() - sub[f"R_flip_run8_{th}"].mean())
        sd_diff = math.hypot(se_mine, se_run8)
        rows.append({"bucket": BUCKET_LABELS[b], "T_h": th, "n": n,
                     "sd_ep": sd_ep, "se_mine": se_mine, "se_run8": se_run8,
                     "diff": diff, "sd_diff": sd_diff, "z": diff / sd_diff})

d = pd.DataFrame(rows)
d.to_csv(OUT, sep="\t", index=False)
print(d.to_string(index=False, float_format=lambda v: f"{v: .3e}"))
print(f"\n|z| 的分佈：max={d['z'].abs().max():.2f}  "
      f"mean={d['z'].mean():+.3f}  sd={d['z'].std(ddof=1):.3f}")
for k in (2, 3, 4):
    print(f"  |z| > {k}：{int((d['z'].abs() > k).sum())}/24"
          f"（標準常態下期望 {24 * 2 * (1 - 0.5 * (1 + math.erf(k / math.sqrt(2)))):.2f}）")
print(f"  z > 0：{int((d['z'] > 0).sum())}/24（無系統性偏移應 ≈12）")
print("\n逐 T 的 z 均值（檢查是否有 T 維度的系統性）：")
print(d.groupby("T_h")["z"].agg(["mean", "std", "count"]).to_string())
