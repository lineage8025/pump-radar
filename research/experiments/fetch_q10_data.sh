#!/bin/sh
# Q10 資料抓取：15m（bbw_pct 分桶，暖機 2022-12）＋ 1m（符號翻轉重建路徑）
# 窗口 in-sample only：15m 2022-12~2025-06、1m 2023-01~2025-06。禁止觸碰封存段。
set -e
P="BTC/USDT ETH/USDT ADA/USDT SOL/USDT XRP/USDT DOGE/USDT BNB/USDT LINK/USDT LTC/USDT AVAX/USDT"
mkdir -p /tmp/kl15 /tmp/kl1m
for pair in $P; do
  python3 research/fetch_klines.py --pairs "$pair" --start 2022-12 --end 2025-06 --interval 15m --out-dir /tmp/kl15 > /tmp/f15_$(echo $pair | cut -d/ -f1).log 2>&1 &
done
wait
echo "=== 15m done ==="
n=0
for pair in $P; do
  python3 research/fetch_klines.py --pairs "$pair" --start 2023-01 --end 2025-06 --interval 1m --out-dir /tmp/kl1m > /tmp/f1m_$(echo $pair | cut -d/ -f1).log 2>&1 &
  n=$((n+1))
done
wait
echo "=== 1m done ==="
ls -la /tmp/kl15 /tmp/kl1m
