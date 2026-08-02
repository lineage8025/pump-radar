"""Q2''（run 5，2026-08-02）補充：**直接切延長樣本**的時期分層版本。

`research/program.md` §4.2 第 3 條原文是「把延長後的樣本切成原窗口期與新增期兩段獨立重算」。
主探針（`2026-08-02_q2doubleprime_extended_window.py`）的作法是**各窗口獨立重跑去叢集掃描**
（P1 從 2023-01-01 起掃、ORIG 從 2025-01-01 起掃）。本檔補上另一種同樣合乎該條文字的作法：
**只切 EXT 那一次掃描的樣本**，不重掃。

為什麼兩種作法會不同（本次運行發現的資料特性，非事後找理由）：
去叢集是「索引 +96 根」的貪婪步進，而候選列在分析窗內是連續的，因此取樣點退化成
**每個標的每天一筆、固定同一個 UTC 時刻**（不是隨機時點）。10 個標的的 2023-03-24
12:45~13:45 UTC 各缺 5 根 K 棒（交易所端同時缺，非抓取失敗），該缺口把索引步進的相位
從 00:00 推移到 01:15。於是：
  - P1（2023-01~2024-12）：兩種作法完全相同（同起點、同相位）。
  - 原窗口：獨立重掃 = 00:00 相位；切 EXT 樣本 = 01:15 相位。
兩者相減即「取樣相位（起算時刻）」對結論的影響量，是一個免費的敏感度檢查。

只讀主探針產出的 TSV，不重抽資料、不改分桶／T／度量／去叢集／標的。
"""

import sys
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
STEM_MAIN = HERE / "2026-08-02_q2doubleprime_extended_window"
BUCKETS = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.25), (0.25, 0.50), (0.50, 0.75), (0.75, 1.0)]
HORIZONS = ["1h", "4h", "12h", "24h"]
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")
N_BOOT = 2000
SEED = 20260802


def label(b):
    lo, hi = b
    return f"[{lo:.2f},{hi:.2f}]" if hi == 1.0 else f"[{lo:.2f},{hi:.2f})"


def sub_seed(*parts):
    return SEED + zlib.crc32("|".join(str(x) for x in parts).encode()) % 100000


def weeks(sub, col):
    return sub.groupby("week")[col].apply(lambda s: s.to_numpy()).to_numpy(dtype=object)


def block_boot(a_df, b_df, col, q, rng, n_boot=N_BOOT):
    a_w, b_w = weeks(a_df, col), weeks(b_df, col)
    out = np.empty(n_boot)
    for k in range(n_boot):
        a_s = np.concatenate([a_w[i] for i in rng.integers(0, len(a_w), size=len(a_w))])
        b_s = np.concatenate([b_w[i] for i in rng.integers(0, len(b_w), size=len(b_w))])
        out[k] = np.quantile(b_s, q) - np.quantile(a_s, q)
    return out


def main():
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)

    s = pd.read_csv(f"{STEM_MAIN}_samples_EXT.tsv", sep="\t", parse_dates=["ts"])
    s["week"] = s["ts"].dt.tz_convert("UTC").dt.strftime("%G-W%V")
    e = pd.read_csv(f"{STEM_MAIN}_events_EXT.tsv", sep="\t", parse_dates=["ts"])
    e["week"] = e["ts"].dt.tz_convert("UTC").dt.strftime("%G-W%V")

    print("=== 取樣時刻分佈（證明去叢集退化成固定日格點，非隨機時點）===")
    print("EXT 樣本：", s["ts"].dt.strftime("%H:%M").value_counts().to_dict())
    print("EXT 事件：涵蓋", e["ts"].dt.hour.nunique(), "個不同 UTC 小時，"
          "前三多的小時 =", e["ts"].dt.hour.value_counts().head(3).to_dict())

    segs = [("EXT_P1(2023-01~2024-12)", s[s.ts < SPLIT], e[e.ts < SPLIT]),
            ("EXT_P2(2025-01~2026-06)", s[s.ts >= SPLIT], e[e.ts >= SPLIT])]

    print("\n=== Q1：最低桶 vs 最高桶 p80 差距（切 EXT 樣本版，逐週區塊 bootstrap）===")
    rows = []
    for name, ss, _ in segs:
        lo = ss[ss.bucket == label(BUCKETS[0])]
        hi = ss[ss.bucket == label(BUCKETS[-1])]
        for T in HORIZONS:
            col = f"amp_{T}"
            d = block_boot(lo, hi, col, 0.80, np.random.default_rng(sub_seed(name, T))) * 100
            ci = np.quantile(d, [0.025, 0.975])
            rows.append({"segment": name, "T": T, "n_lo": len(lo), "n_hi": len(hi),
                         "p80_lo": round(float(lo[col].quantile(0.80)) * 100, 3),
                         "p80_hi": round(float(hi[col].quantile(0.80)) * 100, 3),
                         "diff_p80": round(float(hi[col].quantile(0.80) - lo[col].quantile(0.80)) * 100, 3),
                         "ci_lo": round(float(ci[0]), 3), "ci_hi": round(float(ci[1]), 3)})
    q1 = pd.DataFrame(rows)
    print(q1.to_string(index=False))
    q1.to_csv(str(Path(__file__).with_suffix("")) + "_q1.tsv", sep="\t", index=False)

    print("\n=== Q2'：分桶配對（切 EXT 樣本版，24h p80，event − 同桶隨機）===")
    rows = []
    for name, ss, ee in segs:
        for b in BUCKETS:
            es, rs = ee[ee.bucket == label(b)], ss[ss.bucket == label(b)]
            line = {"segment": name, "bucket": label(b), "n_event": len(es),
                    "n_A": int((es.grade == "A").sum()), "n_random": len(rs)}
            if len(es) == 0:
                rows.append({**line, "diff_p80": None, "ci_lo": None, "ci_hi": None, "note": "無樣本"})
                continue
            diff = float(es.amp_24h.quantile(0.80) - rs.amp_24h.quantile(0.80)) * 100
            line["diff_p80"] = round(diff, 3)
            if len(es) < 30:
                rows.append({**line, "ci_lo": None, "ci_hi": None, "note": "n<30 不判定"})
                continue
            d = block_boot(rs, es, "amp_24h", 0.80, np.random.default_rng(sub_seed(name, b))) * 100
            ci = np.quantile(d, [0.025, 0.975])
            rows.append({**line, "ci_lo": round(float(ci[0]), 3), "ci_hi": round(float(ci[1]), 3), "note": ""})
    q2 = pd.DataFrame(rows)
    print(q2.to_string(index=False))
    q2.to_csv(str(Path(__file__).with_suffix("")) + "_q2.tsv", sep="\t", index=False)

    print("\n=== 相位敏感度：同一段時期（2025-01~2026-06）、同一組分桶，只差取樣起算時刻 ===")
    print("  主探針 ORIG（獨立重掃，00:00 相位）24h p80 差距 = +2.760pp CI [+1.563,+4.060]"
          "（來源：本次 _q1_lowhigh_ci.tsv）")
    row = q1[(q1.segment == "EXT_P2(2025-01~2026-06)") & (q1["T"] == "24h")].iloc[0]
    print(f"  本檔 EXT_P2（切 EXT 樣本，01:15 相位）24h p80 差距 = {row.diff_p80:+.3f}pp "
          f"CI [{row.ci_lo:+.3f},{row.ci_hi:+.3f}]")


if __name__ == "__main__":
    main()
