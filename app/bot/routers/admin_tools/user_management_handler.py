import html
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.bot.filters import IsAdmin
from app.bot.models import ServicesContainer
from app.bot.utils.constants import TransactionStatus
from app.bot.utils.jalali import format_jalali
from app.bot.utils.navigation import NavAdminTools
from app.db.models import CardPayment, Subscription, Transaction, User, Wallet, WalletTransaction

logger = logging.getLogger(__name__)
router = Router(name=__name__)

USERS_PER_PAGE = 8
FILTER_LABELS = {
    "all": "همه کاربران",
    "active": "اشتراک فعال",
    "expired": "اشتراک منقضی",
    "buyers": "خریداران",
    "trial": "دارای اکانت تست",
    "wallet": "دارای موجودی کیف پول",
}


class UserManagementStates(StatesGroup):
    search = State()
    wallet_charge_amount = State()
    wallet_charge_confirm = State()


def _filter_rows(filter_name: str) -> list[list[InlineKeyboardButton]]:
    labels = {
        "all": "👥 همه کاربران",
        "active": "🟢 اشتراک فعال",
        "expired": "🔴 منقضی/بدون فعال",
        "buyers": "💳 خریداران موفق",
        "trial": "🎁 دارای اکانت تست",
        "wallet": "💰 دارای موجودی",
    }
    names = ("all", "active", "expired", "buyers", "trial", "wallet")
    buttons = [
        InlineKeyboardButton(
            text=("✅ " if name == filter_name else "") + labels[name],
            callback_data=f"{NavAdminTools.USER_FILTER}:{name}:0",
        )
        for name in names
    ]
    return [buttons[:2], buttons[2:4], buttons[4:6]]


def _filter_condition(name: str):
    now = datetime.now()
    active_sub = exists(select(Subscription.id).where(
        Subscription.user_id == User.id,
        Subscription.status == "active",
        or_(Subscription.expire_date.is_(None), Subscription.expire_date > now),
    ))
    expired_sub = exists(select(Subscription.id).where(
        Subscription.user_id == User.id,
        or_(
            Subscription.status != "active",
            and_(Subscription.expire_date.is_not(None), Subscription.expire_date <= now),
        ),
    ))
    completed_tx = exists(select(Transaction.id).where(
        Transaction.tg_id == User.tg_id,
        Transaction.status == TransactionStatus.COMPLETED,
    ))
    wallet = exists(select(Wallet.id).where(
        Wallet.user_tg_id == User.tg_id,
        Wallet.balance > 0,
    ))
    return {
        "active": active_sub,
        "expired": and_(expired_sub, ~active_sub),
        "buyers": completed_tx,
        "trial": User.is_trial_used.is_(True),
        "wallet": wallet,
    }.get(name)


def _management_keyboard(page: int, total: int, filter_name: str = "all") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🔎 جستجو با ID / Username / نام", callback_data=NavAdminTools.USER_SEARCH)],
        *_filter_rows(filter_name),
    ]
    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"{NavAdminTools.USER_PAGE}:{filter_name}:{page - 1}"))
    if (page + 1) * USERS_PER_PAGE < total:
        navigation.append(InlineKeyboardButton(text="بعدی ➡️", callback_data=f"{NavAdminTools.USER_PAGE}:{filter_name}:{page + 1}"))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _user_list_keyboard(users: list[User], page: int, total: int, filter_name: str) -> InlineKeyboardMarkup:
    rows = []
    for item in users:
        name = html.escape(item.first_name or "بدون نام")
        username = f" @{html.escape(item.username)}" if item.username else ""
        rows.append([InlineKeyboardButton(
            text=f"👤 {name}{username}",
            callback_data=f"{NavAdminTools.USER_DETAILS}:{item.tg_id}:{page}:{filter_name}",
        )])
    rows.append([InlineKeyboardButton(text="🔎 جستجوی کاربر", callback_data=NavAdminTools.USER_SEARCH)])
    rows.extend(_filter_rows(filter_name))
    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"{NavAdminTools.USER_PAGE}:{filter_name}:{page - 1}"))
    if (page + 1) * USERS_PER_PAGE < total:
        navigation.append(InlineKeyboardButton(text="بعدی ➡️", callback_data=f"{NavAdminTools.USER_PAGE}:{filter_name}:{page + 1}"))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_user_list(
    callback: CallbackQuery,
    session: AsyncSession,
    page: int = 0,
    filter_name: str = "all",
    search: str | None = None,
) -> None:
    if filter_name not in FILTER_LABELS:
        filter_name = "all"
    page = max(0, page)

    condition = _filter_condition(filter_name)
    count_query = select(func.count(User.id))
    users_query = select(User).options(selectinload(User.server)).order_by(User.created_at.desc(), User.id.desc())

    if condition is not None:
        count_query = count_query.where(condition)
        users_query = users_query.where(condition)

    if search:
        value = search.strip().lstrip("@")
        search_condition = (
            User.tg_id == int(value)
            if value.isdigit()
            else or_(User.username.ilike(f"%{value}%"), User.first_name.ilike(f"%{value}%"))
        )
        count_query = count_query.where(search_condition)
        users_query = users_query.where(search_condition)

    total = int((await session.execute(count_query)).scalar_one())
    users = list((await session.execute(
        users_query.offset(page * USERS_PER_PAGE).limit(USERS_PER_PAGE)
    )).scalars())

    title = (
        "👥 <b>مدیریت کاربران</b>\n\n"
        f"📊 تعداد: <b>{total:,}</b>\n"
        f"🔖 فیلتر: <b>{FILTER_LABELS[filter_name]}</b>\n"
        f"📄 صفحه: <b>{page + 1}</b>"
    )
    if search:
        title += f"\n🔎 جستجو: <code>{html.escape(search)}</code>"
    if not users:
        title += "\n\n❌ کاربری با این شرایط پیدا نشد."

    await callback.message.edit_text(
        title,
        reply_markup=_user_list_keyboard(users, page, total, filter_name)
        if users else _management_keyboard(page, total, filter_name),
    )


@router.callback_query(F.data == NavAdminTools.USER_EDITOR, IsAdmin())
async def callback_user_editor(callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext) -> None:
    logger.info("Admin %s opened user management.", user.tg_id)
    await state.clear()
    await callback.answer()
    await _show_user_list(callback, session)


@router.callback_query(F.data.startswith(f"{NavAdminTools.USER_PAGE}:"), IsAdmin())
async def callback_user_page(callback: CallbackQuery, session: AsyncSession) -> None:
    _, filter_name, page_raw = callback.data.split(":", 2)
    await callback.answer()
    await _show_user_list(callback, session, page=int(page_raw), filter_name=filter_name)


@router.callback_query(F.data.startswith(f"{NavAdminTools.USER_FILTER}:"), IsAdmin())
async def callback_user_filter(callback: CallbackQuery, session: AsyncSession) -> None:
    _, filter_name, page_raw = callback.data.split(":", 2)
    await callback.answer()
    await _show_user_list(callback, session, page=int(page_raw), filter_name=filter_name)


@router.callback_query(F.data == NavAdminTools.USER_SEARCH, IsAdmin())
async def callback_user_search(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UserManagementStates.search)
    await callback.answer()
    await callback.message.edit_text(
        "🔎 <b>جستجوی کاربر</b>\n\n"
        "می‌توانی با یکی از این موارد جستجو کنی:\n"
        "• 🆔 Telegram ID دقیق\n"
        "• 🔗 Username با یا بدون @\n"
        "• 📛 بخشی از نام کاربر\n\n"
        "مثال: <code>78797797</code> یا <code>@amin</code> یا <code>Ali</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.USER_EDITOR)]
        ]),
    )


@router.message(UserManagementStates.search, IsAdmin())
async def process_user_search(message: Message, session: AsyncSession, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not value:
        await message.answer("❌ عبارت جستجو نمی‌تواند خالی باشد.")
        return
    await state.clear()

    normalized = value.lstrip("@")
    condition = (
        User.tg_id == int(normalized)
        if normalized.isdigit()
        else or_(User.username.ilike(f"%{normalized}%"), User.first_name.ilike(f"%{normalized}%"))
    )
    total = int((await session.execute(select(func.count(User.id)).where(condition))).scalar_one())
    users = list((await session.execute(
        select(User).options(selectinload(User.server))
        .where(condition)
        .order_by(User.created_at.desc(), User.id.desc())
        .limit(USERS_PER_PAGE)
    )).scalars())

    rows = []
    for item in users:
        name = html.escape(item.first_name or "بدون نام")
        username = f" @{html.escape(item.username)}" if item.username else ""
        rows.append([InlineKeyboardButton(
            text=f"👤 {name}{username}",
            callback_data=f"{NavAdminTools.USER_DETAILS}:{item.tg_id}:0:all",
        )])
    rows.append([InlineKeyboardButton(text="🔎 جستجوی دوباره", callback_data=NavAdminTools.USER_SEARCH)])
    rows.append([InlineKeyboardButton(text="🔙 مدیریت کاربران", callback_data=NavAdminTools.USER_EDITOR)])
    await message.answer(
        "👥 <b>نتایج جستجو</b>\n\n"
        f"🔎 <code>{html.escape(value)}</code>\n"
        f"📊 تعداد نتیجه: <b>{total:,}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def _load_user_details(session: AsyncSession, tg_id: int):
    user = await User.get(session=session, tg_id=tg_id)
    if not user:
        return None, [], None, 0, 0
    subscriptions = list((await session.execute(
        select(Subscription)
        .options(selectinload(Subscription.server))
        .where(Subscription.user_id == user.id)
        .order_by(Subscription.created_at.desc(), Subscription.id.desc())
        .limit(8)
    )).scalars())
    wallet = await Wallet.get(session, tg_id)
    transaction_count = int((await session.execute(
        select(func.count(Transaction.id)).where(Transaction.tg_id == tg_id)
    )).scalar_one())
    completed_count = int((await session.execute(
        select(func.count(Transaction.id)).where(Transaction.tg_id == tg_id, Transaction.status == "completed")
    )).scalar_one())
    return user, subscriptions, wallet, transaction_count, completed_count


def _subscription_status(subscription: Subscription) -> str:
    now = datetime.now()
    if subscription.status == "active" and (subscription.expire_date is None or subscription.expire_date > now):
        return "🟢 فعال"
    if subscription.expire_date and subscription.expire_date <= now:
        return "🔴 منقضی"
    return f"⚪ {html.escape(str(subscription.status))}"


def _details_keyboard(tg_id: int, page: int, filter_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💳 سوابق پرداخت", callback_data=f"{NavAdminTools.USER_PAYMENTS}:{tg_id}:{page}:{filter_name}"),
            InlineKeyboardButton(text="💰 گردش کیف پول", callback_data=f"{NavAdminTools.USER_WALLET_LEDGER}:{tg_id}:{page}:{filter_name}"),
        ],
        [InlineKeyboardButton(text="⚙️ عملیات مدیریتی", callback_data=f"{NavAdminTools.USER_MANAGE}:{tg_id}:{page}:{filter_name}")],
        [InlineKeyboardButton(text="👤 مشاهده پروفایل تلگرام", url=f"tg://user?id={tg_id}")],
        [InlineKeyboardButton(text="🔄 بروزرسانی اطلاعات تلگرام", callback_data=f"{NavAdminTools.USER_REFRESH}:{tg_id}:{page}:{filter_name}")],
        [InlineKeyboardButton(text="🔙 بازگشت به لیست", callback_data=f"{NavAdminTools.USER_PAGE}:{filter_name}:{page}")],
    ])


def _user_details_text(user: User, subscriptions: list[Subscription], wallet: Wallet | None, transaction_count: int, completed_count: int) -> str:
    full_name = html.escape(user.first_name or "بدون نام")
    username = f"@{html.escape(user.username)}" if user.username else "ندارد"
    server = html.escape(user.server.name) if user.server else "تعیین نشده"
    wallet_balance = wallet.balance if wallet else 0
    now = datetime.now()
    active_count = sum(1 for item in subscriptions if item.status == "active" and (item.expire_date is None or item.expire_date > now))
    expired_count = sum(1 for item in subscriptions if item.expire_date and item.expire_date <= now)

    lines = [
        "👤 <b>جزئیات کاربر</b>", "",
        f"🆔 Telegram ID: <code>{user.tg_id}</code>",
        f"📛 نام: <b>{full_name}</b>",
        f"🔗 Username: <b>{username}</b>",
        f"🌐 زبان: <code>{html.escape(user.language_code or '-')}</code>",
        f"🖥 سرور پیش‌فرض: <b>{server}</b>",
        f"🎁 اکانت تست: <b>{'دریافت شده' if user.is_trial_used else 'دریافت نشده'}</b>",
        f"💰 موجودی کیف پول: <b>{wallet_balance:,} تومان</b>",
        f"💳 تراکنش‌ها: <b>{transaction_count:,}</b> (موفق: {completed_count:,})",
        f"📅 ثبت‌نام: <b>{format_jalali(user.created_at)}</b>", "",
        "📦 <b>اشتراک‌ها</b>",
        f"🟢 فعال: {active_count} | 🔴 منقضی: {expired_count}",
    ]
    if not subscriptions:
        lines.append("• هیچ اشتراکی ثبت نشده است.")
    else:
        for item in subscriptions:
            expire = format_jalali(item.expire_date) if item.expire_date else "بدون تاریخ انقضا"
            server_name = html.escape(item.server.name) if item.server else "نامشخص"
            lines.append(
                f"• #{item.id} | {item.volume_gb}GB / {item.duration_days}روز | "
                f"{_subscription_status(item)} | سرور: {server_name} | انقضا: {expire}"
            )
    return "\n".join(lines)



def _user_back_keyboard(tg_id: int, page: int, filter_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 بازگشت به جزئیات کاربر", callback_data=f"{NavAdminTools.USER_DETAILS}:{tg_id}:{page}:{filter_name}")],
        [InlineKeyboardButton(text="🔙 بازگشت به لیست", callback_data=f"{NavAdminTools.USER_PAGE}:{filter_name}:{page}")],
    ])


def _status_label(status: object) -> str:
    value = getattr(status, "value", status)
    return {
        "completed": "✅ موفق",
        "pending": "⏳ در انتظار",
        "canceled": "❌ لغو شده",
        "cancelled": "❌ لغو شده",
        "failed": "⚠️ ناموفق",
    }.get(str(value), html.escape(str(value)))


@router.callback_query(F.data.startswith(f"{NavAdminTools.USER_PAYMENTS}:"), IsAdmin())
async def callback_user_payments(callback: CallbackQuery, session: AsyncSession) -> None:
    _, tg_id_raw, page_raw, filter_name = callback.data.split(":", 3)
    tg_id = int(tg_id_raw)
    transactions = list((await session.execute(
        select(Transaction)
        .where(Transaction.tg_id == tg_id)
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .limit(10)
    )).scalars())
    card_payments = list((await session.execute(
        select(CardPayment)
        .where(CardPayment.user_tg_id == tg_id)
        .order_by(CardPayment.created_at.desc(), CardPayment.id.desc())
        .limit(10)
    )).scalars())

    lines = ["💳 <b>سوابق پرداخت کاربر</b>", "", f"🆔 <code>{tg_id}</code>"]
    if not transactions and not card_payments:
        lines.append("❌ سابقه پرداختی ثبت نشده است.")
    if transactions:
        lines.append("\n🌐 <b>تراکنش‌های درگاه</b>")
        for item in transactions:
            created = format_jalali(item.created_at) if item.created_at else "-"
            gateway = html.escape(item.gateway or "نامشخص")
            plan = html.escape(item.subscription or "-")
            lines.append(
                f"• #{item.id} | {gateway} | {_status_label(item.status)}\n"
                f"  🧾 <code>{html.escape(item.payment_id)}</code> | {plan} | {created}"
            )
    if card_payments:
        lines.append("\n💳 <b>پرداخت‌های کارت‌به‌کارت</b>")
        for item in card_payments:
            created = format_jalali(item.created_at) if item.created_at else "-"
            tracking = html.escape(item.tracking_code or f"#{item.id}")
            lines.append(
                f"• #{item.id} | {item.amount:,} تومان | {_status_label(item.status)}\n"
                f"  🧾 <code>{tracking}</code> | {html.escape(item.payment_type)} | {created}"
            )

    await callback.answer()
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=_user_back_keyboard(tg_id, int(page_raw), filter_name),
    )


@router.callback_query(F.data.startswith(f"{NavAdminTools.USER_WALLET_LEDGER}:"), IsAdmin())
async def callback_user_wallet_ledger(callback: CallbackQuery, session: AsyncSession) -> None:
    _, tg_id_raw, page_raw, filter_name = callback.data.split(":", 3)
    tg_id = int(tg_id_raw)
    wallet = await Wallet.get(session, tg_id)
    entries = list((await session.execute(
        select(WalletTransaction)
        .where(WalletTransaction.user_tg_id == tg_id)
        .order_by(WalletTransaction.created_at.desc(), WalletTransaction.id.desc())
        .limit(15)
    )).scalars())

    balance = wallet.balance if wallet else 0
    lines = [
        "💰 <b>گردش کیف پول کاربر</b>", "",
        f"🆔 <code>{tg_id}</code>",
        f"💳 موجودی فعلی: <b>{balance:,} تومان</b>",
    ]
    if not entries:
        lines.append("\n❌ گردش مالی کیف پول ثبت نشده است.")
    else:
        lines.append("\n📒 <b>آخرین تراکنش‌ها</b>")
        for item in entries:
            created = format_jalali(item.created_at) if item.created_at else "-"
            amount = f"+{item.amount:,}" if item.amount > 0 else f"{item.amount:,}"
            description = html.escape(item.description or item.transaction_type)
            lines.append(
                f"• <b>{amount} تومان</b> | {html.escape(item.transaction_type)} | {created}\n"
                f"  {description}"
            )

    await callback.answer()
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=_user_back_keyboard(tg_id, int(page_raw), filter_name),
    )


@router.callback_query(F.data.startswith(f"{NavAdminTools.USER_MANAGE}:"), IsAdmin())
async def callback_user_manage(callback: CallbackQuery, session: AsyncSession) -> None:
    _, tg_id_raw, page_raw, filter_name = callback.data.split(":", 3)
    tg_id = int(tg_id_raw)
    target = await User.get(session=session, tg_id=tg_id)
    if not target:
        await callback.answer("کاربر پیدا نشد.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        "⚙️ <b>عملیات مدیریتی کاربر</b>\n\n"
        f"🆔 <code>{tg_id}</code>\n"
        f"👤 {html.escape(target.first_name or 'بدون نام')}\n\n"
        "عملیات فعلی عمداً محدود و کنترل‌شده هستند:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 شارژ دستی کیف پول", callback_data=f"{NavAdminTools.USER_MANAGE_CHARGE}:{tg_id}:{page_raw}:{filter_name}")],
            [InlineKeyboardButton(text="🔄 بروزرسانی اطلاعات تلگرام", callback_data=f"{NavAdminTools.USER_REFRESH}:{tg_id}:{page_raw}:{filter_name}")],
            [InlineKeyboardButton(text="🔙 بازگشت به جزئیات", callback_data=f"{NavAdminTools.USER_DETAILS}:{tg_id}:{page_raw}:{filter_name}")],
        ]),
    )


@router.callback_query(F.data.startswith(f"{NavAdminTools.USER_MANAGE_CHARGE}:"), IsAdmin())
async def callback_user_manage_charge(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    _, tg_id_raw, page_raw, filter_name = callback.data.split(":", 3)
    tg_id = int(tg_id_raw)
    target = await User.get(session=session, tg_id=tg_id)
    if not target:
        await callback.answer("کاربر پیدا نشد.", show_alert=True)
        return
    await state.clear()
    await state.update_data(wallet_charge_user_id=tg_id, wallet_charge_page=int(page_raw), wallet_charge_filter=filter_name)
    await state.set_state(UserManagementStates.wallet_charge_amount)
    await callback.answer()
    await callback.message.edit_text(
        "💰 <b>شارژ دستی کیف پول</b>\n\n"
        f"👤 کاربر: <code>{tg_id}</code>\n"
        "مبلغ شارژ را به تومان وارد کنید.\n"
        "پس از ورود مبلغ، مرحله تأیید نهایی نمایش داده می‌شود.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ انصراف", callback_data=NavAdminTools.USER_MANAGE_CHARGE_CANCEL)]
        ]),
    )


@router.message(UserManagementStates.wallet_charge_amount, IsAdmin())
async def process_user_wallet_charge_amount(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ مبلغ نامعتبر است. فقط یک عدد مثبت به تومان وارد کنید.")
        return
    data = await state.get_data()
    amount = int(raw)
    await state.update_data(wallet_charge_amount=amount)
    await state.set_state(UserManagementStates.wallet_charge_confirm)
    await message.answer(
        "⚠️ <b>تأیید شارژ کیف پول</b>\n\n"
        f"👤 کاربر: <code>{data['wallet_charge_user_id']}</code>\n"
        f"💰 مبلغ: <b>{amount:,} تومان</b>\n\n"
        "با تأیید، مبلغ واقعاً به کیف پول کاربر اضافه می‌شود.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ تأیید و شارژ", callback_data=NavAdminTools.USER_MANAGE_CHARGE_CONFIRM)],
            [InlineKeyboardButton(text="❌ لغو", callback_data=NavAdminTools.USER_MANAGE_CHARGE_CANCEL)],
        ]),
    )


@router.callback_query(F.data == NavAdminTools.USER_MANAGE_CHARGE_CONFIRM, IsAdmin())
async def callback_user_wallet_charge_confirm(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    data = await state.get_data()
    target_id = data.get("wallet_charge_user_id")
    amount = data.get("wallet_charge_amount")
    page = int(data.get("wallet_charge_page", 0))
    filter_name = data.get("wallet_charge_filter", "all")
    if not target_id or not amount or int(amount) <= 0:
        await state.clear()
        await callback.answer("اطلاعات شارژ منقضی شده است.", show_alert=True)
        return

    target = await User.get(session=session, tg_id=int(target_id))
    if not target:
        await state.clear()
        await callback.answer("کاربر پیدا نشد.", show_alert=True)
        return

    try:
        balance = await services.wallet.credit(
            user_tg_id=int(target_id),
            amount=int(amount),
            transaction_type="admin_manual_topup",
            description=f"شارژ دستی توسط مدیر {user.tg_id}",
            reference_id=f"admin_manual_topup:{user.tg_id}:{target_id}:{callback.id}",
        )
    except Exception as exc:
        logger.exception("Admin wallet credit failed for target %s: %s", target_id, exc)
        await callback.answer("❌ شارژ انجام نشد.", show_alert=True)
        return

    await state.clear()
    await callback.answer("✅ کیف پول شارژ شد.")
    await callback.message.edit_text(
        f"✅ <b>شارژ با موفقیت انجام شد</b>\n\n"
        f"👤 کاربر: <code>{target_id}</code>\n"
        f"💰 مبلغ: <b>{int(amount):,} تومان</b>\n"
        f"💳 موجودی جدید: <b>{balance:,} تومان</b>\n"
        f"👨‍💼 مدیر: <code>{user.tg_id}</code>",
        reply_markup=_details_keyboard(int(target_id), page, filter_name),
    )


@router.callback_query(F.data == NavAdminTools.USER_MANAGE_CHARGE_CANCEL, IsAdmin())
async def callback_user_wallet_charge_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    target_id = data.get("wallet_charge_user_id")
    page = int(data.get("wallet_charge_page", 0))
    filter_name = data.get("wallet_charge_filter", "all")
    await state.clear()
    await callback.answer("عملیات لغو شد.")
    if target_id:
        await callback.message.edit_text(
            "⚙️ <b>عملیات مدیریتی کاربر</b>\n\n"
            f"🆔 <code>{target_id}</code>\n"
            "عملیات لغو شد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💰 شارژ دستی کیف پول", callback_data=f"{NavAdminTools.USER_MANAGE_CHARGE}:{target_id}:{page}:{filter_name}")],
                [InlineKeyboardButton(text="🔙 بازگشت به جزئیات", callback_data=f"{NavAdminTools.USER_DETAILS}:{target_id}:{page}:{filter_name}")],
            ]),
        )
    else:
        await callback.message.edit_text("❌ عملیات لغو شد.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 مدیریت کاربران", callback_data=NavAdminTools.USER_EDITOR)]
        ]))

@router.callback_query(F.data.startswith(f"{NavAdminTools.USER_DETAILS}:"), IsAdmin())
async def callback_user_details(callback: CallbackQuery, session: AsyncSession) -> None:
    _, tg_id_raw, page_raw, filter_name = callback.data.split(":", 3)
    tg_id = int(tg_id_raw)
    page = int(page_raw)
    user, subscriptions, wallet, transaction_count, completed_count = await _load_user_details(session, tg_id)
    if not user:
        await callback.answer("کاربر پیدا نشد.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        _user_details_text(user, subscriptions, wallet, transaction_count, completed_count),
        reply_markup=_details_keyboard(tg_id, page, filter_name),
    )


@router.callback_query(F.data.startswith(f"{NavAdminTools.USER_REFRESH}:"), IsAdmin())
async def callback_user_refresh(callback: CallbackQuery, session: AsyncSession) -> None:
    _, tg_id_raw, page_raw, filter_name = callback.data.split(":", 3)
    tg_id = int(tg_id_raw)
    page = int(page_raw)

    user = await User.get(session=session, tg_id=tg_id)
    if not user:
        await callback.answer("کاربر پیدا نشد.", show_alert=True)
        return

    try:
        chat = await callback.bot.get_chat(tg_id)
        user.first_name = chat.first_name or user.first_name
        user.username = chat.username
        await session.commit()
        await callback.answer("اطلاعات تلگرام بروزرسانی شد.")
    except Exception as exc:
        logger.warning("Failed to refresh Telegram user %s: %s", tg_id, exc)
        await callback.answer("اطلاعات تلگرام قابل دریافت نبود؛ اطلاعات ذخیره‌شده نمایش داده می‌شود.", show_alert=True)

    user, subscriptions, wallet, transaction_count, completed_count = await _load_user_details(session, tg_id)
    if user:
        await callback.message.edit_text(
            _user_details_text(user, subscriptions, wallet, transaction_count, completed_count),
            reply_markup=_details_keyboard(tg_id, page, filter_name),
        )
