#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Q13 — run 8（Q10 方向二 Phase 0）結果的獨立復算稽核。

車道 audit（`research/program.md` §2）：**只覆核既有主張，不提新主張**。
本腳本刻意**不 import** run 8 的探針 `2026-08-05_q10_shape_capturable_trend.py`，
聚合、block bootstrap、桶界、可捕獲報酬換算全部獨立重寫，
以免把原探針的錯誤一起複製過來。

兩個部分：

Part A（彙總層）
    只讀 repo 內既有的 `2026-08-05_q10_shape_samples.tsv`（9,010 列逐 episode 明細），
    獨立重算 24 格全部統計量與 CI，逐項核對 run 8 日誌 §8.1~§8.4 的每個宣稱數字。

Part B（上游層，獨立資料路徑）
    用重抓的 **15m** K 線獨立重算同一批錨點的 A/B/R_act/amp 與 bbw_pct/bucket。
    數學上 15m 極值 ≡ 對應區間的 1m 極值（15m 的 high 就是其 1m high 的極大值），
    故 `R_act` 與 `amp` 可在完全不碰 1m 資料的情況下獨立驗證。
    `R_flip`（200 次符號翻轉基準）依賴 1m 路徑重建，本層驗證不到——照實聲明。

用法：
    python3 2026-08-06_q13_audit_q10_recompute.py --part A --boot 20000 --seed 4242
    python3 2026-08-06_q13_audit_q10_recompute.py --part B --dir15 /tmp/kl15
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SAMPLES = os.path.join(HERE, "2026-08-05_q10_shape_samples.tsv")
GRID_REF = os.path.join(HERE, "2026-08-05_q10_shape_grid.tsv")

# 凍結網格（`docs/RND_BACKLOG.md` 方向二，一字沿用；本腳本獨立打字，不從原探針 import）
BUCKET_EDGES = [0.0, 0.05, 0.10, 0.25, 0.50, 0.75, 1.0]
BUCKET_NAMES = ["[0,0.05)", "[0.05,0.10)", "[0.10,0.25)",
                "[0.25,0.50)", "[0.50,0.75)", "[0.75,1.0]"]
T_HOURS = [1, 4, 12, 24]
N_CELLS = 24                       # 6 桶 × 4 個 T
ALPHA_ADJ = 0.05 / N_CELLS         # ≈ 0.00208 → 99.79% CI
PAIRS = ["BTC/USDT", "ETH/USDT", "ADA/USDT", "SOL/USDT", "XRP/USDT",
         "DOGE/USDT", "BNB/USDT", "LINK/USDT", "LTC/USDT", "AVAX/USDT"]


def bucket_of(p: float) -> int:
    """bbw_pct -> 桶索引（左閉右開，最後一桶含 1.0）。獨立實作。"""
    for k in range(6):
        lo, hi = BUCKET_EDGES[k], BUCKET_EDGES[k + 1]
        if p >= lo and (p < hi or (k == 5 and p <= 1.0)):
            return k
    return -1


# ---------------------------------------------------------------- block bootstrap

def _week_sums(vals, weeks):
    """把逐 episode 值壓成逐 ISO 週的 (count, sum)，供 block bootstrap 重抽。"""
    codes, _ = pd.factorize(weeks)
    m = codes.max() + 1
    cnt = np.bincount(codes, minlength=m).astype(np.float64)
    out = []
    for v in vals:
        out.append(np.bincount(codes, weights=np.asarray(v, dtype=np.float64), minlength=m))
    return cnt, out


def block_boot_stats(vals, weeks, n_boot, rng, chunk=20000):
    """逐 ISO 週 block bootstrap。回傳每個統計量的 bootstrap 分佈：
    vals 內每個陣列各自回傳 mean 的分佈，另外回傳 mean(vals[0])*mean(vals[1]) 的分佈
    （＝可捕獲報酬 ΔR × E[A+B] 的 bootstrap，僅當 len(vals)>=2）。
    重抽單位是「週」（整週的 episode 一起進出），沿用 Q1' 的教訓。"""
    cnt, sums = _week_sums(vals, weeks)
    m = len(cnt)
    means = [np.empty(n_boot) for _ in sums]
    prod = np.empty(n_boot) if len(sums) >= 2 else None
    done = 0
    while done < n_boot:
        k = min(chunk, n_boot - done)
        idx = rng.integers(0, m, size=(k, m))
        bc = cnt[idx].sum(axis=1)
        bm = []
        for j, s in enumerate(sums):
            bm_j = s[idx].sum(axis=1) / bc
            means[j][done:done + k] = bm_j
            bm.append(bm_j)
        if prod is not None:
            prod[done:done + k] = bm[0] * bm[1]
        done += k
    return means, prod


def ci(dist, alpha):
    return float(np.quantile(dist, alpha / 2)), float(np.quantile(dist, 1 - alpha / 2))


# ---------------------------------------------------------------- Part A

def part_a(boot, seed, out_prefix):
    df = pd.read_csv(SAMPLES, sep="\t")
    print(f"[A] samples.tsv 載入：{len(df)} 列，{df['pair'].nunique()} 標的，"
          f"{df['iso'].nunique()} 個 ISO 週")

    # A0：桶別可重現性——用 bbw_pct 獨立重算桶索引，與檔案內的 bucket 欄比對
    reb = df["bbw_pct"].map(bucket_of)
    n_bucket_mismatch = int((reb != df["bucket"]).sum())
    print(f"[A0] bucket 欄獨立重算不一致列數：{n_bucket_mismatch} / {len(df)}")

    # A0b：R 值域與 R = max(A,B)/(A+B) 的內部一致性（R∈[0.5,1]）
    r_cols = [f"R_act_{h}" for h in T_HOURS]
    r_min = float(df[r_cols].min().min())
    r_max = float(df[r_cols].max().max())
    rf_cols = [f"R_flip_{h}" for h in T_HOURS]
    print(f"[A0b] R_act 值域 [{r_min:.6f}, {r_max:.6f}]（應 ⊂ [0.5,1]）；"
          f"R_flip 值域 [{df[rf_cols].min().min():.6f}, {df[rf_cols].max().max():.6f}]")

    # A0c：dR = R_act − R_flip 的逐列恆等（檢查檔案本身是否自洽）
    idmax = 0.0
    for h in T_HOURS:
        d = (df[f"R_act_{h}"] - df[f"R_flip_{h}"] - df[f"dR_{h}"]).abs().max()
        idmax = max(idmax, float(d))
    print(f"[A0c] |R_act − R_flip − dR| 全列最大值：{idmax:.3e}")

    rng = np.random.default_rng(seed)
    rows = []
    for b in range(6):
        sub_b = df[df["bucket"] == b]
        for h in T_HOURS:
            dr = sub_b[f"dR_{h}"].to_numpy(float)
            drm = sub_b[f"dRm_{h}"].to_numpy(float)
            amp = sub_b[f"amp_{h}"].to_numpy(float) * 100.0     # → %
            absnet = sub_b[f"absnet_{h}"].to_numpy(float) * 100.0
            ract = sub_b[f"R_act_{h}"].to_numpy(float)
            rflip = sub_b[f"R_flip_{h}"].to_numpy(float)
            wk = sub_b["iso"].to_numpy()
            n = len(dr)
            (m_dr, m_amp, m_drm), prod = block_boot_stats([dr, amp, drm], wk, boot, rng)
            lo95, hi95 = ci(m_dr, 0.05)
            loA, hiA = ci(m_dr, ALPHA_ADJ)
            mlo95, mhi95 = ci(m_drm, 0.05)
            mloA, mhiA = ci(m_drm, ALPHA_ADJ)
            clo95, chi95 = ci(prod, 0.05)
            cloA, chiA = ci(prod, ALPHA_ADJ)
            rows.append(dict(
                bucket=BUCKET_NAMES[b], T_h=h, n=n,
                R_act_mean=ract.mean(), R_act_med=float(np.median(ract)),
                R_flip_mean=rflip.mean(),
                dR=dr.mean(), dR_mirror=drm.mean(),
                amp_mean_pct=amp.mean(), absnet_mean_pct=absnet.mean(),
                net_over_amp=absnet.mean() / amp.mean(),
                dR_lo95=lo95, dR_hi95=hi95, dR_loADJ=loA, dR_hiADJ=hiA,
                dRm_lo95=mlo95, dRm_hi95=mhi95, dRm_loADJ=mloA, dRm_hiADJ=mhiA,
                cap_pct=dr.mean() * amp.mean(),
                cap_lo95_pct=clo95, cap_hi95_pct=chi95,
                cap_loADJ_pct=cloA, cap_hiADJ_pct=chiA,
            ))
    aud = pd.DataFrame(rows)
    aud.to_csv(out_prefix + "_gridA.tsv", sep="\t", index=False)

    # ---- 與 run 8 的 grid.tsv 逐欄比對（點估計應完全一致；CI 因 seed 不同會有差異）
    ref = pd.read_csv(GRID_REF, sep="\t")
    key = ["bucket", "T_h"]
    mg = aud.merge(ref, on=key, suffixes=("_new", "_ref"))
    assert len(mg) == 24, f"格位對不齊：{len(mg)}"
    det_cols = ["n", "R_act_mean", "R_act_med", "R_flip_mean", "dR", "dR_mirror",
                "amp_mean_pct", "absnet_mean_pct"]
    ci_cols = ["dR_lo95", "dR_hi95", "dR_loADJ", "dR_hiADJ",
               "dRm_lo95", "dRm_hi95", "dRm_loADJ", "dRm_hiADJ",
               "cap_lo95_pct", "cap_hi95_pct", "cap_loADJ_pct", "cap_hiADJ_pct"]
    print("\n[A1] 決定性統計量（無隨機性，應逐格完全一致）")
    diag = []
    for c in det_cols:
        d = (mg[c + "_new"] - mg[c + "_ref"]).abs()
        print(f"      {c:16s} max|Δ| = {d.max():.3e}")
        diag.append(dict(col=c, kind="deterministic", max_abs_diff=float(d.max())))
    print("\n[A2] bootstrap CI（seed 不同 ⇒ 必有蒙地卡羅差異，看量級是否合理）")
    for c in ci_cols:
        d = (mg[c + "_new"] - mg[c + "_ref"]).abs()
        print(f"      {c:16s} max|Δ| = {d.max():.3e}   mean|Δ| = {d.mean():.3e}")
        diag.append(dict(col=c, kind="bootstrap", max_abs_diff=float(d.max()),
                         mean_abs_diff=float(d.mean())))
    # cap 點估計：ref 的 cap_pct
    d = (mg["cap_pct_new"] - mg["cap_pct_ref"]).abs()
    print(f"      {'cap_pct':16s} max|Δ| = {d.max():.3e}（點估計，應一致）")
    diag.append(dict(col="cap_pct", kind="deterministic", max_abs_diff=float(d.max())))
    pd.DataFrame(diag).to_csv(out_prefix + "_diffA.tsv", sep="\t", index=False)

    # ---- 逐項核對 run 8 日誌的宣稱
    print("\n[A3] run 8 日誌宣稱逐項核對")
    sig95 = aud[(aud.dR_lo95 > 0) | (aud.dR_hi95 < 0)]
    sigadj = aud[(aud.dR_loADJ > 0) | (aud.dR_hiADJ < 0)]
    print(f"      未調整 95% CI 不含 0 的格數：{len(sig95)}（日誌宣稱 5）")
    for _, r in sig95.iterrows():
        print(f"        {r.bucket:14s} T={r.T_h:<3d} n={r.n:<5d} dR={r.dR:+.4f} "
              f"95%[{r.dR_lo95:+.4f},{r.dR_hi95:+.4f}] ADJ[{r.dR_loADJ:+.4f},{r.dR_hiADJ:+.4f}]")
    print(f"      調整後 99.79% CI 不含 0 的格數：{len(sigadj)}（日誌宣稱 1）")
    for _, r in sigadj.iterrows():
        print(f"        {r.bucket:14s} T={r.T_h:<3d} dR={r.dR:+.4f} "
              f"ADJ[{r.dR_loADJ:+.4f},{r.dR_hiADJ:+.4f}] cap={r.cap_pct:+.4f}% "
              f"capADJ[{r.cap_loADJ_pct:+.4f},{r.cap_hiADJ_pct:+.4f}]%")
    # 鏡射版（§1.3）
    sigadj_m = aud[(aud.dRm_loADJ > 0) | (aud.dRm_hiADJ < 0)]
    print(f"      鏡射版調整後不含 0 的格數：{len(sigadj_m)}（日誌宣稱 1，同一格）")
    print(f"      全網格 cap_pct 最大值：{aud.cap_pct.max():+.4f}%（日誌宣稱 +0.0886%）"
          f" @ {aud.loc[aud.cap_pct.idxmax(), 'bucket']} × T={aud.loc[aud.cap_pct.idxmax(), 'T_h']}")
    print(f"      全網格 cap_hi95 最大值：{aud.cap_hi95_pct.max():+.4f}%（日誌宣稱 +0.1443%）")
    print(f"      全網格 cap_hiADJ 最大值：{aud.cap_hiADJ_pct.max():+.4f}%（日誌宣稱 +0.1838%）")
    print(f"      R_flip 均值範圍：[{aud.R_flip_mean.min():.4f}, {aud.R_flip_mean.max():.4f}]"
          f"（日誌宣稱 0.7728~0.7818）")
    print(f"      E|淨位移|/E[A+B] 範圍：[{aud.net_over_amp.min():.4f}, "
          f"{aud.net_over_amp.max():.4f}]（日誌宣稱 0.448~0.517，理論 0.5）")
    # E[A+B] 逐桶單調
    piv = aud.pivot(index="bucket", columns="T_h", values="amp_mean_pct").reindex(BUCKET_NAMES)
    mono = {int(h): bool((piv[h].diff().dropna() > 0).all()) for h in T_HOURS}
    print(f"      E[A+B] 逐桶單調遞增（四個 T）：{mono}（日誌宣稱全部單調、零反轉）")
    print("\n[A4] E[A+B] 表（%）")
    print(piv.round(3).to_string())
    print("\n[A5] ΔR 主表（點估計）")
    print(aud.pivot(index="bucket", columns="T_h", values="dR").reindex(BUCKET_NAMES).round(4).to_string())

    # ---- 經濟門檻對照（TRADEABILITY_PREREG §3.3）
    print("\n[A6] 經濟門檻對照（`TRADEABILITY_PREREG.md` §3.3）")
    for name, thr in [("完整門檻 2×來回0.14%", 0.28), ("無餘裕 0.14%", 0.14),
                      ("滑價歸零 2×0.10%", 0.20), ("滑價歸零無餘裕 0.10%", 0.10)]:
        print(f"      {name:22s} = {thr:.2f}% → cap 點估計最大 {aud.cap_pct.max():.4f}% "
              f"{'≥' if aud.cap_pct.max() >= thr else '<'} 門檻 ；"
              f"cap 調整後 CI 上界最大 {aud.cap_hiADJ_pct.max():.4f}% "
              f"{'≥' if aud.cap_hiADJ_pct.max() >= thr else '<'} 門檻")
    return aud


# ---------------------------------------------------------------- Part B

def load15(dir15, pair):
    """讀 fetch_klines.py 產出的 15m feather（每標的一檔），排序去重。"""
    sym = pair.replace("/", "_")
    fs = sorted([f for f in os.listdir(dir15)
                 if f.startswith(sym + "-15m") and f.endswith(".feather")])
    if not fs:
        raise FileNotFoundError(f"{dir15} 找不到 {sym} 的 15m feather")
    d = pd.concat([pd.read_feather(os.path.join(dir15, f)) for f in fs], ignore_index=True)
    d["date"] = pd.to_datetime(d["date"])
    if getattr(d["date"].dt, "tz", None) is not None:   # feather 是 tz-aware UTC，samples.tsv 是 naive
        d["date"] = d["date"].dt.tz_convert("UTC").dt.tz_localize(None)
    return d.sort_values("date").drop_duplicates("date").reset_index(drop=True)


def part_b(dir15, out_prefix):
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    from detector import add_indicators, PARAMS      # 唯讀複用 production 參數（紅線 2）
    print(f"[B] detector.PARAMS = {PARAMS}")

    smp = pd.read_csv(SAMPLES, sep="\t")
    smp["date"] = pd.to_datetime(smp["date"])

    recs, struct = [], []
    for pair in PAIRS:
        d15 = load15(dir15, pair)
        d15 = add_indicators(d15)
        pos = pd.Series(np.arange(len(d15)), index=pd.DatetimeIndex(d15["date"]))
        hi = d15["high"].to_numpy(float)
        lo = d15["low"].to_numpy(float)
        cl = d15["close"].to_numpy(float)
        bw = d15["bbw_pct"].to_numpy(float)
        sub = smp[smp["pair"] == pair].sort_values("date").reset_index(drop=True)
        loc = pos.reindex(pd.DatetimeIndex(sub["date"])).to_numpy()
        idxs = []
        for k, (_, r) in enumerate(sub.iterrows()):
            if np.isnan(loc[k]):
                recs.append(dict(pair=pair, date=r["date"], err="anchor_not_found"))
                continue
            i = int(loc[k])
            idxs.append(i)
            P0 = cl[i]
            rec = dict(pair=pair, date=r["date"], err="",
                       bbw_ref=r["bbw_pct"], bbw_new=bw[i],
                       bucket_ref=int(r["bucket"]), bucket_new=bucket_of(float(bw[i])))
            for h in T_HOURS:
                nb = h * 4                                  # 15m 根數
                w_hi = hi[i + 1:i + 1 + nb]                 # 窗口從當根之後起算（不含當根）
                w_lo = lo[i + 1:i + 1 + nb]
                A = w_hi.max() / P0 - 1.0
                B = 1.0 - w_lo.min() / P0
                A = max(A, 0.0)
                B = max(B, 0.0)
                amp = A + B
                R = max(A, B) / amp if amp > 0 else np.nan
                rec[f"amp_ref_{h}"] = r[f"amp_{h}"]
                rec[f"amp_new_{h}"] = amp
                rec[f"R_ref_{h}"] = r[f"R_act_{h}"]
                rec[f"R_new_{h}"] = R
            recs.append(rec)
        idxs = np.array(idxs)
        gaps = np.diff(idxs)
        phases = pd.Series(sub["date"].dt.hour * 60 + sub["date"].dt.minute).nunique()
        struct.append(dict(pair=pair, n_anchor=len(sub),
                           gap_min=int(gaps.min()), gap_max=int(gaps.max()),
                           gap_mode=int(pd.Series(gaps).mode().iloc[0]),
                           n_overlap_24h=int((gaps < 96).sum()),
                           n_distinct_phase=int(phases),
                           n_iso_week=int(sub["iso"].nunique())))
    res = pd.DataFrame(recs)
    st = pd.DataFrame(struct)
    res.to_csv(out_prefix + "_partB_rows.tsv", sep="\t", index=False)
    st.to_csv(out_prefix + "_partB_struct.tsv", sep="\t", index=False)

    print(f"\n[B1] 錨點對齊：{len(res)} 列，找不到錨點 {int((res.err=='anchor_not_found').sum())} 列")
    ok = res[res.err == ""]
    print(f"\n[B2] bbw_pct 獨立重算（detector.add_indicators，同一組 production PARAMS）")
    dbw = (ok.bbw_new - ok.bbw_ref).abs()
    print(f"      max|Δbbw_pct| = {dbw.max():.3e}   mean = {dbw.mean():.3e}")
    print(f"      bucket 不一致列數 = {int((ok.bucket_new != ok.bucket_ref).sum())} / {len(ok)}")
    print(f"\n[B3] A/B/R 由 15m 極值獨立重算 vs samples.tsv（1m 路徑重建版）")
    b3 = []
    for h in T_HOURS:
        da = (ok[f"amp_new_{h}"] - ok[f"amp_ref_{h}"]).abs()
        dr = (ok[f"R_new_{h}"] - ok[f"R_ref_{h}"]).abs()
        print(f"      T={h:<3d}h  max|Δamp| = {da.max():.3e}  mean = {da.mean():.3e}   | "
              f"max|ΔR| = {dr.max():.3e}  mean = {dr.mean():.3e}  |  #|ΔR|>1e-6 = {int((dr>1e-6).sum())}")
        b3.append(dict(T_h=h, max_abs_d_amp=float(da.max()), mean_abs_d_amp=float(da.mean()),
                       max_abs_d_R=float(dr.max()), mean_abs_d_R=float(dr.mean()),
                       n_R_diff_gt_1e6=int((dr > 1e-6).sum())))
    pd.DataFrame(b3).to_csv(out_prefix + "_partB_abr.tsv", sep="\t", index=False)
    print(f"\n[B4] 錨點結構（間隔以 15m 根為單位；97 根 ＝ 1455 分鐘 ≥ 最大 T 96 根）")
    print(st.to_string(index=False))
    print(f"      全體 ISO 週數：{smp['iso'].nunique()}（日誌宣稱 131）")
    print(f"      全體錨點數：{len(smp)}（日誌宣稱 9,010 ＝ 10 × 901）")

    # [B5] diag.tsv 的丟棄計數與錨點數／K 棒數的守恆核對。
    # 探針的掃描規則：候選被丟棄時 i += 1，被接受時 i += 97 ⇒
    #   接受數 × 97 + 丟棄數 = 分析窗內掃過的 15m 根數
    diag = pd.read_csv(os.path.join(HERE, "2026-08-05_q10_shape_diag.tsv"), sep="\t")
    # 分析窗＝[WIN_START, WIN_END)，WIN_END=2025-07-01 是封存段起點的排他上界
    win_start, win_end = pd.Timestamp("2023-01-01"), pd.Timestamp("2025-07-01")
    print("\n[B5] diag.tsv 丟棄計數的守恆核對（接受×97 + 丟棄 = 窗內 15m 根數）")
    rec5 = []
    for pair in PAIRS:
        d15 = load15(dir15, pair)
        sub = smp[smp["pair"] == pair]
        n_bar = int(((d15["date"] >= win_start) & (d15["date"] < win_end)).sum())
        dg = diag[diag["pair"] == pair].iloc[0]
        drops = int(dg.drop_nodata + dg.drop_gap + dg.drop_nan)
        lhs = len(sub) * 97 + drops
        rec5.append(dict(pair=pair, n_anchor=len(sub), drops=drops,
                         lhs=lhs, n_bar_window=n_bar, ok=bool(lhs == n_bar),
                         last_anchor=str(sub["date"].max()),
                         max_data_date=str(d15["date"].max())))
    r5 = pd.DataFrame(rec5)
    print(r5.to_string(index=False))
    r5.to_csv(out_prefix + "_partB_reconcile.tsv", sep="\t", index=False)
    return res, st


# ---------------------------------------------------------------- Part S（bootstrap 蒙地卡羅穩定性）

def part_s(seeds, boot, big_boot, out_prefix):
    """量化『未調整 95% CI 不含 0 的格數＝5』這個宣稱對 bootstrap 亂數的敏感度。

    這不是新假設檢定（不新增任何格位）：被檢的統計量與格位完全是 run 8 已申報的那 24 格，
    本節只回答『同一份資料、同一個做法，換一組亂數還會不會得到同一個計數』。"""
    df = pd.read_csv(SAMPLES, sep="\t")
    recs, counts = [], []
    for sd in seeds:
        rng = np.random.default_rng(sd)
        n_sig95 = n_sigadj = 0
        for b in range(6):
            sub_b = df[df["bucket"] == b]
            for h in T_HOURS:
                dr = sub_b[f"dR_{h}"].to_numpy(float)
                amp = sub_b[f"amp_{h}"].to_numpy(float) * 100.0
                wk = sub_b["iso"].to_numpy()
                (m_dr, m_amp), prod = block_boot_stats([dr, amp], wk, boot, rng)
                lo95, hi95 = ci(m_dr, 0.05)
                loA, hiA = ci(m_dr, ALPHA_ADJ)
                s95 = (lo95 > 0) or (hi95 < 0)
                sadj = (loA > 0) or (hiA < 0)
                n_sig95 += s95
                n_sigadj += sadj
                recs.append(dict(seed=sd, bucket=BUCKET_NAMES[b], T_h=h, dR=dr.mean(),
                                 lo95=lo95, hi95=hi95, loADJ=loA, hiADJ=hiA,
                                 sig95=bool(s95), sigADJ=bool(sadj),
                                 cap_hiADJ_pct=float(np.quantile(prod, 1 - ALPHA_ADJ / 2))))
        counts.append(dict(seed=sd, boot=boot, n_sig95=int(n_sig95), n_sigADJ=int(n_sigadj)))
        print(f"[S] seed={sd:<6d} boot={boot}  未調整顯著格數={n_sig95}  調整後顯著格數={n_sigadj}")
    r = pd.DataFrame(recs)
    c = pd.DataFrame(counts)
    r.to_csv(out_prefix + "_seedS_cells.tsv", sep="\t", index=False)
    c.to_csv(out_prefix + "_seedS_counts.tsv", sep="\t", index=False)
    print("\n[S1] 未調整顯著格數的分佈：",
          c.n_sig95.value_counts().sort_index().to_dict())
    print("[S2] 調整後顯著格數的分佈：",
          c.n_sigADJ.value_counts().sort_index().to_dict())
    print("\n[S3] 逐格『被判顯著』的次數（未調整 95%）")
    t = r.groupby(["bucket", "T_h"]).agg(dR=("dR", "first"), n_sig=("sig95", "sum"),
                                         lo95_min=("lo95", "min"), lo95_max=("lo95", "max"),
                                         hi95_min=("hi95", "min"), hi95_max=("hi95", "max"))
    print(t[t.n_sig > 0].round(6).to_string())
    print("\n[S4] 兩個刀鋒格（跨 seed 的 CI 端點極差）")
    for bk, h, side in [("[0,0.05)", 24, "lo95"), ("[0.75,1.0]", 1, "hi95")]:
        s = r[(r.bucket == bk) & (r.T_h == h)]
        print(f"      {bk:12s} T={h:<3d} {side}: min={s[side].min():+.6f} "
              f"max={s[side].max():+.6f} 判顯著次數={int(s.sig95.sum())}/{len(s)}")

    # 高精度單次跑：族系調整分位數（0.104%）在 boot=20000 下只由 ~21 個樣本決定
    print(f"\n[S5] 高精度重跑（boot={big_boot}，單一 seed）——族系調整分位數的收斂檢查")
    rng = np.random.default_rng(20260806)
    big = []
    for b in range(6):
        sub_b = df[df["bucket"] == b]
        for h in T_HOURS:
            dr = sub_b[f"dR_{h}"].to_numpy(float)
            amp = sub_b[f"amp_{h}"].to_numpy(float) * 100.0
            wk = sub_b["iso"].to_numpy()
            (m_dr, m_amp), prod = block_boot_stats([dr, amp], wk, big_boot, rng, chunk=25000)
            lo95, hi95 = ci(m_dr, 0.05)
            loA, hiA = ci(m_dr, ALPHA_ADJ)
            cloA, chiA = ci(prod, ALPHA_ADJ)
            big.append(dict(bucket=BUCKET_NAMES[b], T_h=h, n=len(dr), dR=dr.mean(),
                            lo95=lo95, hi95=hi95, loADJ=loA, hiADJ=hiA,
                            cap_pct=dr.mean() * amp.mean(),
                            cap_loADJ_pct=cloA, cap_hiADJ_pct=chiA))
    bg = pd.DataFrame(big)
    bg.to_csv(out_prefix + "_seedS_bigboot.tsv", sep="\t", index=False)
    s95 = bg[(bg.lo95 > 0) | (bg.hi95 < 0)]
    sadj = bg[(bg.loADJ > 0) | (bg.hiADJ < 0)]
    print(f"      未調整顯著格數={len(s95)}  調整後顯著格數={len(sadj)}")
    print(bg[["bucket", "T_h", "n", "dR", "lo95", "hi95", "loADJ", "hiADJ",
              "cap_pct", "cap_hiADJ_pct"]].round(6).to_string(index=False))
    print(f"      全網格 cap_pct 最大 = {bg.cap_pct.max():.4f}%；"
          f"cap 調整後 CI 上界最大 = {bg.cap_hiADJ_pct.max():.4f}%（門檻 0.28%）")
    return r, c, bg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["A", "B", "S"], required=True)
    ap.add_argument("--seeds", default="1,2,3,4,5,6,7,8,9,10,11,12")
    ap.add_argument("--big-boot", type=int, default=400000)
    ap.add_argument("--boot", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=4242)
    ap.add_argument("--dir15", default="/tmp/kl15")
    ap.add_argument("--out-prefix", default=os.path.join(HERE, "2026-08-06_q13_audit"))
    a = ap.parse_args()
    if a.part == "A":
        part_a(a.boot, a.seed, a.out_prefix)
    elif a.part == "S":
        part_s([int(x) for x in a.seeds.split(",")], a.boot, a.big_boot, a.out_prefix)
    else:
        part_b(a.dir15, a.out_prefix)


if __name__ == "__main__":
    main()
