"""每日結果日報 sidecar：聚合 24h 新訊號＋剛結算的 24h 成績 → repository_dispatch[daily-pulse]。

模式同 crypto-pulse weekly digest（邊界補發語意，實踩教訓照抄）：
- 由外層 sh 迴圈每 ~25 分鐘喚起；marker（logs/.daily_pulse_marker）早於「最近一個
  UTC 01:00（=台北 09:00）」才動作，HTTP 204 成功才 touch——停機/失敗下次喚醒自動補發。
- 無新訊號且無新結算 → 跳過不發（但照 touch marker，當日已處理），安靜日不擾民。
- dispatch 前先跑 stats_engine.refresh 讓計分是最新的（滿 24h 的訊號當場入池）。
- 已回報過的結算列記在 logs/.daily_pulse_state.json，不重複回報。

環境變數：GITHUB_DISPATCH_TOKEN / GITHUB_DISPATCH_REPO（缺任一則整段 no-op，不影響偵測主流程）。
"""

import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import stats_engine

LOG_DIR = Path(os.environ.get("LOG_DIR", "/app/logs"))
JOURNAL = LOG_DIR / "pump_journal.jsonl"
SCORED_CACHE = LOG_DIR / ".scored_forward.tsv"
STATS_FILE = LOG_DIR / ".grade_stats.json"
MARKER = LOG_DIR / ".daily_pulse_marker"
STATE = LOG_DIR / ".daily_pulse_state.json"
BOUNDARY_HOUR_UTC = 1  # 01:00 UTC = 台北 09:00
TARGET_N = 100


def latest_boundary(now: datetime) -> datetime:
    b = now.replace(hour=BOUNDARY_HOUR_UTC, minute=0, second=0, microsecond=0)
    return b if b <= now else b - timedelta(days=1)


def dispatch(token: str, repo: str, payload: dict) -> int:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/dispatches",
        data=json.dumps({"event_type": "daily-pulse",
                         "client_payload": payload}).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "pump-radar-pulse/1.0"},  # Cloudflare/GH 都要 UA
    )
    return urllib.request.urlopen(req, timeout=15).getcode()


def main() -> None:
    token = os.environ.get("GITHUB_DISPATCH_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_DISPATCH_REPO", "").strip()
    now = datetime.now(timezone.utc)
    hb = now.strftime("%H:%M:%S")
    if not token or not repo:
        print(f"[pulse {hb}] no dispatch env, noop", flush=True)
        return
    boundary = latest_boundary(now)
    if MARKER.exists() and datetime.fromtimestamp(
            MARKER.stat().st_mtime, timezone.utc) >= boundary:
        print(f"[pulse {hb}] marker fresh, skip", flush=True)
        return

    try:  # 強制重算讓報告用最新計分；此後偵測容器的 24h age 檢查當日自然 no-op
        stats_engine.refresh(JOURNAL, SCORED_CACHE, STATS_FILE)
    except Exception as e:
        print(f"[pulse] refresh failed, use last stats: {e}", flush=True)

    events = []
    if JOURNAL.exists():
        events = [json.loads(l) for l in JOURNAL.read_text().splitlines()
                  if l.strip() and json.loads(l).get("event") == "pump_signal"]
    since = (boundary - timedelta(days=1)).isoformat()
    new_signals = [{k: e[k] for k in ("ts", "pair", "grade", "close", "vol_z", "bbw_pct")}
                   for e in events if e["ts"] >= since]

    state = json.loads(STATE.read_text()) if STATE.exists() else {"reported": []}
    scored = (pd.read_csv(SCORED_CACHE, sep="\t")
              if SCORED_CACHE.exists() else pd.DataFrame())
    newly_scored = []
    if len(scored):
        scored["key"] = scored["ts"].astype(str) + scored["pair"]
        fresh = scored[~scored["key"].isin(state["reported"])]
        newly_scored = [
            {"ts": r.ts, "pair": r.pair, "grade": r.grade,
             "ret_24h_pct": round(r.ret_24h * 100, 2),
             "net_24h_pct": round(r.net_24h * 100, 2),
             "mfe_pct": round(r.mfe_24h * 100, 2),
             "mae_pct": round(r.mae_24h * 100, 2)}
            for r in fresh.itertuples()]

    if not new_signals and not newly_scored:
        MARKER.touch()
        print(f"[pulse {hb}] nothing new, skip day", flush=True)
        return

    n_scored = len(scored)
    progress = {"signals_total": len(events), "scored_total": n_scored,
                "target": TARGET_N}
    if n_scored:
        net = scored["net_24h"].dropna()
        progress["forward_net24h_mean_pct"] = round(net.mean() * 100, 2)
        progress["forward_win_pct"] = round((net > 0).mean() * 100)
    payload = {
        "date_taipei": (now + timedelta(hours=8)).strftime("%Y-%m-%d"),
        "new_signals_24h": new_signals,
        "newly_scored": newly_scored,
        "forward_progress": progress,
        "insample_baseline": {"net_24h_mean_pct": -0.37, "win_pct": 40,
                              "note": "2026-05-01~07-07, 10 pairs, 235 events"},
        "grade_stats": stats_engine.load_stats(STATS_FILE),
    }
    try:
        code = dispatch(token, repo, payload)
    except urllib.error.HTTPError as e:
        code = e.code  # 403=PAT 沒圈本 repo；marker 不 touch，下次喚醒重試
    if code == 204:
        MARKER.touch()
        state["reported"] += [s["ts"] + s["pair"] for s in newly_scored]
        STATE.write_text(json.dumps(state))
        print(f"[pulse {hb}] dispatched: {len(new_signals)} new, "
              f"{len(newly_scored)} scored", flush=True)
    else:
        print(f"[pulse {hb}] dispatch HTTP {code}, will retry", flush=True)


if __name__ == "__main__":
    main()
