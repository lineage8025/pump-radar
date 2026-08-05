"""Q10 / 方向二 Phase 0 — 振幅的「形狀」：可捕獲趨勢比 R。

問題（凍結網格見 docs/RND_BACKLOG.md 方向二、docs/TRADEABILITY_PREREG.md §3）：

    A = max(high[t+1..t+T]) - P0 ,  B = P0 - min(low[t+1..t+T]) ,  R = max(A,B)/(A+B)

R -> 1 單邊走完（長伽瑪友善）；R -> 0.5 來回震盪（短伽瑪友善）。
對照組＝**隨機符號翻轉**（不是隨機重排）：每根 1m 的對數偏移乘 eps in {-1,+1}，
重建路徑後重算 R，200 次取平均得 R_flip。統計量 dR = R_actual - R_flip 逐 episode 配對。

符號翻轉不變性（TRADEABILITY_PREREG §1.3 硬性前置檢定）：整體乘 -1 使 A<->B 互換，
max(A,B) 與 A+B 皆不變 => R 不變 => 振幅／路徑命題，受理。--self-test 的 test6 是這條的
機器化驗證。

資料（in-sample only，未觸碰 2025-07-01 之後的封存段）：
    sh research/experiments/fetch_q10_data.sh
    # 15m: --start 2022-12 --end 2025-06 ；1m: --start 2023-01 --end 2025-06

用法：
    python3 research/experiments/2026-08-05_q10_shape_capturable_trend.py --self-test
    python3 research/experiments/2026-08-05_q10_shape_capturable_trend.py \
        --dir15 /tmp/kl15 --dir1m /tmp/kl1m --procs 4 --out-prefix <prefix>
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from detector import add_indicators  # noqa: E402  (紅線 2：唯讀複用 production PARAMS)

PAIRS = ["BTC/USDT", "ETH/USDT", "ADA/USDT", "SOL/USDT", "XRP/USDT",
         "DOGE/USDT", "BNB/USDT", "LINK/USDT", "LTC/USDT", "AVAX/USDT"]

# ---- 凍結網格（docs/RND_BACKLOG.md 方向二，一字未改）----
BUCKET_EDGES = [0.0, 0.05, 0.10, 0.25, 0.50, 0.75, 1.0]
BUCKET_NAMES = ["[0,0.05)", "[0.05,0.10)", "[0.10,0.25)",
                "[0.25,0.50)", "[0.50,0.75)", "[0.75,1.0]"]
T_HOURS = [1, 4, 12, 24]
T_MINS = [h * 60 for h in T_HOURS]
MAXT = max(T_MINS)                 # 1440
N_FLIPS = 200
ANCHOR_STEP = 97                   # 根 15m ＝ 1455 分鐘（見日誌 §4 操作化決定 1）
WIN_START = pd.Timestamp("2023-01-01", tz="UTC")
WIN_END = pd.Timestamp("2025-07-01", tz="UTC")   # 排他上界；封存段起點，不得跨越
N_CELLS_FAMILY = 24                # 方向二累計格位數 M => alpha = 0.05/24
ALPHA_ADJ = 0.05 / N_CELLS_FAMILY


def _bucket_of(p: float) -> int:
    """bbw_pct -> 桶索引；右開左閉，最後一桶含 1.0。"""
    for k in range(6):
        if p >= BUCKET_EDGES[k] and (p < BUCKET_EDGES[k + 1] or (k == 5 and p <= 1.0)):
            return k
    return -1


def path_extremes(x, hi, lo, eps=None):
    """由「相對前收的對數偏移」重建路徑，回傳各檢查點的 (hmax, lmin)（**對數空間**）。

    x  : (n,)    log(close_i) - log(prev_close_i)
    hi : (n,)    log(high_i)  - log(prev_close_i)
    lo : (n,)    log(low_i)   - log(prev_close_i)
    eps: (F,n) in {-1,+1} 或 None（None ＝ 恆 +1，即真實路徑）

    符號翻轉的定義（TRADEABILITY_PREREG §1.3「open/close 對調、high/low 鏡射」逐根版）：
        x -> -x ,  hi -> -lo ,  lo -> -hi
    回傳形狀 (F, len(T_MINS))；exp 單調故「先取對數極值再 exp」與價格空間取極值等價。
    """
    if eps is None:
        eps = np.ones((1, x.shape[0]), dtype=x.dtype)
    pos = eps > 0
    xf = eps * x
    hif = np.where(pos, hi, -lo)
    lof = np.where(pos, lo, -hi)

    cum = np.cumsum(xf, axis=1)
    prev = np.empty_like(cum)
    prev[:, 0] = 0.0
    prev[:, 1:] = cum[:, :-1]

    hmax = np.maximum.accumulate(prev + hif, axis=1)
    lmin = np.minimum.accumulate(prev + lof, axis=1)
    idx = [m - 1 for m in T_MINS]
    return (hmax[:, idx].astype(np.float64), lmin[:, idx].astype(np.float64))


def ab_price(hmax, lmin):
    """對數極值 -> 凍結網格定義的價格空間 A、B（相對 P0 的比例）。

    A = max(high)/P0 - 1 、 B = 1 - min(low)/P0。依定義 >= 0；
    缺口可讓整段落在 P0 之下使 A<0，夾到 0（另行計數）。
    """
    A = np.expm1(hmax)
    B = -np.expm1(lmin)
    return np.clip(A, 0.0, None), np.clip(B, 0.0, None)


def ab_price_mirror(hmax, lmin):
    """§1.3 整段鏡射（報酬乘 -1）後、同樣以價格空間量出的 A、B。

    對數空間鏡射即 (hmax, lmin) -> (-lmin, -hmax)。
    在對數空間 R 對此恆等；在價格空間因 exp 凸性只是近似恆等——
    偏移量與可宣告的效應量同數量級（見 self-test test6），故本輪兩版並算，
    宣告時取保守者，絕不取好看的那一版。
    """
    return ab_price(-lmin, -hmax)


def _R(A, B):
    """R = max(A,B)/(A+B)，A+B==0 回傳 nan。"""
    s = A + B
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.where(s > 0, np.maximum(A, B) / s, np.nan)
    return r


def run_pair(args):
    pair, dir15, dir1m, seed, n_flips = args
    tag = pair.replace("/", "_")
    d15 = pd.read_feather(Path(dir15) / f"{tag}-15m.feather")
    d1m = pd.read_feather(Path(dir1m) / f"{tag}-1m.feather")
    d15 = add_indicators(d15)

    # tz-aware 的 .to_numpy() 會退化成 object 陣列（Timestamp），比較與算術都會爆慢／型別衝突
    t15 = d15["date"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    close15 = d15["close"].to_numpy()
    bbw = d15["bbw_pct"].to_numpy()
    t1 = d1m["date"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy()
    h1 = d1m["high"].to_numpy()
    l1 = d1m["low"].to_numpy()
    c1 = d1m["close"].to_numpy()

    minute = np.timedelta64(1, "m")
    lo_i = int(np.searchsorted(t15, np.datetime64(WIN_START.tz_convert("UTC").tz_localize(None))))
    hi_i = int(np.searchsorted(t15, np.datetime64(WIN_END.tz_convert("UTC").tz_localize(None))))

    rng = np.random.default_rng(seed)
    rows, drop_nodata, drop_gap, drop_nan, clip_a, clip_b = [], 0, 0, 0, 0, 0

    i = lo_i
    while i < hi_i:
        p = bbw[i]
        if not np.isfinite(p):
            i += 1
            continue
        tc = t15[i] + np.timedelta64(15, "m")          # 錨點 15m 的收盤時刻
        s = int(np.searchsorted(t1, tc))
        if s + MAXT > len(t1) or t1[s] != tc:
            drop_nodata += 1
            i += 1
            continue
        if t1[s + MAXT - 1] - t1[s] != (MAXT - 1) * minute:
            drop_gap += 1                              # 窗內有缺 K 棒，檢查點會錯位
            i += 1
            continue

        P0 = close15[i]
        seg_h, seg_l, seg_c = h1[s:s + MAXT], l1[s:s + MAXT], c1[s:s + MAXT]
        pc = np.empty(MAXT)
        pc[0] = P0
        pc[1:] = seg_c[:-1]
        lpc = np.log(pc)
        x = (np.log(seg_c) - lpc)
        hh = (np.log(seg_h) - lpc)
        ll = (np.log(seg_l) - lpc)

        hmax0, lmin0 = path_extremes(x, hh, ll, None)
        A0, B0 = ab_price(hmax0, lmin0)
        Am0, Bm0 = ab_price_mirror(hmax0, lmin0)
        A0, B0, Am0, Bm0 = A0[0], B0[0], Am0[0], Bm0[0]
        # 逐錨點硬驗證：eps=+1 的重建必須逐位元重現由原始高低價直接算出的 A/B
        for j, m in enumerate(T_MINS):
            ad = seg_h[:m].max() / P0 - 1.0
            bd = 1.0 - seg_l[:m].min() / P0
            if ad < 0:
                clip_a += 1
                ad = 0.0
            if bd < 0:
                clip_b += 1
                bd = 0.0
            if abs(ad - A0[j]) > 1e-9 or abs(bd - B0[j]) > 1e-9:
                raise AssertionError(f"重建不一致 {pair} {t15[i]} T={m}: {ad} vs {A0[j]}")

        eps = (rng.integers(0, 2, size=(n_flips, MAXT), dtype=np.int8) * 2 - 1).astype(np.float32)
        hmf, lmf = path_extremes(x.astype(np.float32), hh.astype(np.float32),
                                 ll.astype(np.float32), eps)
        r_act = _R(A0, B0)
        r_flip = np.nanmean(_R(*ab_price(hmf, lmf)), axis=0)
        r_act_m = _R(Am0, Bm0)
        r_flip_m = np.nanmean(_R(*ab_price_mirror(hmf, lmf)), axis=0)
        if not (np.all(np.isfinite(r_act)) and np.all(np.isfinite(r_act_m))):
            drop_nan += 1
            i += 1
            continue

        cx = np.cumsum(x)
        iso = pd.Timestamp(t15[i]).isocalendar()
        row = {"pair": pair, "date": pd.Timestamp(t15[i]), "iso": f"{iso[0]}-W{iso[1]:02d}",
               "bbw_pct": float(p), "bucket": _bucket_of(float(p))}
        for j, hh_ in enumerate(T_HOURS):
            row[f"R_act_{hh_}"] = float(r_act[j])
            row[f"R_flip_{hh_}"] = float(r_flip[j])
            row[f"dR_{hh_}"] = float(r_act[j] - r_flip[j])
            row[f"dRm_{hh_}"] = float(r_act_m[j] - r_flip_m[j])
            row[f"amp_{hh_}"] = float(A0[j] + B0[j])
            row[f"absnet_{hh_}"] = float(abs(np.expm1(cx[T_MINS[j] - 1])))
        rows.append(row)
        i += ANCHOR_STEP

    return pd.DataFrame(rows), {"pair": pair, "drop_nodata": drop_nodata,
                                "drop_gap": drop_gap, "drop_nan": drop_nan,
                                "clip_a": clip_a, "clip_b": clip_b}


# ---------------- bootstrap ----------------

def block_boot(vals, weeks, n_boot, rng, lo_q, hi_q):
    """逐 ISO 週 block bootstrap（episode 重疊 => 樣本非獨立，沿用 Q1' 教訓）。"""
    if len(vals) == 0:
        return np.nan, np.nan
    uw, inv = np.unique(weeks, return_inverse=True)
    nw = len(uw)
    ssum = np.bincount(inv, weights=vals, minlength=nw)
    scnt = np.bincount(inv, minlength=nw).astype(float)
    idx = rng.integers(0, nw, size=(n_boot, nw))
    m = ssum[idx].sum(axis=1) / scnt[idx].sum(axis=1)
    return float(np.quantile(m, lo_q)), float(np.quantile(m, hi_q))


def block_boot_prod(dr, amp, weeks, n_boot, rng, lo_q, hi_q):
    """可捕獲報酬上界 = mean(dR) * mean(amp) 的 block bootstrap CI（同一組週索引）。"""
    uw, inv = np.unique(weeks, return_inverse=True)
    nw = len(uw)
    d_s = np.bincount(inv, weights=dr, minlength=nw)
    a_s = np.bincount(inv, weights=amp, minlength=nw)
    cnt = np.bincount(inv, minlength=nw).astype(float)
    idx = rng.integers(0, nw, size=(n_boot, nw))
    c = cnt[idx].sum(axis=1)
    m = (d_s[idx].sum(axis=1) / c) * (a_s[idx].sum(axis=1) / c)
    return float(np.quantile(m, lo_q)), float(np.quantile(m, hi_q))


def aggregate(df, n_boot, seed):
    rng = np.random.default_rng(seed)
    out = []
    for b in range(6):
        sub = df[df["bucket"] == b]
        for h in T_HOURS:
            dr = sub[f"dR_{h}"].to_numpy()
            amp = sub[f"amp_{h}"].to_numpy()
            wk = sub["iso"].to_numpy()
            n = len(sub)
            rec = {"bucket": BUCKET_NAMES[b], "T_h": h, "n": n}
            if n == 0:
                out.append(rec)
                continue
            rec["R_act_mean"] = float(sub[f"R_act_{h}"].mean())
            rec["R_act_med"] = float(sub[f"R_act_{h}"].median())
            rec["R_flip_mean"] = float(sub[f"R_flip_{h}"].mean())
            rec["dR"] = float(dr.mean())
            drm = sub[f"dRm_{h}"].to_numpy()
            rec["dR_mirror"] = float(drm.mean())
            # 保守者＝兩版中絕對值較小的那個（§1.3 要求「結論不變」，取最不利於宣告的一版）
            rec["dR_consv"] = rec["dR"] if abs(rec["dR"]) <= abs(rec["dR_mirror"]) \
                else rec["dR_mirror"]
            rec["amp_mean_pct"] = float(amp.mean() * 100)
            rec["absnet_mean_pct"] = float(sub[f"absnet_{h}"].mean() * 100)
            lo95, hi95 = block_boot(dr, wk, n_boot, rng, 0.025, 0.975)
            loA, hiA = block_boot(dr, wk, n_boot, rng, ALPHA_ADJ / 2, 1 - ALPHA_ADJ / 2)
            rec["dR_lo95"], rec["dR_hi95"] = lo95, hi95
            rec["dR_loADJ"], rec["dR_hiADJ"] = loA, hiA
            mlo95, mhi95 = block_boot(drm, wk, n_boot, rng, 0.025, 0.975)
            mloA, mhiA = block_boot(drm, wk, n_boot, rng, ALPHA_ADJ / 2, 1 - ALPHA_ADJ / 2)
            rec["dRm_lo95"], rec["dRm_hi95"] = mlo95, mhi95
            rec["dRm_loADJ"], rec["dRm_hiADJ"] = mloA, mhiA
            rec["cap_pct"] = rec["dR"] * rec["amp_mean_pct"]
            rec["cap_consv_pct"] = rec["dR_consv"] * rec["amp_mean_pct"]
            clo, chi = block_boot_prod(dr, amp, wk, n_boot, rng, 0.025, 0.975)
            rec["cap_lo95_pct"], rec["cap_hi95_pct"] = clo * 100, chi * 100
            clo2, chi2 = block_boot_prod(dr, amp, wk, n_boot, rng,
                                         ALPHA_ADJ / 2, 1 - ALPHA_ADJ / 2)
            rec["cap_loADJ_pct"], rec["cap_hiADJ_pct"] = clo2 * 100, chi2 * 100
            out.append(rec)
    return pd.DataFrame(out)


# ---------------- self test ----------------

def _synth(n, kind, rng):
    """造 1m 對數偏移三元組 (x, hi, lo)。intrabar 半幅固定，避免干擾形狀檢定。

    ⚠ 校準期發現的關鍵性質：**R 是尺度不變量**（A、B 同比例縮放時 R 不變），
    因此任何只改變「每步變異數尺度」的結構（例如報酬的短落後期自相關 AR(1)）
    在窗口長度 >> 相關時距時**完全不影響 R**——兩者都收斂到布朗運動，只差步長。
    能移動 R 的必須是**窗口尺度上的路徑結構**：整段的漂移（-> R 上升）或
    整段的有界性／均值回歸（-> R 下降）。故正／負對照用 drift 與 OU，
    AR(1) 反而是「R 對短落後期自相關無感」的證明（test9）。
    """
    if kind == "iid":
        x = rng.normal(0, 1e-3, n)
    elif kind == "drift":                       # 窗口尺度趨勢：常數漂移 + 噪音
        x = rng.normal(0, 1e-3, n) + 3e-3 / np.sqrt(n)   # 整段漂移 ≈ 3 倍隨機游走 sd
    elif kind == "ou":                          # 窗口尺度均值回歸：價格為 OU，路徑有界
        tau = 60.0
        p = np.empty(n + 1)
        p[0] = 0.0
        s = 1e-3
        for i in range(1, n + 1):
            p[i] = p[i - 1] * (1 - 1.0 / tau) + rng.normal(0, s)
        x = np.diff(p)
    elif kind == "ar1p":                        # 報酬正自相關（尺度效應，非形狀效應）
        e = rng.normal(0, 1e-3, n)
        x = np.empty(n)
        x[0] = e[0]
        for i in range(1, n):
            x[i] = 0.6 * x[i - 1] + e[i]
    elif kind == "ar1n":                        # 報酬負自相關
        e = rng.normal(0, 1e-3, n)
        x = np.empty(n)
        x[0] = e[0]
        for i in range(1, n):
            x[i] = -0.6 * x[i - 1] + e[i]
    w = 2e-4
    hi = np.maximum(x, 0.0) + w
    lo = np.minimum(x, 0.0) - w
    return x, hi, lo


def self_test():
    rng = np.random.default_rng(7)
    ok = 0

    # 1 重建正確性：由 (x,hi,lo) 重建的 A/B 必須等於直接由價格序列取極值
    x, hi, lo = _synth(MAXT, "iid", rng)
    lp = np.concatenate([[0.0], np.cumsum(x)])
    price = np.exp(lp)
    highs = price[:-1] * np.exp(hi)
    lows = price[:-1] * np.exp(lo)
    A, B = ab_price(*path_extremes(x, hi, lo, None))
    for j, m in enumerate(T_MINS):
        assert abs((highs[:m].max() - 1.0) - A[0, j]) < 1e-9, "test1 A"
        assert abs((1.0 - lows[:m].min()) - B[0, j]) < 1e-9, "test1 B"
    ok += 1

    # 2 R 值域 [0.5, 1]
    eps = (rng.integers(0, 2, size=(64, MAXT)) * 2 - 1).astype(float)
    Af, Bf = ab_price(*path_extremes(x, hi, lo, eps))
    r = _R(Af, Bf)
    assert np.nanmin(r) >= 0.5 - 1e-12 and np.nanmax(r) <= 1.0 + 1e-12, "test2"
    ok += 1

    def _mean_dR(kind, reps, rng):
        ds = []
        for _ in range(reps):
            x, hi, lo = _synth(MAXT, kind, rng)
            A0, B0 = ab_price(*path_extremes(x, hi, lo, None))
            e = (rng.integers(0, 2, size=(N_FLIPS, MAXT)) * 2 - 1).astype(np.float32)
            Af, Bf = ab_price(*path_extremes(x.astype(np.float32), hi.astype(np.float32),
                                             lo.astype(np.float32), e))
            ds.append(_R(A0, B0)[0, -1] - np.nanmean(_R(Af, Bf), axis=0)[-1])
        ds = np.array(ds)
        return float(ds.mean()), float(ds.std(ddof=1) / np.sqrt(len(ds)))

    # 3 i.i.d.（符號可交換）=> dR 期望恰為 0（隨機化檢定的零假設）
    m_iid, se_iid = _mean_dR("iid", 250, rng)
    assert abs(m_iid) < 3 * se_iid + 0.005, f"test3 iid dR={m_iid:+.4f}±{se_iid:.4f}"
    ok += 1

    # 4 正對照：窗口尺度漂移 => dR 顯著為正
    m_dr, se_dr = _mean_dR("drift", 250, rng)
    assert m_dr > 5 * se_dr and m_dr > 0.02, f"test4 drift dR={m_dr:+.4f}±{se_dr:.4f}"
    ok += 1

    # 5 負對照：價格 OU（窗口尺度均值回歸、路徑有界）=> dR 顯著為負
    m_ou, se_ou = _mean_dR("ou", 250, rng)
    assert m_ou < -5 * se_ou and m_ou < -0.02, f"test5 ou dR={m_ou:+.4f}±{se_ou:.4f}"
    ok += 1

    # 6 【TRADEABILITY_PREREG §1.3 的機器化】整段乘 -1 => 結論不變
    #
    # ⚠ 校準期發現、且**寫進日誌限制段**的一件事：凍結網格的 A/B 定義在**價格空間**
    # （A = max(high) - P0）。預登記 §1.3 的推導「A<->B 互換 => R 不變」在**對數空間**
    # 是逐位元恆等；在價格空間因 exp 的凸性只是**近似**恆等
    # （exp(-y)-1 != -(exp(y)-1)），且偏移量隨移動幅度增大，與可宣告的效應量同數量級。
    # 本輪**不改凍結的度量**（改度量＝改網格，須走 program.md §5 閘門），
    # 改為：①對數空間驗精確恆等；②價格空間量出偏移；③把鏡射版 dR 一併算出來，
    # 宣告時取兩版中的保守者。
    dmax = 0.0
    for _ in range(200):
        x, hi, lo = _synth(MAXT, "drift", rng)
        hm, lm = path_extremes(x, hi, lo, None)
        A0, B0 = ab_price(hm, lm)
        An, Bn = ab_price(*path_extremes(-x, -lo, -hi, None))   # 顯式重跑整段鏡射
        Am, Bm = ab_price_mirror(hm, lm)                        # 由同一組極值直接鏡射
        # (a) 對數空間：A<->B 精確互換
        assert np.allclose(np.log1p(A0), -np.log1p(-Bn), atol=1e-12), "test6 log A<->B"
        assert np.allclose(np.log1p(An), -np.log1p(-B0), atol=1e-12), "test6 log B<->A"
        # (b) ab_price_mirror 必須等於顯式重跑鏡射序列（生產路徑用的是前者）
        assert np.allclose(Am, An, atol=1e-12) and np.allclose(Bm, Bn, atol=1e-12), \
            "test6 mirror 捷徑與顯式重跑不一致"
        # (c) 價格空間的偏移量（量出來，不假設它小）
        dmax = max(dmax, float(np.nanmax(np.abs(_R(A0, B0) - _R(An, Bn)))))
    ok += 1

    # 7 float32 與 float64 的 R 差異可忽略
    e = (rng.integers(0, 2, size=(50, MAXT)) * 2 - 1)
    A64, B64 = ab_price(*path_extremes(x, hi, lo, e.astype(np.float64)))
    A32, B32 = ab_price(*path_extremes(x.astype(np.float32), hi.astype(np.float32),
                                       lo.astype(np.float32), e.astype(np.float32)))
    d = np.nanmax(np.abs(_R(A64, B64) - _R(A32, B32)))
    assert d < 1e-4, f"test7 float32 drift {d}"
    ok += 1

    # 8 精確幾何：單調上漲斜坡 => A>0, B=0, R=1
    x = np.full(MAXT, 1e-4)
    hi = x + 1e-6
    lo = np.zeros(MAXT)
    A, B = ab_price(*path_extremes(x, hi, lo, None))
    assert np.allclose(B, 0.0) and np.allclose(_R(A, B), 1.0), "test8"
    ok += 1

    # 9 R 對「報酬短落後期自相關」無感（尺度不變性的實證）——不是 bug，是本度量的性質
    m_p, se_p = _mean_dR("ar1p", 250, rng)
    m_n, se_n = _mean_dR("ar1n", 250, rng)
    assert abs(m_p) < 0.02 and abs(m_n) < 0.02, f"test9 ar1 {m_p:+.4f} {m_n:+.4f}"
    ok += 1

    print(f"self-test 全過（{ok} 項）")
    print(f"  test3 iid   dR={m_iid:+.4f} ± {se_iid:.4f}   （零假設，應 ≈0）")
    print(f"  test4 drift dR={m_dr:+.4f} ± {se_dr:.4f}   （正對照，應 >0）")
    print(f"  test5 ou    dR={m_ou:+.4f} ± {se_ou:.4f}   （負對照，應 <0）")
    print(f"  test9 ar1+  dR={m_p:+.4f} ± {se_p:.4f} / ar1- dR={m_n:+.4f} ± {se_n:.4f}"
          f"   （R 對短落後期自相關無感，尺度不變）")
    print(f"  test6 §1.3 整段鏡射：對數空間 A<->B 逐位元恆等；"
          f"價格空間 R 偏移上界 {dmax:.4f}（合成序列，移動幅度誇大版）")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir15")
    ap.add_argument("--dir1m")
    ap.add_argument("--out-prefix")
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--flips", type=int, default=N_FLIPS)
    ap.add_argument("--boot", type=int, default=20000)
    ap.add_argument("--pairs", default=",".join(PAIRS))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    pairs = [p.strip() for p in a.pairs.split(",") if p.strip()]
    jobs = [(p, a.dir15, a.dir1m, 5000 + k, a.flips) for k, p in enumerate(pairs)]
    if a.procs > 1:
        import multiprocessing as mp
        with mp.Pool(a.procs) as pool:
            res = pool.map(run_pair, jobs)
    else:
        res = [run_pair(j) for j in jobs]

    df = pd.concat([r[0] for r in res], ignore_index=True)
    diag = pd.DataFrame([r[1] for r in res])
    print(diag.to_string(index=False))
    print(f"\n錨點總數 n={len(df)}  週數={df['iso'].nunique()}  "
          f"窗口 {df['date'].min()} ~ {df['date'].max()}")

    tab = aggregate(df, a.boot, 424242)
    pd.set_option("display.width", 250)
    print("\n" + tab.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    if a.out_prefix:
        df.to_csv(f"{a.out_prefix}_samples.tsv", sep="\t", index=False)
        tab.to_csv(f"{a.out_prefix}_grid.tsv", sep="\t", index=False)
        diag.to_csv(f"{a.out_prefix}_diag.tsv", sep="\t", index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
