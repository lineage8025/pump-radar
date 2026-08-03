"""暴力版網格撮合：顯式維護掛單集合，逐點推進。慢但語意直白，用來對拍快速版。"""
import numpy as np


def brute(o, h, l, c, mid, W, N, skip_band=0.25, path_order="auto"):
    lower = mid * (1 - W / 100.0)
    upper = mid * (1 + W / 100.0)
    levels = np.linspace(lower, upper, N + 1)
    sp = levels[1] - levels[0]
    band = skip_band * sp

    # 掛單集合：level index -> 'buy' / 'sell'
    orders = {}
    for i, lv in enumerate(levels):
        if lv <= mid - band:
            orders[i] = "buy"
        elif lv >= mid + band:
            orders[i] = "sell"
    pos = 0.0
    cash = 0.0
    feepx = 0.0
    prev = mid                      # 路徑上的前一個價格點（自錨點起）

    pos_s = np.empty(len(o)); cash_s = np.empty(len(o)); fee_s = np.empty(len(o))

    for t in range(len(o)):
        if path_order == "auto":
            pts = [l[t], h[t], c[t]] if c[t] >= o[t] else [h[t], l[t], c[t]]
        else:
            pts = [h[t], l[t], c[t]] if c[t] >= o[t] else [l[t], h[t], c[t]]
        for p in pts:
            if p > prev:            # 上行：觸發區間 (prev, p] 內的賣單
                hit = [i for i, s in orders.items()
                       if s == "sell" and prev < levels[i] <= p]
                for i in sorted(hit):
                    pos -= 1.0; cash += levels[i]; feepx += levels[i]
                    del orders[i]
                    j = i - 1       # 賣成交於 i → 於 i-1 掛買
                    if 0 <= j and j not in orders:
                        orders[j] = "buy"
            elif p < prev:          # 下行：觸發區間 [p, prev) 內的買單
                hit = [i for i, s in orders.items()
                       if s == "buy" and p <= levels[i] < prev]
                for i in sorted(hit, reverse=True):
                    pos += 1.0; cash -= levels[i]; feepx += levels[i]
                    del orders[i]
                    j = i + 1       # 買成交於 i → 於 i+1 掛賣
                    if j <= N and j not in orders:
                        orders[j] = "sell"
            prev = p
        pos_s[t] = pos; cash_s[t] = cash; fee_s[t] = feepx
    return {"pos": pos_s, "cash": cash_s, "fee_px": fee_s, "mark": c}
