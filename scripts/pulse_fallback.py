"""日報 fallback 鏈第 2/3 層：Claude 不可用時由本腳本接手。

第 2 層：MiniMax API（MiniMax-M2，OpenAI 相容端點）寫日報，標註「MiniMax 代筆」。
第 3 層：MiniMax 也失敗 → 純數字模板直出（無 LLM），Discord 永遠有東西。

紅線：本腳本只做「報表 prose」；不碰 journal、不碰偵測鏈、不做任何決策。
數字一律來自 NAS 聚合 payload，LLM 只組句不計算。
"""
import argparse
import json
import os
import re
import sys
import urllib.request

MINIMAX_URL = "https://api.minimax.io/v1/chat/completions"
MINIMAX_MODEL = os.environ.get("MINIMAX_MODEL", "MiniMax-M3")  # 2026-07 探勘：M3/M2.5/M2 方案內可用
UA = "pump-radar-pulse/1.0"  # Discord webhook 必帶自訂 UA（Cloudflare 擋預設 UA 回 403）


def minimax_digest(payload: dict, api_key: str) -> str:
    """讓 MiniMax 依同一套日報規格組句；失敗拋例外交給模板層。"""
    prompt = (
        "你是 pump-radar（15m 布林帶波段啟動偵測器）的日報代筆。這是偵測追蹤器不是交易系統，"
        "樣本內基準 net_24h 為負，日報意義是誠實對帳不是報喜。以下是過去 24h 聚合數據（JSON）：\n"
        + json.dumps(payload, ensure_ascii=False)
        + "\n\n寫 ≤10 行繁體中文日報：1) 新訊號（標的/級別/vol_z）；2) 剛結算成績逐筆一行"
        "（net_24h 含費，對比基準 mean −0.37%）；3) forward 進度與累計 vs 基準，樣本<30 必說"
        "「樣本不足勿下結論」；4) regime_sentinel 一行（讀數、連續達標 N/30 天）；5) 結尾一句"
        "誠實觀察。數字保留一位小數、不要 code block、不要開頭問候。只輸出日報本文。"
    )
    req = urllib.request.Request(
        MINIMAX_URL, method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        data=json.dumps({
            "model": MINIMAX_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 6144,
        }).encode())
    body = json.loads(urllib.request.urlopen(req, timeout=90).read().decode())
    if body.get("error"):
        raise RuntimeError(f"minimax error: {body['error']}")
    if body["choices"][0].get("finish_reason") != "stop":
        raise RuntimeError(f"finish_reason={body['choices'][0].get('finish_reason')}")
    text = body["choices"][0]["message"]["content"]
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()  # 推理殘留剝除
    if not text or "<think>" in text:   # 空白或未閉合（max_tokens 截斷）都算失敗
        raise RuntimeError("minimax empty/truncated content")
    return f"📡 pump-radar 日報 {payload.get('date_taipei', '')}（MiniMax 代筆）\n{text}"


def template_digest(payload: dict) -> str:
    """第 3 層：純數字模板，欄位缺失容忍，永不拋例外。"""
    lines = [f"📡 pump-radar 日報 {payload.get('date_taipei', '')}（純數字版，LLM 不可用）"]
    sigs = payload.get("new_signals_24h") or []
    lines.append("新訊號：" + ("、".join(
        f"{s.get('pair', '?')} {s.get('grade', '?')}級 vol_z={s.get('vol_z', '?')}"
        for s in sigs[:8]) if sigs else "無"))
    scored = payload.get("newly_scored") or []
    if scored:
        for r in scored[:8]:
            net = r.get("net_24h")
            lines.append(f"結算：{r.get('pair', '?')} {r.get('grade', '?')}級 "
                         f"net_24h={net * 100:+.1f}%" if isinstance(net, (int, float))
                         else f"結算：{r.get('pair', '?')} net 缺值")
    else:
        lines.append("結算：本日無新結算")
    fp = payload.get("forward_progress") or {}
    lines.append(f"forward：{fp.get('scored_total', '?')}/{fp.get('target', '?')} 筆"
                 + (f"，累計 net 均值 {fp['net_mean'] * 100:+.2f}%"
                    if isinstance(fp.get("net_mean"), (int, float)) else ""))
    rs = payload.get("regime_sentinel") or {}
    lines.append(f"哨兵：align_share={rs.get('value', 'null')}，連續達標 "
                 f"{rs.get('streak', '?')}/30 天")
    lines.append("（Claude 與 MiniMax 均不可用，本報由模板直出，僅列事實數字。）")
    return "\n".join(lines[:10])


def post_discord(content: str, webhook: str) -> None:
    req = urllib.request.Request(
        webhook, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": UA},
        data=json.dumps({"content": content}, ensure_ascii=False).encode())
    urllib.request.urlopen(req, timeout=30).read()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", required=True)
    ap.add_argument("--dry-run", action="store_true", help="只印不發 Discord")
    args = ap.parse_args()
    payload = json.load(open(args.payload))

    api_key = os.environ.get("MINIMAX_API_KEY", "")
    digest = None
    if api_key:
        try:
            digest = minimax_digest(payload, api_key)
            print("[fallback] MiniMax 代筆成功", file=sys.stderr)
        except Exception as e:  # 429/逾時/格式全部落模板
            print(f"[fallback] MiniMax 失敗：{e}", file=sys.stderr)
    if digest is None:
        digest = template_digest(payload)
        print("[fallback] 使用純數字模板", file=sys.stderr)

    if args.dry_run:
        print(digest)
        return 0
    post_discord(digest, os.environ["DISCORD_WEBHOOK_URL"])
    print("[fallback] Discord 已送出", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
