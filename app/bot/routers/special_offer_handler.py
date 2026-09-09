import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.models import ServicesContainer
from app.bot.routers.main_menu import handler as main_menu_handler
from app.bot.routers.subscription.subscription_handler import _start_plan_purchase
from app.bot.services.customer_level import get_discounted_plan_price
from app.db.models import (
    ServicePurchasePlan,
    SpecialOfferCampaign,
    SpecialOfferCampaignPlan,
    User,
)

logger = logging.getLogger(__name__)
router = Router(name=__name__)


class SpecialOfferStates(StatesGroup):
    waiting_campaign_title = State()
    waiting_price = State()


def _duration_title(days: int) -> str:
    exact = {
        30: "یک‌ماهه",
        60: "دوماهه",
        90: "سه‌ماهه",
        120: "چهارماهه",
        180: "شش‌ماهه",
        365: "یک‌ساله",
        730: "دوساله",
    }
    return exact.get(days, f"{days} روزه")


async def _campaign_has_active_offers(
    session: AsyncSession,
    campaign_id: int,
) -> bool:
    result = await session.execute(
        select(SpecialOfferCampaignPlan.id)
        .join(ServicePurchasePlan, ServicePurchasePlan.id == SpecialOfferCampaignPlan.plan_id)
        .where(
            SpecialOfferCampaignPlan.campaign_id == campaign_id,
            SpecialOfferCampaignPlan.is_active.is_(True),
            SpecialOfferCampaignPlan.special_price_toman > 0,
            ServicePurchasePlan.is_custom.is_(False),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _active_campaigns_with_offers(
    session: AsyncSession,
) -> list[SpecialOfferCampaign]:
    result = await session.execute(
        select(SpecialOfferCampaign)
        .where(SpecialOfferCampaign.is_active.is_(True))
        .order_by(SpecialOfferCampaign.is_default.asc(), SpecialOfferCampaign.id)
    )
    campaigns = list(result.scalars().all())
    visible: list[SpecialOfferCampaign] = []
    for campaign in campaigns:
        if await _campaign_has_active_offers(session, campaign.id):
            visible.append(campaign)
    return visible


async def _campaign_offers(
    session: AsyncSession,
    campaign_id: int,
    *,
    active_only: bool = True,
) -> list[tuple[SpecialOfferCampaignPlan, ServicePurchasePlan]]:
    query = (
        select(SpecialOfferCampaignPlan, ServicePurchasePlan)
        .join(ServicePurchasePlan, ServicePurchasePlan.id == SpecialOfferCampaignPlan.plan_id)
        .where(
            SpecialOfferCampaignPlan.campaign_id == campaign_id,
            ServicePurchasePlan.is_custom.is_(False),
        )
        .order_by(ServicePurchasePlan.duration_days, ServicePurchasePlan.volume_gb, ServicePurchasePlan.id)
    )
    if active_only:
        query = query.where(
            SpecialOfferCampaignPlan.is_active.is_(True),
            SpecialOfferCampaignPlan.special_price_toman > 0,
        )
    result = await session.execute(query)
    return list(result.all())


async def _all_manageable_plans(session: AsyncSession) -> list[ServicePurchasePlan]:
    result = await session.execute(
        select(ServicePurchasePlan)
        .where(ServicePurchasePlan.is_custom.is_(False))
        .order_by(ServicePurchasePlan.duration_days, ServicePurchasePlan.volume_gb, ServicePurchasePlan.id)
    )
    return list(result.scalars().all())


def _group_plans(
    rows: list[tuple[SpecialOfferCampaignPlan, ServicePurchasePlan]],
) -> list[tuple[int, list[tuple[SpecialOfferCampaignPlan, ServicePurchasePlan]]]]:
    grouped: dict[int, list[tuple[SpecialOfferCampaignPlan, ServicePurchasePlan]]] = {}
    for row in rows:
        grouped.setdefault(row[1].duration_days, []).append(row)
    return sorted(grouped.items(), key=lambda item: item[0])


def _group_all_plans(
    plans: list[ServicePurchasePlan],
) -> list[tuple[int, list[ServicePurchasePlan]]]:
    grouped: dict[int, list[ServicePurchasePlan]] = {}
    for plan in plans:
        grouped.setdefault(plan.duration_days, []).append(plan)
    return sorted(grouped.items(), key=lambda item: item[0])


def _public_campaign_keyboard(
    campaign_id: int,
    rows: list[tuple[SpecialOfferCampaignPlan, ServicePurchasePlan]],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for duration_days, duration_rows in _group_plans(rows):
        builder.row(
            InlineKeyboardButton(
                text=f"📅 {_duration_title(duration_days)}",
                callback_data="special_offer:noop",
            )
        )
        for _, plan in duration_rows:
            offer = next(item for item in rows if item[1].id == plan.id)
            builder.row(
                InlineKeyboardButton(
                    text=f"📦 {plan.volume_gb} گیگ — {offer[0].special_price_toman:,} تومان",
                    callback_data=f"special_offer:plan:{campaign_id}:{plan.id}",
                )
            )
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="main_menu"))
    return builder.as_markup()


async def add_special_offer_buttons(
    reply_markup: InlineKeyboardMarkup,
    session: AsyncSession,
) -> InlineKeyboardMarkup:
    campaigns = await _active_campaigns_with_offers(session)
    for campaign in reversed(campaigns):
        reply_markup.inline_keyboard.insert(
            0,
            [InlineKeyboardButton(text=campaign.title, callback_data=f"special_offer:campaign:{campaign.id}", style="success")],
        )
    return reply_markup


_original_send_main_menu = main_menu_handler.send_main_menu


async def _send_main_menu_with_special_offers(
    bot,
    user,
    services,
    config,
    state,
    session,
):
    message = await _original_send_main_menu(
        bot=bot,
        user=user,
        services=services,
        config=config,
        state=state,
        session=session,
    )
    try:
        if message.reply_markup:
            markup = await add_special_offer_buttons(message.reply_markup, session)
            if markup.inline_keyboard != message.reply_markup.inline_keyboard:
                await message.edit_reply_markup(reply_markup=markup)
    except Exception:
        logger.exception("Failed to append special-offer campaign buttons to main menu")
    return message


main_menu_handler.send_main_menu = _send_main_menu_with_special_offers


@router.callback_query(F.data == "special_offer:noop")
async def callback_special_offer_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.regexp(r"^special_offer:campaign:\d+$"))
async def callback_special_offer_campaign(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    campaign_id = int(callback.data.rsplit(":", 1)[1])
    campaign = await SpecialOfferCampaign.get(session, campaign_id)
    if not campaign or not campaign.is_active:
        await callback.answer("این فروش ویژه دیگر فعال نیست.", show_alert=True)
        return

    rows = await _campaign_offers(session, campaign.id)
    if not rows:
        await callback.answer("این فروش ویژه در حال حاضر سرویسی ندارد.", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text(
        f"🎁 <b>{campaign.title}</b>\n\n"
        "سرویس موردنظر را بر اساس مدت انتخاب کنید:",
        reply_markup=_public_campaign_keyboard(campaign.id, rows),
    )


@router.callback_query(F.data.regexp(r"^special_offer:plan:\d+:\d+$"))
async def callback_special_offer_purchase(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
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

    await _start_plan_purchase(
        event=callback,
        user=user,
        session=session,
        state=state,
        services=services,
        plan=plan,
    )

    data = await state.get_data()
    packed = data.get("subscription_data")

    if isinstance(packed, dict):
        special_price = int(offer.special_price_toman)

        customer_level, _, discounted_special_price = await get_discounted_plan_price(
            session,
            user.tg_id,
            special_price,
        )

        discount_percent = int(
            getattr(customer_level, "discount_percent", 0) or 0
        )

        discount_title = str(
            getattr(customer_level, "title", "")
            or getattr(customer_level, "name", "")
            or "سطح پایه"
        )

        await state.update_data(
            subscription_data={
                **packed,
                "base_plan_price": int(plan.price_toman),
                "price": discounted_special_price,
                "original_price": special_price,
                "discount_percent": discount_percent,
                "discount_level_title": discount_title,
                "special_offer": True,
                "special_offer_campaign_id": campaign.id,
            }
        )


def _admin_campaign_list_keyboard(
    campaigns: list[SpecialOfferCampaign],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for campaign in campaigns:
        status = "🟢" if campaign.is_active else "🔴"
        default = " ⭐" if campaign.is_default else ""
        builder.row(
            InlineKeyboardButton(
                text=f"{status} {campaign.title}{default}",
                callback_data=f"special_offer:admin:campaign:{campaign.id}",
            )
        )
    builder.row(InlineKeyboardButton(text="➕ ایجاد فروش‌های ویژه", callback_data="special_offer:admin:create"))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="service_purchase:management"))
    return builder.as_markup()


@router.callback_query(F.data == "service_purchase:special_products", IsAdmin())
async def callback_special_products(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    campaigns = await SpecialOfferCampaign.list_all(session)
    await callback.answer()
    await callback.message.edit_text(
        "🎁 <b>مدیریت فروش‌های ویژه</b>\n\n"
        "فروش‌های ویژه بر اساس کمپین مدیریت می‌شوند.\n"
        "«فروش ویژه عادی» محصولات ویژه قبلی را نگه می‌دارد و کمپین‌های جدید را می‌توان جداگانه ساخت.",
        reply_markup=_admin_campaign_list_keyboard(campaigns),
    )


@router.callback_query(F.data == "special_offer:admin:create", IsAdmin())
async def callback_special_offer_create(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.clear()
    await state.set_state(SpecialOfferStates.waiting_campaign_title)
    await callback.answer()
    await callback.message.edit_text(
        "➕ <b>ایجاد فروش‌های ویژه</b>\n\n"
        "عنوان فروش ویژه را وارد کنید.\n\n"
        "مثلاً:\n"
        "• فروش ویژه عید نوروز\n"
        "• فروش ویژه تابستان\n"
        "• فروش ویژه جمعه طلایی\n\n"
        "عنوان حداکثر ۱۰۰ کاراکتر باشد."
    )


@router.message(SpecialOfferStates.waiting_campaign_title, IsAdmin())
async def message_special_offer_campaign_title(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    title = " ".join((message.text or "").split()).strip()
    if not title:
        await message.answer("❌ عنوان نمی‌تواند خالی باشد.")
        return
    if len(title) > 100:
        await message.answer("❌ عنوان نباید بیشتر از ۱۰۰ کاراکتر باشد.")
        return

    existing = await session.execute(
        select(SpecialOfferCampaign).where(func.lower(SpecialOfferCampaign.title) == title.lower())
    )
    if existing.scalar_one_or_none():
        await message.answer("❌ این عنوان قبلاً استفاده شده است. یک عنوان دیگر وارد کنید.")
        return

    campaign = SpecialOfferCampaign(title=title, is_default=False, is_active=False)
    session.add(campaign)
    await session.commit()
    await state.clear()

    await message.answer(
        f"✅ فروش ویژه <b>{campaign.title}</b> ایجاد شد.\n\n"
        "حالا سرویس‌های فعال را بر اساس مدت انتخاب کن و برای هرکدام قیمت ویژه تعیین کن."
    )
    await _show_admin_campaign(message, session, campaign.id)


async def _show_admin_campaign(
    target: Message | CallbackQuery,
    session: AsyncSession,
    campaign_id: int,
) -> None:
    campaign = await SpecialOfferCampaign.get(session, campaign_id)
    if not campaign:
        if isinstance(target, CallbackQuery):
            await target.answer("فروش ویژه پیدا نشد.", show_alert=True)
        else:
            await target.answer("❌ فروش ویژه پیدا نشد.")
        return

    plans = await _all_manageable_plans(session)
    assignments = {
        row.plan_id: row
        for row in await SpecialOfferCampaignPlan.list_for_campaign(session, campaign_id, active_only=False)
    }

    builder = InlineKeyboardBuilder()
    for duration_days, duration_plans in _group_all_plans(plans):
        builder.row(
            InlineKeyboardButton(
                text=f"📅 {_duration_title(duration_days)}",
                callback_data="special_offer:noop",
            )
        )
        for plan in duration_plans:
            assignment = assignments.get(plan.id)
            if assignment and assignment.is_active and assignment.special_price_toman > 0:
                text = f"🟢 {plan.volume_gb} گیگ — {assignment.special_price_toman:,} تومان ویژه"
            elif assignment:
                text = f"⚪️ {plan.volume_gb} گیگ — {assignment.special_price_toman:,} تومان (غیرفعال)"
            else:
                text = f"⚪️ {plan.volume_gb} گیگ — قیمت اصلی {plan.price_toman:,} تومان"
            builder.row(
                InlineKeyboardButton(
                    text=text,
                    callback_data=f"special_offer:admin:plan:{campaign_id}:{plan.id}",
                )
            )

    builder.row(
        InlineKeyboardButton(
            text="🔴 غیرفعال کردن" if campaign.is_active else "🟢 فعال کردن",
            callback_data=f"special_offer:admin:toggle:{campaign_id}",
        )
    )
    builder.row(InlineKeyboardButton(text="🔙 لیست فروش‌های ویژه", callback_data="service_purchase:special_products"))

    text = (
        f"🎁 <b>{campaign.title}</b>\n\n"
        f"📌 وضعیت: <b>{'فعال' if campaign.is_active else 'غیرفعال'}</b>\n"
        "\nسرویس‌ها بر اساس مدت واقعی گروه‌بندی شده‌اند.\n"
        "برای افزودن سرویس یا تغییر قیمت، روی همان سرویس بزنید."
    )
    if isinstance(target, CallbackQuery):
        await target.answer()
        await target.message.edit_text(text, reply_markup=builder.as_markup())
    else:
        await target.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.regexp(r"^special_offer:admin:campaign:\d+$"), IsAdmin())
async def callback_special_offer_admin_campaign(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    campaign_id = int(callback.data.rsplit(":", 1)[1])
    await _show_admin_campaign(callback, session, campaign_id)


@router.callback_query(F.data.regexp(r"^special_offer:admin:toggle:\d+$"), IsAdmin())
async def callback_special_offer_admin_toggle(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    campaign_id = int(callback.data.rsplit(":", 1)[1])
    campaign = await SpecialOfferCampaign.get(session, campaign_id)
    if not campaign:
        await callback.answer("فروش ویژه پیدا نشد.", show_alert=True)
        return

    if campaign.is_active:
        campaign.is_active = False
        message = "🔴 فروش ویژه غیرفعال شد."
    else:
        if not await _campaign_has_active_offers(session, campaign.id):
            await callback.answer("ابتدا حداقل یک سرویس با قیمت ویژه فعال کنید.", show_alert=True)
            return
        campaign.is_active = True
        message = "🟢 فروش ویژه فعال شد."
    await session.commit()
    await callback.answer(message)
    await _show_admin_campaign(callback, session, campaign.id)


@router.callback_query(F.data.regexp(r"^special_offer:admin:plan:\d+:\d+$"), IsAdmin())
async def callback_special_offer_admin_plan(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    _, _, _, campaign_id_raw, plan_id_raw = callback.data.split(":")
    campaign_id = int(campaign_id_raw)
    plan_id = int(plan_id_raw)
    campaign = await SpecialOfferCampaign.get(session, campaign_id)
    plan = await ServicePurchasePlan.get(session, plan_id)
    if not campaign or not plan or plan.is_custom:
        await callback.answer("سرویس یا فروش ویژه پیدا نشد.", show_alert=True)
        return

    assignment = await SpecialOfferCampaignPlan.get(session, campaign_id, plan_id)
    await state.clear()
    await state.update_data(
        special_offer_campaign_id=campaign_id,
        special_offer_plan_id=plan_id,
    )
    await state.set_state(SpecialOfferStates.waiting_price)
    await callback.answer()
    current = (
        f"{assignment.special_price_toman:,} تومان"
        if assignment and assignment.special_price_toman > 0
        else "تنظیم نشده"
    )
    await callback.message.edit_text(
        f"💰 <b>قیمت ویژه</b>\n\n"
        f"🎁 فروش ویژه: <b>{campaign.title}</b>\n"
        f"📦 حجم: <b>{plan.volume_gb} گیگ</b>\n"
        f"📅 مدت: <b>{_duration_title(plan.duration_days)}</b>\n"
        f"💵 قیمت اصلی: <b>{plan.price_toman:,} تومان</b>\n"
        f"🔥 قیمت فعلی کمپین: <b>{current}</b>\n\n"
        "قیمت ویژه را به تومان و فقط به صورت عدد وارد کنید.\n"
        "مثلاً: <code>95000</code>"
    )


@router.message(SpecialOfferStates.waiting_price, IsAdmin())
async def message_special_offer_price(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    raw = (message.text or "").replace(",", "").replace("٬", "").strip()
    try:
        price = int(raw)
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ قیمت نامعتبر است. مبلغ را به صورت عددی بزرگ‌تر از صفر وارد کنید.")
        return

    data = await state.get_data()
    campaign_id = int(data["special_offer_campaign_id"])
    plan_id = int(data["special_offer_plan_id"])
    campaign = await SpecialOfferCampaign.get(session, campaign_id)
    plan = await ServicePurchasePlan.get(session, plan_id)
    if not campaign or not plan:
        await state.clear()
        await message.answer("❌ فروش ویژه یا سرویس پیدا نشد.")
        return

    assignment = await SpecialOfferCampaignPlan.get(session, campaign_id, plan_id)
    if assignment is None:
        assignment = SpecialOfferCampaignPlan(
            campaign_id=campaign_id,
            plan_id=plan_id,
            special_price_toman=price,
            is_active=True,
        )
        session.add(assignment)
    else:
        assignment.special_price_toman = price
        assignment.is_active = True

    await session.commit()
    await state.clear()
    await message.answer(
        f"✅ قیمت ویژه <b>{price:,} تومان</b> برای «{campaign.title}» ذخیره و سرویس فعال شد."
    )
    await _show_admin_campaign(message, session, campaign.id)
