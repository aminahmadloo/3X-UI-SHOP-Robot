import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import ServicesContainer
from app.bot.utils.constants import (
    MAIN_MESSAGE_ID_KEY,
    PREVIOUS_CALLBACK_KEY,
    ReferrerRewardLevel,
    ReferrerRewardType,
    TransactionStatus,
)
from app.bot.utils.formatting import format_subscription_period
from app.bot.utils.navigation import NavMain, NavReferral
from app.config import Config
from app.db.models import Referral, ReferrerReward, ReferralSettings, User

from .keyboard import referral_keyboard

logger = logging.getLogger(__name__)
router = Router(name=__name__)


async def generate_referral_summary_text(
    session: AsyncSession,
    user: User,
    config: Config,
    bot_username: str,
) -> str:
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import func, select

    referral_link = f"https://t.me/{bot_username}?start=ref_{user.tg_id}"
    referrals_count = await Referral.get_referral_count(
        session=session, referrer_tg_id=user.tg_id
    )
    settings = await ReferralSettings.get_or_create(session)

    referred_ids = select(Referral.referred_tg_id).where(
        Referral.referrer_tg_id == user.tg_id
    )
    from app.bot.models import SubscriptionData
    from app.db.models import Transaction, WalletTransaction

    result = await session.execute(
        select(Transaction).where(
            Transaction.tg_id.in_(referred_ids),
            Transaction.status == TransactionStatus.COMPLETED,
        )
    )
    purchase_count = 0
    for tx in result.scalars().all():
        try:
            data = SubscriptionData.deserialize(tx.subscription)
            if data.payment_kind == "wallet_topup":
                continue
        except Exception:
            pass
        purchase_count += 1

    since = datetime.now(timezone.utc) - timedelta(days=30)
    income_30d = await session.scalar(
        select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(
            WalletTransaction.user_tg_id == user.tg_id,
            WalletTransaction.transaction_type == "referral_reward",
            WalletTransaction.created_at >= since,
        )
    ) or 0

    first_rate = int(settings.reward_percent)
    repeat_rate = int(settings.repeat_reward_percent)

    return (
        "🎁 <b>معرفی به دوستان</b>\n\n"
        f"🔗 لینک دعوت اختصاصی شما:{referral_link}\n"
        "➡️ با هر نفر که با لینکت ثبت‌نام کنه:\n"
        f"- <b>{first_rate}%</b> از اولین خریدش به کیف پولت\n"
        f"- <b>{repeat_rate}%</b> از هر خرید بعدیش، مادام‌العمر\n\n"
        "➕ هر دعوت موفق یه امتیاز هم داره؛ امتیازهات که جمع بشه، سطحت بالا می‌ره و تخفیف دائمی می‌گیری.\n\n"
        "📊 <b>آمار دعوت شما</b>\n"
        f"├ 👤 افراد دعوت‌شده: <b>{referrals_count}</b>\n"
        f"├ 💳 تعداد خریدها: <b>{purchase_count}</b>\n"
        f"└ 💰 درآمد ۳۰ روز اخیر: <b>{int(income_30d):,}</b> تومان"
    )


@router.callback_query(F.data == NavReferral.MAIN)
async def callback_referral(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    session: AsyncSession,
    config: Config,
) -> None:
    logger.info(f"User {user.tg_id} opened referral page.")

    bot_username = (await callback.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start=ref_{user.tg_id}"

    await state.update_data({PREVIOUS_CALLBACK_KEY: NavReferral.MAIN})

    await callback.message.edit_text(
        text=await generate_referral_summary_text(
            session=session,
            user=user,
            config=config,
            bot_username=bot_username,
        ),
        reply_markup=referral_keyboard(referral_link=referral_link),
    )


@router.callback_query(F.data == NavReferral.GET_REFERRED_TRIAL)
async def callback_get_referred_trial(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    services: ServicesContainer,
    config: Config,
) -> None:
    logger.info(f"User {user.tg_id} triggered getting bonus days.")

    server = await services.server_pool.get_available_server()

    if not server:
        await services.notification.show_popup(
            callback=callback,
            text=_("referral:popup:no_available_servers"),
        )
        return

    is_referred_trial_available = await services.referral.is_referred_trial_available(user=user)

    if not is_referred_trial_available:
        await services.notification.show_popup(
            callback=callback,
            text=_("referral:popup:trial_unavailable_for_user"),
        )
        return

    referred_trial_period = config.shop.REFERRED_TRIAL_PERIOD

    success = await services.referral.reward_referred_user(
        user=user, days_count=referred_trial_period
    )

    main_message_id = await state.get_value(MAIN_MESSAGE_ID_KEY)
    if success:
        await state.update_data({PREVIOUS_CALLBACK_KEY: NavMain.MAIN_MENU})
        await callback.bot.edit_message_text(
            text=_("subscription:ntf:trial_activate_success").format(
                duration=format_subscription_period(referred_trial_period),
            ),
            chat_id=callback.message.chat.id,
            message_id=main_message_id,
            reply_markup=referral_keyboard(connect=True),
        )
    else:
        text = _("referral:ntf:referred_trial_activate_failed")
        await services.notification.notify_by_message(
            message=callback.message, text=text, duration=15
        )
