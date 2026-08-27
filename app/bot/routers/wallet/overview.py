from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import ServicesContainer
from app.bot.routers.subscription.keyboard import promocode_keyboard
from app.bot.utils.constants import MAIN_MESSAGE_ID_KEY
from app.bot.utils.jalali import format_jalali
from app.bot.utils.navigation import NavMain, NavSubscription
from app.db.models import Subscription, Transaction, User, WalletTransaction

router = Router(name=__name__)


WALLET_TOPUP_MENU = "wallet:topup_menu"
WALLET_TRANSACTIONS = "wallet:transactions"


def wallet_overview_keyboard(language: str = "fa") -> InlineKeyboardMarkup:
    if language == "en":
        topup = "💰 Add balance"
        gift = "🎁 Gift code"
        history = "📜 Transaction history"
        back = "🔙 Back to main menu"
    elif language == "ru":
        topup = "💰 Пополнить баланс"
        gift = "🎁 Подарочный код"
        history = "📜 История транзакций"
        back = "🔙 В главное меню"
    else:
        topup = "💰 افزایش موجودی"
        gift = "🎁 کد هدیه"
        history = "📜 تاریخچه تراکنش‌ها"
        back = "🔙 بازگشت به منوی اصلی"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=topup, callback_data=WALLET_TOPUP_MENU)],
            [InlineKeyboardButton(text=gift, callback_data=NavSubscription.PROMOCODE)],
            [InlineKeyboardButton(text=history, callback_data=WALLET_TRANSACTIONS)],
            [InlineKeyboardButton(text=back, callback_data=NavMain.MAIN_MENU)],
        ]
    )


async def _wallet_overview_text(
    session: AsyncSession,
    services: ServicesContainer,
    user: User,
) -> str:
    balance = await services.wallet.get_balance(user.tg_id)
    now = datetime.utcnow()

    active_services = await session.scalar(
        select(func.count(Subscription.id)).where(
            Subscription.user_id == user.id,
            Subscription.status == "active",
            or_(Subscription.expire_date.is_(None), Subscription.expire_date > now),
        )
    ) or 0

    last_wallet_activity = await session.scalar(
        select(func.max(WalletTransaction.created_at)).where(
            WalletTransaction.user_tg_id == user.tg_id
        )
    )
    last_purchase_activity = await session.scalar(
        select(func.max(Transaction.updated_at)).where(
            Transaction.tg_id == user.tg_id
        )
    )

    last_activity = max(
        [dt for dt in (last_wallet_activity, last_purchase_activity) if dt is not None],
        default=None,
    )

    if user.language_code == "en":
        return (
            "💳 <b>Wallet</b>\n\n"
            f"💰 Balance: <b>{balance:,}</b> Toman\n"
            f"🆔 ID: <code>{user.tg_id}</code>\n"
            f"📦 Active services: {active_services}\n"
            f"🗓 Membership date: {format_jalali(user.created_at)}\n"
            f"📆 Last activity: {format_jalali(last_activity) if last_activity else '-'}"
        )
    if user.language_code == "ru":
        return (
            "💳 <b>Кошелёк</b>\n\n"
            f"💰 Баланс: <b>{balance:,}</b> томан\n"
            f"🆔 ID: <code>{user.tg_id}</code>\n"
            f"📦 Активных сервисов: {active_services}\n"
            f"🗓 Дата регистрации: {format_jalali(user.created_at)}\n"
            f"📆 Последняя активность: {format_jalali(last_activity) if last_activity else '-'}"
        )
    return (
        "💳 <b>کیف پول</b>\n\n"
        f"💰 موجودی: <b>{balance:,}</b> تومان\n"
        f"🆔 آیدی: <code>{user.tg_id}</code>\n"
        f"📦 سرویس‌های فعال: {active_services}\n"
        f"🗓 تاریخ عضویت: {format_jalali(user.created_at)}\n"
        f"📆 آخرین فعالیت: {format_jalali(last_activity) if last_activity else '-'}"
    )


@router.callback_query(F.data == NavMain.WALLET)
async def callback_wallet_overview(
    callback: CallbackQuery,
    user: User,
    services: ServicesContainer,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await callback.answer()
    await state.clear()
    await state.update_data({MAIN_MESSAGE_ID_KEY: callback.message.message_id})
    await callback.message.edit_text(
        text=await _wallet_overview_text(session, services, user),
        reply_markup=wallet_overview_keyboard(user.language_code),
    )


@router.callback_query(F.data == WALLET_TRANSACTIONS)
async def callback_wallet_transactions(
    callback: CallbackQuery,
    user: User,
    services: ServicesContainer,
    state: FSMContext,
) -> None:
    await callback.answer()
    transactions = await services.wallet.get_recent_transactions(user.tg_id, limit=20)

    if user.language_code == "en":
        title = "📜 <b>Wallet transaction history</b>\n\n"
        empty = "No wallet transactions yet."
        back = "🔙 Back to wallet"
    elif user.language_code == "ru":
        title = "📜 <b>История операций кошелька</b>\n\n"
        empty = "Операций по кошельку пока нет."
        back = "🔙 Назад к кошельку"
    else:
        title = "📜 <b>تاریخچه تراکنش‌های کیف پول</b>\n\n"
        empty = "هنوز تراکنشی برای کیف پول ثبت نشده است."
        back = "🔙 بازگشت به کیف پول"

    if not transactions:
        text = title + empty
    else:
        lines = [title]
        for tx in transactions:
            sign = "+" if tx.amount > 0 else ""
            date = format_jalali(tx.created_at)
            description = f" — {tx.description}" if tx.description else ""
            lines.append(
                f"{date} | <b>{sign}{tx.amount:,}</b> تومان | {tx.transaction_type}{description}"
            )
        text = "\n".join(lines)

    await state.update_data({MAIN_MESSAGE_ID_KEY: callback.message.message_id})
    await callback.message.edit_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=back, callback_data=NavMain.WALLET)],
                [InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data=NavMain.MAIN_MENU)],
            ]
        ),
    )
