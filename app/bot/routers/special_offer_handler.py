import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.models import ServicesContainer
from app.bot.routers.main_menu import handler as main_menu_handler
from app.bot.routers.subscription.subscription_handler import _start_plan_purchase
from app.db.models import ServicePurchasePlan, User

logger = logging.getLogger(__name__)
router = Router(name=__name__)


class SpecialOfferStates(StatesGroup):
    waiting_price = State()


def _offer_title(plan: ServicePurchasePlan) -> str:
    period = "یک‌ماهه" if plan.service_type == "one_month" else "سه‌ماهه"
    return f"🔥 فروش ویژه سرویس {plan.volume_gb} گیگ {period} {int(plan.special_offer_price_toman)} تومان"


async def _active_special_offers(session: AsyncSession) -> list[ServicePurchasePlan]:
    result = await session.execute(
        select(ServicePurchasePlan)
        .where(
            ServicePurchasePlan.is_custom.is_(False),
            ServicePurchasePlan.is_special_offer.is_(True),
            ServicePurchasePlan.special_offer_price_toman.is_not(None),
            ServicePurchasePlan.special_offer_price_toman > 0,
        )
        .order_by(ServicePurchasePlan.id)
    )
    return list(result.scalars().all())


async def add_special_offer_buttons(
    reply_markup: InlineKeyboardMarkup,
    session: AsyncSession,
) -> InlineKeyboardMarkup:
    offers = await _active_special_offers(session)
    for plan in reversed(offers):
        reply_markup.inline_keyboard.insert(
            0,
            [InlineKeyboardButton(
                text=_offer_title(plan),
                callback_data=f"special_offer:{plan.id}",
                style="success",
            )],
        )
    return reply_markup


# Decorate the existing main-menu sender instead of changing its existing
# construction logic. This keeps all healthy main-menu behavior intact.
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
            await message.edit_reply_markup(reply_markup=markup)
    except Exception:
        logger.exception("Failed to append special-offer buttons to main menu")
    return message


main_menu_handler.send_main_menu = _send_main_menu_with_special_offers


@router.callback_query(
    F.data.regexp(r"^special_offer:\d+$")
)
async def callback_special_offer_purchase(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    try:
        plan_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("سرویس نامعتبر است.", show_alert=True)
        return

    plan = await ServicePurchasePlan.get(session, plan_id)
    if (
        not plan
        or plan.is_custom
        or not plan.is_special_offer
        or not plan.special_offer_price_toman
        or plan.special_offer_price_toman <= 0
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
        special_price = int(plan.special_offer_price_toman)
        await state.update_data(
            subscription_data={
                **packed,
                "price": special_price,
                "original_price": special_price,
                "discount_percent": 0,
                "discount_level_title": "فروش ویژه",
                "special_offer": True,
            }
        )


def _special_offer_admin_keyboard(plans: list[ServicePurchasePlan]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        status = "🟢" if plan.is_special_offer and plan.special_offer_price_toman else "⚪️"
        period = "یک‌ماهه" if plan.service_type == "one_month" else "سه‌ماهه"
        price = f" — {int(plan.special_offer_price_toman):,} تومان" if plan.special_offer_price_toman else ""
        builder.row(InlineKeyboardButton(
            text=f"{status} {plan.volume_gb} گیگ {period}{price}",
            callback_data=f"special_offer:admin:{plan.id}",
        ))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="service_purchase:management"))
    return builder.as_markup()


async def _load_all_plans(session: AsyncSession) -> list[ServicePurchasePlan]:
    one = await ServicePurchasePlan.list_by_type(session, "one_month", include_custom=False)
    three = await ServicePurchasePlan.list_by_type(session, "three_month", include_custom=False)
    return one + three


@router.callback_query(F.data == "service_purchase:special_products", IsAdmin())
async def callback_special_products(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    plans = await _load_all_plans(session)
    if not plans:
        await callback.answer("هنوز سرویسی ثبت نشده است.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        "🎁 <b>مدیریت فروش ویژه</b>\n\nسرویس موردنظر را انتخاب کنید:",
        reply_markup=_special_offer_admin_keyboard(plans),
    )


@router.callback_query(F.data.startswith("special_offer:admin:"), IsAdmin())
async def callback_special_offer_admin_details(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    plan = await ServicePurchasePlan.get(session, int(callback.data.rsplit(":", 1)[1]))
    if not plan:
        await callback.answer("سرویس پیدا نشد.", show_alert=True)
        return

    period = "یک‌ماهه" if plan.service_type == "one_month" else "سه‌ماهه"
    status = "فعال" if plan.is_special_offer and plan.special_offer_price_toman else "غیرفعال"
    special_price = f"{int(plan.special_offer_price_toman):,} تومان" if plan.special_offer_price_toman else "تنظیم نشده"
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        "🎁 <b>فروش ویژه سرویس</b>\n\n"
        f"📦 حجم: <b>{plan.volume_gb} گیگ</b>\n"
        f"📅 مدت: <b>{period}</b>\n"
        f"💰 قیمت اصلی: <b>{plan.price_toman:,} تومان</b>\n"
        f"🔥 قیمت ویژه: <b>{special_price}</b>\n"
        f"📌 وضعیت: <b>{status}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 تعیین قیمت ویژه", callback_data=f"special_offer:set_price:{plan.id}")],
            [InlineKeyboardButton(text="🟢 فعال کردن", callback_data=f"special_offer:enable:{plan.id}")],
            [InlineKeyboardButton(text="🔴 غیرفعال کردن", callback_data=f"special_offer:disable:{plan.id}")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="service_purchase:special_products")],
        ]),
    )


@router.callback_query(F.data.startswith("special_offer:set_price:"), IsAdmin())
async def callback_special_offer_set_price(callback: CallbackQuery, state: FSMContext) -> None:
    plan_id = int(callback.data.rsplit(":", 1)[1])
    await state.clear()
    await state.update_data(special_offer_plan_id=plan_id)
    await state.set_state(SpecialOfferStates.waiting_price)
    await callback.answer()
    await callback.message.edit_text(
        "💰 <b>قیمت فروش ویژه</b>\n\nقیمت جدید را به تومان و فقط به صورت عدد وارد کنید.\nمثلاً: <code>95000</code>"
    )


@router.message(SpecialOfferStates.waiting_price, IsAdmin())
async def message_special_offer_price(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").replace(",", "").replace("٬", "").strip()
    try:
        price = int(raw)
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ قیمت نامعتبر است. مبلغ را به صورت عددی بزرگ‌تر از صفر وارد کنید.")
        return

    data = await state.get_data()
    plan = await ServicePurchasePlan.get(session, int(data["special_offer_plan_id"]))
    if not plan:
        await state.clear()
        await message.answer("❌ سرویس پیدا نشد.")
        return

    plan.special_offer_price_toman = price
    plan.is_special_offer = True
    await session.commit()
    await state.clear()
    await message.answer("✅ فروش ویژه فعال شد و قیمت ویژه ذخیره شد.")


@router.callback_query(F.data.startswith("special_offer:enable:"), IsAdmin())
async def callback_special_offer_enable(callback: CallbackQuery, session: AsyncSession) -> None:
    plan = await ServicePurchasePlan.get(session, int(callback.data.rsplit(":", 1)[1]))
    if not plan or not plan.special_offer_price_toman or plan.special_offer_price_toman <= 0:
        await callback.answer("ابتدا قیمت ویژه را تعیین کنید.", show_alert=True)
        return
    plan.is_special_offer = True
    await session.commit()
    await callback.answer("✅ فروش ویژه فعال شد")
    await callback.message.edit_text(
        "🟢 <b>فروش ویژه فعال است.</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="service_purchase:special_products")]
        ]),
    )


@router.callback_query(F.data.startswith("special_offer:disable:"), IsAdmin())
async def callback_special_offer_disable(callback: CallbackQuery, session: AsyncSession) -> None:
    plan = await ServicePurchasePlan.get(session, int(callback.data.rsplit(":", 1)[1]))
    if not plan:
        await callback.answer("سرویس پیدا نشد.", show_alert=True)
        return
    plan.is_special_offer = False
    await session.commit()
    await callback.answer("🔴 فروش ویژه غیرفعال شد")
    await callback.message.edit_text(
        "🔴 <b>فروش ویژه غیرفعال شد.</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="service_purchase:special_products")]
        ]),
    )
