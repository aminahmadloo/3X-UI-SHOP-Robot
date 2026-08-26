from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import SubscriptionData
from app.bot.payment_gateways import GatewayFactory
from app.bot.routers.wallet.handler import has_pending_payment
from app.bot.utils.navigation import NavMain, NavSubscription
from app.db.models import User

router = Router(name=__name__)


@router.callback_query(F.data.regexp(r"^wallet:method:gateway:\d+$"))
async def callback_wallet_payment_gateway(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    gateway_factory: GatewayFactory,
) -> None:
    amount = int((callback.data or "").rsplit(":", 1)[1])

    if amount <= 0:
        await state.clear()
        await callback.answer("❌ مبلغ پرداخت معتبر نیست.", show_alert=True)
        return

    if await has_pending_payment(session, user.tg_id):
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً ابتدا همان درخواست را تعیین تکلیف کنید.", show_alert=True)
        return

    data = SubscriptionData(
        state=NavSubscription.CONFIG_NAME,
        is_extend=False,
        is_change=False,
        user_id=user.tg_id,
        devices=0,
        duration=0,
        price=amount,
        plan_id=0,
        volume_gb=0,
        config_name="wallet_topup",
        payment_kind="wallet_topup",
    )

    try:
        gateway = gateway_factory.get_gateway(NavSubscription.PAY_ZARINPAL.value)
        pay_url = await gateway.create_payment(data)
    except Exception:
        await callback.answer("❌ ایجاد لینک پرداخت شارژ کیف پول انجام نشد. لطفاً دوباره تلاش کنید.", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text(
        "🏦 <b>شارژ کیف پول</b>\n\n"
        f"💰 مبلغ شارژ: <b>{amount:,} تومان</b>\n\n"
        "برای تکمیل پرداخت روی دکمه زیر بزنید:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💳 پرداخت در زرین‌پال", url=pay_url)],
                [InlineKeyboardButton(text="🔙 تغییر روش پرداخت", callback_data=NavMain.WALLET)],
            ]
        ),
    )
