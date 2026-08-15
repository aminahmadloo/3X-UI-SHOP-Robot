import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.filters import IsAdmin
from app.bot.models import ServicesContainer
from app.bot.utils.navigation import NavAdminTools
from app.db.models import CardPayment, User

logger = logging.getLogger(__name__)
router = Router(name=__name__)


class ManualWalletChargeState(StatesGroup):
    waiting_user_id = State()
    waiting_amount = State()


@router.callback_query(F.data == "cardpay:menu", IsAdmin())
async def card_payment_menu(callback: CallbackQuery, session) -> None:
    pending = await CardPayment.get_pending(session)
    if not pending:
        text = "💳 <b>پرداخت‌های کارت به کارت</b>\n\nدر حال حاضر درخواست در انتظار بررسی وجود ندارد."
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 شارژ دستی کیف پول", callback_data="wallet_manual_charge")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)],
        ])
    else:
        text = "💳 <b>پرداخت‌های در انتظار بررسی</b>\n\n" + "\n".join(
            f"{p.tracking_code or f'#{p.id}'} — <code>{p.user_tg_id}</code> — <b>{p.amount:,} تومان</b>" for p in pending
        )
        rows = [[InlineKeyboardButton(text=f"🔎 {p.tracking_code or f'درخواست #{p.id}'}", callback_data=f"cardpay:view:{p.id}")] for p in pending]
        rows += [
            [InlineKeyboardButton(text="💰 شارژ دستی کیف پول", callback_data="wallet_manual_charge")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)],
        ]
        markup = InlineKeyboardMarkup(inline_keyboard=rows)
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=markup)


@router.callback_query(F.data.regexp(r"^cardpay:view:\d+$"), IsAdmin())
async def card_payment_view(callback: CallbackQuery, session) -> None:
    payment_id = int(callback.data.rsplit(":", 1)[1])
    payment = await CardPayment.get(session, payment_id)
    if not payment:
        await callback.answer("❌ درخواست پیدا نشد.", show_alert=True)
        return
    await callback.answer()
    await callback.message.bot.send_photo(
        callback.from_user.id,
        payment.receipt_file_id,
        caption=(
            f"💳 <b>درخواست کارت به کارت</b>\n\n"
            f"🆔 کد پیگیری: <code>{payment.tracking_code or f'#{payment.id}'}</code>\n"
            f"👤 آیدی تلگرام پرداخت‌کننده: <code>{payment.user_tg_id}</code>\n"
            f"💰 مبلغ: <b>{payment.amount:,} تومان</b>\n"
            f"🧾 شماره درخواست داخلی: <code>#{payment.id}</code>\n"
            f"📌 وضعیت: <b>{payment.status}</b>"
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ تأیید و شارژ کیف پول", callback_data=f"cardpay:approve:{payment.id}")],
            [InlineKeyboardButton(text="❌ رد پرداخت", callback_data=f"cardpay:reject:{payment.id}")],
        ]),
    )


@router.callback_query(F.data.regexp(r"^cardpay:approve:\d+$"), IsAdmin())
async def approve_card_payment(callback: CallbackQuery, user: User, services: ServicesContainer, session, bot) -> None:
    payment_id = int(callback.data.rsplit(":", 1)[1])
    payment = await CardPayment.get(session, payment_id)
    if not payment:
        await callback.answer("❌ درخواست پیدا نشد.", show_alert=True)
        return
    if payment.status != "pending":
        await callback.answer("⚠️ این درخواست قبلاً بررسی شده است.", show_alert=True)
        return

    payment.status = "approved"
    payment.admin_tg_id = user.tg_id
    payment.reviewed_at = datetime.now()
    await session.commit()
    try:
        balance = await services.wallet.credit(
            user_tg_id=payment.user_tg_id,
            amount=payment.amount,
            transaction_type="card_topup",
            description=f"کارت به کارت - کد پیگیری {payment.tracking_code or payment.id}",
            reference_id=f"card_payment:{payment.id}",
        )
    except Exception as exc:
        payment.status = "pending"
        payment.admin_tg_id = None
        payment.reviewed_at = None
        await session.commit()
        logger.exception("Failed to credit card payment %s: %s", payment.id, exc)
        await callback.answer("❌ شارژ کیف پول انجام نشد و درخواست به حالت بررسی برگشت.", show_alert=True)
        return

    await callback.answer("✅ پرداخت تأیید و کیف پول شارژ شد.", show_alert=True)
    if callback.message.photo:
        await callback.message.edit_caption(caption=(callback.message.caption or "") + f"\n\n✅ <b>تأیید شد</b> توسط <code>{user.tg_id}</code>\n💰 موجودی جدید: <b>{balance:,} تومان</b>")
    try:
        await bot.send_message(payment.user_tg_id, f"✅ <b>پرداخت شما تأیید شد.</b>\n\n🆔 کد پیگیری: <code>{payment.tracking_code or payment.id}</code>\n💰 مبلغ <b>{payment.amount:,} تومان</b> به کیف پول شما اضافه شد.\n💳 موجودی جدید: <b>{balance:,} تومان</b>")
    except Exception:
        logger.exception("Failed to notify user %s", payment.user_tg_id)


@router.callback_query(F.data.regexp(r"^cardpay:reject:\d+$"), IsAdmin())
async def reject_card_payment(callback: CallbackQuery, user: User, session, bot) -> None:
    payment_id = int(callback.data.rsplit(":", 1)[1])
    payment = await CardPayment.get(session, payment_id)
    if not payment:
        await callback.answer("❌ درخواست پیدا نشد.", show_alert=True)
        return
    if payment.status != "pending":
        await callback.answer("⚠️ این درخواست قبلاً بررسی شده است.", show_alert=True)
        return
    payment.status = "rejected"
    payment.admin_tg_id = user.tg_id
    payment.reviewed_at = datetime.now()
    await session.commit()
    await callback.answer("❌ پرداخت رد شد.", show_alert=True)
    if callback.message.photo:
        await callback.message.edit_caption(caption=(callback.message.caption or "") + f"\n\n❌ <b>رد شد</b> توسط <code>{user.tg_id}</code>")
    try:
        await bot.send_message(payment.user_tg_id, f"❌ <b>پرداخت شما تأیید نشد.</b>\n\n🆔 کد پیگیری: <code>{payment.tracking_code or payment.id}</code>\nرسید پرداخت شما توسط مدیریت تأیید نشد. در صورت اشتباه، با پشتیبانی تماس بگیرید.")
    except Exception:
        logger.exception("Failed to notify user %s", payment.user_tg_id)


MANUAL_CHARGE = "wallet_manual_charge"


@router.callback_query(F.data == MANUAL_CHARGE, IsAdmin())
async def manual_charge_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ManualWalletChargeState.waiting_user_id)
    await callback.message.edit_text("💰 <b>شارژ دستی کیف پول</b>\n\nآیدی عددی تلگرام کاربر را وارد کنید:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)]]))


@router.message(ManualWalletChargeState.waiting_user_id, IsAdmin())
async def manual_charge_user(message: Message, state: FSMContext, session) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("❌ آیدی تلگرام باید عددی باشد.")
        return
    target = await session.get(User, int(raw))
    if not target:
        await message.answer("❌ کاربری با این آیدی در ربات پیدا نشد.")
        return
    await state.update_data(manual_user_id=int(raw))
    await state.set_state(ManualWalletChargeState.waiting_amount)
    await message.answer("💰 مبلغ شارژ را به تومان وارد کنید.\nمثال: <code>500000</code>")


@router.message(ManualWalletChargeState.waiting_amount, IsAdmin())
async def manual_charge_amount(message: Message, user: User, state: FSMContext, services: ServicesContainer) -> None:
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ مبلغ نامعتبر است.")
        return
    data = await state.get_data()
    target = int(data["manual_user_id"])
    amount = int(raw)
    balance = await services.wallet.credit(user_tg_id=target, amount=amount, transaction_type="manual_topup", description=f"شارژ دستی توسط مدیر {user.tg_id}", reference_id=f"manual_topup:{user.tg_id}:{target}:{message.message_id}")
    await state.clear()
    await message.answer(f"✅ کیف پول کاربر <code>{target}</code> شارژ شد.\n\n💰 مبلغ: <b>{amount:,} تومان</b>\n💳 موجودی جدید: <b>{balance:,} تومان</b>")
