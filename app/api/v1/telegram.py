"""
Telegram bot webhook — responds only to OWNER_TELEGRAM_ID.
Anyone else gets a polite "ليس مصرحًا لك" reply.
"""

import logging
import io
import json
from typing import Optional, Annotated

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import get_db
from app.core.analyzer import AnalyzerError
from app.services.analysis_service import perform_analysis

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/telegram", tags=["telegram"])


TG_API = "https://api.telegram.org"


# ─── Telegram API helpers ───

async def _tg(method: str, **payload):
    if not settings.TELEGRAM_BOT_TOKEN:
        return None
    url = f"{TG_API}/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        return r.json()


async def _send_message(chat_id: int, text: str, parse_mode: str = "HTML"):
    return await _tg("sendMessage", chat_id=chat_id, text=text, parse_mode=parse_mode)


async def _download_file(file_id: str) -> Optional[bytes]:
    if not settings.TELEGRAM_BOT_TOKEN:
        return None
    info = await _tg("getFile", file_id=file_id)
    if not info or not info.get("ok"):
        return None
    file_path = info["result"]["file_path"]
    file_url = f"{TG_API}/file/bot{settings.TELEGRAM_BOT_TOKEN}/{file_path}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(file_url)
        r.raise_for_status()
        return r.content


# ─── Owner check ───

def _is_owner(tg_user_id: int) -> bool:
    return settings.OWNER_TELEGRAM_ID and tg_user_id == settings.OWNER_TELEGRAM_ID


# ─── Webhook ───

@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
):
    """Telegram webhook entry point."""
    # Verify webhook secret
    if settings.TELEGRAM_WEBHOOK_SECRET:
        if x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(403, "Bad webhook secret")

    update = await request.json()
    message = update.get("message") or update.get("channel_post") or {}
    if not message:
        return {"ok": True}

    tg_user = message.get("from", {})
    tg_user_id = tg_user.get("id")
    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()

    # Reject non-owner
    if not _is_owner(tg_user_id):
        if chat_id:
            try:
                await _send_message(chat_id, "⛔ هذا البوت خاص. ليس مصرحًا لك.")
            except Exception:
                pass
        return {"ok": True, "ignored": True}

    # ─── Commands ───

    if text.startswith("/start"):
        await _send_message(chat_id,
            f"<b>أهلاً {settings.OWNER_DISPLAY_NAME} 👋</b>\n\n"
            f"ابعث صورة شارت XAUUSD لتحليل فوري.\n"
            f"أوامر: /help /stats /last"
        )
        return {"ok": True}

    if text.startswith("/help"):
        await _send_message(chat_id,
            "<b>الأوامر المتاحة:</b>\n"
            "📸 ارسل صورة شارت → تحليل فوري\n"
            "/stats — إحصائيات حسابك\n"
            "/last — آخر تحليل"
        )
        return {"ok": True}

    if text.startswith("/stats"):
        from sqlalchemy import select, func
        from app.models.analysis import Analysis
        total = (await db.execute(select(func.count(Analysis.id)))).scalar_one()
        cost = (await db.execute(select(func.coalesce(func.sum(Analysis.cost_usd), 0)))).scalar_one()
        await _send_message(chat_id,
            f"<b>📊 الإحصائيات</b>\n"
            f"إجمالي التحاليل: <b>{total}</b>\n"
            f"التكلفة الإجمالية: <b>${float(cost):.4f}</b>"
        )
        return {"ok": True}

    if text.startswith("/last"):
        from sqlalchemy import select
        from app.models.analysis import Analysis
        last = (await db.execute(
            select(Analysis).order_by(Analysis.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        if not last:
            await _send_message(chat_id, "ما في تحاليل بعد. ابعث صورة!")
        else:
            setups = (last.result_json or {}).get("setups", [])
            await _send_message(chat_id,
                f"<b>آخر تحليل</b>\n"
                f"📊 {last.symbol} · {last.timeframe}\n"
                f"💰 السعر: {last.chart_price or '?'}\n"
                f"📈 Bias: {last.primary_bias or '?'}\n"
                f"🎯 Setups: {len(setups)}\n"
                f"🌐 {settings.BASE_URL.rstrip('/')}/history"
            )
        return {"ok": True}

    # ─── Photo handling ───

    photos = message.get("photo")
    document = message.get("document")
    file_id = None
    if photos:
        file_id = photos[-1]["file_id"]  # largest
    elif document and (document.get("mime_type") or "").startswith("image/"):
        file_id = document["file_id"]

    if file_id:
        await _send_message(chat_id, "🔄 جاري التحليل...")

        try:
            img_bytes = await _download_file(file_id)
            if not img_bytes:
                await _send_message(chat_id, "❌ تعذّر تحميل الصورة")
                return {"ok": True}

            extra_context = message.get("caption") or None
            analysis = await perform_analysis(
                db, [img_bytes], extra_context, source="telegram", actor="telegram_bot",
            )

            # Format short reply
            r = analysis.result_json or {}
            cm = r.get("chart_meta", {})
            sb = r.get("session_bias", {})
            pd = r.get("premium_discount", {})
            setups = r.get("setups", [])

            lines = [
                f"<b>✅ التحليل جاهز</b>",
                f"📊 {cm.get('symbol','?')} · {cm.get('timeframe','?')} @ {cm.get('current_price') or '?'}",
                f"📈 Bias: {sb.get('primary_bias','?')} | Zone: {pd.get('current_zone','?')}",
                "",
            ]
            for i, s in enumerate(setups[:3]):
                emoji = "🟢" if s.get('direction') == 'buy' else "🔴"
                tps = ", ".join(str(t.get("level", "?")) for t in s.get("take_profits", [])[:3])
                lines.append(f"{emoji} <b>{s.get('label','?')}</b>")
                lines.append(f"   Entry: {s.get('avg_entry') or s.get('entries',[None])[0]} · SL: {s.get('stop_loss')} · TP: {tps}")
                lines.append(f"   R:R: {s.get('risk_reward','?')}")
                lines.append("")

            lines.append(f"🌐 {settings.BASE_URL.rstrip('/')}/history")
            await _send_message(chat_id, "\n".join(lines))

        except AnalyzerError as e:
            await _send_message(chat_id, f"⚠️ {e}")
        except Exception as e:
            logger.exception("Telegram analysis failed")
            await _send_message(chat_id, f"❌ خطأ داخلي: {e}")

        return {"ok": True}

    # Fallback
    if chat_id:
        await _send_message(chat_id, "ابعث صورة شارت أو استخدم /help")
    return {"ok": True}
