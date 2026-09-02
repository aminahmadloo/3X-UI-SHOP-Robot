import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import SubscriptionData
from app.bot.routers.subscription.keyboard import service_purchase_plan_keyboard
from app.bot.utils.navigation import NavMain, NavSubscription
from app.db.models import AdvertisingCampaign, AdvertisingEvent, ConnectedDeviceSettings, ServicePeriod, ServicePurchasePlan, User

logger = logging.getLogger(__name__)
router = Router(name=__name__)


def _home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU)]])


async def _show_campaign_purchase(message: Message, session: AsyncSession, user: User, campaign_id: int, period_id: int | None, plan_id: int | None) -> None:
    campaign = await session.get(AdvertisingCampaign, campaign_id)
    if not campaign or not campaign.is_active:
        await message.answer("❌ این تبلیغ دیگر فعال نیست.", reply_markup=_home_keyboard())
        return

    settings = await ConnectedDeviceSettings.get_or_create(session)
    periods = await ServicePeriod.list_active(session)
    period = next((item for item in periods if item.id == period_id), None) if period_id else None
    if period is None:
        period = next((item for item in periods if await ServicePurchasePlan.list_by_type(session, item.service_type)), None)
    if period is None:
        await message.answer("❌ در حال حاضر سرویس قابل خریدی وجود ندارد.", reply_markup=_home_keyboard())
        return

    plans = await ServicePurchasePlan.list_by_type(session, period.service_type)
    if not plans:
        await message.answer("❌ برای این دوره هنوز محصولی فعال نشده است.", reply_markup=_home_keyboard())
        return

    data = SubscriptionData(state=NavSubscription.PLAN, user_id=user.tg_id, devices=settings.max_connected_devices)
    text = f"{campaign.body}\n\n🛒 <b>انتخاب سرویس</b>\nلطفاً سرویس مورد نظر را انتخاب کنید:"
    markup = service_purchase_plan_keyboard(plans, data, period.id)

    # Keep the exact advertised plan at the top when it is still available.
    if plan_id and any(plan.id == plan_id for plan in plans):
        selected = next(plan for plan in plans if plan.id == plan_id)
        rest = [plan for plan in plans if plan.id != plan_id]
        ordered = [selected, *rest]
        markup = service_purchase_plan_keyboard(ordered, data, period.id)

    await message.answer(text, reply_markup=markup)


@router.message(Command(NavMain.START))
async def tracked_ad_start(message: Message, command: CommandObject, user: User, session: AsyncSession, state: FSMContext) -> None:
    args = (command.args or "").strip()
    if not args.startswith("ad_"):
        return

    parts = args.split("_")
    try:
        campaign_id = int(parts[1])
        period_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        plan_id = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
    except (ValueError, IndexError):
        return

    await state.clear()
    unique = await AdvertisingEvent.record_unique(session, campaign_id, user.tg_id, "start", plan_id=plan_id)
    logger.info("Advertising start: campaign=%s user=%s unique=%s", campaign_id, user.tg_id, unique)
    await _show_campaign_purchase(message, session, user, campaign_id, period_id, plan_id)


@router.callback_query(F.data.regexp(r"^ad_click:\d+:\d+:\d+$"))
async def tracked_ad_button(callback: CallbackQuery, user: User, session: AsyncSession) -> None:
    _, campaign_raw, period_raw, plan_raw = callback.data.split(":")
    campaign_id, period_id, plan_id = int(campaign_raw), int(period_raw), int(plan_raw)
    await AdvertisingEvent.record_unique(session, campaign_id, user.tg_id, "button", plan_id=plan_id)
    await callback.answer("در حال انتقال به سرویس...")
    if callback.message:
        await _show_campaign_purchase(callback.message, session, user, campaign_id, period_id, plan_id)
