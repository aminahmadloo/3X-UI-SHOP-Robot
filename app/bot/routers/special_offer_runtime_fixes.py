"""Runtime fixes for the named special-offer campaign UI.

This module keeps compatibility with the existing special-offer handler while
fixing main-menu markup insertion and campaign navigation.
"""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.db.models import ServicePurchasePlan, SpecialOfferCampaign, SpecialOfferCampaignPlan

from . import special_offer_handler as special_offer

router = Router(name=__name__)


async def _safe_add_special_offer_buttons(
    reply_markup: InlineKeyboardMarkup,
    session: AsyncSession,
) -> InlineKeyboardMarkup:
    """Return a new markup with one green direct-purchase button per active offer."""
    campaigns = await special_offer._active_campaigns_with_offers(session)
    rows = [list(row) for row in reply_markup.inline_keyboard]
    offer_buttons: list[InlineKeyboardButton] = []
    for campaign in campaigns:
        offers = await special_offer._campaign_offers(session, campaign.id)
        for assignment, plan in offers:
            offer_buttons.append(
                InlineKeyboardButton(
                    text=(
                        f"{campaign.title} | {plan.volume_gb} گیگ | "
                        f"{special_offer._duration_title(plan.duration_days)} | "
                        f"{assignment.special_price_toman:,} تومان"
                    ),
                    callback_data=f"special_offer:plan:{campaign.id}:{plan.id}",
                    style="success",
                )
            )
    for button in reversed(offer_buttons):
        rows.insert(0, [button])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _safe_campaign_has_active_offers(session: AsyncSession, campaign_id: int) -> bool:
    result = await session.execute(
        select(SpecialOfferCampaignPlan.id)
        .join(ServicePurchasePlan, ServicePurchasePlan.id == SpecialOfferCampaignPlan.plan_id)
        .where(
            SpecialOfferCampaignPlan.campaign_id == campaign_id,
            SpecialOfferCampaignPlan.is_active.is_(True),
            SpecialOfferCampaignPlan.special_price_toman > 0,
            ServicePurchasePlan.is_custom.is_(False),
            ServicePurchasePlan.duration_days > 0,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _safe_campaign_offers(session: AsyncSession, campaign_id: int, *, active_only: bool = True):
    rows = await _original_campaign_offers(session, campaign_id, active_only=active_only)
    return [row for row in rows if row[1].duration_days > 0]


async def _safe_all_manageable_plans(session: AsyncSession):
    plans = await _original_all_manageable_plans(session)
    return [plan for plan in plans if plan.duration_days > 0]


_original_campaign_offers = special_offer._campaign_offers
_original_all_manageable_plans = special_offer._all_manageable_plans
special_offer.add_special_offer_buttons = _safe_add_special_offer_buttons
special_offer._campaign_has_active_offers = _safe_campaign_has_active_offers
special_offer._campaign_offers = _safe_campaign_offers
special_offer._all_manageable_plans = _safe_all_manageable_plans


async def _show_campaign_list(callback: CallbackQuery, session: AsyncSession) -> None:
    campaigns = await SpecialOfferCampaign.list_all(session)
    await callback.message.edit_text(
        "🎁 <b>مدیریت فروش‌های ویژه</b>\n\n"
        "فروش‌های ویژه بر اساس کمپین مدیریت می‌شوند.\n"
        "«فروش ویژه عادی» محصولات ویژه قبلی را نگه می‌دارد و کمپین‌های جدید را می‌توان جداگانه ساخت.",
        reply_markup=special_offer._admin_campaign_list_keyboard(campaigns),
    )


@router.callback_query(F.data == "service_purchase:special_products", IsAdmin())
async def callback_special_products_back_fix(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """Return from campaign detail to the campaign list."""
    await state.clear()
    await callback.answer()
    await _show_campaign_list(callback, session)


@router.callback_query(F.data.regexp(r"^special_offer:admin:campaign:\d+$"), IsAdmin())
async def callback_campaign_detail_back_fix(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """Own the campaign-detail navigation callback so it cannot be swallowed by another router."""
    await state.clear()
    campaign_id = int(callback.data.rsplit(":", 1)[1])
    await callback.answer()
    await special_offer._show_admin_campaign(callback, session, campaign_id)


@router.callback_query(F.data == "special_offer:admin:back_to_purchase_management", IsAdmin())
async def callback_campaign_list_back_fix(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """Return from the campaign list to service-purchase management."""
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        "🛒 <b>تنظیمات خرید سرویس|حجم سرویس|زمان سرویس</b>",
        reply_markup=special_offer._service_purchase_management_keyboard(),
    )


@router.callback_query(F.data.regexp(r"^special_offer:admin:plan:\d+:\d+$"), IsAdmin())
async def callback_special_offer_admin_plan_with_remove(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    _, _, _, campaign_id_raw, plan_id_raw = callback.data.split(":")
    campaign_id = int(campaign_id_raw)
    plan_id = int(plan_id_raw)
    campaign = await SpecialOfferCampaign.get(session, campaign_id)
    plan = await ServicePurchasePlan.get(session, plan_id)
    if not campaign or not plan or plan.is_custom or plan.duration_days <= 0:
        await callback.answer("سرویس یا فروش ویژه پیدا نشد.", show_alert=True)
        return
    assignment = await SpecialOfferCampaignPlan.get(session, campaign_id, plan_id)
    await state.clear()
    await state.update_data(special_offer_campaign_id=campaign_id, special_offer_plan_id=plan_id)
    await state.set_state(special_offer.SpecialOfferStates.waiting_price)
    await callback.answer()
    current = f"{assignment.special_price_toman:,} تومان" if assignment and assignment.special_price_toman > 0 and assignment.is_active else "تنظیم نشده"
    buttons = [
        [InlineKeyboardButton(text="🔴 حذف از این فروش ویژه", callback_data=f"special_offer:admin:remove:{campaign_id}:{plan_id}")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"special_offer:admin:campaign:{campaign_id}")],
    ]
    await callback.message.edit_text(
        f"💰 <b>قیمت ویژه</b>\n\n"
        f"🎁 فروش ویژه: <b>{campaign.title}</b>\n"
        f"📦 حجم: <b>{plan.volume_gb} گیگ</b>\n"
        f"📅 مدت: <b>{special_offer._duration_title(plan.duration_days)}</b>\n"
        f"💵 قیمت اصلی: <b>{plan.price_toman:,} تومان</b>\n"
        f"🔥 قیمت فعلی کمپین: <b>{current}</b>\n\n"
        "قیمت ویژه را به تومان و فقط به صورت عدد وارد کنید.\n"
        "مثلاً: <code>95000</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.regexp(r"^special_offer:admin:remove:\d+:\d+$"), IsAdmin())
async def callback_special_offer_admin_remove(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    _, _, _, campaign_id_raw, plan_id_raw = callback.data.split(":")
    campaign_id = int(campaign_id_raw)
    plan_id = int(plan_id_raw)
    assignment = await SpecialOfferCampaignPlan.get(session, campaign_id, plan_id)
    campaign = await SpecialOfferCampaign.get(session, campaign_id)
    if not assignment or not campaign:
        await state.clear()
        await callback.answer("این سرویس در فروش ویژه انتخاب نشده است.", show_alert=True)
        return
    assignment.is_active = False
    await session.commit()
    await state.clear()
    await callback.answer("✅ سرویس از این فروش ویژه خارج شد.")
    await special_offer._show_admin_campaign(callback, session, campaign_id)
