import html
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.i18n import gettext as _
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.utils.jalali import format_jalali
from app.bot.utils.navigation import NavAdminTools
from app.db.models import Subscription, Transaction, User, Wallet

logger = logging.getLogger(__name__)
router = Router(name=__name__)

USERS_PER_PAGE = 8


class UserManagementStates(StatesGroup):
    search = State()


def _page_keyboard(page: int, total: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="🔎 جستجوی کاربر",
                callback_data=NavAdminTools.USER_SEARCH,
            )
        ]
    ]
    navigation = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="⬅️ قبلی",
                callback_data=f"{NavAdminTools.USER_PAGE}:{page - 1}",
            )
        )
    if (page + 1) * USERS_PER_PAGE < total:
        navigation.append(
            InlineKeyboardButton(
                text="بعدی ➡️",
                callback_data=f"{NavAdminTools.USER_PAGE}:{page + 1}",
            )
        )
    if navigation:
        rows.append(navigation)
    rows.append(
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _user_list_keyboard(users: list[User], page: int, total: int) -> InlineKeyboardMarkup:
    rows = []
    for item in users:
        name = html.escape(item.first_name or "بدون نام")
        username = f" @{html.escape(item.username)}" if item.username else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"👤 {name}{username}",
                    callback_data=f"{NavAdminTools.USER_DETAILS}:{item.tg_id}:{page}",
                )
            ]
        )
    return _append_user_list_controls(rows, page, total)


def _append_user_list_controls(
    rows: list[list[InlineKeyboardButton]], page: int, total: int
) -> InlineKeyboardMarkup:
    rows.append(
        [
            InlineKeyboardButton(
                text="🔎 جستجوی کاربر",
                callback_data=NavAdminTools.USER_SEARCH,
            )
        ]
    )
    navigation = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="⬅️ قبلی",
                callback_data=f"{NavAdminTools.USER_PAGE}:{page - 1}",
            )
        )
    if (page + 1) * USERS_PER_PAGE < total:
        navigation.append(
            InlineKeyboardButton(
                text="بعدی ➡️",
                callback_data=f"{NavAdminTools.USER_PAGE}:{page + 1}",
            )
        )
    if navigation:
        rows.append(navigation)
    rows.append(
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_user_list(
    callback: CallbackQuery,
    session: AsyncSession,
    page: int = 0,
    search: str | None = None,
) -> None:
    page = max(0, page)

    count_query = select(func.count(User.id))
    users_query = select(User).order_by(User.created_at.desc(), User.id.desc())

    if search:
        value = search.strip()
        if value.isdigit():
            condition = User.tg_id == int(value)
        else:
            pattern = f"%{value}%"
            condition = or_(
                User.first_name.ilike(pattern),
                User.username.ilike(pattern),
            )
        count_query = count_query.where(condition)
        users_query = users_query.where(condition)

    total = int((await session.execute(count_query)).scalar_one())
    users = list(
        (
            await session.execute(
                users_query.offset(page * USERS_PER_PAGE).limit(USERS_PER_PAGE)
            )
        ).scalars()
    )

    if search:
        title = (
            "👥 <b>نتایج جستجوی کاربران</b>\n\n"
            f"🔎 عبارت: <code>{html.escape(search)}</code>\n"
            f"📊 تعداد نتیجه: <b>{total:,}</b>"
        )
    else:
        title = (
            "👥 <b>مدیریت کاربران</b>\n\n"
            f"📊 تعداد کل کاربران ربات: <b>{total:,}</b>\n"
            f"📄 صفحه: <b>{page + 1}</b>"
        )

    if not users:
        title += "\n\n❌ کاربری پیدا نشد."

    await callback.message.edit_text(
        title,
        reply_markup=_user_list_keyboard(users, page, total)
        if users
        else _page_keyboard(page, total),
    )


@router.callback_query(F.data == NavAdminTools.USER_EDITOR, IsAdmin())
async def callback_user_editor(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    logger.info("Admin %s opened user management.", user.tg_id)
    await state.clear()
    await callback.answer()
    await _show_user_list(callback, session)


@router.callback_query(F.data.startswith(f"{NavAdminTools.USER_PAGE}:"), IsAdmin())
async def callback_user_page(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    page = int(callback.data.rsplit(":", 1)[1])
    await callback.answer()
    await _show_user_list(callback, session, page=page)


@router.callback_query(F.data == NavAdminTools.USER_SEARCH, IsAdmin())
async def callback_user_search(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.set_state(UserManagementStates.search)
    await callback.answer()
    await callback.message.edit_text(
        "🔎 <b>جستجوی کاربر</b>\n\n"
        "یکی از موارد زیر را ارسال کن:\n"
        "• Telegram ID\n"
        "• Username بدون @\n"
        "• نام کاربر\n\n"
        "مثال: <code>123456789</code> یا <code>amin</code>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 بازگشت",
                        callback_data=NavAdminTools.USER_EDITOR,
                    )
                ]
            ]
        ),
    )


@router.message(UserManagementStates.search, IsAdmin())
async def process_user_search(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    value = (message.text or "").strip()
    if not value:
        await message.answer("❌ عبارت جستجو نمی‌تواند خالی باشد.")
        return

    await state.clear()

    count_query = select(func.count(User.id))
    users_query = select(User).order_by(User.created_at.desc(), User.id.desc())

    if value.isdigit():
        condition = User.tg_id == int(value)
    else:
        pattern = f"%{value}%"
        condition = or_(
            User.first_name.ilike(pattern),
            User.username.ilike(pattern),
        )

    count_query = count_query.where(condition)
    users_query = users_query.where(condition).limit(USERS_PER_PAGE)

    total = int((await session.execute(count_query)).scalar_one())
    users = list((await session.execute(users_query)).scalars())

    rows = []
    for item in users:
        name = html.escape(item.first_name or "بدون نام")
        username = f" @{html.escape(item.username)}" if item.username else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"👤 {name}{username}",
                    callback_data=f"{NavAdminTools.USER_DETAILS}:{item.tg_id}:0",
                )
            ]
        )
    markup = _append_user_list_controls(rows, 0, total)
    await message.answer(
        "👥 <b>نتایج جستجو</b>\n\n"
        f"🔎 <code>{html.escape(value)}</code>\n"
        f"📊 تعداد نتیجه: <b>{total:,}</b>",
        reply_markup=markup,
    )


async def _load_user_details(session: AsyncSession, tg_id: int) -> tuple[User | None, list[Subscription], Wallet | None, int]:
    user = await User.get(session=session, tg_id=tg_id)
    if not user:
        return None, [], None, 0

    subscriptions = list(
        (
            await session.execute(
                select(Subscription)
                .where(Subscription.user_id == user.id)
                .order_by(Subscription.created_at.desc(), Subscription.id.desc())
                .limit(5)
            )
        ).scalars()
    )
    wallet = await Wallet.get(session, tg_id)
    transaction_count = int(
        (
            await session.execute(
                select(func.count(Transaction.id)).where(Transaction.tg_id == tg_id)
            )
        ).scalar_one()
    )
    return user, subscriptions, wallet, transaction_count


def _subscription_status(subscription: Subscription) -> str:
    status = subscription.status or "unknown"
    if status == "active":
        if subscription.expire_date and subscription.expire_date < datetime.now(
            subscription.expire_date.tzinfo
        ):
            return "منقضی"
        return "فعال"
    return status


def _details_keyboard(tg_id: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👤 مشاهده پروفایل تلگرام",
                    url=f"tg://user?id={tg_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 بروزرسانی اطلاعات تلگرام",
                    callback_data=f"{NavAdminTools.USER_REFRESH}:{tg_id}:{page}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 بازگشت به لیست",
                    callback_data=f"{NavAdminTools.USER_PAGE}:{page}",
                )
            ],
        ]
    )


def _user_details_text(
    user: User,
    subscriptions: list[Subscription],
    wallet: Wallet | None,
    transaction_count: int,
) -> str:
    full_name = html.escape(user.first_name or "بدون نام")
    username = f"@{html.escape(user.username)}" if user.username else "ندارد"
    server = html.escape(user.server.name) if user.server else "تعیین نشده"
    wallet_balance = wallet.balance if wallet else 0

    lines = [
        "👤 <b>مدیریت کاربر</b>",
        "",
        f"🆔 Telegram ID: <code>{user.tg_id}</code>",
        f"📛 نام: <b>{full_name}</b>",
        f"🔗 Username: <b>{username}</b>",
        f"🌐 زبان: <code>{html.escape(user.language_code or '-')}</code>",
        f"🖥 سرور پیش‌فرض: <b>{server}</b>",
        f"🎁 اکانت تست: <b>{'دریافت شده' if user.is_trial_used else 'دریافت نشده'}</b>",
        f"💰 موجودی کیف پول: <b>{wallet_balance:,} تومان</b>",
        f"💳 تعداد تراکنش‌ها: <b>{transaction_count:,}</b>",
        f"📅 ثبت‌نام: <b>{format_jalali(user.created_at)}</b>",
        "",
        "📦 <b>اشتراک‌ها</b>",
    ]

    if not subscriptions:
        lines.append("• هیچ اشتراکی ثبت نشده است.")
    else:
        for item in subscriptions:
            expire = (
                format_jalali(item.expire_date)
                if item.expire_date
                else "بدون تاریخ انقضا"
            )
            lines.append(
                f"• #{item.id} | {item.volume_gb}GB / {item.duration_days}روز | "
                f"{_subscription_status(item)} | انقضا: {expire}"
            )

    return "\n".join(lines)


@router.callback_query(F.data.startswith(f"{NavAdminTools.USER_DETAILS}:"), IsAdmin())
async def callback_user_details(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    _, tg_id_raw, page_raw = callback.data.split(":", 2)
    tg_id = int(tg_id_raw)
    page = int(page_raw)

    user, subscriptions, wallet, transaction_count = await _load_user_details(
        session, tg_id
    )
    if not user:
        await callback.answer("کاربر پیدا نشد.", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text(
        _user_details_text(user, subscriptions, wallet, transaction_count),
        reply_markup=_details_keyboard(tg_id, page),
    )


@router.callback_query(F.data.startswith(f"{NavAdminTools.USER_REFRESH}:"), IsAdmin())
async def callback_user_refresh(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    _, tg_id_raw, page_raw = callback.data.split(":", 2)
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
        await callback.answer(
            "اطلاعات تلگرام قابل دریافت نبود؛ اطلاعات ذخیره‌شده نمایش داده می‌شود.",
            show_alert=True,
        )

    user, subscriptions, wallet, transaction_count = await _load_user_details(
        session, tg_id
    )
    if user:
        await callback.message.edit_text(
            _user_details_text(user, subscriptions, wallet, transaction_count),
            reply_markup=_details_keyboard(tg_id, page),
        )
