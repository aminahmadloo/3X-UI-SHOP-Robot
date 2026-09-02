import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.states.advertising import AdvertisingStates
from app.bot.utils.navigation import NavAdminTools
from app.db.models import AdvertisingCampaign, AdvertisingChannel, AdvertisingEvent, ServicePeriod, ServicePurchasePlan

logger = logging.getLogger(__name__)
router = Router(name=__name__)


def menu_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➕ افزودن کانال", callback_data="advertising:add_channel"))
    b.row(InlineKeyboardButton(text="📣 ساخت و انتشار تبلیغ", callback_data="advertising:create"))
    b.row(InlineKeyboardButton(text="📊 گزارش تبلیغات", callback_data="advertising:stats"))
    b.row(InlineKeyboardButton(text="📋 مدیریت کانال‌ها", callback_data="advertising:channels"))
    b.row(InlineKeyboardButton(text="🏠 منوی مدیریت", callback_data=NavAdminTools.MAIN))
    return b.as_markup()


@router.callback_query(F.data == "advertising:menu", IsAdmin())
async def menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "📣 <b>مرکز تبلیغات ToonelVPN</b>\n\n"
        "ساخت کمپین، انتشار همزمان در چند کانال و اندازه‌گیری ورودی یکتا.",
        reply_markup=menu_keyboard(),
    )


@router.callback_query(F.data == "advertising:add_channel", IsAdmin())
async def add_channel_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdvertisingStates.waiting_channel)
    await callback.answer()
    await callback.message.edit_text(
        "📢 <b>افزودن کانال</b>\n\n"
        "آیدی یا یوزرنیم کانال را ارسال کنید.\n"
        "مثال: <code>@ToonelVPN_Official</code>\n\n"
        "ربات باید در کانال عضو و ترجیحاً ادمین باشد."
    )


@router.message(AdvertisingStates.waiting_channel, IsAdmin())
async def add_channel(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("❌ مقدار خالی است. یوزرنیم یا chat_id کانال را ارسال کنید.")
        return
    try:
        chat = await message.bot.get_chat(raw)
    except Exception as exc:
        logger.warning("Cannot resolve advertising channel %s: %s", raw, exc)
        await message.answer("❌ کانال پیدا نشد یا ربات به آن دسترسی ندارد.\nیوزرنیم را با @ ارسال کنید و مطمئن شوید ربات داخل کانال است.")
        return

    existing = await AdvertisingChannel.get_by_chat_id(session, chat.id)
    if existing:
        existing.username = chat.username
        existing.title = chat.title or chat.username or str(chat.id)
        existing.is_active = True
    else:
        session.add(AdvertisingChannel(chat_id=chat.id, username=chat.username, title=chat.title or chat.username or str(chat.id)))
    await session.commit()
    await state.clear()
    await message.answer(f"✅ کانال <b>{chat.title or chat.username or chat.id}</b> اضافه شد و برای انتشار فعال است.", reply_markup=menu_keyboard())


@router.callback_query(F.data == "advertising:channels", IsAdmin())
async def channels(callback: CallbackQuery, session: AsyncSession) -> None:
    result = await session.execute(select(AdvertisingChannel).order_by(AdvertisingChannel.id))
    rows = list(result.scalars().all())
    b = InlineKeyboardBuilder()
    lines = ["📋 <b>کانال‌های تبلیغاتی</b>", ""]
    if not rows:
        lines.append("هنوز کانالی ثبت نشده است.")
    for channel in rows:
        status = "🟢" if channel.is_active else "🔴"
        b.row(InlineKeyboardButton(text=f"{status} {channel.title}", callback_data=f"advertising:toggle:{channel.id}"))
        lines.append(f"{status} {channel.title} — <code>{channel.chat_id}</code>")
    b.row(InlineKeyboardButton(text="➕ افزودن کانال", callback_data="advertising:add_channel"))
    b.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="advertising:menu"))
    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^advertising:toggle:\d+$"), IsAdmin())
async def toggle_channel(callback: CallbackQuery, session: AsyncSession) -> None:
    channel_id = int(callback.data.rsplit(":", 1)[1])
    channel = await session.get(AdvertisingChannel, channel_id)
    if not channel:
        await callback.answer("کانال پیدا نشد.", show_alert=True)
        return
    channel.is_active = not channel.is_active
    await session.commit()
    await callback.answer("وضعیت کانال تغییر کرد.")
    await channels(callback, session)


@router.callback_query(F.data == "advertising:create", IsAdmin())
async def create_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not await AdvertisingChannel.list_active(session):
        await callback.answer("ابتدا حداقل یک کانال تبلیغاتی اضافه کنید.", show_alert=True)
        return
    await state.set_state(AdvertisingStates.waiting_campaign_title)
    await callback.answer()
    await callback.message.edit_text("📝 <b>ساخت کمپین</b>\n\nعنوان کمپین را ارسال کنید. این عنوان فقط برای گزارش مدیریتی استفاده می‌شود.")


@router.message(AdvertisingStates.waiting_campaign_title, IsAdmin())
async def create_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title or len(title) > 255:
        await message.answer("❌ عنوان نامعتبر است (حداکثر ۲۵۵ کاراکتر).")
        return
    await state.update_data(campaign_title=title)
    await state.set_state(AdvertisingStates.waiting_campaign_body)
    await message.answer("✍️ متن تبلیغ را ارسال کنید.\n\nمی‌توانید از HTML پشتیبانی‌شده تلگرام مثل <b>bold</b> استفاده کنید.")


async def _build_ad_markup(campaign_id: int, bot_username: str, session: AsyncSession) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    periods = await ServicePeriod.list_active(session)
    for period in periods:
        plans = await ServicePurchasePlan.list_by_type(session, period.service_type)
        for plan in plans:
            volume = f"{plan.volume_gb:,}".translate(str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬"))
            duration = f"{plan.duration_days:,}".translate(str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬"))
            price = f"{plan.price_toman:,}".translate(str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬"))
            url = f"https://t.me/{bot_username}?start=ad_{campaign_id}_{period.id}_{plan.id}"
            b.row(
                InlineKeyboardButton(text=f"📦 {volume} گیگ / {duration} روز", url=url),
                InlineKeyboardButton(text=f"💰 {price} تومان", url=url),
            )
    b.row(InlineKeyboardButton(text="🎁 مشاهده و خرید سرویس", url=f"https://t.me/{bot_username}?start=ad_{campaign_id}"))
    return b.as_markup()


@router.message(AdvertisingStates.waiting_campaign_body, IsAdmin())
async def create_and_publish(message: Message, state: FSMContext, session: AsyncSession) -> None:
    body = (message.text or message.caption or "").strip()
    if not body:
        await message.answer("❌ متن تبلیغ خالی است.")
        return
    data = await state.get_data()
    me = await message.bot.get_me()
    campaign = AdvertisingCampaign(title=data["campaign_title"], body=body, bot_username=me.username)
    session.add(campaign)
    await session.commit()

    markup = await _build_ad_markup(campaign.id, me.username or "", session)
    channels = await AdvertisingChannel.list_active(session)
    published, failed = [], []
    for channel in channels:
        try:
            sent = await message.bot.send_message(chat_id=channel.chat_id, text=body, reply_markup=markup)
            published.append(channel.title)
            logger.info("Advertising campaign %s published to %s as message %s", campaign.id, channel.chat_id, sent.message_id)
        except Exception as exc:
            failed.append(f"{channel.title}: {exc}")
            logger.exception("Advertising publish failed campaign=%s channel=%s", campaign.id, channel.chat_id)

    await state.clear()
    result = [f"✅ <b>کمپین #{campaign.id} ساخته شد.</b>", "", f"📣 منتشرشده: <b>{len(published)}</b>", f"❌ ناموفق: <b>{len(failed)}</b>"]
    if published:
        result.append("\n🟢 " + "\n🟢 ".join(published))
    if failed:
        result.append("\n🔴 " + "\n🔴 ".join(failed[:5]))
    await message.answer("\n".join(result), reply_markup=menu_keyboard())


@router.callback_query(F.data == "advertising:stats", IsAdmin())
async def stats(callback: CallbackQuery, session: AsyncSession) -> None:
    campaigns = list((await session.execute(select(AdvertisingCampaign).order_by(AdvertisingCampaign.id.desc()).limit(20))).scalars().all())
    lines = ["📊 <b>گزارش کمپین‌های تبلیغاتی</b>", ""]
    for campaign in campaigns:
        starts = await session.scalar(select(func.count()).select_from(AdvertisingEvent).where(AdvertisingEvent.campaign_id == campaign.id, AdvertisingEvent.event_type == "start")) or 0
        lines.append(f"#{campaign.id} — <b>{campaign.title}</b> | ورودی یکتا: <b>{starts}</b>")
    if not campaigns:
        lines.append("هنوز کمپینی ساخته نشده است.")
    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=menu_keyboard())
