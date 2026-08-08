"""Q19（run 28，`audit`）：Q10 的價格資料（現貨）vs 其判定門檻的成本模型（USDT-M 永續）。

要覆核的既有主張，不提新主張：
  `docs/TRADEABILITY_PREREG.md` §3.3 的成本模型自陳為「Binance USDT-M 永續，VIP0」，
  由它導出的 0.28% 門檻是 Q10 判 weakens（結局②）的決定性數字；
  但 Q10 的價格資料來自 `research/fetch_klines.py`，其 BASE 指向 data/spot/monthly/klines。
  ⇒ 效應量在現貨上量、門檻用永續費率算。方向一（GRID_SIM_PREREG §限制 1）記過這條，
  方向二（run 8 §9 限制段七條）沒有。本輪補缺口並量化方向與量級。

作法（刻意最小化自由度）：
  1. 錨點完全沿用 run 8 的 samples.tsv（9,010 個），不重新取樣、不改分桶、不改 T。
  2. 用**同一份程式碼**在現貨 15m 與永續 15m 上重算 A/B/amp/R_act，逐錨點配對比較。
     現貨側同時作為正確性檢查：必須重現 samples.tsv（Q13 已證 15m 路徑與 run 8 的 1m
     路徑重建在 9,010 個錨點上 |Δ|>1e-6 為 0 列）。
  3. 只報四個 T 的**彙總**比值（不分桶）＋頭條格位（bucket=[0.10,0.25) × 24h）一格，
     不做任何顯著性宣告、不算 CI ⇒ 比照 run13/18/22 記 [cells=0]。

符號翻轉檢定（TRADEABILITY_PREREG §1.3，硬性前置，推導見日誌）：
  amp = A+B 與 R = max(A,B)/(A+B) 在報酬整體乘 −1 下皆不變；費率差是常數與方向無關
  ⇒ 結論不變 ⇒ 振幅／路徑命題 ⇒ 受理。

窗口：2023-01-01 ~ 2025-06-30（in-sample only）。抓取月份上界寫死 2025-06，
      **不觸碰 2025-07-01 之後的封存段**（TRADEABILITY_PREREG §4）。

用法：
  python research/experiments/2026-08-08_q19_perp_vs_spot.py --stage fetch --market um   --out-dir /tmp/um15
  python research/experiments/2026-08-08_q19_perp_vs_spot.py --stage fetch --market spot --out-dir /tmp/sp15
  python research/experiments/2026-08-08_q19_perp_vs_spot.py --stage analyze \
      --spot-dir /tmp/sp15 --perp-dir /tmp/um15 \
      --samples research/experiments/2026-08-05_q10_shape_samples.tsv \
      --out-prefix research/experiments/2026-08-08_q19
"""

import argparse
import io
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# fetch_klines.py 對本迴圈唯讀：只 import 與資料源 BASE 無關的兩個純函式，一行未改。
from fetch_klines import COLS, UA, months, to_candles  # noqa: E402

BASES = {
    "spot": "https://data.binance.vision/data/spot/monthly/klines",
    "um": "https://data.binance.vision/data/futures/um/monthly/klines",
}
PAIRS = ["BTC/USDT", "ETH/USDT", "ADA/USDT", "SOL/USDT", "XRP/USDT",
         "DOGE/USDT", "BNB/USDT", "LINK/USDT", "LTC/USDT", "AVAX/USDT"]
START, END = "2023-01", "2025-06"      # 上界寫死；2025-07 起是封存段，本檔不得抓
T_HOURS = [1, 4, 12, 24]
T_BARS = [4, 16, 48, 96]               # 15m 根數
MAXBAR = 96
HEADLINE_BUCKET = 2                    # [0.10,0.25)
HEADLINE_T = 24


def fetch_month(base: str, symbol: str, month: str, interval: str = "15m"):
    url = f"{base}/{symbol}/{interval}/{symbol}-{interval}-{month}.zip"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            blob = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"  [skip] {symbol} {month} 無資料（404）", file=sys.stderr)
            return None
        raise
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        raw = zf.read(zf.namelist()[0]).decode("utf-8")
    first = raw.split("\n", 1)[0].split(",")[0].strip()
    header = 0 if not first.lstrip("-").isdigit() else None
    df = pd.read_csv(io.StringIO(raw), header=header, names=None if header == 0 else COLS)
    if header == 0:
        df.columns = COLS[: len(df.columns)]
    return df


def stage_fetch(market: str, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = BASES[market]
    rc = 0
    for pair in PAIRS:
        symbol = pair.replace("/", "")
        path = out_dir / f"{pair.replace('/', '_')}-15m.feather"
        if path.exists():
            print(f"[cached] {pair}", file=sys.stderr)
            continue
        parts = []
        for m in months(START, END):
            got = fetch_month(base, symbol, m)
            if got is not None and len(got):
                parts.append(to_candles(got))
        if not parts:
            print(f"[warn] {pair} 一個月都沒抓到", file=sys.stderr)
            rc = 1
            continue
        c = (pd.concat(parts, ignore_index=True)
               .drop_duplicates(subset="date").sort_values("date").reset_index(drop=True))
        assert c["date"].max() < pd.Timestamp("2025-07-01", tz="UTC"), "抓到封存段資料"
        c.to_feather(path)
        print(f"[ok] {market} {pair}: {len(c)} 根（{c['date'].iloc[0]:%Y-%m-%d}~"
              f"{c['date'].iloc[-1]:%Y-%m-%d}）", file=sys.stderr)
    return rc


def measure(dir15: Path, pair: str, anchors: np.ndarray):
    """在給定錨點時刻上，由 15m K 線算 A/B/amp/R。回傳 (ok_mask, amp[n,4], R[n,4])。

    A = max(high[t+1..t+T])/P0 − 1、B = 1 − min(low[t+1..t+T])/P0，皆 clip 於 0，
    R = max(A,B)/(A+B)——與 run 8 `ab_price` / `_R` 的價格空間定義逐字相同。
    """
    tag = pair.replace("/", "_")
    d = pd.read_feather(dir15 / f"{tag}-15m.feather")
    t = d["date"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    hi, lo, cl = d["high"].to_numpy(), d["low"].to_numpy(), d["close"].to_numpy()
    step = np.timedelta64(15, "m")

    n = len(anchors)
    amp = np.full((n, 4), np.nan)
    R = np.full((n, 4), np.nan)
    ok = np.zeros(n, dtype=bool)
    idx = np.searchsorted(t, anchors)
    for k in range(n):
        i = int(idx[k])
        if i >= len(t) or t[i] != anchors[k]:
            continue                                    # 該時刻在此市場無 K 棒
        if i + MAXBAR >= len(t):
            continue
        seg_t = t[i + 1: i + 1 + MAXBAR]
        if seg_t[-1] - seg_t[0] != (MAXBAR - 1) * step:
            continue                                    # 窗內缺 K 棒 → 檢查點錯位，丟棄
        P0 = cl[i]
        sh, sl = hi[i + 1: i + 1 + MAXBAR], lo[i + 1: i + 1 + MAXBAR]
        for j, nb in enumerate(T_BARS):
            A = max(sh[:nb].max() / P0 - 1.0, 0.0)
            B = max(1.0 - sl[:nb].min() / P0, 0.0)
            s = A + B
            amp[k, j] = s
            R[k, j] = max(A, B) / s if s > 0 else np.nan
        ok[k] = np.all(np.isfinite(R[k]))
    return ok, amp, R


def stage_analyze(spot_dir: Path, perp_dir: Path, samples: Path, prefix: str) -> int:
    sm = pd.read_csv(samples, sep="\t")
    sm["date"] = pd.to_datetime(sm["date"])
    print(f"錨點 {len(sm)} 個，{sm['date'].min()} ~ {sm['date'].max()}")
    assert sm["date"].max() < pd.Timestamp("2025-07-01"), "錨點跨越封存段"

    per_pair, rows = [], []
    for pair in PAIRS:
        sub = sm[sm["pair"] == pair].reset_index(drop=True)
        anchors = sub["date"].to_numpy(dtype="datetime64[ns]")
        ok_s, amp_s, R_s = measure(spot_dir, pair, anchors)
        ok_p, amp_p, R_p = measure(perp_dir, pair, anchors)
        both = ok_s & ok_p

        # 正確性檢查：現貨 15m 重算 vs run 8 samples.tsv（Q13 已證應為 0）
        dmax_amp = dmax_R = 0.0
        for j, h in enumerate(T_HOURS):
            ref_a = sub[f"amp_{h}"].to_numpy()[ok_s]
            ref_r = sub[f"R_act_{h}"].to_numpy()[ok_s]
            dmax_amp = max(dmax_amp, float(np.nanmax(np.abs(amp_s[ok_s, j] - ref_a))))
            dmax_R = max(dmax_R, float(np.nanmax(np.abs(R_s[ok_s, j] - ref_r))))
        per_pair.append({"pair": pair, "n_anchor": len(sub), "n_spot_ok": int(ok_s.sum()),
                         "n_perp_ok": int(ok_p.sum()), "n_both": int(both.sum()),
                         "spot_vs_run8_maxabs_amp": dmax_amp,
                         "spot_vs_run8_maxabs_R": dmax_R})
        print(f"[{pair}] both={both.sum()}/{len(sub)}  spot重算vs run8 max|Δ|: "
              f"amp={dmax_amp:.3e} R={dmax_R:.3e}", file=sys.stderr)

        d = pd.DataFrame({"pair": pair, "date": sub["date"], "bucket": sub["bucket"],
                          "both": both})
        for j, h in enumerate(T_HOURS):
            d[f"amp_s_{h}"] = amp_s[:, j]
            d[f"amp_p_{h}"] = amp_p[:, j]
            d[f"R_s_{h}"] = R_s[:, j]
            d[f"R_p_{h}"] = R_p[:, j]
        rows.append(d)

    pp = pd.DataFrame(per_pair)
    pp.to_csv(f"{prefix}_coverage.tsv", sep="\t", index=False)
    print("\n== 覆蓋率與現貨側正確性檢查 ==")
    print(pp.to_string(index=False))

    all_d = pd.concat(rows, ignore_index=True)
    all_d.to_csv(f"{prefix}_paired.tsv.gz", sep="\t", index=False, compression="gzip")
    m = all_d[all_d["both"]].reset_index(drop=True)

    out = []
    for j, h in enumerate(T_HOURS):
        a_s, a_p = m[f"amp_s_{h}"].to_numpy(), m[f"amp_p_{h}"].to_numpy()
        r_s, r_p = m[f"R_s_{h}"].to_numpy(), m[f"R_p_{h}"].to_numpy()
        out.append({"scope": "ALL", "T_h": h, "n": len(m),
                    "amp_spot_pct": a_s.mean() * 100, "amp_perp_pct": a_p.mean() * 100,
                    "amp_ratio": a_p.mean() / a_s.mean(),
                    "R_spot": r_s.mean(), "R_perp": r_p.mean(),
                    "R_diff": r_p.mean() - r_s.mean(),
                    "R_absdiff_mean": np.abs(r_p - r_s).mean()})
    hb = m[m["bucket"] == HEADLINE_BUCKET]
    h = HEADLINE_T
    a_s, a_p = hb[f"amp_s_{h}"].to_numpy(), hb[f"amp_p_{h}"].to_numpy()
    r_s, r_p = hb[f"R_s_{h}"].to_numpy(), hb[f"R_p_{h}"].to_numpy()
    out.append({"scope": "HEADLINE[0.10,0.25)", "T_h": h, "n": len(hb),
                "amp_spot_pct": a_s.mean() * 100, "amp_perp_pct": a_p.mean() * 100,
                "amp_ratio": a_p.mean() / a_s.mean(),
                "R_spot": r_s.mean(), "R_perp": r_p.mean(),
                "R_diff": r_p.mean() - r_s.mean(),
                "R_absdiff_mean": np.abs(r_p - r_s).mean()})
    res = pd.DataFrame(out)
    res.to_csv(f"{prefix}_summary.tsv", sep="\t", index=False)
    print("\n== 現貨 vs USDT-M 永續（同錨點配對，不分桶；末列為頭條格位）==")
    print(res.to_string(index=False))

    # Q10 頭條數字在「標的改判為永續」下的重算上界（ΔR 沿用現貨值，見日誌限制段）
    cap_spot = 0.0886
    ratio = float(res.iloc[-1]["amp_ratio"])
    print(f"\ncap(現貨,run8) = {cap_spot:.4f}% ；頭條格位 amp 比值 = {ratio:.6f}")
    print(f"⇒ cap(永續 amp 代入, ΔR 不變) ≈ {cap_spot * ratio:.4f}%  vs 門檻 0.28%")
    print(f"⇒ 要跨過 0.28% 需要 amp 比值 ≥ {0.28 / cap_spot:.4f}（實測 {ratio:.4f}）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=["fetch", "analyze"])
    ap.add_argument("--market", choices=["spot", "um"])
    ap.add_argument("--out-dir")
    ap.add_argument("--spot-dir")
    ap.add_argument("--perp-dir")
    ap.add_argument("--samples")
    ap.add_argument("--out-prefix")
    a = ap.parse_args()
    if a.stage == "fetch":
        return stage_fetch(a.market, Path(a.out_dir))
    return stage_analyze(Path(a.spot_dir), Path(a.perp_dir), Path(a.samples), a.out_prefix)


if __name__ == "__main__":
    sys.exit(main())
