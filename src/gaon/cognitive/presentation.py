"""Read-only rendering of explicitly requested client snapshots, never evidence."""

import math
import re


def binance_snapshot_reply(message: str, context: object) -> str | None:
    text = message.casefold()
    if not (any(x in text for x in ("binance", "바이낸스")) and
            any(x in text for x in ("포지션", "잔고", "position", "balance"))):
        return None
    if not isinstance(context, dict) or context.get("domain") != "binance":
        return None
    if context.get("source") != "dashboard_state_snapshot" or context.get("unavailable"):
        return "현재 Binance 상태 스냅샷을 읽을 수 없습니다. 실시간 잔고나 포지션을 추정하지 않겠습니다."
    positions = context.get("positions")
    if not isinstance(positions, list):
        return "Binance 포지션 스냅샷 형식이 올바르지 않아 상태를 확정할 수 없습니다."
    lines = ["Dashboard가 제공한 Binance 스냅샷입니다. 거래소 실시간 재조회 결과는 아닙니다."]
    stamp = context.get("updated_at")
    if isinstance(stamp, str) and re.fullmatch(r"[0-9T:Z+.\- ]{10,40}", stamp):
        lines.append(f"스냅샷 기준: {stamp}")
    else:
        lines.append("스냅샷 시각이 없어 최신 여부를 확인할 수 없습니다.")
    equity = context.get("equity")
    if isinstance(equity, (int, float)) and not isinstance(equity, bool) and math.isfinite(equity):
        lines.append(f"Futures 평가금액: {equity:,.2f} USDT (거래 손익과 다릅니다)")
    if not positions:
        lines.append("이 스냅샷에 기록된 보유 포지션은 없습니다.")
    for item in positions[:10]:
        if not isinstance(item, dict) or not re.fullmatch(r"[A-Z0-9]{2,30}", str(item.get("symbol", ""))):
            continue
        amount = item.get("amount")
        if not isinstance(amount, (int, float)) or isinstance(amount, bool) or not math.isfinite(amount):
            continue
        lines.append(f"- {item['symbol']}: 수량 {amount:g}")
    return "\n".join(lines)
