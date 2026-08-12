import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import ServicesContainer
from app.bot.utils.navigation import NavMain
from app.db.models import User, WalletTopupAmount

from ..main_menu.wallet_keyboard import wallet_keyboard

logger = logging.getLogger(__name__)
router = Router(name=__name__)


def wallet_text(language: str, balance: int, has_amounts: bool) -> str:
    balance_text = f"{balance:,}"

    if language == "en":
        if has_amounts:
            options = "Select a top-up amount below:"
        else:
            options = "No top-up amounts are currently available."
        return (
            "💰 <b>Wallet</b>\n\n"
            f"💳 <b>Balance:</b> {balance_text} Toman\n\n"
            f"{options}"
        )

    if language == "ru":
        if has_amounts:
            options = "Выберите сумму пополнения ниже:"
        else:
            options = "Суммы пополнения пока недоступны."
        return (
            "💰 <b>Кошелёк</b>\n\n"
            f"💳 <b>Баланс:</b> {balance_text} томан\n\n"
            f"{options}"
        )

    if has_amounts:
        options = "مبلغ مورد نظر برای شارژ را انتخاب کنید:"
    else:
        options = "در حال حاضر مبلغی برای شارژ کیف پول تعریف نشده است."
    return (
        "💰 <b>کیف پول</b>\n\n"
        f"💳 <b>موجودی:</b> {balance_text} تومان\n\n"
        f"{options}"
    )


def payment_unavailable_text(language: str) -> str:
    if language == "en":
        return "💳 Online wallet top-up payment is not enabled yet."
    if language == "ru":
        return "💳 Онлайн-пополнение кошелька пока не подключено."
    return "💳 پرداخت آنلاین شارژ کیف پول هنوز فعال نشده است."


@router.callback_query(F.data == NavMain.WALLET)
async def callback_wallet(
    callback: CallbackQuery,
    user: User,
    services: ServicesContainer,
    session: AsyncSession,
) -> None:
    logger.info(f"User {user.tg_id} opened wallet page.")
    await callback.answer()

    balance = await services.wallet.get_balance(user.tg_id)
    amounts = await WalletTopupAmount.get_all(session)

    await callback.message.edit_text(
        text=wallet_text(user.language_code, balance, bool(amounts)),
        reply_markup=wallet_keyboard(amounts, user.language_code),
    )


@router.callback_query(F.data.regexp(r"^wallet:topup:\d+$"))
async def callback_wallet_topup(callback: CallbackQuery, user: User) -> None:
    logger.info(f"User {user.tg_id} selected wallet top-up amount: {callback.data}")
    await callback.answer(payment_unavailable_text(user.language_code), show_alert=True)
