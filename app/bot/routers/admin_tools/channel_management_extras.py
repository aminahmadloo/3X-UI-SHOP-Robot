from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.routers.admin_tools.channel_management_handler import ChannelStates, _channel, _menu
from app.bot.routers.special_offer_handler import _campaign_offers, _duration_title
from app.db.models import ChannelContent, SpecialOfferCampaign

router = Router(name=__name__)


@router.callback_query(F.data == "channel:server_notice", IsAdmin())
async def server_notice_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await _channel(session):
        await callback.answer("ابتدا کانال را متصل کن.", show_alert=True)
        return
    await state.clear()
    await state.update_data(title="اطلاعیه سرور")
    await state.set_state(ChannelStates.waiting_text)
    await callback.answer()
    await callback.message.edit_text("⚡ <b>اطلاعیه سرور</b>\n\nمتن اطلاعیه را ارسال کن.\nمثلاً: سرور هلند در حال بروزرسانی است و تا ۱۵ دقیقه دیگر فعال می‌شود.", reply_markup=__import__("app.bot.routers.admin_tools.channel_management_handler", fromlist=["_cancel"])._cancel())


@router.callback_query(F.data == "channel:special", IsAdmin())
async def special_offer_start(callback: CallbackQuery, session: AsyncSession):
    result = await session.execute(
        __import__("sqlalchemy").select(SpecialOfferCampaign)
        .where(SpecialOfferCampaign.is_active.is_(True))
        .order_by(SpecialOfferCampaign.is_default.asc(), SpecialOfferCampaign.id)
    )
    campaigns = list(result.scalars().all())
    b = InlineKeyboardBuilder()
    for campaign in campaigns:
        offers = await _campaign_offers(session, campaign.id)
        if offers:
            b.row(InlineKeyboardButton(text=f"🔥 {campaign.title}", callback_data=f"channel:special:publish:{campaign.id}"))
    b.row(InlineKeyboardButton(text="🔙 مدیریت کانال", callback_data="channel:menu"))
    await callback.answer()
    await callback.message.edit_text("🔥 <b>انتشار فروش ویژه</b>\n\nکمپین فروش ویژه موردنظر را انتخاب کن:", reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^channel:special:publish:\d+$"), IsAdmin())
async def special_offer_publish(callback: CallbackQuery, session: AsyncSession):
    campaign_id = int(callback.data.rsplit(":", 1)[1])
    channel = await _channel(session)
    campaign = await session.get(SpecialOfferCampaign, campaign_id)
    if not channel or not campaign or not campaign.is_active:
        await callback.answer("کمپین یا کانال پیدا نشد.", show_alert=True)
        return
    offers = await _campaign_offers(session, campaign.id)
    if not offers:
        await callback.answer("این کمپین سرویس فعالی ندارد.", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    body = [f"🔥 <b>{campaign.title}</b>", "", "🎁 پیشنهادهای ویژه امروز:", ""]
    for _, plan in offers:
        offer = next(row[0] for row in offers if row[1].id == plan.id)
        body.append(f"📦 {plan.volume_gb} گیگ — {plan.duration_days} روزه — <b>{offer.special_price_toman:,} تومان</b>")
        builder.row(InlineKeyboardButton(text=f"🛒 {plan.volume_gb} گیگ / {_duration_title(plan.duration_days)}", callback_data=f"special_offer:plan:{campaign.id}:{plan.id}"))
    builder.row(InlineKeyboardButton(text="🚀 مشاهده همه پیشنهادها", callback_data=f"special_offer:campaign:{campaign.id}"))
    sent = await callback.message.bot.send_message(channel.chat_id, "\n".join(body), reply_markup=builder.as_markup())
    content = ChannelContent(channel_id=channel.id, title=campaign.title[:255], content_type="text", body="\n".join(body), status="published", published_at=__import__("datetime").datetime.utcnow(), telegram_message_id=sent.message_id)
    content.buttons = [
        {"label": f"🛒 {plan.volume_gb} گیگ / {_duration_title(plan.duration_days)}", "callback_data": f"special_offer:plan:{campaign.id}:{plan.id}"}
        for _, plan in offers
    ]
    session.add(content)
    await session.commit()
    await callback.answer("✅ فروش ویژه در کانال منتشر شد")
    await callback.message.edit_text(f"✅ فروش ویژه <b>{campaign.title}</b> منتشر شد.\n🆔 پیام: <code>{sent.message_id}</code>", reply_markup=_menu())
