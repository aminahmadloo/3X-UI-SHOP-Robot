import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.bot.utils.constants import MAIN_MESSAGE_ID_KEY
from app.bot.utils.navigation import NavMain

logger = logging.getLogger(__name__)
router = Router(name=__name__)

# Temporary defaults. These will move to the admin-managed wallet settings
# when the payment/admin stage is implemented.
WALLET_PRESET_AMOUNTS: tuple[int, ...] = (100_000, 250_000, 500_000, 1_000_000)
MIN_CUSTOM_AMOUNT = 10_000
MAX_CUSTOM_AMOUNT = 50_000_000


class WalletStates(StatesGroup):
    custom_amount = State()


def _money(amount: int) -> str:
    return f"{amount:,}".replace(",", "٬")


def wallet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 شارژ کیف پول", callback_data=NavMain.WALLET_TOPUP)],
            [InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data=NavMain.MAIN_MENU)],
        ]
    )


def topup_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index in range(0, len(WALLET_PRESET_AMOUNTS), 2):
        row = []
        for amount in WALLET_PRESET_AMOUNTS[index : index + 2]:
            row.append(
                InlineKeyboardButton(
                    text=f"💳 {_money(amount)} تومان",
                    callback_data=f"wallet:amount:{amount}",
                )
            )
        rows.append(row)

    rows.append(
        [InlineKeyboardButton(text="✏️ مبلغ دلخواه", callback_data=NavMain.WALLET_CUSTOM)]
    )
    rows.append(
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavMain.WALLET)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_wallet(callback: CallbackQuery, user: User) -> None:
    balance = user.wallet_balance or 0
    text = (
        "🧾 <b>کیف پول</b>\n\n"
        "در این بخش می‌توانید موجودی کیف پول خود را مشاهده کنید و "
        "در صورت نیاز آن را برای پرداخت‌های بعدی شارژ نمایید. 💎\n\n"
        f"💰 <b>موجودی کیف پول شما:</b> {_money(balance)} تومان"
    )
    await callback.message.edit_text(text=text, reply_markup=wallet_keyboard())


@router.callback_query(F.data == NavMain.WALLET)
async def callback_wallet(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await state.update_data({MAIN_MESSAGE_ID_KEY: callback.message.message_id})
    await _show_wallet(callback, user)


@router.callback_query(F.data == NavMain.WALLET_TOPUP)
async def callback_wallet_topup(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await state.update_data({MAIN_MESSAGE_ID_KEY: callback.message.message_id})
    await callback.message.edit_text(
        text="💳 <b>مبلغ شارژ کیف پول را انتخاب کنید:</b>\n\n"
        "یا می‌توانید مبلغ دلخواه خود را وارد کنید.",
        reply_markup=topup_keyboard(),
    )


@router.callback_query(F.data.startswith("wallet:amount:"))
async def callback_wallet_amount(callback: CallbackQuery, state: FSMContext) -> None:
    amount = int(callback.data.rsplit(":", 1)[1])
    if amount not in WALLET_PRESET_AMOUNTS:
        await callback.answer("مبلغ نامعتبر است.", show_alert=True)
        return

    await state.update_data(wallet_amount=amount)
    await callback.answer()
    await callback.message.edit_text(
        text=(
            "لینک پرداخت برای شما ساخته شد ✅\n\n"
            "جهت پرداخت بر روی دکمه زیر کلیک کنید 👇\n"
            "و پرداخت را انجام دهید.\n\n"
            "حتما با وی‌پی‌ان خاموش وارد درگاه پرداخت شوید.\n\n"
            f"💳 مبلغ درخواستی: <b>{_money(amount)} تومان</b>\n\n"
            "⚠️ اتصال درگاه پرداخت در مرحله بعدی این بخش انجام می‌شود."
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"💳 شارژ {_money(amount)} تومان", callback_data=f"wallet:pay:{amount}")],
                [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavMain.WALLET_TOPUP)],
            ]
        ),
    )


@router.callback_query(F.data == NavMain.WALLET_CUSTOM)
async def callback_wallet_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(WalletStates.custom_amount)
    await state.update_data({MAIN_MESSAGE_ID_KEY: callback.message.message_id})
    await callback.message.edit_text(
        text=(
            "✏️ <b>مبلغ دلخواه را به تومان وارد کنید.</b>\n\n"
            f"حداقل: {_money(MIN_CUSTOM_AMOUNT)} تومان\n"
            f"حداکثر: {_money(MAX_CUSTOM_AMOUNT)} تومان"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavMain.WALLET_TOPUP)]
            ]
        ),
    )


@router.message(WalletStates.custom_amount)
async def handle_wallet_custom_amount(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip().replace(",", "").replace("٬", "").replace(" ", "")
    if not raw.isdigit():
        await message.answer("❌ لطفاً فقط مبلغ را به عدد وارد کنید.")
        return

    amount = int(raw)
    if not MIN_CUSTOM_AMOUNT <= amount <= MAX_CUSTOM_AMOUNT:
        await message.answer(
            f"❌ مبلغ باید بین {_money(MIN_CUSTOM_AMOUNT)} تا {_money(MAX_CUSTOM_AMOUNT)} تومان باشد."
        )
        return

    await state.update_data(wallet_amount=amount)
    await state.clear()
    await message.answer(
        "لینک پرداخت برای شما ساخته شد ✅\n\n"
        "جهت پرداخت بر روی دکمه زیر کلیک کنید 👇\n"
        "و پرداخت را انجام دهید.\n\n"
        "حتما با وی‌پی‌ان خاموش وارد درگاه پرداخت شوید.\n\n"
        f"💳 مبلغ درخواستی: <b>{_money(amount)} تومان</b>\n\n"
        "⚠️ اتصال درگاه پرداخت در مرحله بعدی این بخش انجام می‌شود."
    )


@router.callback_query(F.data.startswith("wallet:pay:"))
async def callback_wallet_pay(callback: CallbackQuery) -> None:
    await callback.answer(
        "درگاه پرداخت هنوز به کیف پول متصل نشده است. این مرحله را بعد از بررسی InstaHolo تکمیل می‌کنیم.",
        show_alert=True,
    )
