import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.utils.navigation import NavMain, NavSupport
from app.config import Config
from app.db.models import SupportMessage, SupportTicket, User

from .keyboard import (
    admin_ticket_keyboard,
    contact_keyboard,
    support_keyboard,
    ticket_keyboard,
    training_keyboard,
    training_platform_keyboard,
)

logger = logging.getLogger(__name__)
router = Router(name=__name__)


class SupportStates(StatesGroup):
    waiting_user_message = State()
    waiting_user_reply = State()
    waiting_admin_reply = State()


def _ticket_id(data: str) -> int | None:
    try:
        return int(data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        return None


def _status_text(status: str) -> str:
    return {
        "waiting_support": "🟡 منتظر پاسخ پشتیبانی",
        "waiting_user": "🔵 منتظر پاسخ شما",
        "closed": "⚫ بسته شده",
    }.get(status, "🟢 فعال")


def _ticket_preview(messages: list[SupportMessage]) -> str:
    if not messages:
        return "بدون پیام"
    text = messages[-1].text.replace("\n", " ").strip()
    return text[:90] + ("…" if len(text) > 90 else "")


async def _load_user_ticket(
    session: AsyncSession, ticket_id: int, user: User
) -> SupportTicket | None:
    return await SupportTicket.get_for_user(session, ticket_id, user.id)


async def _conversation(session: AsyncSession, ticket_id: int) -> list[SupportMessage]:
    result = await session.execute(
        select(SupportMessage)
        .where(SupportMessage.ticket_id == ticket_id)
        .order_by(SupportMessage.created_at)
    )
    return list(result.scalars().all())


async def _render_ticket(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    ticket_id: int,
    conversation: bool = False,
) -> None:
    ticket = await _load_user_ticket(session, ticket_id, user)
    if not ticket:
        await callback.answer("❌ تیکت پیدا نشد.", show_alert=True)
        return

    messages = await _conversation(session, ticket_id)
    if conversation:
        lines = [
            f"🎫 <b>مکالمه تیکت #{ticket.id}</b>",
            f"{_status_text(ticket.status)}",
            "",
        ]
        for item in messages[-20:]:
            sender = "👤 شما" if item.sender_type == "user" else "👨‍💻 پشتیبانی"
            lines.append(f"{sender}:\n{item.text[:700]}")
            lines.append("")
        text = "\n".join(lines)[:3900]
    else:
        text = (
            f"🎫 <b>تیکت #{ticket.id}</b>\n\n"
            f"{_status_text(ticket.status)}\n\n"
            f"آخرین پیام:\n{_ticket_preview(messages)}"
        )

    await callback.message.edit_text(
        text=text,
        reply_markup=ticket_keyboard(ticket.id, ticket.status != "closed"),
    )


@router.callback_query(F.data == NavSupport.MAIN)
async def callback_support(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        text=(
            "🎧 <b>مرکز پشتیبانی ToonelVPN</b>\n\n"
            "اگر برای اتصال یا استفاده از سرویس نیاز به راهنمایی داری، "
            "از گزینه‌های زیر استفاده کن.\n\n"
            "📚 آموزش\n"
            "راهنمای کامل اتصال به ToonelVPN\n\n"
            "💬 ارتباط با پشتیبانی\n"
            "ارسال پیام و پیگیری درخواست‌های پشتیبانی"
        ),
        reply_markup=support_keyboard(),
    )


@router.callback_query(F.data == NavSupport.TRAINING)
async def callback_training(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        text=(
            "📚 <b>آموزش اتصال به ToonelVPN</b>\n\n"
            "برای اتصال، برنامه <b>Happ</b> را روی دستگاه خود نصب کنید، "
            "سپس کلید اتصال سرویس را در برنامه وارد کنید.\n\n"
            "👇 سیستم‌عامل خود را انتخاب کنید تا آموزش مرحله‌به‌مرحله نمایش داده شود."
        ),
        reply_markup=training_keyboard(),
    )


@router.callback_query(F.data == NavSupport.TRAINING_ANDROID)
async def callback_training_android(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        text=(
            "🤖 <b>آموزش اتصال در Android</b>\n\n"
            "<b>۱.</b> برنامه Happ را نصب و اجرا کن.\n"
            "<b>۲.</b> از ToonelVPN کلید اتصال سرویس را دریافت کن.\n"
            "<b>۳.</b> کلید را در Happ وارد کن یا روی لینک اتصال سرویس بزن.\n"
            "<b>۴.</b> سرویس را انتخاب و فعال کن.\n"
            "<b>۵.</b> وقتی وضعیت اتصال فعال شد، اینترنت دستگاه از سرویس ToonelVPN عبور می‌کند.\n\n"
            "💡 اگر اتصال برقرار نشد، ابتدا تاریخ و ساعت گوشی را روی حالت خودکار قرار بده و دوباره کلید را وارد کن."
        ),
        reply_markup=training_platform_keyboard("android"),
    )


@router.callback_query(F.data == NavSupport.TRAINING_IOS)
async def callback_training_ios(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        text=(
            "🍎 <b>آموزش اتصال در iPhone / iPad</b>\n\n"
            "<b>۱.</b> برنامه Happ را از App Store نصب کن.\n"
            "<b>۲.</b> برنامه را باز کن.\n"
            "<b>۳.</b> کلید اتصال سرویس ToonelVPN را دریافت کن.\n"
            "<b>۴.</b> لینک اتصال را باز کن تا سرویس به Happ اضافه شود.\n"
            "<b>۵.</b> سرویس را فعال کن و اجازه ایجاد VPN را تأیید کن.\n\n"
            "💡 اگر اتصال برقرار نشد، یک‌بار Happ را ببند و دوباره باز کن و سرویس را مجدداً فعال کن."
        ),
        reply_markup=training_platform_keyboard("ios"),
    )


@router.callback_query(F.data == NavSupport.TRAINING_WINDOWS)
async def callback_training_windows(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        text=(
            "💻 <b>آموزش اتصال در Windows</b>\n\n"
            "<b>۱.</b> برنامه Happ را نصب کن.\n"
            "<b>۲.</b> برنامه را اجرا کن.\n"
            "<b>۳.</b> کلید اتصال ToonelVPN را دریافت کن.\n"
            "<b>۴.</b> لینک اتصال را باز کن تا سرویس به Happ اضافه شود.\n"
            "<b>۵.</b> سرویس را انتخاب و فعال کن.\n\n"
            "💡 برای اولین اتصال، اجازه‌های امنیتی Windows را در صورت نمایش تأیید کن."
        ),
        reply_markup=training_platform_keyboard("windows"),
    )


@router.callback_query(F.data == NavSupport.CONTACT)
async def callback_contact(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        text=(
            "💬 <b>ارتباط با پشتیبانی</b>\n\n"
            "لطفاً پیام خود را ارسال کنید.\n"
            "کارشناس پشتیبانی پس از بررسی به شما پاسخ خواهد داد.\n\n"
            "از این بخش می‌توانی تیکت جدید ایجاد کنی یا تیکت‌های قبلی خود را پیگیری کنی."
        ),
        reply_markup=contact_keyboard(),
    )


@router.callback_query(F.data == NavSupport.SEND_MESSAGE)
async def callback_send_message(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(SupportStates.waiting_user_message)
    await state.update_data(support_return=NavSupport.CONTACT)
    await callback.message.edit_text(
        text=(
            "✏️ <b>ارسال پیام به پشتیبانی</b>\n\n"
            "لطفاً مشکل یا درخواست خود را در یک پیام بنویس و ارسال کن.\n\n"
            "بعد از ارسال، یک تیکت برایت ایجاد می‌شود."
        ),
        reply_markup=None,
    )


@router.message(SupportStates.waiting_user_message)
async def receive_new_ticket(
    message: Message,
    user: User,
    session: AsyncSession,
    config: Config,
    state: FSMContext,
) -> None:
    if not message.text:
        await message.answer("❌ لطفاً پیام متنی خود را ارسال کن.")
        return

    ticket = SupportTicket(user_id=user.id, status="waiting_support")
    session.add(ticket)
    await session.flush()
    session.add(
        SupportMessage(ticket_id=ticket.id, sender_type="user", text=message.text)
    )
    await session.commit()
    await state.clear()

    try:
        username = f"@{user.username}" if user.username else "بدون یوزرنیم"
        await message.bot.send_message(
            chat_id=config.bot.SUPPORT_ID,
            text=(
                f"🎫 <b>تیکت جدید #{ticket.id}</b>\n\n"
                f"👤 {user.first_name}\n"
                f"🔗 {username}\n"
                f"🆔 <code>{user.tg_id}</code>\n\n"
                f"💬 پیام کاربر:\n{message.text[:3000]}"
            ),
            reply_markup=admin_ticket_keyboard(ticket.id),
        )
    except Exception:
        logger.exception("Failed to notify support for ticket %s", ticket.id)

    await message.answer(
        f"✅ <b>تیکت #{ticket.id} با موفقیت ثبت شد.</b>\n\n"
        "کارشناس پشتیبانی پس از بررسی به شما پاسخ خواهد داد.",
        reply_markup=contact_keyboard(),
    )


@router.callback_query(F.data == NavSupport.MY_TICKETS)
async def callback_my_tickets(
    callback: CallbackQuery, user: User, session: AsyncSession
) -> None:
    await callback.answer()
    result = await session.execute(
        select(SupportTicket)
        .where(SupportTicket.user_id == user.id)
        .order_by(desc(SupportTicket.updated_at), desc(SupportTicket.id))
        .limit(20)
    )
    tickets = list(result.scalars().all())

    if not tickets:
        await callback.message.edit_text(
            text="📋 <b>تیکت‌های من</b>\n\nهنوز هیچ تیکتی ثبت نکرده‌ای.",
            reply_markup=contact_keyboard(),
        )
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    for ticket in tickets:
        builder.row(
            __import__("aiogram").types.InlineKeyboardButton(
                text=f"#{ticket.id} — {_status_text(ticket.status)}",
                callback_data=f"{NavSupport.TICKET_VIEW}:{ticket.id}",
            )
        )
    builder.row(__import__("aiogram").types.InlineKeyboardButton(text="🔙 ارتباط با پشتیبانی", callback_data=NavSupport.CONTACT))
    builder.row(__import__("aiogram").types.InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU))

    await callback.message.edit_text(
        text="📋 <b>تیکت‌های من</b>\n\nتیکت موردنظر را انتخاب کن:",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith(NavSupport.TICKET_VIEW))
async def callback_ticket_view(
    callback: CallbackQuery, user: User, session: AsyncSession
) -> None:
    ticket_id = _ticket_id(callback.data)
    if ticket_id is None:
        await callback.answer("❌ شناسه تیکت نامعتبر است.", show_alert=True)
        return
    await callback.answer()
    await _render_ticket(callback, session, user, ticket_id)


@router.callback_query(F.data.startswith(NavSupport.TICKET_CONVERSATION))
async def callback_ticket_conversation(
    callback: CallbackQuery, user: User, session: AsyncSession
) -> None:
    ticket_id = _ticket_id(callback.data)
    if ticket_id is None:
        await callback.answer("❌ شناسه تیکت نامعتبر است.", show_alert=True)
        return
    await callback.answer()
    await _render_ticket(callback, session, user, ticket_id, conversation=True)


@router.callback_query(F.data.startswith(NavSupport.TICKET_REPLY))
async def callback_ticket_reply(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    config: Config,
    state: FSMContext,
) -> None:
    ticket_id = _ticket_id(callback.data)
    if ticket_id is None:
        await callback.answer("❌ شناسه تیکت نامعتبر است.", show_alert=True)
        return

    if callback.from_user.id == config.bot.SUPPORT_ID:
        result = await session.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
        ticket = result.scalar_one_or_none()
        if not ticket or ticket.status == "closed":
            await callback.answer("❌ این تیکت بسته شده یا وجود ندارد.", show_alert=True)
            return
        await state.set_state(SupportStates.waiting_admin_reply)
        await state.update_data(support_ticket_id=ticket_id)
        await callback.answer()
        await callback.message.answer(f"✏️ پاسخ تیکت #{ticket_id} را ارسال کنید.")
        return

    ticket = await _load_user_ticket(session, ticket_id, user)
    if not ticket or ticket.status == "closed":
        await callback.answer("❌ این تیکت بسته شده یا وجود ندارد.", show_alert=True)
        return
    await state.set_state(SupportStates.waiting_user_reply)
    await state.update_data(support_ticket_id=ticket_id)
    await callback.answer()
    await callback.message.answer(f"✏️ پاسخ خود را برای تیکت #{ticket_id} ارسال کن.")


@router.message(SupportStates.waiting_user_reply)
async def receive_user_ticket_reply(
    message: Message,
    user: User,
    session: AsyncSession,
    config: Config,
    state: FSMContext,
) -> None:
    if not message.text:
        await message.answer("❌ لطفاً پیام متنی خود را ارسال کن.")
        return
    data = await state.get_data()
    ticket_id = data.get("support_ticket_id")
    if not isinstance(ticket_id, int):
        await state.clear()
        await message.answer("❌ تیکت انتخاب‌شده معتبر نیست.", reply_markup=contact_keyboard())
        return

    ticket = await _load_user_ticket(session, ticket_id, user)
    if not ticket or ticket.status == "closed":
        await state.clear()
        await message.answer("❌ این تیکت بسته شده است.", reply_markup=contact_keyboard())
        return

    session.add(SupportMessage(ticket_id=ticket.id, sender_type="user", text=message.text))
    ticket.status = "waiting_support"
    await session.commit()
    await state.clear()

    try:
        await message.bot.send_message(
            chat_id=config.bot.SUPPORT_ID,
            text=f"💬 <b>پاسخ جدید در تیکت #{ticket.id}</b>\n\n👤 {user.first_name}\n\n{message.text[:3000]}",
            reply_markup=admin_ticket_keyboard(ticket.id),
        )
    except Exception:
        logger.exception("Failed to notify support about ticket reply %s", ticket.id)

    await message.answer(
        f"✅ پاسخ شما در تیکت #{ticket.id} ثبت شد.",
        reply_markup=contact_keyboard(),
    )


@router.message(SupportStates.waiting_admin_reply)
async def receive_admin_ticket_reply(
    message: Message,
    session: AsyncSession,
    config: Config,
    state: FSMContext,
) -> None:
    if message.from_user is None or message.from_user.id != config.bot.SUPPORT_ID:
        return
    if not message.text:
        await message.answer("❌ لطفاً پاسخ متنی خود را ارسال کنید.")
        return

    data = await state.get_data()
    ticket_id = data.get("support_ticket_id")
    if not isinstance(ticket_id, int):
        await state.clear()
        return

    result = await session.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if not ticket or ticket.status == "closed":
        await state.clear()
        await message.answer("❌ تیکت بسته شده یا وجود ندارد.")
        return

    user_result = await session.execute(select(User).where(User.id == ticket.user_id))
    customer = user_result.scalar_one_or_none()
    if not customer:
        await state.clear()
        await message.answer("❌ کاربر تیکت پیدا نشد.")
        return

    session.add(SupportMessage(ticket_id=ticket.id, sender_type="support", text=message.text))
    ticket.status = "waiting_user"
    await session.commit()
    await state.clear()

    await message.bot.send_message(
        chat_id=customer.tg_id,
        text=f"👨‍💻 <b>پاسخ پشتیبانی — تیکت #{ticket.id}</b>\n\n{message.text[:3500]}",
        reply_markup=ticket_keyboard(ticket.id, True),
    )
    await message.answer(f"✅ پاسخ تیکت #{ticket.id} برای کاربر ارسال شد.")


@router.callback_query(F.data.startswith(NavSupport.TICKET_CLOSE))
async def callback_ticket_close(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    config: Config,
    state: FSMContext,
) -> None:
    ticket_id = _ticket_id(callback.data)
    if ticket_id is None:
        await callback.answer("❌ شناسه تیکت نامعتبر است.", show_alert=True)
        return

    result = await session.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if not ticket:
        await callback.answer("❌ تیکت پیدا نشد.", show_alert=True)
        return

    is_admin = callback.from_user.id == config.bot.SUPPORT_ID
    if not is_admin and ticket.user_id != user.id:
        await callback.answer("❌ دسترسی به این تیکت مجاز نیست.", show_alert=True)
        return

    ticket.status = "closed"
    await session.commit()
    await state.clear()
    await callback.answer("✅ تیکت بسته شد.")

    if is_admin:
        customer_result = await session.execute(select(User).where(User.id == ticket.user_id))
        customer = customer_result.scalar_one_or_none()
        if customer:
            await callback.bot.send_message(
                chat_id=customer.tg_id,
                text=f"🔒 <b>تیکت #{ticket.id} بسته شد.</b>\n\nاگر دوباره به کمک نیاز داشتی، از بخش پشتیبانی یک تیکت جدید ایجاد کن.",
                reply_markup=contact_keyboard(),
            )
        await callback.message.edit_text(f"🔒 <b>تیکت #{ticket.id} بسته شد.</b>")
    else:
        await callback.message.edit_text(
            text=f"🔒 <b>تیکت #{ticket.id} بسته شد.</b>\n\nدر صورت نیاز می‌توانی از بخش ارتباط با پشتیبانی تیکت جدیدی ایجاد کنی.",
            reply_markup=contact_keyboard(),
        )
