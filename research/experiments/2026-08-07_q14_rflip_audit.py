#!/usr/bin/env python3
"""Q14（2026-08-07 run 18，`audit` 車道）——Q10 對照組 `R_flip` 的獨立實作復驗。

背景：run 13（Q13）對 run 8（Q10）做過一次獨立復算，但其限制段 1 明說——
`R_flip`（每 episode 200 次隨機符號翻轉的 R 均值）**驗不到**，因為 15m 資料在原理上
重建不出 1m 逐根的翻轉路徑。因此 `ΔR = R_act − R_flip` 只有**被減數**被獨立驗證，
翻轉機制的 `ε ≠ +1` 分支仍只有 run 8 自己的 self-test 背書。

本檔補上那一塊。**獨立性協定**（見 research/log/2026-08-07-run18.md §4）：
  1. 依 run 8 日誌 §4 的**文字規格**從頭實作，撰寫期間不閱讀原探針的翻轉實作段落。
  2. 全程 float64（run 8 的翻轉批次用 float32），RNG 用不同的 bit generator 與 seed。
  3. 向量化實作之外另寫一份逐根 for-loop 的樸素參考實作逐位元對拍
     （Q8 教訓：合成測試不能取代對拍參考實作）。

規格（抄自 research/log/2026-08-05.md §4 的四條操作化決定）：
  - 第 i 根 1m 相對前收的三個對數偏移 x_i=log(c_i/c_{i-1})、hi_i=log(h_i/c_{i-1})、
    lo_i=log(l_i/c_{i-1})；第一根的「前收」＝錨點 15m 收盤 P0。
  - 翻轉：x_i→−x_i、hi_i→−lo_i、lo_i→−hi_i（同時鏡射 intrabar 極值）。
  - 路徑在對數空間、A/B 在價格空間：A=exp(max_k Hpath_k)−1、B=1−exp(min_k Lpath_k)，
    其中 Hpath_k = C_{k−1}+hi_k、Lpath_k = C_{k−1}+lo_k、C_k=Σ_{j≤k} x_j、C_0=0；A,B 夾在 ≥0。
  - ΔR 是逐 episode 配對量：R_act − mean(200 次翻轉的 R)，再在格位內平均。

**唯讀複用**：本檔不 import 任何既有探針，只讀取 repo 內既有的
`2026-08-05_q10_shape_samples.tsv`（錨點清單與 run 8 的逐 episode 結果）與
`2026-08-05_q10_shape_grid.tsv`（run 8 的 24 格結果），以及 fetch_klines.py 抓下來的 K 線。

窗口：1m 2023-01-01~2025-06-30、15m 2022-12-01~2025-06-30。**未觸碰 2025-07-01 之後的封存段。**

用法：
  python3 2026-08-07_q14_rflip_audit.py --part det  --dir15 /tmp/kl15 --dir1m /tmp/kl1m
  python3 2026-08-07_q14_rflip_audit.py --part mc   --dir15 /tmp/kl15 --dir1m /tmp/kl1m
  python3 2026-08-07_q14_rflip_audit.py --part grid --boot 20000
"""

import argparse
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SAMPLES = HERE / "2026-08-05_q10_shape_samples.tsv"
RUN8_GRID = HERE / "2026-08-05_q10_shape_grid.tsv"
OUT_PREFIX = HERE / "2026-08-07_q14_rflip"

T_HOURS = [1, 4, 12, 24]
T_BARS = {1: 60, 4: 240, 12: 720, 24: 1440}
N_FLIP = 200                      # 凍結值（RND_BACKLOG 方向二：隨機符號翻轉 × 200 次）
MAXT = 1440
BUCKET_LABELS = ["[0,0.05)", "[0.05,0.10)", "[0.10,0.25)", "[0.25,0.50)",
                 "[0.50,0.75)", "[0.75,1.0]"]
# 三組獨立 seed：兩組 PCG64 + 一組 Philox（run 8 未在日誌宣告其 seed）
SEEDS = [("pcg64", 20260807), ("pcg64", 990017), ("philox", 424242)]


# ---------------------------------------------------------------- 基礎工具

def load_samples() -> pd.DataFrame:
    df = pd.read_csv(SAMPLES, sep="\t")
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_kl(path: Path) -> pd.DataFrame:
    df = pd.read_feather(path)
    d = pd.to_datetime(df["date"])
    if getattr(d.dtype, "tz", None) is not None:
        d = d.dt.tz_convert("UTC").dt.tz_localize(None)
    df["date"] = d
    return df.sort_values("date").reset_index(drop=True)


def pair_file(dirpath: Path, pair: str, interval: str) -> Path:
    return Path(dirpath) / f"{pair.replace('/', '_')}-{interval}.feather"


def episode_base(P0: float, h: np.ndarray, l: np.ndarray, c: np.ndarray):
    """回傳 (x, hi, lo) 三個對數偏移陣列（float64）。"""
    prev = np.empty_like(c)
    prev[0] = P0
    prev[1:] = c[:-1]
    return np.log(c / prev), np.log(h / prev), np.log(l / prev)


def _ab_from_logext(mx: np.ndarray, mn: np.ndarray):
    """對數空間極值 → 價格空間 A/B（夾在 ≥0）。"""
    A = np.maximum(np.expm1(mx), 0.0)
    B = np.maximum(-np.expm1(mn), 0.0)
    return A, B


def _R(A, B):
    s = A + B
    out = np.full(np.shape(s), np.nan, dtype=np.float64)
    ok = s > 0
    out[ok] = np.maximum(A[ok], B[ok]) / s[ok]
    return out


def flip_batch(x, hi, lo, eps, dtype=np.float64):
    """向量化：給定 (n_flip, N) 的 ε 矩陣，回傳每個 T 的 (A,B,R) 與對數空間極值。

    eps 為 ±1 的 int8 矩陣。全程 dtype（預設 float64）。
    """
    x = x.astype(dtype, copy=False)
    hi = hi.astype(dtype, copy=False)
    lo = lo.astype(dtype, copy=False)
    e = eps.astype(dtype)
    pos = eps > 0

    xf = x[None, :] * e
    hif = np.where(pos, hi[None, :], -lo[None, :])
    lof = np.where(pos, lo[None, :], -hi[None, :])

    C = np.cumsum(xf, axis=1)
    Cprev = np.empty_like(C)
    Cprev[:, 0] = 0.0
    Cprev[:, 1:] = C[:, :-1]

    H = Cprev + hif
    L = Cprev + lof
    np.maximum.accumulate(H, axis=1, out=H)
    np.minimum.accumulate(L, axis=1, out=L)

    res = {}
    for th in T_HOURS:
        k = T_BARS[th] - 1
        mx = H[:, k].astype(np.float64)
        mn = L[:, k].astype(np.float64)
        A, B = _ab_from_logext(mx, mn)
        res[th] = (A, B, _R(A, B), mx, mn)
    return res


def flip_naive(x, hi, lo, eps_row):
    """樸素逐根參考實作（純 Python 迴圈），結構與向量化版完全不同。"""
    cum = 0.0
    mx = -math.inf
    mn = math.inf
    out = {}
    want = {T_BARS[th]: th for th in T_HOURS}
    for k in range(len(x)):
        e = eps_row[k]
        if e > 0:
            xk, hk, lk = x[k], hi[k], lo[k]
        else:
            xk, hk, lk = -x[k], -lo[k], -hi[k]
        hv = cum + hk
        lv = cum + lk
        if hv > mx:
            mx = hv
        if lv < mn:
            mn = lv
        cum += xk
        if (k + 1) in want:
            A = max(math.expm1(mx), 0.0)
            B = max(-math.expm1(mn), 0.0)
            R = max(A, B) / (A + B) if (A + B) > 0 else float("nan")
            out[want[k + 1]] = (A, B, R, mx, mn)
    return out


def make_rng(kind: str, seed: int, stream: int):
    ss = np.random.SeedSequence([seed, stream])
    bg = np.random.Philox(ss) if kind == "philox" else np.random.PCG64(ss)
    return np.random.Generator(bg)


# ---------------------------------------------------------------- 逐標的處理

def prep_pair(pair: str, dir15: Path, dir1m: Path, anchors: pd.DataFrame):
    """回傳 (list of (x,hi,lo) float64 arrays, P0 array, direct A/B, 診斷 dict)。"""
    k15 = load_kl(pair_file(dir15, pair, "15m"))
    k1 = load_kl(pair_file(dir1m, pair, "1m"))

    idx15 = pd.Index(k15["date"])
    idx1 = pd.Index(k1["date"])
    pos15 = idx15.get_indexer(anchors["date"])
    starts = idx1.get_indexer(anchors["date"] + pd.Timedelta(minutes=15))

    diag = {"pair": pair, "n_anchor": len(anchors),
            "miss15": int((pos15 < 0).sum()), "miss1m": int((starts < 0).sum())}

    h1 = k1["high"].to_numpy(np.float64)
    l1 = k1["low"].to_numpy(np.float64)
    c1 = k1["close"].to_numpy(np.float64)
    d1 = k1["date"].to_numpy()
    P0 = k15["close"].to_numpy(np.float64)[pos15]
    c15_prev_close_1m = c1[np.maximum(starts - 1, 0)]

    bases, directs, contig, n_clamp = [], [], 0, [0, 0]
    for j, s in enumerate(starts):
        sl = slice(s, s + MAXT)
        # 連續性檢查：窗內 1440 根必須逐分鐘連續
        span = (d1[s + MAXT - 1] - d1[s]) / np.timedelta64(1, "m")
        if span == MAXT - 1:
            contig += 1
        x, hi, lo = episode_base(P0[j], h1[sl], l1[sl], c1[sl])
        bases.append((x, hi, lo))
        row = {}
        for th in T_HOURS:
            n = T_BARS[th]
            # 與 run 8 §4 決定 3 一致：A、B 依定義夾在 ≥0（整段落在 P0 同側時觸發）
            dA = h1[s:s + n].max() / P0[j] - 1.0
            dB = 1.0 - l1[s:s + n].min() / P0[j]
            n_clamp[0] += int(dA < 0)
            n_clamp[1] += int(dB < 0)
            row[th] = (max(dA, 0.0), max(dB, 0.0))
        directs.append(row)
    diag["n_contiguous"] = contig
    diag["n_clamped_A"] = n_clamp[0]
    diag["n_clamped_B"] = n_clamp[1]
    diag["max_abs_P0_vs_1m"] = float(np.max(np.abs(P0 / c15_prev_close_1m - 1.0)))
    return bases, P0, directs, diag


def part_det_pair(args):
    """Part 1：確定性檢定（ε≡+1、ε≡−1、固定樣式對拍）。"""
    pair, dir15, dir1m, sub, n_brute = args
    bases, P0, directs, diag = prep_pair(pair, Path(dir15), Path(dir1m), sub)
    N = MAXT

    rows = []
    err_plus = {th: 0.0 for th in T_HOURS}      # ε≡+1 vs 直接取極值
    err_s8 = {th: 0.0 for th in T_HOURS}        # 我的 R_act vs run 8 samples.tsv
    err_s8amp = {th: 0.0 for th in T_HOURS}
    err_mir_log = {th: 0.0 for th in T_HOURS}   # ε≡−1 對數空間 R 不變性
    err_mir_swap = {th: 0.0 for th in T_HOURS}  # ε≡−1 的 A↔B 互換（對數空間）
    dev_mir_price = {th: [] for th in T_HOURS}  # ε≡−1 價格空間 R 的偏移（非零是預期內）

    eps_p = np.ones((1, N), dtype=np.int8)
    eps_m = -np.ones((1, N), dtype=np.int8)

    for j, (x, hi, lo) in enumerate(bases):
        rp = flip_batch(x, hi, lo, eps_p)
        rm = flip_batch(x, hi, lo, eps_m)
        for th in T_HOURS:
            A, B, R, mx, mn = rp[th]
            dA, dB = directs[j][th]
            err_plus[th] = max(err_plus[th], abs(A[0] - dA), abs(B[0] - dB))
            err_s8[th] = max(err_s8[th], abs(R[0] - sub[f"R_act_{th}"].iat[j]))
            err_s8amp[th] = max(err_s8amp[th], abs(A[0] + B[0] - sub[f"amp_{th}"].iat[j]))
            Am, Bm, Rm, mxm, mnm = rm[th]
            # 對數空間：鏡射後 A'↔B' 互換 ⇒ R_log 不變
            Rlog = max(mx[0], -mn[0]) / (mx[0] + (-mn[0]))
            Rlogm = max(mxm[0], -mnm[0]) / (mxm[0] + (-mnm[0]))
            err_mir_log[th] = max(err_mir_log[th], abs(Rlog - Rlogm))
            err_mir_swap[th] = max(err_mir_swap[th],
                                   abs(mxm[0] - (-mn[0])), abs((-mnm[0]) - mx[0]))
            dev_mir_price[th].append(Rm[0] - R[0])

    # Part 1(c)：固定 ε 樣式 × 樸素參考實作對拍（隨機抽樣錨點）
    rng = np.random.default_rng(777)
    pick = rng.choice(len(bases), size=min(n_brute, len(bases)), replace=False)
    pats = {}
    half = np.ones(N, dtype=np.int8); half[N // 2:] = -1
    alt = np.where(np.arange(N) % 2 == 0, 1, -1).astype(np.int8)
    rnd = (rng.integers(0, 2, size=N, dtype=np.int8) * 2 - 1)
    for name, e in (("half", half), ("alt", alt), ("rand", rnd)):
        m = 0.0
        for j in pick:
            x, hi, lo = bases[j]
            vec = flip_batch(x, hi, lo, e[None, :])
            nai = flip_naive(x, hi, lo, e)
            for th in T_HOURS:
                m = max(m, abs(vec[th][0][0] - nai[th][0]),
                        abs(vec[th][1][0] - nai[th][1]),
                        abs(vec[th][2][0] - nai[th][2]))
        pats[name] = m

    for th in T_HOURS:
        rows.append({
            "pair": pair, "T_h": th,
            "max_err_eps_plus_vs_direct": err_plus[th],
            "max_err_Ract_vs_run8": err_s8[th],
            "max_err_amp_vs_run8": err_s8amp[th],
            "max_err_mirror_logR": err_mir_log[th],
            "max_err_mirror_AB_swap": err_mir_swap[th],
            "max_dev_mirror_priceR": float(np.max(np.abs(dev_mir_price[th]))),
            "mean_signed_dev_mirror_priceR": float(np.mean(dev_mir_price[th])),
            "mean_abs_dev_mirror_priceR": float(np.mean(np.abs(dev_mir_price[th]))),
            "brute_half": pats["half"], "brute_alt": pats["alt"], "brute_rand": pats["rand"],
        })
    return rows, diag


def part_mc_pair(args):
    """Part 2/3：獨立蒙地卡羅 R_flip（多 seed）＋ float32/64 與 ε 抽樣偏誤檢查。"""
    pair, dir15, dir1m, sub, do_f32, stream = args
    bases, P0, directs, diag = prep_pair(pair, Path(dir15), Path(dir1m), sub)
    N = MAXT
    n = len(bases)

    out = {(kind, sd, th): np.empty(n) for (kind, sd) in SEEDS for th in T_HOURS}
    eps_sum = 0
    eps_cnt = 0
    f32_dev = []

    for si, (kind, sd) in enumerate(SEEDS):
        rng = make_rng(kind, sd, stream)
        for j, (x, hi, lo) in enumerate(bases):
            eps = (rng.integers(0, 2, size=(N_FLIP, N), dtype=np.int8) * 2 - 1)
            if si == 0:
                eps_sum += int(eps.sum())
                eps_cnt += eps.size
            r = flip_batch(x, hi, lo, eps)
            for th in T_HOURS:
                out[(kind, sd, th)][j] = np.nanmean(r[th][2])
            if do_f32 and si == 0 and j < 50:
                r32 = flip_batch(x, hi, lo, eps, dtype=np.float32)
                for th in T_HOURS:
                    f32_dev.append(float(np.nanmax(np.abs(r32[th][2] - r[th][2]))))

    rows = []
    for j in range(n):
        rec = {"pair": pair, "date": sub["date"].iat[j], "iso": sub["iso"].iat[j],
               "bucket": int(sub["bucket"].iat[j])}
        for th in T_HOURS:
            rec[f"amp_{th}"] = float(sub[f"amp_{th}"].iat[j])
            rec[f"R_act_{th}"] = float(sub[f"R_act_{th}"].iat[j])
            rec[f"R_flip_run8_{th}"] = float(sub[f"R_flip_{th}"].iat[j])
            for (kind, sd) in SEEDS:
                rec[f"R_flip_{kind}{sd}_{th}"] = float(out[(kind, sd, th)][j])
        rows.append(rec)
    diag["eps_mean"] = eps_sum / eps_cnt if eps_cnt else float("nan")
    diag["eps_n"] = eps_cnt
    diag["f32_max_dev"] = float(np.max(f32_dev)) if f32_dev else float("nan")
    diag["f32_mean_dev"] = float(np.mean(f32_dev)) if f32_dev else float("nan")
    return rows, diag


# ---------------------------------------------------------------- Part 4：判定重推

def block_bootstrap(df: pd.DataFrame, dr_col: str, amp_col: str, boot: int, seed: int):
    """逐 ISO 週 block bootstrap：回傳 (dR 的 CI 四端點, cap 的 CI 四端點)。"""
    weeks = df["iso"].to_numpy()
    uw, inv = np.unique(weeks, return_inverse=True)
    nw = len(uw)
    dr = df[dr_col].to_numpy(np.float64)
    amp = df[amp_col].to_numpy(np.float64)
    s_dr = np.bincount(inv, weights=dr, minlength=nw)
    s_amp = np.bincount(inv, weights=amp, minlength=nw)
    cnt = np.bincount(inv, minlength=nw).astype(np.float64)

    rng = np.random.default_rng(seed)
    pick = rng.integers(0, nw, size=(boot, nw))
    c = cnt[pick].sum(axis=1)
    m_dr = s_dr[pick].sum(axis=1) / c
    m_amp = s_amp[pick].sum(axis=1) / c
    cap = m_dr * m_amp * 100.0
    a_adj = 0.05 / 24.0
    q = [2.5, 97.5, a_adj / 2 * 100, (1 - a_adj / 2) * 100]
    return np.percentile(m_dr, q), np.percentile(cap, q)


def build_grid(samp: pd.DataFrame, rflip_col_tpl: str, boot: int, seed: int) -> pd.DataFrame:
    rows = []
    for b in range(6):
        for th in T_HOURS:
            sub = samp[samp["bucket"] == b].copy()
            sub["_dr"] = sub[f"R_act_{th}"] - sub[rflip_col_tpl.format(th=th)]
            sub["_amp"] = sub[f"amp_{th}"]
            dr = float(sub["_dr"].mean())
            amp = float(sub["_amp"].mean())
            (dlo, dhi, dloA, dhiA), (clo, chi, cloA, chiA) = block_bootstrap(
                sub, "_dr", "_amp", boot, seed + b * 17 + th)
            rows.append({
                "bucket": BUCKET_LABELS[b], "T_h": th, "n": len(sub),
                "R_act_mean": float(sub[f"R_act_{th}"].mean()),
                "R_flip_mean": float(sub[rflip_col_tpl.format(th=th)].mean()),
                "dR": dr, "amp_mean_pct": amp * 100.0, "cap_pct": dr * amp * 100.0,
                "dR_lo95": dlo, "dR_hi95": dhi, "dR_loADJ": dloA, "dR_hiADJ": dhiA,
                "cap_lo95_pct": clo, "cap_hi95_pct": chi,
                "cap_loADJ_pct": cloA, "cap_hiADJ_pct": chiA,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["det", "mc", "grid"], required=True)
    ap.add_argument("--dir15", default="/tmp/kl15")
    ap.add_argument("--dir1m", default="/tmp/kl1m")
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--boot", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=4242)
    ap.add_argument("--n-brute", type=int, default=25)
    a = ap.parse_args()

    samp = load_samples()
    pairs = list(dict.fromkeys(samp["pair"]))

    if a.part in ("det", "mc"):
        fn = part_det_pair if a.part == "det" else part_mc_pair
        jobs = []
        for i, p in enumerate(pairs):
            sub = samp[samp["pair"] == p].reset_index(drop=True)
            if a.part == "det":
                jobs.append((p, a.dir15, a.dir1m, sub, a.n_brute))
            else:
                jobs.append((p, a.dir15, a.dir1m, sub, True, i))
        allrows, diags = [], []
        with ProcessPoolExecutor(max_workers=a.procs) as ex:
            for rows, d in ex.map(fn, jobs):
                allrows.extend(rows)
                diags.append(d)
                print(f"  [{d['pair']}] done  n={d['n_anchor']}", flush=True)
        suffix = "det" if a.part == "det" else "mc"
        pd.DataFrame(allrows).to_csv(f"{OUT_PREFIX}_{suffix}.tsv", sep="\t", index=False)
        pd.DataFrame(diags).to_csv(f"{OUT_PREFIX}_{suffix}_diag.tsv", sep="\t", index=False)
        print(pd.DataFrame(diags).to_string(index=False))
        if a.part == "det":
            d = pd.DataFrame(allrows)
            print("\n=== Part 1 摘要（全標的取最大）===")
            for c in ["max_err_eps_plus_vs_direct", "max_err_Ract_vs_run8",
                      "max_err_amp_vs_run8", "max_err_mirror_logR",
                      "max_err_mirror_AB_swap", "max_dev_mirror_priceR",
                      "mean_abs_dev_mirror_priceR",
                      "brute_half", "brute_alt", "brute_rand"]:
                print(f"  {c:32s} {d[c].max():.3e}")
        return

    # part == grid
    mc = pd.read_csv(f"{OUT_PREFIX}_mc.tsv", sep="\t")
    run8 = pd.read_csv(RUN8_GRID, sep="\t")
    cols = {"run8": "R_flip_run8_{th}"}
    for (kind, sd) in SEEDS:
        cols[f"{kind}{sd}"] = f"R_flip_{kind}{sd}_{{th}}"

    grids = {k: build_grid(mc, tpl, a.boot, a.seed) for k, tpl in cols.items()}
    for k, g in grids.items():
        g.to_csv(f"{OUT_PREFIX}_grid_{k}.tsv", sep="\t", index=False)

    # 逐格 seed 間標準差（蒙地卡羅誤差的直接估計）
    keys = [k for k in cols if k != "run8"]
    base = grids[keys[0]][["bucket", "T_h", "n"]].copy()
    stack = np.stack([grids[k]["R_flip_mean"].to_numpy() for k in keys])
    base["R_flip_mine_mean"] = stack.mean(axis=0)
    base["R_flip_mine_sd"] = stack.std(axis=0, ddof=1)
    base["R_flip_run8"] = grids["run8"]["R_flip_mean"].to_numpy()
    base["diff_mine_minus_run8"] = base["R_flip_mine_mean"] - base["R_flip_run8"]
    base["dR_mine"] = np.stack([grids[k]["dR"].to_numpy() for k in keys]).mean(axis=0)
    base["dR_run8"] = grids["run8"]["dR"].to_numpy()
    r8 = run8.set_index(["bucket", "T_h"])
    base["dR_run8_file"] = [r8.loc[(b, t), "dR"] for b, t in zip(base["bucket"], base["T_h"])]
    base["cap_run8_file_pct"] = [r8.loc[(b, t), "cap_pct"] for b, t in zip(base["bucket"], base["T_h"])]
    base.to_csv(f"{OUT_PREFIX}_compare.tsv", sep="\t", index=False)
    print(base.to_string(index=False))

    # ---- Part 2 判準：逐格差異 vs 4×se_MC，以及 24 格的系統性偏移（符號檢定）
    se = base["R_flip_mine_sd"] / math.sqrt(len(keys))
    within = (base["diff_mine_minus_run8"].abs() <= 4 * se)
    npos = int((base["diff_mine_minus_run8"] > 0).sum())
    print("\n=== Part 2 判準 ===")
    print(f"  逐格 |R_flip 差| 落在 4×se_MC 內：{int(within.sum())}/24")
    print(f"  最大 |R_flip 差| = {base['diff_mine_minus_run8'].abs().max():.3e}"
          f"   最大 4×se_MC = {(4*se).max():.3e}")
    print(f"  seed 間 sd 範圍 = [{base['R_flip_mine_sd'].min():.3e},"
          f" {base['R_flip_mine_sd'].max():.3e}]")
    print(f"  24 格中 (mine − run8) > 0 的格數 = {npos}/24（無系統性偏移應 ≈12）")
    print(f"  最大 |dR 差| = {(base['dR_mine']-base['dR_run8_file']).abs().max():.3e}")

    # ---- Part 4 判準：Q10 的三個決定性宣告
    print("\n=== Part 4 判定重推 ===")
    for k, g in grids.items():
        sig_adj = g[(g["dR_loADJ"] > 0) | (g["dR_hiADJ"] < 0)]
        sig_95 = g[(g["dR_lo95"] > 0) | (g["dR_hi95"] < 0)]
        cells = ", ".join(f"{r.bucket}×{r.T_h}h" for r in sig_adj.itertuples())
        print(f"  [{k:12s}] 調整後顯著 {len(sig_adj)} 格（{cells}）；未調整顯著 {len(sig_95)} 格；"
              f" cap 點估計最大 {g['cap_pct'].max():.4f}%；"
              f" cap 調整後 CI 上界最大 {g['cap_hiADJ_pct'].max():.4f}%")


if __name__ == "__main__":
    main()
