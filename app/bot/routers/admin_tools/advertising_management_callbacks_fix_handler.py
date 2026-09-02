from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.states.advertising import AdvertisingStates
from app.bot.routers.admin_tools.advertising_management_handler import (
    _button_edit_screen,
    _campaign_menu,
    _get_campaign,
    _sync_publications,
)

router = Router(name=__name__)


@router.callback_query(F.data.regexp(r"^advertising:button_edit:\d+:\d+$"), IsAdmin())
async def button_edit(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, campaign_raw, index_raw = callback.data.split(":")
    campaign = await _get_campaign(session, int(campaign_raw))
    index = int(index_raw)
    if not campaign or index < 0 or index >= len(campaign.custom_buttons):
        await callback.answer("دکمه پیدا نشد.", show_alert=True)
        return
    await callback.answer()
    await _button_edit_screen(callback, campaign, index)


@router.callback_query(F.data.regexp(r"^advertising:button_title_edit:\d+:\d+$"), IsAdmin())
async def button_title_edit_start(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, campaign_raw, index_raw = callback.data.split(":")
    await state.update_data(edit_campaign_id=int(campaign_raw), edit_button_index=int(index_raw))
    await state.set_state(AdvertisingStates.waiting_edit_button_title)
    await callback.answer()
    await callback.message.edit_text(
        "✏️ عنوان جدید دکمه را ارسال کن.",
        reply_markup=__import__("aiogram").types.InlineKeyboardMarkup(
            inline_keyboard=[[__import__("aiogram").types.InlineKeyboardButton(text="❌ لغو", callback_data="advertising:manage:cancel")]]
        ),
    )


@router.callback_query(F.data.regexp(r"^advertising:button_url_edit:\d+:\d+$"), IsAdmin())
async def button_url_edit_start(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, campaign_raw, index_raw = callback.data.split(":")
    await state.update_data(edit_campaign_id=int(campaign_raw), edit_button_index=int(index_raw))
    await state.set_state(AdvertisingStates.waiting_edit_button_url)
    await callback.answer()
    await callback.message.edit_text(
        "🔗 لینک / اکشن جدید دکمه را ارسال کن.",
        reply_markup=__import__("aiogram").types.InlineKeyboardMarkup(
            inline_keyboard=[[__import__("aiogram").types.InlineKeyboardButton(text="❌ لغو", callback_data="advertising:manage:cancel")]]
        ),
    )


@router.callback_query(F.data.regexp(r"^advertising:button_color_edit:\d+:\d+$"), IsAdmin())
async def button_color_edit_start(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, campaign_raw, index_raw = callback.data.split(":")
    campaign = await _get_campaign(session, int(campaign_raw))
    index = int(index_raw)
    if not campaign or index < 0 or index >= len(campaign.custom_buttons):
        await callback.answer("دکمه پیدا نشد.", show_alert=True)
        return
    b = InlineKeyboardBuilder()
    for color, label in (("green", "🟢 سبز"), ("red", "🔴 قرمز"), ("blue", "🔵 آبی"), ("none", "⚪ بدون رنگ")):
        b.row(InlineKeyboardBuilder().button(text=label, callback_data=f"advertising:button_color_set:{campaign.id}:{index}:{color}").as_markup().inline_keyboard[0][0])
    b.row(__import__("aiogram").types.InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"advertising:button_edit:{campaign.id}:{index}"))
    await callback.answer()
    await callback.message.edit_text("🎨 رنگ جدید را انتخاب کن.", reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^advertising:button_color_set:\d+:\d+:(green|red|blue|none)$"), IsAdmin())
async def button_color_set(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, campaign_raw, index_raw, color = callback.data.split(":")
    campaign = await _get_campaign(session, int(campaign_raw))
    index = int(index_raw)
    if not campaign or index < 0 or index >= len(campaign.custom_buttons):
        await callback.answer("دکمه پیدا نشد.", show_alert=True)
        return
    buttons = campaign.custom_buttons
    buttons[index]["color"] = color
    campaign.custom_buttons = buttons
    updated, failed = await _sync_publications(campaign, callback.message.bot, session)
    await session.commit()
    await callback.answer("رنگ ذخیره شد")
    await callback.message.edit_text(
        f"✅ رنگ دکمه ذخیره شد.\n📡 موفق: {updated}\n⚠️ ناموفق: {failed}",
        reply_markup=_campaign_menu(campaign),
    )


@router.callback_query(F.data.regexp(r"^advertising:button_delete:\d+:\d+$"), IsAdmin())
async def button_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, campaign_raw, index_raw = callback.data.split(":")
    campaign = await _get_campaign(session, int(campaign_raw))
    index = int(index_raw)
    if not campaign or index < 0 or index >= len(campaign.custom_buttons):
        await callback.answer("دکمه پیدا نشد.", show_alert=True)
        return
    buttons = campaign.custom_buttons
    buttons.pop(index)
    campaign.custom_buttons = buttons
    updated, failed = await _sync_publications(campaign, callback.message.bot, session)
    await session.commit()
    await callback.answer("دکمه حذف شد")
    await callback.message.edit_text(
        f"✅ دکمه حذف شد.\n📡 موفق: {updated}\n⚠️ ناموفق: {failed}",
        reply_markup=__import__("app.bot.routers.admin_tools.advertising_management_handler", fromlist=["_button_menu"])._button_menu(campaign),
    )


@router.callback_query(F.data.regexp(r"^advertising:button_(up|down):\d+:\d+$"), IsAdmin())
async def button_move(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, direction, campaign_raw, index_raw = callback.data.split(":")
    campaign = await _get_campaign(session, int(campaign_raw))
    index = int(index_raw)
    if not campaign or index < 0 or index >= len(campaign.custom_buttons):
        await callback.answer("دکمه پیدا نشد.", show_alert=True)
        return
    target = index - 1 if direction == "up" else index + 1
    buttons = campaign.custom_buttons
    if target < 0 or target >= len(buttons):
        await callback.answer()
        return
    buttons[index], buttons[target] = buttons[target], buttons[index]
    campaign.custom_buttons = buttons
    updated, failed = await _sync_publications(campaign, callback.message.bot, session)
    await session.commit()
    await callback.answer("ترتیب دکمه‌ها تغییر کرد")
    await callback.message.edit_text(
        f"✅ ترتیب دکمه‌ها ذخیره شد.\n📡 موفق: {updated}\n⚠️ ناموفق: {failed}",
        reply_markup=__import__("app.bot.routers.admin_tools.advertising_management_handler", fromlist=["_button_menu"])._button_menu(campaign),
    )
