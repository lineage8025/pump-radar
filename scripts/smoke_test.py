"""CD 閘門用最小煙測：純合成資料、無網路、不讀狀態檔。

1. 全部 scripts/*.py 語法編譯（不 import，避免 ccxt 依賴）
2. detector 核心鏈路：合成 OHLCV → add_indicators → 人造突破必須產出事件

不驗證統計正確性（那是 DETECTOR_PREREG 的事），只擋「爛 code 自動部署上線」。
"""
import py_compile
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent

for f in sorted(SCRIPTS.glob("*.py")):
    py_compile.compile(str(f), doraise=True)
print(f"compile ok: {len(list(SCRIPTS.glob('*.py')))} files")

sys.path.insert(0, str(SCRIPTS))
import pandas as pd  # noqa: E402
from detector import PARAMS, add_indicators, iter_events  # noqa: E402

# 合成 1200 根：微幅震盪 + 尾端人造放量突破（決定性，無隨機）
n = 1200
rows = []
for i in range(n):
    c = 100 + (i % 7) * 0.01
    rows.append({"date": pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=15 * i),
                 "open": c - 0.005, "high": c + 0.02, "low": c - 0.02, "close": c,
                 "volume": 10 + (i % 5) * 0.1})
rows[-1].update({"open": 100.0, "close": 110.0, "high": 110.5, "low": 99.9, "volume": 1000.0})
df = add_indicators(pd.DataFrame(rows), PARAMS)

for col in ("bb_upper", "bb_lower", "bbw_pct", "vol_z", "event", "grade"):
    assert col in df.columns, f"missing column {col}"
events = list(iter_events(df, "TEST/USDT", PARAMS))
assert len(events) == 1, f"expected 1 synthetic breakout event, got {len(events)}"
ev = events[0]
for key in ("ts", "pair", "grade", "close", "bb_upper", "vol_z"):
    assert key in ev, f"event missing key {key}"
assert ev["grade"] in ("A", "B") and ev["close"] == 110.0
print("detector chain ok:", {k: ev[k] for k in ("grade", "close", "vol_z")})
print("SMOKE OK")
