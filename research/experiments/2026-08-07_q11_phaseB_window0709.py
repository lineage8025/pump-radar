"""Q11 Phase B 窗口維度擴展：BTC/ETH/SOL x 2024-07~09（trend_ratio 最低的對照窗口）。

不重寫撮合邏輯——唯讀 import `2026-08-06_q11_phaseB_realpath_grid.py`
（`simulate_episode_real`、`self_test` 皆已通過對拍驗證，見該檔與 run11 日誌），
只覆寫模組層級的 `PAIRS`（維持既有 3 標的不變，控制標的維度）與 `MONTHS`
（改成 2024-07~09，本輪窗口維度的唯一變數）後呼叫其 `run_full()`。

選窗方法與依據見 `research/log/2026-08-07-run19.md` §2/§6：用 BTC 15m 收盤價把
in-sample 全段切 10 個日曆季，`trend_ratio = |net_ret| / range` 最低者（2024 Q3，
0.0334）與既有窗口 2024 Q1（0.8174）形成最尖銳對照，選窗規則先於任何 Phase B
結果寫死。

用法：
  python3 research/experiments/2026-08-07_q11_phaseB_window0709.py --out-prefix <前綴>
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

# 標的維度維持既有 3 標的（BTC/ETH/SOL）不變，本輪只變窗口
phaseB.PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
phaseB.MONTHS = ["2024-07", "2024-08", "2024-09"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-prefix", required=True)
    ap.add_argument("--per-pair-auto-accuracy-out", default=None)
    args = ap.parse_args()

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
