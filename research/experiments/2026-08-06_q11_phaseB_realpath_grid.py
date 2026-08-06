"""Q11 Phase B — 用 aggTrades 真實 intrabar 序重跑 Q8 頭條格位，結案 Q9。

`docs/RND_BACKLOG.md` 方向三 Phase B：Q8（`research/experiments/2026-08-03_phase1_grid_replay.py`）
的雙路徑序敏感度檢查顯示 1m OHLC 決定不了等差網格頭條格位的損益符號（`auto` 0/450 格為正，
`reverse` 115/450 格為正）。本腳本用 Q11 Phase A 產出的 1m aggTrades 摘要（含
`high_before_low`：該分鐘內最高價是否先於最低價出現，事後可觀測的真實到達順序）重建
「真實」intrabar 路徑序，取代 auto/reverse 的假設，量出真值落在雙界的哪裡。

**不是新的方向性命題**：本題延續已於 2026-08-03 收攤的方向一（Q8/Q9），問的是「哪個路徑
假設更接近真實」這個方法論問題，不是「網格能不能賺」——方向一已依 kill criteria 收攤，
不因本輪結果重開。`TRADEABILITY_PREREG.md` §1.3 的符號翻轉檢定不適用：這裡沒有提出任何
新的振幅/方向命題，只是比較同一組已凍結格位在三種 intrabar 路徑假設下的結果一致性
（Q9 開題時已論證此為方法論問題，見 `research/backlog.md` Q9 段）。

核心機制（與 Q8 的 dn_first 語意對應，見該檔 `simulate_episode` 註解）：
    dn_first=True  ⟺ 該根路徑「先探低、後探高」⟺ low 先於 high 到達 ⟺ NOT high_before_low
    dn_first=False ⟺ 「先探高、後探低」⟺ high 先於 low 到達 ⟺ high_before_low
故 real_dn_first = ~high_before_low，直接由 aggTrades 摘要逐分鐘給出，不假設任何固定規則。

用法
----
  python3 research/experiments/2026-08-06_q11_phaseB_realpath_grid.py --self-test
  python3 research/experiments/2026-08-06_q11_phaseB_realpath_grid.py --out-prefix <前綴>
"""

import argparse
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
Q8_PATH = HERE / "2026-08-03_phase1_grid_replay.py"

spec = importlib.util.spec_from_file_location("q8grid", Q8_PATH)
q8grid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q8grid)

# ─── 頭條格位（docs/GRID_SIM_PREREG.md §一 出廠具名格位，一字不改）───────
W = 4.6
N = 80
POLICY = "hold"
LEV = 30
MAINT = 0.020        # 主
FEE = 0.00011         # 主
HORIZONS_D = [1, 7, 30]
BARS_PER_DAY = 1440   # 1m 資料
ANCHOR_STRIDE = 1441  # 沿用 Q8：1440+1 分鐘，錨點相位漂移避開固定 UTC 時刻退化
LEVERAGES = q8grid.LEVERAGES   # [3, 5, 10, 15, 30]，槓桿不影響路徑，evaluate() 後處理免費算

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]     # Q11 Phase A 涵蓋範圍
MONTHS = ["2024-01", "2024-02", "2024-03"]     # Q11 Phase A 涵蓋範圍，in-sample 段內
DATA_DIR = HERE / "q11_aggtrades"

# Q9 的 115 個「auto 點估計為負、reverse 點估計為正」翻轉格位，去重到 (W,N,policy) 層級
# （槓桿與 T 不影響路徑序，故同一組態的多個槓桿/T 翻轉格位共用同一次撮合）。
# 取自 research/experiments/2026-08-03_phase1_grid_replay_result_table.tsv 與
# _revpath_result_table.tsv 的 scenario=='main' 交集，net_mean 由負轉正者，2026-08-06 對拍萃取。
FLIPPED_CONFIGS = [
    (3.0, 40, "close"), (3.0, 40, "hold"),
    (4.6, 40, "close"), (4.6, 40, "hold"), (4.6, 40, "recover"), (4.6, 80, "close"),
    (7.0, 40, "close"), (7.0, 40, "hold"), (7.0, 40, "recover"),
    (7.0, 80, "close"), (7.0, 80, "hold"), (7.0, 80, "recover"),
    (10.0, 40, "close"), (10.0, 40, "hold"), (10.0, 40, "recover"),
    (10.0, 80, "close"), (10.0, 80, "hold"), (10.0, 80, "recover"),
]
CONFIGS = [(W, N, POLICY)] + FLIPPED_CONFIGS   # 頭條格位 + 全部 18 個翻轉組態


# ─── 真實路徑撮合：q8grid.simulate_episode 的逐行對照版本 ─────────────────
# 與原函式的唯一差異：dn_first 由外部傳入的真實觀測陣列決定，不由
# _leg_down_first_arr(o, c, path_order) 從 open/close 假設推導。
# 其餘全部邏輯（levels/clamp monoid/現金流/policy 處置）逐行對照原函式，
# 未新增任何本題定義以外的規則。
def simulate_episode_real(o, h, l, c, dn_first_arr, mid, half_band_pct, n, policy):
    levels = q8grid.build_levels(mid, half_band_pct, n)
    lower, upper = float(levels[0]), float(levels[-1])
    spacing = float(levels[1] - levels[0])
    nb = len(o)
    e0 = n // 2

    a_dn = q8grid._idx_ceil(l, lower, spacing, n)
    b_up = q8grid._idx_floor(h, lower, spacing, n)
    c_ce = q8grid._idx_ceil(c, lower, spacing, n)
    c_fl = q8grid._idx_floor(c, lower, spacing, n)

    dn_first = dn_first_arr
    negB, posB = -q8grid.BIG, q8grid.BIG
    L1 = np.where(dn_first, negB, b_up)
    U1 = np.where(dn_first, a_dn, posB)
    L2 = np.where(dn_first, b_up, negB)
    U2 = np.where(dn_first, posB, a_dn)
    L3 = np.where(dn_first, negB, c_fl)
    U3 = np.where(dn_first, c_ce, posB)
    Lb, Ub = q8grid._compose(L1, U1, L2, U2)
    Lb, Ub = q8grid._compose(Lb, Ub, L3, U3)

    e_end = q8grid._scan_clamp(Lb, Ub, e0)
    e_prev = np.empty(nb, dtype=np.int64)
    e_prev[0] = e0
    e_prev[1:] = e_end[:-1]

    s1 = q8grid._clamp(e_prev, L1, U1)
    s2 = q8grid._clamp(s1, L2, U2)
    s3 = q8grid._clamp(s2, L3, U3)

    d_cash = np.zeros(nb)
    d_feepx = np.zeros(nb)
    for a, b in ((e_prev, s1), (s1, s2), (s2, s3)):
        dn = b < a
        up = b > a
        s_dn = q8grid._range_sum(b, a - 1, lower, spacing)
        s_up = q8grid._range_sum(a + 1, b, lower, spacing)
        d_cash += np.where(dn, -s_dn, 0.0) + np.where(up, s_up, 0.0)
        d_feepx += np.where(dn, s_dn, 0.0) + np.where(up, s_up, 0.0)

    idx_end = e_end
    C = e0
    pos = (C - idx_end).astype(np.float64)
    cash = np.cumsum(d_cash)
    fee_px = np.cumsum(d_feepx)

    out = (l < lower) | (h > upper)
    bi = int(np.nonzero(out)[0][0]) if out.any() else -1

    if bi >= 0 and policy == "close":
        cash = cash.copy(); pos = pos.copy(); fee_px = fee_px.copy()
        px = float(np.clip(c[bi], lower, upper))
        cash[bi:] = cash[bi] + pos[bi] * px
        fee_px[bi:] = fee_px[bi] + abs(pos[bi]) * px
        pos[bi:] = 0.0
    elif bi >= 0 and policy == "recover":
        cash, pos, fee_px = q8grid._apply_recover(cash, pos, fee_px, bi, e_end, lower, spacing)

    res = {"pos": pos, "cash": cash, "fee_px": fee_px, "mark": c, "breach_i": bi,
           "spacing": spacing, "levels": levels}
    if policy == "hold":
        res["avg_entry"] = q8grid._open_avg_entry(idx_end, C, lower, spacing)
    return res


def self_test() -> int:
    """驗證 simulate_episode_real 在餵入與 auto/reverse 相同的 dn_first 陣列時，
    與 q8grid.simulate_episode 逐位元一致（唯一差異是 dn_first 的來源）。"""
    ok = True

    def chk(label, cond, extra=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"   {extra}" if extra and not cond else ""))

    rng = np.random.default_rng(11)
    for trial in range(30):
        n_bars = rng.integers(200, 3000)
        px = 100.0 * np.exp(np.cumsum(rng.normal(
            rng.choice([-1, 0, 1]) * rng.uniform(0, 3e-4), 6e-4, n_bars)))
        o = px[:-1]
        c = px[1:]
        h = np.maximum(o, c) + rng.uniform(0, 0.05, n_bars - 1)
        l = np.minimum(o, c) - rng.uniform(0, 0.05, n_bars - 1)
        mid = 100.0
        for W_ in (1.5, 4.6, 10.0):
            for pol_ in ("hold", "close", "recover"):
                for path_ in ("auto", "reverse"):
                    dn_first_ref = q8grid._leg_down_first_arr(o, c, path_)
                    ep_ref = q8grid.simulate_episode(o, h, l, c, mid, W_, 40, pol_, path_)
                    ep_real = simulate_episode_real(o, h, l, c, dn_first_ref, mid, W_, 40, pol_)
                    for key in ("pos", "cash", "fee_px"):
                        d = np.max(np.abs(ep_ref[key] - ep_real[key]))
                        chk(f"trial{trial} W={W_} pol={pol_} path={path_} {key} 逐位元一致",
                            d < 1e-9, f"maxdiff={d}")
                    chk(f"trial{trial} W={W_} pol={pol_} path={path_} breach_i 一致",
                        ep_ref["breach_i"] == ep_real["breach_i"])

    # dn_first 全 True／全 False 的退化案例（等同 high_before_low 全 False/全 True）
    n_bars = 500
    px = 100.0 + 3.0 * np.sin(np.linspace(0, 8 * np.pi, n_bars + 1))
    o, c = px[:-1], px[1:]
    h = np.maximum(o, c) + 0.02
    l = np.minimum(o, c) - 0.02
    for flag in (True, False):
        dn_first_arr = np.full(n_bars, flag)
        path_ = "auto" if flag == (c[0] >= o[0]) else "reverse"
        # 僅在逐點一致時才能直接比較；改用單獨對拍：real 版本自洽（不崩潰、pos 有界）
        ep = simulate_episode_real(o, h, l, c, dn_first_arr, mid, 4.6, 40, "hold")
        chk(f"退化案例 dn_first 全{flag}：pos 有界",
            np.all(np.abs(ep["pos"]) <= 40), f"max|pos|={np.max(np.abs(ep['pos']))}")

    print("\n" + ("SELF-TEST ALL PASS" if ok else "SELF-TEST FAILED"))
    return 0 if ok else 1


def _load_asset(pair: str) -> pd.DataFrame:
    dfs = [pd.read_feather(DATA_DIR / f"{pair}-aggtrades-1m-{m}.feather") for m in MONTHS]
    df = pd.concat(dfs, ignore_index=True).sort_values("minute").reset_index(drop=True)
    diffs = df["minute"].diff().dropna().dt.total_seconds().div(60).unique()
    assert list(diffs) == [1.0], f"{pair} 分鐘序列不連續: {diffs}"
    return df


def run_full(out_prefix: str) -> int:
    horizons = [d * BARS_PER_DAY for d in HORIZONS_D]
    max_h = max(horizons)
    rows = []
    bracket_rows = []

    for pair in PAIRS:
        df = _load_asset(pair)
        o = df["open"].to_numpy(np.float64)
        h = df["high"].to_numpy(np.float64)
        l = df["low"].to_numpy(np.float64)
        c = df["close"].to_numpy(np.float64)
        hbl = df["high_before_low"].to_numpy(bool)
        real_dn_first_full = ~hbl
        minutes = df["minute"].to_numpy()
        nbars = len(c)
        anchors = np.arange(0, nbars - max_h - 1, ANCHOR_STRIDE)
        print(f"[{pair}] nbars={nbars} anchors={len(anchors)} configs={len(CONFIGS)}", file=sys.stderr)

        for a in anchors:
            mid = float(c[a])
            s = slice(a + 1, a + 1 + max_h)
            oo, hh, ll, cc = o[s], h[s], l[s], c[s]
            dn_real = real_dn_first_full[s]
            wk = pd.Timestamp(minutes[a]).isocalendar()
            week_key = wk[0] * 100 + wk[1]

            for (cfg_w, cfg_n, cfg_pol) in CONFIGS:
                is_headline = (cfg_w, cfg_n, cfg_pol) == (W, N, POLICY)
                ep_auto = q8grid.simulate_episode(oo, hh, ll, cc, mid, cfg_w, cfg_n, cfg_pol, "auto")
                ep_rev = q8grid.simulate_episode(oo, hh, ll, cc, mid, cfg_w, cfg_n, cfg_pol, "reverse")
                ep_real = simulate_episode_real(oo, hh, ll, cc, dn_real, mid, cfg_w, cfg_n, cfg_pol)

                levs = LEVERAGES if not is_headline else [LEV] + [lv for lv in LEVERAGES if lv != LEV]
                for T in horizons:
                    for lev in levs:
                        r_auto = q8grid.evaluate(ep_auto, mid, cfg_n, lev, MAINT, FEE, T)
                        r_rev = q8grid.evaluate(ep_rev, mid, cfg_n, lev, MAINT, FEE, T)
                        r_real = q8grid.evaluate(ep_real, mid, cfg_n, lev, MAINT, FEE, T)
                        lo = min(r_auto["net_return"], r_rev["net_return"])
                        hi = max(r_auto["net_return"], r_rev["net_return"])
                        in_bracket = lo - 1e-12 <= r_real["net_return"] <= hi + 1e-12
                        cfg_tag = f"W{cfg_w}_N{cfg_n}_{cfg_pol}"
                        if is_headline and lev == LEV:
                            for path_name, r in (("auto", r_auto), ("reverse", r_rev), ("real", r_real)):
                                rows.append({
                                    "pair": pair, "anchor": int(a), "week": week_key,
                                    "T_days": T // BARS_PER_DAY, "cfg": cfg_tag, "lev": lev,
                                    "path": path_name, "net_return": r["net_return"],
                                    "liquidated": r["liquidated"],
                                })
                        bracket_rows.append({
                            "pair": pair, "anchor": int(a), "week": week_key, "T_days": T // BARS_PER_DAY,
                            "cfg": cfg_tag, "lev": lev, "is_headline": is_headline,
                            "was_flipped_cell": (not is_headline),
                            "auto": r_auto["net_return"], "reverse": r_rev["net_return"],
                            "real": r_real["net_return"], "in_bracket": bool(in_bracket),
                        })

    samples = pd.DataFrame(rows)
    brackets = pd.DataFrame(bracket_rows)
    samples.to_feather(f"{out_prefix}_samples.feather")
    brackets.to_feather(f"{out_prefix}_brackets.feather")

    summary_lines = []
    for T in HORIZONS_D:
        sub_b = brackets[brackets["T_days"] == T]
        n_ep = len(sub_b)
        n_in = int(sub_b["in_bracket"].sum())
        summary_lines.append(f"T={T}d: n_episode={n_ep}, real落在[auto,reverse]界內={n_in} ({n_in/n_ep*100:.1f}%)")
        for path_ in ("auto", "reverse", "real"):
            sub = samples[(samples["T_days"] == T) & (samples["path"] == path_)]
            v = sub["net_return"].to_numpy()
            wk = sub["week"].to_numpy()
            ci = q8grid._block_bootstrap_ci(v, wk)
            liq = sub["liquidated"].mean()
            summary_lines.append(
                f"  path={path_:8s} n={len(v):4d} mean={v.mean()*100:+7.2f}% median={np.median(v)*100:+7.2f}% "
                f"liq_rate={liq*100:5.1f}% CI95=[{ci[0]*100:+.2f},{ci[1]*100:+.2f}]%")

    # ── Q9 結案：115 個翻轉格位逐一比對 real 落在哪一側 ──────────────────
    flipped_ref = pd.read_csv(HERE / "2026-08-06_q11_phaseB_flipped_cells_ref.tsv", sep="\t")
    flipped_ref["cfg"] = flipped_ref.apply(
        lambda r: f"W{r['half_band_pct']}_N{r['grid_count']}_{r['policy']}", axis=1)
    resolved_rows = []
    for _, fr in flipped_ref.iterrows():
        cfg_tag, lev, T = fr["cfg"], int(fr["leverage"]), int(fr["horizon_d"])
        sub = brackets[(brackets["cfg"] == cfg_tag) & (brackets["lev"] == lev) & (brackets["T_days"] == T)]
        if sub.empty:
            continue
        real_mean = sub["real"].mean()
        auto_mean = sub["auto"].mean()
        rev_mean = sub["reverse"].mean()
        in_bracket_rate = sub["in_bracket"].mean()
        side = "auto側(負)" if real_mean < 0 else ("reverse側(正)" if real_mean > 0 else "邊界")
        resolved_rows.append({
            "cfg": cfg_tag, "leverage": lev, "horizon_d": T, "n": len(sub),
            "auto_mean": auto_mean, "reverse_mean": rev_mean, "real_mean": real_mean,
            "real_side": side, "in_bracket_rate": in_bracket_rate,
        })
    resolved = pd.DataFrame(resolved_rows)
    resolved.to_csv(f"{out_prefix}_flipped_resolved.tsv", sep="\t", index=False)
    n_resolved = len(resolved)
    n_auto_side = int((resolved["real_mean"] < 0).sum())
    n_rev_side = int((resolved["real_mean"] > 0).sum())
    n_out_bracket_any = int((resolved["in_bracket_rate"] < 1.0).sum())
    summary_lines.append("")
    summary_lines.append(
        f"Q9 115 翻轉格位（本子集可評估 {n_resolved} 格，3標的x3月）：real 點估計落在 "
        f"auto側(負)={n_auto_side}、reverse側(正)={n_rev_side}；"
        f"{n_out_bracket_any} 格至少一次錨點 real 落在 [auto,reverse] 界外")

    summary_txt = "\n".join(summary_lines)
    print(summary_txt)
    with open(f"{out_prefix}_summary.txt", "w") as f:
        f.write(summary_txt + "\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--out-prefix")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.out_prefix:
        ap.error("--out-prefix 為必填（或用 --self-test）")
    return run_full(args.out_prefix)


if __name__ == "__main__":
    raise SystemExit(main())
