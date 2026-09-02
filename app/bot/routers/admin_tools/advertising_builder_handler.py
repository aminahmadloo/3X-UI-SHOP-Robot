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
COLORS = {"green": "🟢", "red": "🔴", "blue": "🔵", "none": ""}
COLOR_NAMES = {"green": "سبز", "red": "قرمز", "blue": "آبی", "none": "بدون رنگ"}


def fmt(value: int) -> str:
    return f"{value:,}".translate(str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬"))


def offer_key(period_id: int, plan_id: int) -> str:
    return f"{period_id}:{plan_id}"


def valid_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https", "tg"} and bool(parsed.netloc or parsed.scheme == "tg")
    except ValueError:
        return False


def menu_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➕ افزودن کانال", callback_data="advertising:add_channel"))
    b.row(InlineKeyboardButton(text="📣 ساخت تبلیغ", callback_data="advertising:create"))
    b.row(InlineKeyboardButton(text="📊 گزارش تبلیغات", callback_data="advertising:stats"))
    b.row(InlineKeyboardButton(text="📋 مدیریت کانال‌ها", callback_data="advertising:channels"))
    b.row(InlineKeyboardButton(text="🏠 منوی مدیریت", callback_data=NavAdminTools.MAIN))
    return b.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ لغو", callback_data="advertising:cancel")]])


async def get_offers(session: AsyncSession) -> list[tuple[ServicePeriod, ServicePurchasePlan]]:
    result = []
    for period in await ServicePeriod.list_active(session):
        for plan in await ServicePurchasePlan.list_by_type(session, period.service_type):
            result.append((period, plan))
    return result


async def build_ad_markup(
    campaign_id: int,
    bot_username: str,
    channel_id: int,
    session: AsyncSession,
    buttons: list[dict],
    selected_offers: list[str],
    show_services: bool,
) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()

    # Custom buttons: maximum 2 buttons per row.
    custom_row = []
    for item in buttons:
        url = str(item.get("url", ""))
        if not url:
            continue

        color = COLORS.get(str(item.get("color", "none")), "")
        label = str(item.get("label", "دکمه"))[:60]
        text = f"{color} {label}" if color else label

        custom_row.append(InlineKeyboardButton(text=text, url=url))

        if len(custom_row) == 2:
            b.row(*custom_row)
            custom_row = []

    if custom_row:
        b.row(*custom_row)

    if show_services:
        selected = set(selected_offers)
        for period, plan in await get_offers(session):
            key = offer_key(period.id, plan.id)
            if selected and key not in selected:
                continue
            url = f"https://t.me/{bot_username}?start=ad_{campaign_id}_{period.id}_{plan.id}_{channel_id}"
            b.row(
                InlineKeyboardButton(text=f"📦 {fmt(plan.volume_gb)} گیگ / {fmt(plan.duration_days)} روز", url=url),
                InlineKeyboardButton(text=f"💰 {fmt(plan.price_toman)} تومان", url=url),
            )
    return b.as_markup()


@router.callback_query(F.data == "advertising:menu", IsAdmin())
async def menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "📣 <b>مرکز تبلیغات ToonelVPN</b>\n\n"
        "سازنده تبلیغ حرفه‌ای: متن دلخواه، تعداد دلخواه دکمه سفارشی، رنگ نمایشی، انتخاب دقیق سرویس/دوره، پیش‌نمایش و انتشار چندکاناله.\n\n"
        "⚠️ Telegram Bot API رنگ واقعی پس‌زمینه Inline Button را قابل تنظیم نمی‌کند؛ انتخاب رنگ به‌صورت نشانگر رنگی در عنوان ذخیره و نمایش داده می‌شود.",
        reply_markup=menu_keyboard(),
    )


@router.callback_query(F.data == "advertising:add_channel", IsAdmin())
async def add_channel_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdvertisingStates.waiting_channel)
    await callback.answer()
    await callback.message.edit_text("📢 یوزرنیم یا chat_id کانال را ارسال کنید.\nمثال: <code>@ToonelVPN_Official</code>", reply_markup=cancel_keyboard())


@router.message(AdvertisingStates.waiting_channel, IsAdmin())
async def add_channel(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip()
    try:
        chat = await message.bot.get_chat(raw)
    except Exception:
        await message.answer("❌ کانال پیدا نشد یا ربات دسترسی ندارد.")
        return
    channel = await AdvertisingChannel.get_by_chat_id(session, chat.id)
    if channel:
        channel.username = chat.username
        channel.title = chat.title or chat.username or str(chat.id)
        channel.is_active = True
    else:
        session.add(AdvertisingChannel(chat_id=chat.id, username=chat.username, title=chat.title or chat.username or str(chat.id)))
    await session.commit()
    await state.clear()
    await message.answer(f"✅ کانال <b>{chat.title or chat.username or chat.id}</b> فعال شد.", reply_markup=menu_keyboard())


@router.callback_query(F.data == "advertising:channels", IsAdmin())
async def channels(callback: CallbackQuery, session: AsyncSession) -> None:
    rows = list((await session.execute(select(AdvertisingChannel).order_by(AdvertisingChannel.id))).scalars().all())
    b = InlineKeyboardBuilder()
    lines = ["📋 <b>کانال‌های تبلیغاتی</b>", ""]
    for channel in rows:
        status = "🟢" if channel.is_active else "🔴"
        lines.append(f"{status} {channel.title} — <code>{channel.chat_id}</code>")
        b.row(InlineKeyboardButton(text=f"{status} {channel.title}", callback_data=f"advertising:toggle:{channel.id}"))
    if not rows:
        lines.append("هنوز کانالی ثبت نشده است.")
    b.row(InlineKeyboardButton(text="➕ افزودن کانال", callback_data="advertising:add_channel"))
    b.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="advertising:menu"))
    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^advertising:toggle:\d+$"), IsAdmin())
async def toggle_channel(callback: CallbackQuery, session: AsyncSession) -> None:
    channel = await session.get(AdvertisingChannel, int(callback.data.rsplit(":", 1)[1]))
    if not channel:
        await callback.answer("کانال پیدا نشد.", show_alert=True)
        return
    channel.is_active = not channel.is_active
    await session.commit()
    await callback.answer("وضعیت تغییر کرد")
    await channels(callback, session)


@router.callback_query(F.data == "advertising:create", IsAdmin())
async def create_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    if not await AdvertisingChannel.list_active(session):
        await callback.answer("ابتدا حداقل یک کانال فعال اضافه کنید.", show_alert=True)
        return
    await state.clear()
    await state.set_state(AdvertisingStates.waiting_campaign_title)
    await state.update_data(custom_buttons=[], selected_offers=[], show_services=True)
    await callback.answer()
    await callback.message.edit_text("🧩 <b>سازنده تبلیغ</b>\n\nمرحله ۱/۵ — عنوان داخلی کمپین را ارسال کنید.", reply_markup=cancel_keyboard())


@router.message(AdvertisingStates.waiting_campaign_title, IsAdmin())
async def title(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not value or len(value) > 255:
        await message.answer("❌ عنوان نامعتبر است.")
        return
    await state.update_data(campaign_title=value)
    await state.set_state(AdvertisingStates.waiting_campaign_body)
    await message.answer("✍️ <b>مرحله ۲/۵</b> — متن کامل تبلیغ را ارسال کنید.", reply_markup=cancel_keyboard())


@router.message(AdvertisingStates.waiting_campaign_body, IsAdmin())
async def body(message: Message, state: FSMContext) -> None:
    value = (message.text or message.caption or "").strip()
    if not value:
        await message.answer("❌ متن تبلیغ خالی است.")
        return
    await state.update_data(campaign_body=value, custom_buttons=[])
    await state.set_state(AdvertisingStates.waiting_button_title)
    await message.answer(
        "🔘 <b>مرحله ۳/۵ — دکمه سفارشی</b>\n\n"
        "عنوان دکمه را بفرست. می‌توانی هر تعداد دکمه که لازم داری بسازی.\n"
        "مثال: <code>🔥 خرید ویژه امروز</code>\nبرای پایان ساخت دکمه‌ها: <code>رد کردن</code>",
        reply_markup=cancel_keyboard(),
    )


@router.message(AdvertisingStates.waiting_button_title, IsAdmin())
async def button_title(message: Message, state: FSMContext, session: AsyncSession) -> None:
    value = (message.text or "").strip()

    if value in {"رد کردن", "رد", "skip", "Skip"}:
        await state.set_state(AdvertisingStates.waiting_service_selection)
        await show_services(message, state, session)
        return

    if not value or len(value) > 64:
        await message.answer("❌ عنوان دکمه باید حداکثر ۶۴ کاراکتر باشد.")
        return
    await state.update_data(pending_button_title=value)
    await state.set_state(AdvertisingStates.waiting_button_url)
    await message.answer("🔗 لینک مقصد دکمه را ارسال کنید (http/https یا tg://).", reply_markup=cancel_keyboard())


@router.message(AdvertisingStates.waiting_button_url, IsAdmin())
async def button_url(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not valid_url(value):
        await message.answer("❌ لینک نامعتبر است.")
        return
    await state.update_data(pending_button_url=value)
    b = InlineKeyboardBuilder()
    for color in ("green", "red", "blue", "none"):
        label = COLOR_NAMES[color]
        icon = COLORS[color]
        text = f"{icon} {label}" if icon else label
        b.row(InlineKeyboardButton(text=text, callback_data=f"advertising:button_color:{color}"))
    b.row(InlineKeyboardButton(text="❌ لغو", callback_data="advertising:cancel"))
    await message.answer("🎨 رنگ نمایشی این دکمه را انتخاب کنید.\n(رنگ واقعی پس‌زمینه توسط Telegram قابل تنظیم نیست.)", reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^advertising:button_color:(green|red|blue|none)$"), IsAdmin())
async def button_color(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    buttons = list(data.get("custom_buttons", []))
    buttons.append({"label": data.get("pending_button_title", "دکمه"), "url": data.get("pending_button_url", ""), "color": callback.data.rsplit(":", 1)[1]})
    await state.update_data(custom_buttons=buttons, pending_button_title=None, pending_button_url=None)
    await callback.answer(f"دکمه {len(buttons)} ذخیره شد")
    await state.set_state(AdvertisingStates.waiting_button_title)
    await callback.message.edit_text(
        f"✅ دکمه {len(buttons)} ذخیره شد.\n\n"
        "دکمه بعدی را بساز یا «رد کردن» را بفرست.",
        reply_markup=cancel_keyboard(),
    )


async def show_services(message: Message, state: FSMContext, session: AsyncSession) -> None:
    offers = await get_offers(session)
    if not offers:
        await state.update_data(show_services=False, selected_offers=[])
        await message.answer("⚠️ سرویس فعالی وجود ندارد؛ تبلیغ بدون سرویس ساخته می‌شود.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👁 پیش‌نمایش", callback_data="advertising:preview")]]))
        return
    selected = set((await state.get_data()).get("selected_offers", []))
    b = InlineKeyboardBuilder()
    for period, plan in offers:
        key = offer_key(period.id, plan.id)
        mark = "☑️" if key in selected else "⬜"
        text = f"{mark} {period.name} | {fmt(plan.volume_gb)}GB | {fmt(plan.duration_days)}روز | {fmt(plan.price_toman)}"
        b.row(InlineKeyboardButton(text=text[:64], callback_data=f"advertising:offer:{period.id}:{plan.id}"))
    b.row(InlineKeyboardButton(text="🚫 بدون سرویس", callback_data="advertising:services_off"))
    b.row(InlineKeyboardButton(text="👁 پیش‌نمایش", callback_data="advertising:preview"))
    b.row(InlineKeyboardButton(text="❌ لغو", callback_data="advertising:cancel"))
    await message.answer("🛒 <b>مرحله ۴/۵ — سرویس‌های تبلیغ</b>\n\nموارد انتخاب‌شده فقط در تبلیغ نمایش داده می‌شوند.\nاگر هیچ موردی انتخاب نکنی، همه سرویس‌های فعال نمایش داده می‌شوند.", reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^advertising:offer:\d+:\d+$"), IsAdmin())
async def offer_toggle(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    _, _, period_id, plan_id = callback.data.split(":")
    key = offer_key(int(period_id), int(plan_id))
    data = await state.get_data()
    selected = set(data.get("selected_offers", []))
    selected.remove(key) if key in selected else selected.add(key)
    await state.update_data(selected_offers=sorted(selected), show_services=True)
    await callback.answer("انتخاب به‌روزرسانی شد")
    await show_services(callback.message, state, session)


@router.callback_query(F.data == "advertising:services_off", IsAdmin())
async def services_off(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(show_services=False, selected_offers=[])
    await callback.answer("سرویس‌ها حذف شدند")
    await callback.message.edit_text("🚫 سرویس‌ها نمایش داده نمی‌شوند.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👁 پیش‌نمایش", callback_data="advertising:preview")],
        [InlineKeyboardButton(text="❌ لغو", callback_data="advertising:cancel")],
    ]))


async def save_draft(session: AsyncSession, data: dict, username: str) -> AdvertisingCampaign:
    campaign = AdvertisingCampaign(title=data["campaign_title"], body=data["campaign_body"], bot_username=username, show_services=bool(data.get("show_services", True)))
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
    campaign = await save_draft(session, data, me.username)
    await session.commit()
    await state.update_data(draft_campaign_id=campaign.id)
    markup = await build_ad_markup(campaign.id, me.username, channels[0].id, session, campaign.custom_buttons, campaign.selected_offers, campaign.show_services)
    await callback.answer()
    await callback.message.edit_text("👁 <b>پیش‌نمایش متن تبلیغ</b>\n\n" + campaign.body)
    await callback.message.answer("🔘 <b>پیش‌نمایش دکمه‌ها</b>", reply_markup=markup)
    await callback.message.answer("اگر مورد تأیید است منتشر کن:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 انتشار در کانال‌های فعال", callback_data=f"advertising:publish:{campaign.id}")],
        [InlineKeyboardButton(text="❌ لغو", callback_data=f"advertising:discard:{campaign.id}")],
    ]))


@router.callback_query(F.data.regexp(r"^advertising:publish:\d+$"), IsAdmin())
async def publish(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    campaign = await session.get(AdvertisingCampaign, int(callback.data.rsplit(":", 1)[1]))
    if not campaign or not campaign.is_active:
        await callback.answer("کمپین پیدا نشد یا غیرفعال است.", show_alert=True)
        return
    channels = await AdvertisingChannel.list_active(session)
    ok, failed = [], []
    for channel in channels:
        try:
            markup = await build_ad_markup(campaign.id, campaign.bot_username or "", channel.id, session, campaign.custom_buttons, campaign.selected_offers, campaign.show_services)
            await callback.message.bot.send_message(chat_id=channel.chat_id, text=campaign.body, reply_markup=markup)
            ok.append(channel.title)
        except Exception as exc:
            failed.append(f"{channel.title}: {exc}")
            logger.exception("Advertising publish failed: campaign=%s channel=%s", campaign.id, channel.chat_id)
    await state.clear()
    await callback.answer("انتشار انجام شد")
    text = [f"✅ <b>کمپین #{campaign.id} منتشر شد.</b>", f"🟢 موفق: {len(ok)}", f"🔴 ناموفق: {len(failed)}"]
    if ok:
        text.append("\n" + "\n".join(f"🟢 {name}" for name in ok))
    if failed:
        text.append("\n" + "\n".join(f"🔴 {item}" for item in failed[:5]))
    await callback.message.edit_text("\n".join(text), reply_markup=menu_keyboard())


@router.callback_query(F.data.regexp(r"^advertising:discard:\d+$"), IsAdmin())
async def discard(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    campaign = await session.get(AdvertisingCampaign, int(callback.data.rsplit(":", 1)[1]))
    if campaign:
        campaign.is_active = False
        await session.commit()
    await state.clear()
    await callback.answer("لغو شد")
    await callback.message.edit_text("❌ تبلیغ منتشر نشد.", reply_markup=menu_keyboard())


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
        buyers = await session.scalar(select(func.count(func.distinct(AdvertisingEvent.tg_id))).select_from(AdvertisingEvent).join(Transaction, Transaction.tg_id == AdvertisingEvent.tg_id).where(AdvertisingEvent.campaign_id == campaign.id, AdvertisingEvent.event_type == "start", Transaction.status == TransactionStatus.COMPLETED)) or 0
        lines.append(f"#{campaign.id} — <b>{campaign.title}</b> | ورودی: <b>{leads}</b> | خریدار: <b>{buyers}</b>")
    if not campaigns:
        lines.append("هنوز کمپینی ساخته نشده است.")
    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=menu_keyboard())
