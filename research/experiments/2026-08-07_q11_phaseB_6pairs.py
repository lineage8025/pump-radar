"""Q11 Phase B 擴大標的涵蓋範圍：BTC/ETH/SOL（既有）+ XRP/LINK/AVAX（新增），共 6 標的。

不重寫撮合邏輯——唯讀 import `2026-08-06_q11_phaseB_realpath_grid.py`
（`simulate_episode_real`、`self_test` 皆已通過對拍驗證，見該檔與 run11 日誌），
只覆寫模組層級的 `PAIRS` 常數後呼叫其 `run_full()`。目的是把 run11 對 3 標的
（BTC/ETH/SOL）的「auto 規則準確率／頭條格位路徑穩健性／Q9 翻轉格位歸屬」全部
分析，擴大到流動性/市值光譜更廣的 6 標的子集，檢驗 run11 最強反駁點名的外部效度
開放問題（`auto` 規則是否在低流動性標的上系統性失準）。

用法：
  python3 research/experiments/2026-08-07_q11_phaseB_6pairs.py --out-prefix <前綴>
"""

import argparse
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PHASEB_PATH = HERE / "2026-08-06_q11_phaseB_realpath_grid.py"

spec = importlib.util.spec_from_file_location("phaseB", PHASEB_PATH)
phaseB = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phaseB)

# run11 涵蓋 BTCUSDT/ETHUSDT/SOLUSDT；本輪新增 XRPUSDT/LINKUSDT/AVAXUSDT
# （Q11 Phase A 本輪產出，research/experiments/q11_aggtrades/ 下 9 個新增
# 標的-月 feather，2024-01~03，交叉驗證誤差 0，見 research/log/2026-08-07-run17.md）。
phaseB.PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT", "AVAXUSDT"]
# MONTHS 沿用既有 2024-01~03（in-sample 段內，與既有 Phase A/B 一致以維持可比性）


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-prefix", required=True)
    ap.add_argument("--per-pair-auto-accuracy-out", default=None,
                     help="逐標的 auto 規則準確率輸出路徑（tsv）")
    args = ap.parse_args()

    # 逐標的 auto 規則準確率（run11 表格的 6 標的擴展版），run_full() 本身不產出這張表
    import pandas as pd
    acc_rows = []
    for pair in phaseB.PAIRS:
        df = phaseB._load_asset(pair)
        o = df["open"].to_numpy()
        c = df["close"].to_numpy()
        hbl = df["high_before_low"].to_numpy(bool)
        real_dn_first = ~hbl
        auto_dn_first = phaseB.q8grid._leg_down_first_arr(o, c, "auto")
        acc = float((auto_dn_first == real_dn_first).mean())
        acc_rows.append({"pair": pair, "n_minutes": len(df), "auto_accuracy": acc})
        print(f"[auto-accuracy] {pair}: {acc*100:.2f}% (n={len(df)})", file=sys.stderr)
    acc_df = pd.DataFrame(acc_rows)
    acc_out = args.per_pair_auto_accuracy_out or f"{args.out_prefix}_auto_accuracy.tsv"
    acc_df.to_csv(acc_out, sep="\t", index=False)

    return phaseB.run_full(args.out_prefix)


if __name__ == "__main__":
    sys.exit(main())
