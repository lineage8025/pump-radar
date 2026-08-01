"""Q3 audit（2026-08-01 run 1）：DETECTOR_PREREG.md 樣本內基準能否用
data/insample_scored.tsv 逐筆重算出來。只覆核既有主張，不修正、不新增結論。
兩份檔案對本迴圈皆唯讀，本檔只讀取不寫入。
"""

import pandas as pd

df = pd.read_csv("data/insample_scored.tsv", sep="\t")
ORIGINAL_4 = {"BTC/USDT", "ETH/USDT", "ADA/USDT", "SOL/USDT"}

print(f"總列數: {len(df)}（DETECTOR_PREREG 補充表宣稱 235）")
print(f"A/B 級列數: A={len(df[df.grade=='A'])} B={len(df[df.grade=='B'])}"
      f"（宣稱 A=64 B=171）")

print("\n--- 原始 4 標的子集（BTC/ETH/ADA/SOL），對照『樣本內基準』表 ---")
sub4 = df[df["pair"].isin(ORIGINAL_4)]
print(f"子集列數: {len(sub4)}（宣稱 107 事件）")
net = sub4["net_24h"].dropna()
print(f"net_24h: mean {net.mean()*100:+.2f}%  median {net.median()*100:+.2f}%  "
      f"win {(net>0).mean()*100:.0f}%  n={len(net)}"
      f"（宣稱 mean -0.31% median -0.36% win 39% n=102）")
netA = sub4.loc[sub4.grade == "A", "net_24h"].dropna()
print(f"net_24h A級: mean {netA.mean()*100:+.2f}%  win {(netA>0).mean()*100:.0f}%  n={len(netA)}"
      f"（宣稱 mean -0.27% win 36% n=28）")
mfe = sub4["mfe_24h"].dropna()
mae = sub4["mae_24h"].dropna()
print(f"mfe_24h mean {mfe.mean()*100:+.2f}%（宣稱 +1.81%）  "
      f"mae_24h mean {mae.mean()*100:+.2f}%（宣稱 -2.12%）")

print("\n--- 全 10 標的（235 事件），對照『全10標的分級分佈』表 ---")
for g, nA in [("A", 64), ("B", 171)]:
    s = df[df.grade == g]
    mfe_med = s["mfe_24h"].median() * 100
    mae_med = s["mae_24h"].median() * 100
    net_med = s["net_24h"].median() * 100
    win = (s["net_24h"].dropna() > 0).mean() * 100
    mfe_ge2 = (s["mfe_24h"] >= 0.02).mean() * 100
    mae_le3 = (s["mae_24h"] <= -0.03).mean() * 100
    print(f"{g}級(n={len(s)}, 宣稱{nA}): MFE中位 {mfe_med:+.2f}%(宣稱見文件) "
          f"MAE中位 {mae_med:+.2f}%  net_24h中位 {net_med:+.2f}%/勝率{win:.0f}% "
          f"MFE>=2%佔比{mfe_ge2:.0f}% MAE<=-3%佔比{mae_le3:.0f}%")
