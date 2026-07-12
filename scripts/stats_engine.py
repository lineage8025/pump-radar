"""同型訊號歷史分佈引擎：樣本內種子＋forward journal → 分級統計 → 訊息「漲跌展望」行。

設計原則（2026-07-12 使用者拍板「不寫死、要顯示漲跌%數」）：
- 顯示的是同型訊號歷史「分佈」（ret_24h 分位數＋MFE/MAE），不是方向預測——次根方向預測仍是紅線。
- 數字不寫死：forward 訊號滿 24h 窗後自動計分入池（增量快取 logs/.scored_forward.tsv），
  統計取滾動 STATS_WINDOW_DAYS（預設 120 天）窗，種子事件（data/insample_scored.tsv，
  2026-05-01~07-07 全 10 標的 235 筆）隨窗口平移自然淡出——regime 變了數字自己跟著變。
- 計分口徑與 score_signals 完全一致（次根開盤進場、24h 窗；共用 score_event/load_candles，
  邏輯絕不分岔）。分位數校準檢查已預登記（結算時 p25~p75 實際覆蓋率應 ≈50%）。
- 單一分級窗內樣本 < MIN_N 時退回「全池」統計（不足時寧可用舊數據也不用小樣本雜訊）。
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from score_signals import load_candles, score_event

SEED_TSV = Path(__file__).resolve().parent.parent / "data" / "insample_scored.tsv"
WINDOW_DAYS = int(os.environ.get("STATS_WINDOW_DAYS", "120"))
MIN_N = int(os.environ.get("STATS_MIN_N", "30"))
REFRESH_HOURS = 24
COLS = ["ts", "pair", "grade", "ret_24h", "net_24h", "mfe_24h", "mae_24h"]

# 種子統計快照（引擎/檔案任一不可用時的最後防線；來源=種子 TSV，口徑同上）
FALLBACK = {
    "A": {"n": 62, "fw": 0, "p25": -0.0096, "p50": -0.0017, "p75": 0.0083,
          "mfe": 0.0128, "mae": -0.0137, "tail": 0.14},
    "B": {"n": 166, "fw": 0, "p25": -0.0159, "p50": -0.0031, "p75": 0.0117,
          "mfe": 0.0138, "mae": -0.0199, "tail": 0.26},
}


def _summarize(pool: pd.DataFrame, fw_ts: set) -> dict:
    out = {}
    for g in ("A", "B"):
        d = pool[pool["grade"] == g]
        r = d["ret_24h"].dropna()
        if r.empty:
            out[g] = dict(FALLBACK[g])
            continue
        out[g] = {
            "n": int(len(r)),
            "fw": int(d["ts"].isin(fw_ts).sum()),
            "p25": float(r.quantile(0.25)),
            "p50": float(r.median()),
            "p75": float(r.quantile(0.75)),
            "mfe": float(d["mfe_24h"].median()),
            "mae": float(d["mae_24h"].median()),
            "tail": float((d["mae_24h"] <= -0.03).mean()),
        }
    return out


def refresh(journal: Path, cache: Path, stats_file: Path) -> None:
    """增量計分 forward journal → 併種子池 → 滾動窗統計 → 寫 stats JSON。"""
    scored = pd.read_csv(cache, sep="\t") if cache.exists() else pd.DataFrame(columns=COLS)
    if len(scored):  # 防兩容器同刻 refresh 造成的重複列
        scored = scored.drop_duplicates(subset=["ts", "pair"], ignore_index=True)
    events = []
    if journal.exists():
        events = [json.loads(l) for l in journal.read_text().splitlines()
                  if l.strip() and json.loads(l).get("event") == "pump_signal"]
    done = set(scored["ts"].astype(str) + scored["pair"]) if len(scored) else set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=25)  # 滿 24h 窗才可計分
    pending = [e for e in events
               if e["ts"] + e["pair"] not in done and pd.Timestamp(e["ts"]) < cutoff]
    rows = []
    for pair in sorted({e["pair"] for e in pending}):
        candles = load_candles(pair, None)  # ccxt 近 35 天，足夠覆蓋待計分事件
        for ev in (e for e in pending if e["pair"] == pair):
            row = score_event(ev, candles)
            if row and row["ret_24h"] is not None:
                rows.append({c: row[c] for c in COLS})
    if rows:
        scored = (pd.concat([scored, pd.DataFrame(rows)], ignore_index=True)
                  if len(scored) else pd.DataFrame(rows))
        scored.to_csv(cache, sep="\t", index=False)

    seed = pd.read_csv(SEED_TSV, sep="\t") if SEED_TSV.exists() else pd.DataFrame(columns=COLS)
    pool_all = pd.concat([seed, scored], ignore_index=True)
    win_start = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).isoformat()
    pool_win = pool_all[pool_all["ts"] >= win_start]
    fw_ts = set(scored["ts"]) if len(scored) else set()
    stats_win, stats_all = _summarize(pool_win, fw_ts), _summarize(pool_all, fw_ts)
    stats = {g: (stats_win[g] if stats_win[g]["n"] >= MIN_N else stats_all[g])
             for g in ("A", "B")}
    stats["updated"] = datetime.now(timezone.utc).isoformat()
    stats_file.write_text(json.dumps(stats))


def maybe_refresh(journal: Path, cache: Path, stats_file: Path) -> None:
    """stats 檔缺失或超過 REFRESH_HOURS 才重算；失敗不擋主流程（訊息退回上次/種子統計）。"""
    if stats_file.exists():
        age = datetime.now(timezone.utc) - datetime.fromisoformat(
            json.loads(stats_file.read_text())["updated"])
        if age < timedelta(hours=REFRESH_HOURS):
            return
    try:
        refresh(journal, cache, stats_file)
        print("[stats] refreshed", flush=True)
    except Exception as e:
        print(f"[stats] refresh failed: {e}", flush=True)


def load_stats(stats_file: Path) -> dict:
    try:
        return json.loads(stats_file.read_text())
    except Exception:
        return FALLBACK


def outlook_line(grade: str, stats: dict) -> str:
    """訊息第三行：24h 漲跌展望（歷史分佈，自動更新）。"""
    s = stats.get(grade) or FALLBACK[grade]
    pct = lambda v: f"{v * 100:+.1f}%".replace("-", "−")
    fw = f"，含 forward {s['fw']}" if s.get("fw") else ""
    return (f"📊 24h 漲跌展望（{grade} 級同型歷史 n={s['n']}{fw}）："
            f"中位 {pct(s['p50'])}｜常見區間 {pct(s['p25'])} ～ {pct(s['p75'])}"
            f"｜典型先衝 {pct(s['mfe'])}、回檔 {pct(s['mae'])}"
            f"｜重挫 ≤−3% 機率 {s['tail'] * 100:.0f}%")
