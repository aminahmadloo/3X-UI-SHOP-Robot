from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import SubscriptionData
from app.bot.routers.custom_service_card_payment import custom_service_payment_card
from app.bot.utils.navigation import NavSubscription
from app.config import Config
from app.db.models import User

router = Router(name=__name__)


@router.callback_query(F.data.regexp(r"^mp_card:\d+$"))
async def managed_card_payment(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    config: Config,
) -> None:
    plan_id = int((callback.data or "").rsplit(":", 1)[1])
    data = await state.get_data()
    packed = data.get("subscription_data")

    if not isinstance(packed, dict):
        await state.clear()
        await callback.answer("❌ اطلاعات سفارش منقضی شده است. لطفاً دوباره پلن را انتخاب کنید.", show_alert=True)
        return

    try:
        subscription_data = SubscriptionData(
            state=NavSubscription.CONFIG_NAME,
            is_extend=packed.get("is_extend", False),
            is_change=packed.get("is_change", False),
            user_id=packed.get("user_id", user.tg_id),
            devices=packed.get("devices", 0),
            duration=packed.get("duration", 0),
            price=packed.get("price", 0),
            plan_id=packed.get("plan_id", 0),
            volume_gb=packed.get("volume_gb", 0),
            config_name=packed.get("config_name", ""),
        )
    except (TypeError, ValueError):
        await state.clear()
        await callback.answer("❌ اطلاعات سفارش نامعتبر است.", show_alert=True)
        return

    if subscription_data.user_id != user.tg_id or subscription_data.plan_id != plan_id:
        await callback.answer("❌ اطلاعات سفارش با پلن انتخاب‌شده مطابقت ندارد.", show_alert=True)
        return

    if subscription_data.price <= 0 or not subscription_data.config_name:
        await callback.answer("❌ اطلاعات مبلغ یا نام کانفیگ سفارش نامعتبر است.", show_alert=True)
        return

    await state.update_data(
        custom_service_subscription=subscription_data.pack(),
        custom_service_total=int(subscription_data.price),
    )
    await custom_service_payment_card(
        callback=callback,
        user=user,
        session=session,
        state=state,
        config=config,
    )
