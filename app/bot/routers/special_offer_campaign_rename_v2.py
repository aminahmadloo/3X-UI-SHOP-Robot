"""Campaign title editing extension for the special-offer router."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.db.models import SpecialOfferCampaign

from . import special_offer_handler


router = Router(name=__name__)
_original_show_admin_campaign = special_offer_handler._show_admin_campaign


class CampaignRenameStates(StatesGroup):
    waiting_title = State()


async def _show_admin_campaign_with_rename(
    target: Message | CallbackQuery,
    session: AsyncSession,
    campaign_id: int,
) -> None:
    await _original_show_admin_campaign(target, session, campaign_id)

    message = target.message if isinstance(target, CallbackQuery) else target
    if not message or not message.reply_markup:
        return

    campaign = await SpecialOfferCampaign.get(session, campaign_id)
    if not campaign:
        return

    rows = [list(row) for row in message.reply_markup.inline_keyboard]
    rename_callback = f"special_offer:admin:rename:{campaign_id}"
    if any(button.callback_data == rename_callback for row in rows for button in row):
        return

    rows.insert(
        max(0, len(rows) - 1),
        [InlineKeyboardButton(text="✏️ ویرایش عنوان", callback_data=rename_callback)],
    )
    await message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


special_offer_handler._show_admin_campaign = _show_admin_campaign_with_rename


@router.callback_query(F.data.regexp(r"^special_offer:admin:rename:\d+$"), IsAdmin())
async def callback_special_offer_admin_rename(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    campaign_id = int(callback.data.rsplit(":", 1)[1])
    campaign = await SpecialOfferCampaign.get(session, campaign_id)
    if not campaign:
        await callback.answer("فروش ویژه پیدا نشد.", show_alert=True)
        return

    await state.clear()
    await state.update_data(special_offer_campaign_id=campaign.id)
    await state.set_state(CampaignRenameStates.waiting_title)
    await callback.answer()
    await callback.message.edit_text(
        "✏️ <b>ویرایش عنوان فروش ویژه</b>\n\n"
        f"عنوان فعلی: <b>{campaign.title}</b>\n\n"
        "عنوان جدید را وارد کنید.\n"
        "عنوان حداکثر ۱۰۰ کاراکتر باشد."
    )


@router.message(CampaignRenameStates.waiting_title, IsAdmin())
async def message_special_offer_campaign_title_edit(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    data = await state.get_data()
    campaign_id = data.get("special_offer_campaign_id")
    if campaign_id is None:
        await state.clear()
        await message.answer("❌ اطلاعات ویرایش فروش ویژه پیدا نشد.")
        return

    title = " ".join((message.text or "").split()).strip()
    if not title:
        await message.answer("❌ عنوان نمی‌تواند خالی باشد.")
        return
    if len(title) > 100:
        await message.answer("❌ عنوان نباید بیشتر از ۱۰۰ کاراکتر باشد.")
        return

    result = await session.execute(
        select(SpecialOfferCampaign).where(
            func.lower(SpecialOfferCampaign.title) == title.lower(),
            SpecialOfferCampaign.id != int(campaign_id),
        )
    )
    if result.scalar_one_or_none():
        await message.answer("❌ این عنوان قبلاً استفاده شده است. یک عنوان دیگر وارد کنید.")
        return

    campaign = await SpecialOfferCampaign.get(session, int(campaign_id))
    if not campaign:
        await state.clear()
        await message.answer("❌ فروش ویژه پیدا نشد.")
        return

    campaign.title = title
    await session.commit()
    await state.clear()
    await message.answer(f"✅ عنوان فروش ویژه به <b>{campaign.title}</b> تغییر کرد.")
    await _show_admin_campaign_with_rename(message, session, campaign.id)
