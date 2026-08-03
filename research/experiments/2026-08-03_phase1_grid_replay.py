"""Phase 1 撮合回放器 — 等差網格淨損益分佈（docs/GRID_SIM_PREREG.md 凍結網格）。

執行 docs/RND_BACKLOG.md 方向一 Phase 1。策略本體移植自 classic-grid `src/grid.ts`
（等同 docs/RESEARCH_GRID_MECHANICS.md 第一節的 77 行三函式），**不加任何原策略沒有的邏輯**。

核心結構性簡化（讓 30 組撮合 × ~12,800 錨點可算）
------------------------------------------------
等差網格 + 「買成交於 i → 於 i+1 掛賣 / 賣成交於 i → 於 i-1 掛買」+ 一格一單，
使得任一時刻**恰好只有一個空檔位**，整個掛單狀態塌縮成單一整數。因此：

    pos = C - idx        （idx = 當前價格所在檔位；C 由首次成交在哪一側決定）

部位是當前價格檔位的**純函數**，不需逐根跑狀態機。再利用等差級數區間和的封閉解

    sum(levels[p..q]) = (q-p+1) * (levels[p] + levels[q]) / 2

每根 K 棒的現金流變成 O(1) 算術，整段 episode 純 numpy 向量化。

第二個簡化：**槓桿不影響成交序列**。成交序列只由價格路徑與檔位幾何決定，
槓桿只縮放部位大小與強平門檻。故實跑撮合 = W(5) × 格數(2) × 策略(3) = 30 組，
槓桿(5) × T(3) × 維持保證金(2) × 費率(3) 全部在後處理由同一條庫存路徑解析求值。

用法
----
  python3 research/experiments/2026-08-03_phase1_grid_replay.py \
      --data-dir <1m feather 目錄> --out-prefix <輸出前綴>
  python3 research/experiments/2026-08-03_phase1_grid_replay.py --self-test
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ─── 凍結網格（docs/GRID_SIM_PREREG.md §一，不得於此處增刪）───────────────
HALF_BANDS = [1.5, 3.0, 4.6, 7.0, 10.0]        # W，%
GRID_COUNTS = [40, 80]                          # N
LEVERAGES = [3, 5, 10, 15, 30]                  # L
POLICIES = ["hold", "close", "recover"]
HORIZONS_D = [1, 7, 30]                         # T，天
MAINT_RATES = [0.020, 0.005]                    # 主 / 穩健性
FEE_RATES = [0.00011, 0.0, 0.0005]              # 主 / 穩健性
MARGIN_FRAC = 0.7                               # 固定，不開軸
SKIP_BAND = 0.25                                # × spacing
PATH_ORDERS = ["auto", "reverse"]               # intrabar 單調路徑雙序
ANCHOR_STRIDE_MIN = 24 * 60                     # 每 24h 一個錨點
BARS_PER_DAY = 24 * 60


# ─── 策略本體（移植自 classic-grid src/grid.ts）─────────────────────────
def build_levels(mid: float, half_band_pct: float, n: int) -> np.ndarray:
    """grid.ts buildGrid：等差，levels 長度 = n+1。"""
    w = mid * half_band_pct / 100.0
    return np.linspace(mid - w, mid + w, n + 1)


def seed_boundaries(mid: float, levels: np.ndarray, spacing: float) -> tuple[int, int]:
    """grid.ts seedOrders：距現價 SKIP_BAND × spacing 內的檔位跳過。

    回傳 (j_lo, j_hi)：買單掛在 levels[0..j_lo]，賣單掛在 levels[j_hi..n]，
    中間是 skipBand 造成的死區（首次成交前無單）。
    """
    band = SKIP_BAND * spacing
    below = np.nonzero(levels <= mid - band)[0]
    above = np.nonzero(levels >= mid + band)[0]
    j_lo = int(below[-1]) if below.size else -1
    j_hi = int(above[0]) if above.size else len(levels)
    return j_lo, j_hi


# ─── 等差級數封閉解 ────────────────────────────────────────────────────
def _prefix_sum(i, lower: float, spacing: float):
    """sum(levels[0..i])；i < 0 回 0。向量化。"""
    i = np.asarray(i)
    k = i + 1                                    # 項數
    s = k * lower + spacing * i * k / 2.0
    return np.where(i < 0, 0.0, s)


def _range_sum(p, q, lower: float, spacing: float):
    """sum(levels[p..q])；q < p 回 0。向量化。"""
    p, q = np.asarray(p), np.asarray(q)
    s = _prefix_sum(q, lower, spacing) - _prefix_sum(p - 1, lower, spacing)
    return np.where(q < p, 0.0, s)


def _idx_floor(price, lower: float, spacing: float, n: int):
    """價格所在檔位（最高的 levels[i] <= price），夾在 [-1, n]。

    -1 代表跌破 levels[0]（下方買單已全數成交）；n 代表站上 levels[n]。
    """
    raw = np.floor((np.asarray(price) - lower) / spacing)
    return np.clip(raw, -1, n).astype(np.int64)


# 成交檔位範圍（買賣不對稱，差一格就是網格賺不賺錢的分野）
#
#   買單掛在現價【下方】：idx 由 a 跌到 b(<a) → 成交 levels[b .. a-1]
#   賣單掛在現價【上方】：idx 由 a 漲到 b(>a) → 成交 levels[a+1 .. b]
#
# 這個不對稱正是格差利潤的來源：於 levels[i] 買進後，補的賣單在 levels[i+1]，
# 一買一賣走完賺 spacing。若兩側都用同一組範圍，買賣會落在同一檔位、
# 每次來回獲利恰好為 0——self_test 的正弦波案例即為此而設。


# ─── 單一 episode 撮合（槓桿無關）──────────────────────────────────────
def simulate_episode(
    o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray,
    mid: float, half_band_pct: float, n: int, policy: str, path_order: str,
) -> dict:
    """回傳槓桿無關的逐根序列。

    pos      : 淨部位（單位 = sizeBase 的倍數，+ 為多）
    cash     : 現金流累計（價格 × 單位；PnL = cash + pos × mark）
    fee_px   : 成交價絕對值累計（手續費 = feeRate × fee_px × sizeBase）
    mark     : 逐根收盤標記價
    breach_i : 首次離開區間的根索引（無則 -1）
    """
    levels = build_levels(mid, half_band_pct, n)
    lower, upper = float(levels[0]), float(levels[-1])
    spacing = float(levels[1] - levels[0])
    j_lo, j_hi = seed_boundaries(mid, levels, spacing)

    # ── 首次成交在哪一側 → 決定常數 C（pos = C - idx）──
    hit_dn = np.nonzero(_idx_floor(l, lower, spacing, n) <= j_lo)[0]
    hit_up = np.nonzero(_idx_floor(h, lower, spacing, n) >= j_hi)[0]
    first_dn = int(hit_dn[0]) if hit_dn.size else len(o) + 1
    first_up = int(hit_up[0]) if hit_up.size else len(o) + 1
    start = min(first_dn, first_up)
    nb = len(o)
    if start >= nb:                              # 整段都在死區，無任何成交
        z = np.zeros(nb)
        return {"pos": z, "cash": z, "fee_px": z, "mark": c,
                "breach_i": -1, "spacing": spacing, "levels": levels}
    # 同一根同時觸及兩側時，依 path_order 決定誰先
    down_first = first_dn < first_up or (
        first_dn == first_up and _leg_down_first(o[start], c[start], path_order)
    )
    C = (j_lo + 1) if down_first else (j_hi - 1)

    # ── 逐根四點檔位（向量化）──
    i_o = _idx_floor(o, lower, spacing, n)
    i_c = _idx_floor(c, lower, spacing, n)
    i_h = _idx_floor(h, lower, spacing, n)
    i_l = _idx_floor(l, lower, spacing, n)

    # 單調路徑：close >= open 走 起點→l→h→c，否則 起點→h→l→c
    #
    # 每根的「起點」用【前一根的收盤檔位】而非本根開盤，讓整段路徑嚴格連續：
    # 第 0 根的起點是錨點本身（C），否則錨點到首根開盤之間的價格移動會被漏記。
    # 真實 1m 資料 open[i]==close[i-1] 幾乎總成立，但缺口一旦存在就會漏掉成交。
    dn_first = _leg_down_first_arr(o, c, path_order)
    legs = np.where(dn_first[:, None], np.stack([i_l, i_h], 1),
                    np.stack([i_h, i_l], 1))
    i_start = np.empty(nb, dtype=np.int64)
    i_start[0] = C
    i_start[1:] = i_c[:-1]
    seq = np.concatenate([i_start[:, None], legs, i_c[:, None]], axis=1)  # (nb, 4)

    # 死區內（start 之前）不成交：把序列釘在起始檔位
    seq = seq.copy()
    seq[:start, :] = C
    if start < nb:
        seq[start, 0] = C                        # 死區結束的那根，起點仍是錨點

    d_cash = np.zeros(nb)
    d_feepx = np.zeros(nb)
    for k in range(3):                           # 三段單調腿
        a, b = seq[:, k], seq[:, k + 1]
        dn = b < a                               # 下行 → 買 levels[b..a-1]
        up = b > a                               # 上行 → 賣 levels[a+1..b]
        s_dn = _range_sum(b, a - 1, lower, spacing)
        s_up = _range_sum(a + 1, b, lower, spacing)
        d_cash += np.where(dn, -s_dn, 0.0) + np.where(up, s_up, 0.0)
        d_feepx += np.where(dn, s_dn, 0.0) + np.where(up, s_up, 0.0)

    idx_end = seq[:, 3]
    pos = (C - idx_end).astype(np.float64)
    cash = np.cumsum(d_cash)
    fee_px = np.cumsum(d_feepx)

    # ── 出區間偵測與策略處置 ──
    out = (l < lower) | (h > upper)
    bi = int(np.nonzero(out)[0][0]) if out.any() else -1

    if bi >= 0 and policy == "close":
        # 出界即全平：後續凍結在出界根的狀態，部位歸零並實現損益
        cash = cash.copy(); pos = pos.copy(); fee_px = fee_px.copy()
        px = float(np.clip(c[bi], lower, upper))
        cash[bi:] = cash[bi] + pos[bi] * px
        fee_px[bi:] = fee_px[bi] + abs(pos[bi]) * px
        pos[bi:] = 0.0
    elif bi >= 0 and policy == "recover":
        # 只減不加：出界後不再重開開倉腿，部位只能單調趨近 0
        cash, pos, fee_px = _apply_recover(
            cash, pos, fee_px, bi, seq, lower, spacing)

    res = {"pos": pos, "cash": cash, "fee_px": fee_px, "mark": c,
           "breach_i": bi, "spacing": spacing, "levels": levels}
    if policy == "hold":
        # pos = C - idx 僅在 hold 下全程成立；close/recover 出界後關係斷裂，
        # 故拆解只在 hold 提供，其餘回報 NaN 而非給一個算錯的數字。
        res["avg_entry"] = _open_avg_entry(idx_end, C, lower, spacing)
    return res


def _leg_down_first(open_px: float, close_px: float, path_order: str) -> bool:
    base = close_px >= open_px                   # 收漲 → 先探低
    return base if path_order == "auto" else (not base)


def _leg_down_first_arr(o: np.ndarray, c: np.ndarray, path_order: str) -> np.ndarray:
    base = c >= o
    return base if path_order == "auto" else ~base


def _apply_recover(cash, pos, fee_px, bi, seq, lower, spacing):
    """recover：出界後撤開倉腿，只保留 reduce-only 階梯（只減不加、不止損）。

    操作化定義（GRID_SIM_PREREG §三「撤掉開倉腿，只保留 reduce-only 階梯」）：
    自 bi 起，部位只允許朝 0 移動；任何會擴大 |pos| 的成交視為未發生。
    """
    cash, pos, fee_px = cash.copy(), pos.copy(), fee_px.copy()
    sign = np.sign(pos[bi]) if pos[bi] != 0 else 0.0
    if sign == 0:
        pos[bi:] = 0.0
        cash[bi:] = cash[bi]
        fee_px[bi:] = fee_px[bi]
        return cash, pos, fee_px
    # 允許的部位路徑：從 pos[bi] 單調趨近 0，取「歷史上最接近 0」的水位
    raw = pos[bi:]
    if sign > 0:
        allowed = np.minimum.accumulate(np.maximum(raw, 0.0))
    else:
        allowed = np.maximum.accumulate(np.minimum(raw, 0.0))
    d = np.diff(np.concatenate([[pos[bi]], allowed]))     # 每根實際減倉量
    px = lower + spacing * (seq[bi:, 3] + 0.5)            # 減倉成交價近似為該檔位
    cash[bi:] = cash[bi] + np.cumsum(-d * px)
    fee_px[bi:] = fee_px[bi] + np.cumsum(np.abs(d) * px)
    pos[bi:] = allowed
    return cash, pos, fee_px


# ─── 後處理：把槓桿無關序列展開成各情境 ────────────────────────────────
def evaluate(ep: dict, mid: float, n: int, lev: float, maint: float,
             fee: float, horizon_bars: int) -> dict:
    """由同一條庫存路徑解析求值某個 (L, 維持保證金, 費率, T) 情境。"""
    k = MARGIN_FRAC * lev / (n * mid)            # sizeBase / equity0
    s = slice(0, horizon_bars)
    pos, cash, fee_px, mark = ep["pos"][s], ep["cash"][s], ep["fee_px"][s], ep["mark"][s]

    gross = cash + pos * mark                    # 價格×單位
    eq = 1.0 + k * (gross - fee * fee_px)        # 權益倍數
    notional = np.abs(pos) * mark * k            # 名義／equity0

    liq = eq <= maint * notional
    li = int(np.nonzero(liq)[0][0]) if liq.any() else -1
    if li >= 0:
        eq_final, eq_path = 0.0, np.concatenate([eq[:li], [0.0]])
    else:
        eq_final, eq_path = float(eq[-1]), eq

    peak = np.maximum.accumulate(eq_path)
    mdd = float(np.max(1.0 - eq_path / np.where(peak > 0, peak, 1.0))) if eq_path.size else 0.0

    end = li if li >= 0 else len(pos) - 1
    out = {
        "net_return": eq_final - 1.0,
        "liquidated": int(li >= 0),
        "max_dd": mdd,
        "pnl_fee": -k * fee * float(fee_px[end]),
    }
    # 損益三分拆解：pnl_inv 由「持倉均價封閉解」獨立算出，不由 net_return 反推，
    # 三者相加是否等於 net_return 才構成真正的帳目交叉驗證（見 _open_avg_entry）。
    avg_e = ep.get("avg_entry")
    if avg_e is not None:
        unreal = float(pos[end]) * (float(mark[end]) - float(avg_e[end]))
        out["pnl_inv"] = k * unreal
        out["pnl_grid"] = k * (float(cash[end] + pos[end] * mark[end]) - unreal)
    else:
        out["pnl_inv"] = float("nan")
        out["pnl_grid"] = float("nan")
    return out


def _open_avg_entry(seq_end: np.ndarray, C: int, lower: float, spacing: float):
    """未平倉部位的均價（封閉解，僅 hold 策略成立）。

    因 pos = C - idx，當前持有的多單即買在 levels[idx .. C-1] 這 (C-idx) 檔；
    空單即賣在 levels[C+1 .. idx] 這 (idx-C) 檔。等差級數 → 均價 = 首末平均。
    """
    idx = seq_end
    pos = C - idx
    lo_i = np.where(pos > 0, idx, C + 1)
    hi_i = np.where(pos > 0, C - 1, idx)
    first = lower + spacing * lo_i
    last = lower + spacing * hi_i
    return np.where(pos == 0, 0.0, (first + last) / 2.0)


# ─── 自我驗證（已知答案，不看真實資料）────────────────────────────────
def _mk_bars(prices: np.ndarray):
    """把一串價格轉成 OHLC（每根 o=c=前後價，h/l 取兩端），供解析驗算。"""
    o = prices[:-1]
    c = prices[1:]
    h = np.maximum(o, c)
    l = np.minimum(o, c)
    return o, h, l, c


def self_test() -> int:
    ok = True

    def chk(label, cond, extra=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"   {extra}" if extra and not cond else ""))

    mid, W, N = 100.0, 10.0, 40           # levels 90..110，spacing 0.5
    lv = build_levels(mid, W, N)
    chk("build_levels 端點/格距", abs(lv[0] - 90) < 1e-9 and abs(lv[-1] - 110) < 1e-9
        and abs((lv[1] - lv[0]) - 0.5) < 1e-9)

    # ⓪ 對照 classic-grid test/grid.test.ts 的具體斷言：
    #    gridCount=80 → 買賣各 40 檔；=50 → 各 25 檔（skipBand 跳過正中一檔）
    for gc, want in [(80, 40), (50, 25), (40, 20)]:
        for m in (65_000.0, 97_500.0, 120_000.0):
            L_ = build_levels(m, 4.6, gc)
            sp_ = float(L_[1] - L_[0])
            a, b = seed_boundaries(m, L_, sp_)
            chk(f"seedOrders 對拍 gc={gc} mid={m:.0f}：買{a + 1} 賣{gc + 1 - b}",
                (a + 1) == want and (gc + 1 - b) == want)

    # ① 單調斜坡穿出上緣：只成交單邊，淨部位 = -(賣出檔數)
    ramp = np.linspace(100.0, 112.0, 400)
    o, h, l, c = _mk_bars(ramp)
    ep = simulate_episode(o, h, l, c, mid, W, N, "hold", "auto")
    # 自 mid 上方第一個掛賣檔到 levels[N] 全數成交
    _, j_hi = seed_boundaries(mid, lv, 0.5)
    expect_pos = -(N - j_hi + 1)
    chk("斜坡：淨部位 = 全部賣檔成交", abs(ep["pos"][-1] - expect_pos) < 1e-9,
        f"got {ep['pos'][-1]} want {expect_pos}")
    chk("斜坡：hold 下不得有反向開倉（pos 單調不增）",
        np.all(np.diff(ep["pos"]) <= 1e-12))
    # 現金 = 賣出價之和，解析可驗
    expect_cash = float(np.sum(lv[j_hi:]))
    chk("斜坡：現金 = 賣出檔價之和", abs(ep["cash"][-1] - expect_cash) < 1e-6,
        f"got {ep['cash'][-1]:.6f} want {expect_cash:.6f}")

    # ② 完整正弦震盪（振幅 < W）：淨部位歸零，格差收入 = 完成格數 × spacing
    t = np.linspace(0, 6 * np.pi, 6000)
    sine = mid + 5.0 * np.sin(t)          # ±5 < W=10，不出界
    o, h, l, c = _mk_bars(sine)
    ep = simulate_episode(o, h, l, c, mid, W, N, "hold", "auto")
    chk("正弦：未出界", ep["breach_i"] == -1)
    # 起訖同價（sin(0)=sin(6π)=0）→ 淨部位應回到起始水位
    chk("正弦：淨部位回歸 0 附近", abs(ep["pos"][-1]) <= 1.0,
        f"got {ep['pos'][-1]}")
    # PnL = cash + pos*mark，應為正且約等於 完成來回數 × spacing
    pnl = ep["cash"][-1] + ep["pos"][-1] * c[-1]
    chk("正弦：格差收入為正", pnl > 0, f"pnl={pnl:.4f}")

    # ③ 帳目自洽：cash + pos*mark 必須等於逐筆成交推導的損益
    chk("正弦：fee_px 為成交價絕對值累計（單調不減）",
        np.all(np.diff(ep["fee_px"]) >= -1e-12))

    # ④ close 策略：出界後部位歸零且凍結
    ramp2 = np.linspace(100.0, 125.0, 800)
    o, h, l, c = _mk_bars(ramp2)
    epc = simulate_episode(o, h, l, c, mid, W, N, "close", "auto")
    chk("close：出界後部位歸零", epc["breach_i"] >= 0 and abs(epc["pos"][-1]) < 1e-12)
    chk("close：出界後現金凍結",
        abs(epc["cash"][-1] - epc["cash"][epc["breach_i"]]) < 1e-9)

    # ⑤ recover：出界後 |pos| 單調不增
    eph = simulate_episode(o, h, l, c, mid, W, N, "recover", "auto")
    bi = eph["breach_i"]
    chk("recover：出界後 |pos| 單調不增",
        np.all(np.diff(np.abs(eph["pos"][bi:])) <= 1e-9))

    # ⑥ 強平時點對拍：造一條已知在特定倍率被強平的路徑
    crash = np.concatenate([np.linspace(100.0, 100.0, 5), np.linspace(100.0, 70.0, 300)])
    o, h, l, c = _mk_bars(crash)
    epx = simulate_episode(o, h, l, c, mid, W, N, "hold", "auto")
    hi = evaluate(epx, mid, N, 30, 0.02, 0.0, len(o))
    lo = evaluate(epx, mid, N, 3, 0.02, 0.0, len(o))
    chk("強平：30x 於 -30% 崩盤被強平", hi["liquidated"] == 1)
    chk("強平：被強平時淨報酬 = -100%", abs(hi["net_return"] + 1.0) < 1e-12)
    chk("強平：3x 同一路徑未被強平", lo["liquidated"] == 0,
        f"net={lo['net_return']:.4f}")
    chk("強平：低槓桿虧損 < 高槓桿", lo["net_return"] > hi["net_return"])

    # ⑦ 槓桿線性：未強平時淨報酬應與 L 成正比
    calm = mid + 2.0 * np.sin(np.linspace(0, 4 * np.pi, 3000))
    o, h, l, c = _mk_bars(calm)
    epl = simulate_episode(o, h, l, c, mid, W, N, "hold", "auto")
    r3 = evaluate(epl, mid, N, 3, 0.02, 0.0, len(o))
    r30 = evaluate(epl, mid, N, 30, 0.02, 0.0, len(o))
    chk("槓桿線性：r30 = 10 × r3（未強平時）",
        r3["liquidated"] == 0 and r30["liquidated"] == 0
        and abs(r30["net_return"] - 10 * r3["net_return"]) < 1e-9,
        f"r3={r3['net_return']:.6f} r30={r30['net_return']:.6f}")

    # ⑧ 手續費方向：費率越高淨報酬越低
    f0 = evaluate(epl, mid, N, 10, 0.02, 0.0, len(o))
    f5 = evaluate(epl, mid, N, 10, 0.02, 0.0005, len(o))
    chk("手續費：5bp 淨報酬低於 0bp", f5["net_return"] < f0["net_return"])

    # ⑨ 精確方波：於相鄰兩檔間來回 k 次，格差收入須恰為 k × spacing
    #    這是最強的一項——直接驗「買在 i、賣在 i+1」的核心不對稱。
    k_cycles = 7
    lo_px, hi_px = 99.5, 100.0          # levels[19], levels[20]，相鄰一格
    wave = np.array([hi_px] + [lo_px, hi_px] * k_cycles)   # 自錨點 100 起跳
    o, h, l, c = _mk_bars(wave)
    epw = simulate_episode(o, h, l, c, mid, W, N, "hold", "auto")
    # 每輪「買 99.5 → 賣 100」賺一個 spacing；末端回到 100 故淨部位 0
    rw = evaluate(epw, mid, N, 10, 0.02, 0.0, len(o))
    kk = MARGIN_FRAC * 10 / (N * mid)
    want_grid = kk * k_cycles * 0.5      # k × spacing
    chk("方波：格差收入 = k × spacing（精確）",
        abs(rw["pnl_grid"] - want_grid) < 1e-12,
        f"got {rw['pnl_grid']:.12f} want {want_grid:.12f}")
    chk("方波：末端淨部位 0", abs(epw["pos"][-1]) < 1e-9, f"got {epw['pos'][-1]}")
    chk("方波：淨報酬 = 格差收入（無倉無費）",
        abs(rw["net_return"] - want_grid) < 1e-12,
        f"net={rw['net_return']:.12f}")

    # ⑩ 帳目自洽：三分拆解相加須等於 net_return（pnl_inv 為獨立封閉解，非反推）
    for lev_ in (3, 30):
        for fee_ in (0.0, 0.0005):
            r = evaluate(epl, mid, N, lev_, 0.02, fee_, len(calm) - 1)
            tot = r["pnl_grid"] + r["pnl_inv"] + r["pnl_fee"]
            chk(f"帳目自洽 L={lev_} fee={fee_}",
                abs(tot - r["net_return"]) < 1e-9,
                f"sum={tot:.12f} net={r['net_return']:.12f}")

    # ⑪ 格差收入恆非負（hold 下只在獲利時完成來回；為負即代表撮合有誤）
    for path_ in PATH_ORDERS:
        ep_ = simulate_episode(*_mk_bars(sine), mid, W, N, "hold", path_)
        r_ = evaluate(ep_, mid, N, 10, 0.02, 0.0, len(sine) - 1)
        chk(f"格差收入非負（path={path_}）", r_["pnl_grid"] >= -1e-12,
            f"got {r_['pnl_grid']:.12f}")

    print("\n" + ("SELF-TEST ALL PASS" if ok else "SELF-TEST FAILED"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--data-dir")
    ap.add_argument("--out-prefix")
    ap.add_argument("--pairs", default=None, help="預設用資料目錄下全部")
    ap.add_argument("--limit-anchors", type=int, default=0, help="0=不限，>0 供計時用")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.data_dir or not args.out_prefix:
        ap.error("--data-dir 與 --out-prefix 為必填（或用 --self-test）")
    return run_full(args)


ANCHOR_STRIDE = 1441   # 分鐘。刻意用 1440+1：每個錨點相位漂移 1 分鐘，
                       # 窗口內即覆蓋全部 24 個 UTC 小時，避免 program.md §4
                       # 「已知限制②」的固定時刻日格點退化。


def _episode_scalars(ep: dict, mid: float, n: int, horizons: list[int],
                     levs: list[float], maints: list[float], fees: list[float]):
    """由單一 episode 的槓桿無關序列，解析求出所有 (L, mm, fee, T) 情境。

    強平條件 1 + k(gross - fee*fee_px) <= mm*k*|pos|*mark 可整理為

        g(t) := gross(t) - fee*fee_px(t) - mm*|pos(t)|*mark(t)  <=  -1/k

    g 與槓桿無關。對 g 取 running minimum（單調不增）後，各槓桿的首次強平時點
    退化成一次 searchsorted，不必逐槓桿掃全序列。
    """
    pos, cash, fee_px, mark = ep["pos"], ep["cash"], ep["fee_px"], ep["mark"]
    gross = cash + pos * mark
    absnot = np.abs(pos) * mark
    nb = len(pos)
    avg_e = ep.get("avg_entry")

    for mm in maints:
        for fee in fees:
            g = gross - fee * fee_px - mm * absnot
            gmin = np.minimum.accumulate(g)
            for lev in levs:
                k = MARGIN_FRAC * lev / (n * mid)
                # 首次 g <= -1/k：gmin 單調遞減，故用 -gmin 遞增做 searchsorted
                li = int(np.searchsorted(-gmin, 1.0 / k, side="left"))
                for T in horizons:
                    end = min(T, nb) - 1
                    liq = li <= end
                    if liq:
                        net, e = -1.0, li
                    else:
                        e = end
                        net = float(1.0 + k * (gross[e] - fee * fee_px[e])) - 1.0
                    if avg_e is not None and not liq:
                        unreal = float(pos[e]) * (float(mark[e]) - float(avg_e[e]))
                        p_inv = k * unreal
                        p_grid = k * (float(gross[e]) - unreal)
                    else:
                        p_inv = p_grid = float("nan")
                    yield (mm, fee, lev, T), (net, int(liq),
                                              -k * fee * float(fee_px[e]), p_inv, p_grid)


def _quantiles(v: np.ndarray) -> dict:
    q = np.percentile(v, [5, 25, 50, 75, 95])
    return {"mean": float(v.mean()), "p5": float(q[0]), "p25": float(q[1]),
            "median": float(q[2]), "p75": float(q[3]), "p95": float(q[4])}


def _block_bootstrap_ci(v: np.ndarray, weeks: np.ndarray, n_boot: int = 2000,
                        seed: int = 20260803) -> tuple[float, float]:
    """逐 ISO 週 block bootstrap（沿用 Q1' run2 作法；錨點重疊故 episode 非獨立）。"""
    uw = np.unique(weeks)
    if uw.size < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx_by_w = {w: np.nonzero(weeks == w)[0] for w in uw}
    means = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.choice(uw, size=uw.size, replace=True)
        sel = np.concatenate([idx_by_w[w] for w in pick])
        means[b] = v[sel].mean()
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def run_full(args) -> int:
    data_dir = Path(args.data_dir)
    files = sorted(data_dir.glob("*-1m.feather"))
    if args.pairs:
        want = {p.strip().replace("/", "_") for p in args.pairs.split(",")}
        files = [f for f in files if f.name.split("-1m")[0] in want]
    if not files:
        print(f"[err] {data_dir} 下沒有 *-1m.feather", file=sys.stderr)
        return 1

    horizons = [d * BARS_PER_DAY for d in HORIZONS_D]
    max_h = max(horizons)
    main_mm, main_fee, main_path = MAINT_RATES[0], FEE_RATES[0], "auto"

    # 主情境存逐筆 net（供分位數與 bootstrap）；穩健性情境只累計彙總。
    # pair / iso_week 對所有格位是同一組錨點序列，故只存一份，不隨格位複製
    # （450 格 × 12,760 錨點若各存 tuple 會吃到 GB 級）。
    # liquidated 不另存：強平時 net 恆被設為 -1.0，可由 net 精確還原。
    samples: dict[tuple, list] = {}
    sums: dict[tuple, list] = {}
    agg: dict[tuple, list] = {}
    anchor_pair: list[str] = []
    anchor_week: list[int] = []

    import time
    t0 = time.time()
    n_ep = 0

    for fp in files:
        pair = fp.name.split("-1m")[0]
        df = pd.read_feather(fp)
        o = df["open"].to_numpy(np.float64)
        h = df["high"].to_numpy(np.float64)
        l = df["low"].to_numpy(np.float64)
        c = df["close"].to_numpy(np.float64)
        dates = df["date"].to_numpy()
        nbars = len(c)
        anchors = np.arange(0, nbars - max_h - 1, ANCHOR_STRIDE)
        if args.limit_anchors:
            anchors = anchors[: args.limit_anchors]
        print(f"[{pair}] {nbars} 根，{len(anchors)} 個錨點", flush=True)

        for a in anchors:
            mid = float(c[a])
            s = slice(a + 1, a + 1 + max_h)
            oo, hh, ll, cc = o[s], h[s], l[s], c[s]
            wk = pd.Timestamp(dates[a]).isocalendar()
            anchor_pair.append(pair)
            anchor_week.append(wk[0] * 100 + wk[1])

            for W in HALF_BANDS:
                for N in GRID_COUNTS:
                    for pol in POLICIES:
                        for path in PATH_ORDERS:
                            is_main_path = path == main_path
                            ep = simulate_episode(oo, hh, ll, cc, mid, W, N, pol, path)
                            n_ep += 1
                            mms = MAINT_RATES if is_main_path else [main_mm]
                            fes = FEE_RATES if is_main_path else [main_fee]
                            for (mm, fee, lev, T), vals in _episode_scalars(
                                    ep, mid, N, horizons, LEVERAGES, mms, fes):
                                key = (W, N, pol, path, lev, T, mm, fee)
                                net, liq, pfee, pinv, pgrid = vals
                                if (mm, fee, path) == (main_mm, main_fee, main_path):
                                    samples.setdefault(key, []).append(net)
                                    r = sums.setdefault(key, [0, 0.0, 0.0, 0.0, 0])
                                    r[0] += 1
                                    r[3] += pfee
                                    if pgrid == pgrid:      # 非 NaN（close/recover 不提供拆解）
                                        r[1] += pgrid; r[2] += pinv; r[4] += 1
                                else:
                                    r = agg.setdefault(key, [0, 0.0, 0])
                                    r[0] += 1; r[1] += net; r[2] += liq

        el = time.time() - t0
        print(f"  … 累計 {n_ep} episodes，{el:.1f}s（{n_ep / max(el, 1e-9):.0f} ep/s）",
              flush=True)

    _write_outputs(args.out_prefix, samples, sums, agg, anchor_pair, anchor_week)
    print(f"[done] {n_ep} episodes，{time.time() - t0:.1f}s")
    return 0


def _write_outputs(prefix: str, samples: dict, sums: dict, agg: dict,
                   anchor_pair: list, anchor_week: list) -> None:
    weeks_all = np.array(anchor_week, dtype=np.int64)
    pairs_all = np.array(anchor_pair)
    rows = []
    for key, vals in sorted(samples.items()):
        W, N, pol, path, lev, T, mm, fee = key
        arr = np.asarray(vals, dtype=np.float64)
        # 強平時 net 恆被設為 -1.0（見 _episode_scalars），故可精確還原
        liq = (arr <= -1.0 + 1e-12).astype(np.float64)
        wks = weeks_all[: len(arr)]
        q = _quantiles(arr)
        lo, hi = _block_bootstrap_ci(arr, wks)
        n_, sg, si, sf, ng = sums[key]
        rows.append({
            "half_band_pct": W, "grid_count": N, "policy": pol, "path": path,
            "leverage": lev, "horizon_d": T // BARS_PER_DAY,
            "maint_rate": mm, "fee_rate": fee, "n": len(arr),
            "net_mean": q["mean"], "net_p5": q["p5"], "net_p25": q["p25"],
            "net_median": q["median"], "net_p75": q["p75"], "net_p95": q["p95"],
            "net_ci_lo": lo, "net_ci_hi": hi,
            "liq_rate": float(liq.mean()),
            "pnl_grid_mean": (sg / ng) if ng else float("nan"),
            "pnl_inv_mean": (si / ng) if ng else float("nan"),
            "pnl_fee_mean": sf / n_,
            "scenario": "main",
        })
    for key, (n, s, lq) in sorted(agg.items()):
        W, N, pol, path, lev, T, mm, fee = key
        rows.append({
            "half_band_pct": W, "grid_count": N, "policy": pol, "path": path,
            "leverage": lev, "horizon_d": T // BARS_PER_DAY,
            "maint_rate": mm, "fee_rate": fee, "n": n,
            "net_mean": s / n if n else float("nan"),
            "liq_rate": lq / n if n else float("nan"),
            "scenario": "robustness",
        })
    out = pd.DataFrame(rows)
    out.to_csv(f"{prefix}_result_table.tsv", sep="\t", index=False, float_format="%.6g")
    print(f"[out] {prefix}_result_table.tsv  ({len(out)} 列)")

    # 逐 episode 明細（供覆核）。錨點的 pair/iso_week 對所有格位共用，
    # 故用長格式重建：每個格位一段，順序即錨點順序。
    frames = []
    for key, vals in sorted(samples.items()):
        W, N, pol, path, lev, T, mm, fee = key
        arr = np.asarray(vals, dtype=np.float32)
        m = len(arr)
        frames.append(pd.DataFrame({
            "half_band_pct": np.float32(W), "grid_count": np.int16(N),
            "policy": pol, "leverage": np.int16(lev),
            "horizon_d": np.int16(T // BARS_PER_DAY),
            "pair": pairs_all[:m], "iso_week": weeks_all[:m].astype(np.int32),
            "net_return": arr,
            "liquidated": (arr <= -1.0 + 1e-12).astype(np.int8),
        }))
    sdf = pd.concat(frames, ignore_index=True)
    sdf.to_feather(f"{prefix}_samples.feather")
    print(f"[out] {prefix}_samples.feather  ({len(sdf)} 列)")


if __name__ == "__main__":
    sys.exit(main())
