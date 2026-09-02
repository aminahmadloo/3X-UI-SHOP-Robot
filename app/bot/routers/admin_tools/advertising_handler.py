import logging
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.states.advertising import AdvertisingStates
from app.bot.utils.constants import TransactionStatus
from app.bot.utils.navigation import NavAdminTools
from app.db.models import AdvertisingCampaign, AdvertisingChannel, AdvertisingEvent, ServicePeriod, ServicePurchasePlan, Transaction

logger = logging.getLogger(__name__)
router = Router(name=__name__)

COLOR_EMOJI = {"green": "🟢", "red": "🔴", "blue": "🔵"}
COLOR_NAMES = {"green": "سبز", "red": "قرمز", "blue": "آبی"}


def menu_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➕ افزودن کانال", callback_data="advertising:add_channel"))
    b.row(InlineKeyboardButton(text="📣 ساخت تبلیغ", callback_data="advertising:create"))
    b.row(InlineKeyboardButton(text="📊 گزارش تبلیغات", callback_data="advertising:stats"))
    b.row(InlineKeyboardButton(text="📋 مدیریت کانال‌ها", callback_data="advertising:channels"))
    b.row(InlineKeyboardButton(text="🏠 منوی مدیریت", callback_data=NavAdminTools.MAIN))
    return b.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ لغو", callback_data="advertising:cancel")],
    ])


def is_valid_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https", "tg"} and bool(parsed.netloc or parsed.scheme == "tg")
    except ValueError:
        return False


def _fmt(number: int) -> str:
    return f"{number:,}".translate(str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬"))


def _offer_key(period_id: int, plan_id: int) -> str:
    return f"{period_id}:{plan_id}"


async def _offers(session: AsyncSession) -> list[tuple[ServicePeriod, ServicePurchasePlan]]:
    result: list[tuple[ServicePeriod, ServicePurchasePlan]] = []
    for period in await ServicePeriod.list_active(session):
        for plan in await ServicePurchasePlan.list_by_type(session, period.service_type):
            result.append((period, plan))
    return result


async def _build_markup(
    campaign_id: int,
    bot_username: str,
    channel_id: int,
    session: AsyncSession,
    *,
    custom_buttons: list[dict] | None = None,
    selected_offers: list[str] | None = None,
    show_services: bool = True,
) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()

    for button in custom_buttons or []:
        label = str(button.get("label") or "دکمه")[:64]
        color = str(button.get("color") or "blue")
        prefix = COLOR_EMOJI.get(color, "🔵")
        url = str(button.get("url") or "")
        if url:
            b.row(InlineKeyboardButton(text=f"{prefix} {label}", url=url))

    if show_services:
        allowed = set(selected_offers or [])
        offers = await _offers(session)
        for period, plan in offers:
            key = _offer_key(period.id, plan.id)
            if allowed and key not in allowed:
                continue
            volume = _fmt(plan.volume_gb)
            duration = _fmt(plan.duration_days)
            price = _fmt(plan.price_toman)
            url = f"https://t.me/{bot_username}?start=ad_{campaign_id}_{period.id}_{plan.id}_{channel_id}"
            b.row(
                InlineKeyboardButton(text=f"📦 {volume} گیگ / {duration} روز", url=url),
                InlineKeyboardButton(text=f"💰 {price} تومان", url=url),
            )

    return b.as_markup()


@router.callback_query(F.data == "advertising:menu", IsAdmin())
async def menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "📣 <b>مرکز تبلیغات ToonelVPN</b>\n\n"
        "سازنده تبلیغ: متن دلخواه، تا ۳ دکمه سفارشی، انتخاب رنگ نمایشی، انتخاب دقیق سرویس‌ها/دوره‌ها، پیش‌نمایش و انتشار چندکاناله.\n\n"
        "⚠️ تلگرام رنگ واقعی پس‌زمینه Inline Button را در Bot API قابل تنظیم نمی‌کند؛ رنگ انتخابی به‌صورت نشانگر رنگی در عنوان دکمه اعمال می‌شود.",
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
        "ربات باید داخل کانال دسترسی لازم برای ارسال پیام داشته باشد.",
        reply_markup=cancel_keyboard(),
    )


@router.message(AdvertisingStates.waiting_channel, IsAdmin())
async def add_channel(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("❌ مقدار خالی است.")
        return
    try:
        chat = await message.bot.get_chat(raw)
    except Exception as exc:
        logger.warning("Cannot resolve advertising channel %s: %s", raw, exc)
        await message.answer("❌ کانال پیدا نشد یا ربات به آن دسترسی ندارد.")
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
    await message.answer(f"✅ کانال <b>{chat.title or chat.username or chat.id}</b> فعال شد.", reply_markup=menu_keyboard())


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
    await state.update_data(custom_buttons=[], selected_offers=[], show_services=True)
    await callback.answer()
    await callback.message.edit_text(
        "🧩 <b>سازنده تبلیغ</b>\n\n"
        "مرحله ۱ از ۵ — عنوان داخلی کمپین را ارسال کنید.\nاین عنوان فقط برای مدیریت و گزارش است.",
        reply_markup=cancel_keyboard(),
    )


@router.message(AdvertisingStates.waiting_campaign_title, IsAdmin())
async def create_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title or len(title) > 255:
        await message.answer("❌ عنوان نامعتبر است (حداکثر ۲۵۵ کاراکتر).")
        return
    await state.update_data(campaign_title=title)
    await state.set_state(AdvertisingStates.waiting_campaign_body)
    await message.answer(
        "✍️ <b>مرحله ۲ از ۵</b>\n\nمتن اصلی تبلیغ را ارسال کنید.\nایموجی، فاصله و خطوط دلخواه شما حفظ می‌شود.",
        reply_markup=cancel_keyboard(),
    )


@router.message(AdvertisingStates.waiting_campaign_body, IsAdmin())
async def create_body(message: Message, state: FSMContext) -> None:
    body = (message.text or message.caption or "").strip()
    if not body:
        await message.answer("❌ متن تبلیغ خالی است.")
        return
    await state.update_data(campaign_body=body, custom_buttons=[])
    await state.set_state(AdvertisingStates.waiting_button_title)
    await message.answer(
        "🔘 <b>مرحله ۳ از ۵ — دکمه‌های سفارشی</b>\n\n"
        "می‌توانی ۱ تا ۳ دکمه تبلیغاتی با عنوان کاملاً دلخواه بسازی.\n"
        "برای رد کردن این بخش، «رد کردن» را بفرست.\n\n"
        "مثال عنوان: <code>🔥 خرید ویژه امروز</code>",
        reply_markup=cancel_keyboard(),
    )


@router.message(AdvertisingStates.waiting_button_title, IsAdmin())
async def button_title(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text in {"رد کردن", "رد", "skip", "Skip"}:
        await state.set_state(AdvertisingStates.waiting_service_selection)
        await message.answer("🛒 مرحله ۴ از ۵ — انتخاب سرویس‌ها در حال آماده‌سازی...", reply_markup=cancel_keyboard())
        return
    data = await state.get_data()
    buttons = data.get("custom_buttons", [])
    if len(buttons) >= 3:
        await state.set_state(AdvertisingStates.waiting_service_selection)
        await message.answer("حداکثر ۳ دکمه ثبت شد. حالا سرویس‌ها را انتخاب می‌کنیم.", reply_markup=cancel_keyboard())
        return
    if not text or len(text) > 64:
        await message.answer("❌ عنوان دکمه باید بین ۱ تا ۶۴ کاراکتر باشد.")
        return
    await state.update_data(pending_button_title=text)
    await state.set_state(AdvertisingStates.waiting_button_url)
    await message.answer("🔗 لینک مقصد این دکمه را ارسال کن.\nمثال: <code>https://t.me/ToonelVPNBot</code>", reply_markup=cancel_keyboard())


@router.message(AdvertisingStates.waiting_button_url, IsAdmin())
async def button_url(message: Message, state: FSMContext) -> None:
    url = (message.text or "").strip()
    if not is_valid_url(url):
        await message.answer("❌ لینک نامعتبر است. فقط http/https یا tg:// مجاز است.")
        return
    await state.update_data(pending_button_url=url)
    b = InlineKeyboardBuilder()
    for color in ("green", "red", "blue"):
        b.row(InlineKeyboardButton(text=f"{COLOR_EMOJI[color]} {COLOR_NAMES[color]}", callback_data=f"advertising:button_color:{color}"))
    b.row(InlineKeyboardButton(text="❌ لغو", callback_data="advertising:cancel"))
    await state.set_state(AdvertisingStates.waiting_button_url)
    await message.answer("🎨 رنگ نمایشی دکمه را انتخاب کن.\n(رنگ واقعی پس‌زمینه دکمه توسط Telegram Bot API قابل تغییر نیست.)", reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^advertising:button_color:(green|red|blue)$"), IsAdmin())
async def button_color(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    color = callback.data.rsplit(":", 1)[1]
    data = await state.get_data()
    buttons = list(data.get("custom_buttons", []))
    buttons.append({"label": data.get("pending_button_title", "دکمه"), "url": data.get("pending_button_url", ""), "color": color})
    await state.update_data(custom_buttons=buttons, pending_button_title=None, pending_button_url=None)
    await callback.answer(f"دکمه {len(buttons)} ذخیره شد.")
    if len(buttons) < 3:
        await state.set_state(AdvertisingStates.waiting_button_title)
        await callback.message.edit_text(
            f"✅ دکمه {len(buttons)} ذخیره شد.\n\nیک دکمه دیگر بساز یا «رد کردن» را بفرست.",
            reply_markup=cancel_keyboard(),
        )
    else:
        await state.set_state(AdvertisingStates.waiting_service_selection)
        await _show_service_selection(callback.message, state, session)


async def _show_service_selection(message: Message, state: FSMContext, session: AsyncSession) -> None:
    offers = await _offers(session)
    if not offers:
        await state.update_data(show_services=False, selected_offers=[])
        await message.answer("⚠️ هیچ سرویس فعالی برای نمایش پیدا نشد؛ تبلیغ بدون جدول سرویس ادامه پیدا می‌کند.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👁 پیش‌نمایش", callback_data="advertising:preview")]]))
        return
    data = await state.get_data()
    selected = set(data.get("selected_offers", []))
    b = InlineKeyboardBuilder()
    for period, plan in offers:
        key = _offer_key(period.id, plan.id)
        mark = "☑️" if key in selected else "⬜"
        label = f"{mark} {period.name} | {_fmt(plan.volume_gb)}GB | {_fmt(plan.duration_days)}روز | {_fmt(plan.price_toman)} تومان"
        b.row(InlineKeyboardButton(text=label[:64], callback_data=f"advertising:offer:{period.id}:{plan.id}"))
    b.row(InlineKeyboardButton(text="🚫 عدم نمایش سرویس‌ها", callback_data="advertising:services_off"))
    b.row(InlineKeyboardButton(text="👁 پیش‌نمایش", callback_data="advertising:preview"))
    b.row(InlineKeyboardButton(text="❌ لغو", callback_data="advertising:cancel"))
    await message.answer(
        "🛒 <b>مرحله ۴ از ۵ — انتخاب سرویس‌ها</b>\n\n"
        "هر موردی که انتخاب شود در تبلیغ نمایش داده می‌شود.\n"
        "اگر هیچ موردی انتخاب نشود، همه سرویس‌های فعال نمایش داده خواهند شد.",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data.regexp(r"^advertising:offer:\d+:\d+$"), IsAdmin())
async def toggle_offer(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    _, _, period_id, plan_id = callback.data.split(":")
    key = _offer_key(int(period_id), int(plan_id))
    data = await state.get_data()
    selected = set(data.get("selected_offers", []))
    if key in selected:
        selected.remove(key)
    else:
        selected.add(key)
    await state.update_data(selected_offers=sorted(selected), show_services=True)
    await callback.answer("انتخاب به‌روزرسانی شد")
    await _show_service_selection(callback.message, state, session)


@router.callback_query(F.data == "advertising:services_off", IsAdmin())
async def services_off(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(show_services=False, selected_offers=[])
    await callback.answer("سرویس‌ها از تبلیغ حذف شدند")
    await callback.message.edit_text(
        "🚫 نمایش سرویس‌ها خاموش شد.\n\nحالا پیش‌نمایش را ببین.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👁 پیش‌نمایش", callback_data="advertising:preview")],
            [InlineKeyboardButton(text="❌ لغو", callback_data="advertising:cancel")],
        ]),
    )


async def _create_draft(session: AsyncSession, data: dict, bot_username: str) -> AdvertisingCampaign:
    campaign = AdvertisingCampaign(
        title=data["campaign_title"],
        body=data["campaign_body"],
        bot_username=bot_username,
        show_services=bool(data.get("show_services", True)),
    )
    campaign.custom_buttons = list(data.get("custom_buttons", []))
    campaign.selected_offers = list(data.get("selected_offers", []))
    session.add(campaign)
    await session.flush()
    return campaign


@router.callback_query(F.data == "advertising:preview", IsAdmin())
async def preview(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    if not data.get("campaign_body"):
        await callback.answer("اطلاعات تبلیغ ناقص است.", show_alert=True)
        return
    me = await callback.message.bot.get_me()
    channels = await AdvertisingChannel.list_active(session)
    if not me.username or not channels:
        await callback.answer("ربات username یا کانال فعال ندارد.", show_alert=True)
        return

    # Draft is persisted so the preview uses the exact same campaign/deep-link id as publication.
    campaign = await _create_draft(session, data, me.username)
    await session.commit()
    await state.update_data(draft_campaign_id=campaign.id)
    markup = await _build_markup(
        campaign.id,
        me.username,
        channels[0].id,
        session,
        custom_buttons=campaign.custom_buttons,
        selected_offers=campaign.selected_offers,
        show_services=campaign.show_services,
    )
    await callback.answer()
    await callback.message.edit_text(
        "👁 <b>پیش‌نمایش تبلیغ</b>\n\n" + campaign.body + "\n\n"
        "━━━━━━━━━━━━━━\n"
        "اگر تأیید است، انتشار را بزن. در غیر این صورت لغو کن و تنظیمات را دوباره بساز.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 انتشار در کانال‌های فعال", callback_data=f"advertising:publish:{campaign.id}")],
            [InlineKeyboardButton(text="❌ لغو", callback_data=f"advertising:discard:{campaign.id}")],
        ]),
    )


@router.callback_query(F.data.regexp(r"^advertising:publish:\d+$"), IsAdmin())
async def publish(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    campaign_id = int(callback.data.rsplit(":", 1)[1])
    campaign = await session.get(AdvertisingCampaign, campaign_id)
    if not campaign:
        await callback.answer("کمپین پیدا نشد.", show_alert=True)
        return
    channels = await AdvertisingChannel.list_active(session)
    if not channels:
        await callback.answer("هیچ کانال فعالی وجود ندارد.", show_alert=True)
        return

    published, failed = [], []
    for channel in channels:
        try:
            markup = await _build_markup(
                campaign.id,
                campaign.bot_username or "",
                channel.id,
                session,
                custom_buttons=campaign.custom_buttons,
                selected_offers=campaign.selected_offers,
                show_services=campaign.show_services,
            )
            sent = await callback.message.bot.send_message(chat_id=channel.chat_id, text=campaign.body, reply_markup=markup)
            published.append(channel.title)
            logger.info("Advertising campaign %s published to %s as message %s", campaign.id, channel.chat_id, sent.message_id)
        except Exception as exc:
            failed.append(f"{channel.title}: {exc}")
            logger.exception("Advertising publish failed campaign=%s channel=%s", campaign.id, channel.chat_id)

    await state.clear()
    await callback.answer("انتشار انجام شد")
    result = [f"✅ <b>کمپین #{campaign.id} منتشر شد.</b>", "", f"📣 موفق: <b>{len(published)}</b>", f"❌ ناموفق: <b>{len(failed)}</b>"]
    if published:
        result.append("\n🟢 " + "\n🟢 ".join(published))
    if failed:
        result.append("\n🔴 " + "\n🔴 ".join(failed[:5]))
    await callback.message.edit_text("\n".join(result), reply_markup=menu_keyboard())


@router.callback_query(F.data.regexp(r"^advertising:discard:\d+$"), IsAdmin())
async def discard(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    campaign_id = int(callback.data.rsplit(":", 1)[1])
    campaign = await session.get(AdvertisingCampaign, campaign_id)
    if campaign:
        campaign.is_active = False
        await session.commit()
    await state.clear()
    await callback.answer("پیش‌نمایش لغو شد")
    await callback.message.edit_text("❌ تبلیغ لغو شد و منتشر نشد.", reply_markup=menu_keyboard())


@router.callback_query(F.data == "advertising:cancel", IsAdmin())
async def cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("لغو شد")
    await callback.message.edit_text("❌ ساخت تبلیغ لغو شد.", reply_markup=menu_keyboard())


@router.callback_query(F.data == "advertising:stats", IsAdmin())
async def stats(callback: CallbackQuery, session: AsyncSession) -> None:
    campaigns = list((await session.execute(select(AdvertisingCampaign).order_by(AdvertisingCampaign.id.desc()).limit(20))).scalars().all())
    lines = ["📊 <b>گزارش کمپین‌های تبلیغاتی</b>", ""]
    for campaign in campaigns:
        leads = await session.scalar(select(func.count()).select_from(AdvertisingEvent).where(AdvertisingEvent.campaign_id == campaign.id, AdvertisingEvent.event_type == "start")) or 0
        buyers = await session.scalar(
            select(func.count(func.distinct(AdvertisingEvent.tg_id)))
            .select_from(AdvertisingEvent)
            .join(Transaction, Transaction.tg_id == AdvertisingEvent.tg_id)
            .where(AdvertisingEvent.campaign_id == campaign.id, AdvertisingEvent.event_type == "start", Transaction.status == TransactionStatus.COMPLETED)
        ) or 0
        lines.append(f"#{campaign.id} — <b>{campaign.title}</b> | ورودی یکتا: <b>{leads}</b> | مشتری خریدار: <b>{buyers}</b>")
    if not campaigns:
        lines.append("هنوز کمپینی ساخته نشده است.")
    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=menu_keyboard())
