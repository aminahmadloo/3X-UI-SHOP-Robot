from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.states.advertising import AdvertisingStates
from app.bot.utils.navigation import NavAdminTools
from app.bot.routers.admin_tools.advertising_builder_handler import normalize_url, valid_url
from app.bot.routers.admin_tools.advertising_management_handler import _campaign_menu, _get_campaign, _sync_publications

router = Router(name=__name__)


def _menu_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➕ افزودن کانال", callback_data="advertising:add_channel"))
    b.row(InlineKeyboardButton(text="📣 ساخت تبلیغ", callback_data="advertising:create"))
    b.row(InlineKeyboardButton(text="📢 مدیریت کمپین‌ها", callback_data="advertising:manage"))
    b.row(InlineKeyboardButton(text="📊 گزارش تبلیغات", callback_data="advertising:stats"))
    b.row(InlineKeyboardButton(text="📋 مدیریت کانال‌ها", callback_data="advertising:channels"))
    b.row(InlineKeyboardButton(text="🏠 منوی مدیریت", callback_data=NavAdminTools.MAIN))
    return b.as_markup()


@router.callback_query(F.data == "advertising:menu", IsAdmin())
async def enhanced_advertising_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "📣 <b>مرکز تبلیغات ToonelVPN</b>\n\n"
        "ساخت و مدیریت کمپین‌ها با متن، عکس، ویدئو، دکمه‌های رنگی، سرویس‌های انتخابی و انتشار چندکاناله.",
        reply_markup=_menu_keyboard(),
    )


@router.callback_query(F.data.regexp(r"^advertising:button_add:\d+$"), IsAdmin())
async def add_button_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    campaign_id = int(callback.data.rsplit(":", 1)[1])
    campaign = await _get_campaign(session, campaign_id)
    if not campaign:
        await callback.answer("کمپین پیدا نشد.", show_alert=True)
        return
    if len(campaign.custom_buttons) >= 3:
        await callback.answer("حداکثر ۳ دکمه مجاز است.", show_alert=True)
        return
    await state.update_data(edit_campaign_id=campaign_id)
    await state.set_state(AdvertisingStates.waiting_add_button_title)
    await callback.answer()
    await callback.message.edit_text(
        "➕ <b>افزودن دکمه</b>\n\nعنوان دکمه را ارسال کن.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ لغو", callback_data="advertising:manage:cancel")]]
        ),
    )


@router.message(AdvertisingStates.waiting_add_button_title, IsAdmin())
async def add_button_title(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not value or len(value) > 64:
        await message.answer("❌ عنوان دکمه باید بین ۱ تا ۶۴ کاراکتر باشد.")
        return
    await state.update_data(pending_add_button_title=value)
    await state.set_state(AdvertisingStates.waiting_add_button_url)
    await message.answer(
        "🔗 لینک / اکشن دکمه را ارسال کن.\n\n"
        "مثال: <code>https://example.com</code> یا <code>https://t.me/ToonelVPN</code> یا <code>@ToonelVPN</code>.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ لغو", callback_data="advertising:manage:cancel")]]
        ),
    )


@router.message(AdvertisingStates.waiting_add_button_url, IsAdmin())
async def add_button_url(message: Message, state: FSMContext) -> None:
    value = normalize_url((message.text or "").strip())
    if not valid_url(value):
        await message.answer("❌ لینک معتبر نیست.")
        return
    await state.update_data(pending_add_button_url=value)
    await state.set_state(AdvertisingStates.waiting_add_button_color)
    b = InlineKeyboardBuilder()
    for color, label in (("green", "🟢 سبز"), ("red", "🔴 قرمز"), ("blue", "🔵 آبی"), ("none", "⚪ بدون رنگ")):
        b.row(InlineKeyboardButton(text=label, callback_data=f"advertising:add_button_color:{color}"))
    b.row(InlineKeyboardButton(text="❌ لغو", callback_data="advertising:manage:cancel"))
    await message.answer("🎨 رنگ دکمه را انتخاب کن.", reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^advertising:add_button_color:(green|red|blue|none)$"), IsAdmin())
async def add_button_color(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    color = callback.data.rsplit(":", 1)[1]
    data = await state.get_data()
    campaign = await _get_campaign(session, int(data["edit_campaign_id"]))
    if not campaign:
        await state.clear()
        await callback.answer("کمپین پیدا نشد.", show_alert=True)
        return
    buttons = campaign.custom_buttons
    if len(buttons) >= 3:
        await callback.answer("حداکثر ۳ دکمه مجاز است.", show_alert=True)
        await state.clear()
        return
    buttons.append(
        {
            "label": data.get("pending_add_button_title", "دکمه"),
            "url": data.get("pending_add_button_url", ""),
            "color": color,
        }
    )
    campaign.custom_buttons = buttons
    updated, failed = await _sync_publications(campaign, callback.message.bot, session)
    await session.commit()
    await state.clear()
    await callback.answer("دکمه اضافه شد")
    await callback.message.edit_text(
        f"✅ دکمه اضافه شد.\n📡 انتشارهای به‌روزشده: {updated}\n⚠️ ناموفق: {failed}",
        reply_markup=_campaign_menu(campaign),
    )
