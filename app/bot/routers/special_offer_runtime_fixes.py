"""Runtime fixes for the named special-offer campaign UI."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.models import ServicesContainer
from app.bot.services.customer_level import get_discounted_plan_price
from app.db.models import ServicePurchasePlan, SpecialOfferCampaign, SpecialOfferCampaignPlan, User

from . import special_offer_handler as special_offer

router = Router(name=__name__)


async def _safe_add_special_offer_buttons(reply_markup: InlineKeyboardMarkup, session: AsyncSession) -> InlineKeyboardMarkup:
    campaigns = await special_offer._active_campaigns_with_offers(session)
    rows = [list(row) for row in reply_markup.inline_keyboard]
    buttons = []
    for campaign in campaigns:
        for assignment, plan in await special_offer._campaign_offers(session, campaign.id):
            buttons.append(InlineKeyboardButton(
                text=f"{campaign.title} | {plan.volume_gb} گیگ | {special_offer._duration_title(plan.duration_days)} | {assignment.special_price_toman:,} تومان",
                callback_data=f"special_offer:plan:{campaign.id}:{plan.id}", style="success"))
    for button in reversed(buttons):
        rows.insert(0, [button])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _safe_campaign_has_active_offers(session: AsyncSession, campaign_id: int) -> bool:
    result = await session.execute(
        select(SpecialOfferCampaignPlan.id).join(ServicePurchasePlan, ServicePurchasePlan.id == SpecialOfferCampaignPlan.plan_id).where(
            SpecialOfferCampaignPlan.campaign_id == campaign_id,
            SpecialOfferCampaignPlan.is_active.is_(True),
            SpecialOfferCampaignPlan.special_price_toman > 0,
            ServicePurchasePlan.is_custom.is_(False),
            ServicePurchasePlan.duration_days > 0,
        ).limit(1))
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


@router.callback_query(F.data.regexp(r"^special_offer:plan:\d+:\d+$"))
async def callback_special_offer_purchase_with_customer_discount(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    """Preserve the campaign price as the base and apply the customer-level discount."""
    _, _, campaign_id_raw, plan_id_raw = callback.data.split(":")
    campaign_id = int(campaign_id_raw)
    plan_id = int(plan_id_raw)

    campaign = await SpecialOfferCampaign.get(session, campaign_id)
    plan = await ServicePurchasePlan.get(session, plan_id)
    offer = await SpecialOfferCampaignPlan.get(session, campaign_id, plan_id)

    if (
        not campaign
        or not campaign.is_active
        or not plan
        or plan.is_custom
        or not offer
        or not offer.is_active
        or offer.special_price_toman <= 0
    ):
        await callback.answer("این فروش ویژه دیگر فعال نیست.", show_alert=True)
        return

    await special_offer._start_plan_purchase(
        event=callback,
        user=user,
        session=session,
        state=state,
        services=services,
        plan=plan,
    )

    data = await state.get_data()
    packed = data.get("subscription_data")
    if not isinstance(packed, dict):
        return

    special_price = int(offer.special_price_toman)
    customer_level, _, discounted_special_price = await get_discounted_plan_price(
        session,
        user.tg_id,
        special_price,
    )
    discount_percent = int(getattr(customer_level, "discount_percent", 0) or 0)
    discount_level_title = str(getattr(customer_level, "title", "") or "")

    await state.update_data(
        subscription_data={
            **packed,
            "price": discounted_special_price,
            "original_price": special_price,
            "discount_percent": discount_percent,
            "discount_level_title": discount_level_title,
            "special_offer": True,
            "special_offer_campaign_id": campaign.id,
        }
    )


@router.callback_query(F.data == "service_purchase:special_products", IsAdmin())
async def callback_special_products_back_fix(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    campaigns = await SpecialOfferCampaign.list_all(session)
    await callback.answer()
    await callback.message.edit_text(
        "🎁 <b>مدیریت فروش‌های ویژه</b>\n\nفروش‌های ویژه بر اساس کمپین مدیریت می‌شوند.\n«فروش ویژه عادی» محصولات ویژه قبلی را نگه می‌دارد و کمپین‌های جدید را می‌توان جداگانه ساخت.",
        reply_markup=special_offer._admin_campaign_list_keyboard(campaigns),
    )


@router.callback_query(F.data == "service_purchase:management", IsAdmin())
async def callback_special_products_list_back_fix(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    # Let the existing service-purchase-management handler render the real menu.
    from .admin_tools.service_purchase_management_menu_handler import callback_service_purchase_management
    await callback_service_purchase_management(callback)


@router.callback_query(F.data.regexp(r"^special_offer:admin:campaign:\d+$"), IsAdmin())
async def callback_campaign_detail_fix(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    campaign_id = int(callback.data.rsplit(":", 1)[1])
    await special_offer._show_admin_campaign(callback, session, campaign_id)


@router.callback_query(F.data.regexp(r"^special_offer:admin:plan:\d+:\d+$"), IsAdmin())
async def callback_special_offer_admin_plan_with_remove(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    _, _, _, campaign_id_raw, plan_id_raw = callback.data.split(":")
    campaign_id, plan_id = int(campaign_id_raw), int(plan_id_raw)
    campaign = await SpecialOfferCampaign.get(session, campaign_id)
    plan = await ServicePurchasePlan.get(session, plan_id)
    if not campaign or not plan or plan.is_custom or plan.duration_days <= 0:
        await callback.answer("سرویس یا فروش ویژه پیدا نشد.", show_alert=True)
        return
    assignment = await SpecialOfferCampaignPlan.get(session, campaign_id, plan_id)
    await state.clear()
    await state.update_data(special_offer_campaign_id=campaign_id, special_offer_plan_id=plan_id)
    await state.set_state(special_offer.SpecialOfferStates.waiting_price)
    current = f"{assignment.special_price_toman:,} تومان" if assignment and assignment.special_price_toman > 0 and assignment.is_active else "تنظیم نشده"
    await callback.answer()
    await callback.message.edit_text(
        f"💰 <b>قیمت ویژه</b>\n\n🎁 فروش ویژه: <b>{campaign.title}</b>\n📦 حجم: <b>{plan.volume_gb} گیگ</b>\n📅 مدت: <b>{special_offer._duration_title(plan.duration_days)}</b>\n💵 قیمت اصلی: <b>{plan.price_toman:,} تومان</b>\n🔥 قیمت فعلی کمپین: <b>{current}</b>\n\nقیمت ویژه را به تومان و فقط به صورت عدد وارد کنید.\nمثلاً: <code>95000</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔴 حذف از این فروش ویژه", callback_data=f"special_offer:admin:remove:{campaign_id}:{plan_id}")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"special_offer:admin:campaign:{campaign_id}")],
        ]))


@router.callback_query(F.data.regexp(r"^special_offer:admin:remove:\d+:\d+$"), IsAdmin())
async def callback_special_offer_admin_remove(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    _, _, _, campaign_id_raw, plan_id_raw = callback.data.split(":")
    campaign_id, plan_id = int(campaign_id_raw), int(plan_id_raw)
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
