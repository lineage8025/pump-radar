"""pump-radar 偵測核心（純函式；live 迴圈與歷史回放共用同一份邏輯，避免兩套實作分岔）。

定位：15m 布林帶「壓縮→放量突破上軌」的波段啟動**事件偵測**。
方法論紅線（繼承 crypto-pulse 教訓）：
- 本模組不做次根方向預測——15m 動能式方向預測已被 DirProbe 92k 樣本證偽（命中 ~46%）。
- 參數預登記於 docs/DETECTOR_PREREG.md，上線後不得在同段資料上回頭調參再宣稱有效。
"""

import pandas as pd

PARAMS = {
    "bb_window": 20,         # 布林帶 20 × 2σ（15m）
    "bb_std": 2.0,
    "bbw_pct_window": 2880,  # BBW 百分位回看 30 天（2880 根 15m）
    "bbw_pct_min_periods": 960,  # 至少 10 天樣本才給百分位（冷啟動期不判壓縮）
    "squeeze_pct": 0.25,     # 事前壓縮：觸發前一根的 BBW 百分位 ≤ 25%
    "vol_window": 96,        # 量能基準：前 24h（不含當根，防自我抬升）
    "vol_z_min": 3.0,        # 量能異常門檻
    "cooldown_bars": 16,     # 同標的觸發後冷卻 4h，防連環轟炸
}


def add_indicators(df: pd.DataFrame, p: dict = PARAMS) -> pd.DataFrame:
    """輸入 OHLCV DataFrame（欄位 date/open/high/low/close/volume，時間升冪），
    回傳加上布林帶、BBW 百分位、量能 z-score 與事件旗標的副本。只用已收盤資料，無前視。"""
    df = df.copy().reset_index(drop=True)

    mid = df["close"].rolling(p["bb_window"]).mean()
    sd = df["close"].rolling(p["bb_window"]).std(ddof=0)
    df["bb_upper"] = mid + p["bb_std"] * sd
    df["bb_lower"] = mid - p["bb_std"] * sd
    df["bbw"] = (df["bb_upper"] - df["bb_lower"]) / mid

    # BBW 在回看窗內的百分位（rolling rank 只排當前值，無前視）；壓縮判定看「前一根」的狀態，
    # 讓觸發根自己的爆發不汙染壓縮判定。
    df["bbw_pct"] = df["bbw"].rolling(
        p["bbw_pct_window"], min_periods=p["bbw_pct_min_periods"]
    ).rank(pct=True)
    df["squeeze_before"] = (df["bbw_pct"].shift(1) <= p["squeeze_pct"]).fillna(False)

    vol_hist = df["volume"].shift(1)  # 量能基準排除當根
    vol_mean = vol_hist.rolling(p["vol_window"]).mean()
    vol_std = vol_hist.rolling(p["vol_window"]).std(ddof=0)
    df["vol_z"] = (df["volume"] - vol_mean) / vol_std

    # 觸發：收盤自下而上穿越上軌 × 陽線 × 量能異常
    cross_up = (df["close"] > df["bb_upper"]) & (
        df["close"].shift(1) <= df["bb_upper"].shift(1)
    )
    df["event"] = cross_up & (df["close"] > df["open"]) & (df["vol_z"] >= p["vol_z_min"])
    # A 級 = 壓縮後爆發（教科書型態）；B 級 = 無壓縮前置的放量突破
    df["grade"] = df["squeeze_before"].map({True: "A", False: "B"})
    return df


def iter_events(df: pd.DataFrame, pair: str, p: dict = PARAMS):
    """套用冷卻規則後，逐一產出事件 dict（df 需已過 add_indicators）。"""
    cooldown_until = -1
    for i, row in df[df["event"]].iterrows():
        if i <= cooldown_until:
            continue
        cooldown_until = i + p["cooldown_bars"]
        yield {
            "ts": row["date"].isoformat() if hasattr(row["date"], "isoformat") else str(row["date"]),
            "pair": pair,
            "event": "pump_signal",
            "grade": row["grade"],
            "close": float(row["close"]),
            "bb_upper": float(row["bb_upper"]),
            "bbw_pct": round(float(row["bbw_pct"]), 4) if pd.notna(row["bbw_pct"]) else None,
            "vol_z": round(float(row["vol_z"]), 2),
        }
