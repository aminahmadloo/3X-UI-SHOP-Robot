import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.routers.admin_tools.advertising_builder_handler import build_ad_markup
from app.db.models import AdvertisingCampaign, AdvertisingChannel, AdvertisingEvent, AdvertisingPublication

logger = logging.getLogger(__name__)
router = Router(name=__name__)


def _is_missing_message_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "message to edit not found",
            "message not found",
            "message_id_invalid",
            "there is no message",
        )
    )


async def _check_publication(bot, session: AsyncSession, campaign: AdvertisingCampaign, publication: AdvertisingPublication, channel: AdvertisingChannel) -> str:
    """Check whether Telegram still exposes the publication message.

    Telegram Bot API has no getMessage method. Editing the message's reply markup with
    the campaign's current markup is a non-destructive existence/permission check.
    """
    try:
        markup = await build_ad_markup(
            campaign.id,
            campaign.bot_username or "",
            channel.id,
            session,
            campaign.custom_buttons,
            campaign.selected_offers,
            campaign.show_services,
        )
        await bot.edit_message_reply_markup(
            chat_id=channel.chat_id,
            message_id=publication.message_id,
            reply_markup=markup,
        )
        return "present"
    except Exception as exc:
        if _is_missing_message_error(exc):
            return "deleted"
        logger.warning(
            "Could not verify advertising publication campaign=%s channel=%s message=%s: %s",
            campaign.id,
            channel.chat_id,
            publication.message_id,
            exc,
        )
        return "unknown"


async def _campaign_status(bot, session: AsyncSession, campaign: AdvertisingCampaign) -> tuple[int, int, int, int]:
    result = await session.execute(
        select(AdvertisingPublication, AdvertisingChannel)
        .join(AdvertisingChannel, AdvertisingChannel.id == AdvertisingPublication.channel_id)
        .where(AdvertisingPublication.campaign_id == campaign.id)
        .order_by(AdvertisingPublication.id),
    )
    rows = list(result.all())
    if not rows:
        return 0, 0, 0, 0

    present = deleted = unknown = 0
    for publication, channel in rows:
        status = await _check_publication(bot, session, campaign, publication, channel)
        if status == "present":
            present += 1
        elif status == "deleted":
            deleted += 1
        else:
            unknown += 1
    return len(rows), present, deleted, unknown


def _status_label(total: int, present: int, deleted: int, unknown: int) -> str:
    if total == 0:
        return "⚪ منتشر نشده"
    if present == total:
        return "🟢 موجود در کانال"
    if deleted == total:
        return "🔴 حذف‌شده از کانال"
    if unknown:
        return "🟡 نیاز به بررسی"
    return "🟠 بخشی حذف شده"


async def _render_status_list(callback: CallbackQuery, session: AsyncSession) -> None:
    campaigns = list(
        (
            await session.execute(
                select(AdvertisingCampaign).order_by(AdvertisingCampaign.id.desc()).limit(30)
            )
        ).scalars().all()
    )
    b = InlineKeyboardBuilder()
    lines = ["🔍 <b>وضعیت انتشار کمپین‌ها</b>", "", "وضعیت واقعی پیام‌های کمپین در کانال بررسی می‌شود:", ""]

    if not campaigns:
        lines.append("هنوز کمپینی ساخته نشده است.")
    else:
        for campaign in campaigns:
            total, present, deleted, unknown = await _campaign_status(callback.message.bot, session, campaign)
            label = _status_label(total, present, deleted, unknown)
            detail = f"{present}/{total} پیام موجود"
            if deleted:
                detail += f" | {deleted} حذف‌شده"
            if unknown:
                detail += f" | {unknown} نامشخص"
            lines.append(f"<b>#{campaign.id} — {campaign.title[:38]}</b>\n{label} · {detail}")
            b.row(
                InlineKeyboardButton(
                    text=f"🔎 جزئیات #{campaign.id}",
                    callback_data=f"advertising:publication_status:{campaign.id}",
                )
            )

    b.row(InlineKeyboardButton(text="🔄 بررسی مجدد", callback_data="advertising:publication_status"))
    b.row(InlineKeyboardButton(text="🔙 مرکز تبلیغات", callback_data="advertising:menu"))
    await callback.message.edit_text("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(F.data == "advertising:publication_status", IsAdmin())
async def publication_status(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer("در حال بررسی پیام‌های کانال…")
    await _render_status_list(callback, session)


@router.callback_query(F.data.regexp(r"^advertising:publication_status:\d+$"), IsAdmin())
async def publication_status_detail(callback: CallbackQuery, session: AsyncSession) -> None:
    campaign_id = int(callback.data.rsplit(":", 1)[1])
    campaign = await session.get(AdvertisingCampaign, campaign_id)
    if not campaign:
        await callback.answer("کمپین پیدا نشد.", show_alert=True)
        return

    result = await session.execute(
        select(AdvertisingPublication, AdvertisingChannel)
        .join(AdvertisingChannel, AdvertisingChannel.id == AdvertisingPublication.channel_id)
        .where(AdvertisingPublication.campaign_id == campaign.id)
        .order_by(AdvertisingPublication.id),
    )
    rows = list(result.all())
    b = InlineKeyboardBuilder()
    lines = [f"🔍 <b>وضعیت کانال — کمپین #{campaign.id}</b>", f"🏷 {campaign.title}", ""]

    if not rows:
        lines.append("⚪ این کمپین هنوز هیچ انتشاری در کانال ثبت‌شده ندارد.")
    else:
        for publication, channel in rows:
            status = await _check_publication(callback.message.bot, session, campaign, publication, channel)
            if status == "present":
                label = "🟢 موجود"
            elif status == "deleted":
                label = "🔴 حذف‌شده"
            else:
                label = "🟡 قابل بررسی نیست"
            channel_name = channel.title or channel.username or str(channel.chat_id)
            lines.append(
                f"{label} · <b>{channel_name}</b>\n"
                f"   🆔 پیام: <code>{publication.message_id}</code>"
            )

    b.row(InlineKeyboardButton(text="🔄 بررسی مجدد", callback_data=f"advertising:publication_status:{campaign.id}"))
    b.row(InlineKeyboardButton(text="✏️ مدیریت کمپین", callback_data=f"advertising:manage:{campaign.id}"))
    b.row(InlineKeyboardButton(text="🗑 حذف کمپین", callback_data=f"advertising:delete_campaign:{campaign.id}"))
    b.row(InlineKeyboardButton(text="🔙 فهرست وضعیت‌ها", callback_data="advertising:publication_status"))
    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=b.as_markup())


async def _delete_campaign_messages(callback: CallbackQuery, session: AsyncSession, campaign_id: int) -> tuple[int, int]:
    result = await session.execute(
        select(AdvertisingPublication, AdvertisingChannel).join(
            AdvertisingChannel, AdvertisingChannel.id == AdvertisingPublication.channel_id
        ).where(AdvertisingPublication.campaign_id == campaign_id)
    )
    rows = list(result.all())
    deleted = failed = 0
    for publication, channel in rows:
        try:
            await callback.message.bot.delete_message(
                chat_id=channel.chat_id,
                message_id=publication.message_id,
            )
            deleted += 1
        except Exception as exc:
            text = str(exc).lower()
            if _is_missing_message_error(exc) or "message can't be deleted" in text or "message to delete not found" in text:
                deleted += 1
            else:
                failed += 1
                logger.warning(
                    "Could not delete campaign publication campaign=%s channel=%s message=%s: %s",
                    campaign_id,
                    channel.chat_id,
                    publication.message_id,
                    exc,
                )
    return deleted, failed


@router.callback_query(F.data.regexp(r"^advertising:delete_campaign:\d+$"), IsAdmin())
async def delete_campaign_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    campaign_id = int(callback.data.rsplit(":", 1)[1])
    campaign = await session.get(AdvertisingCampaign, campaign_id)
    if not campaign:
        await callback.answer("کمپین پیدا نشد.", show_alert=True)
        return

    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="⚠️ بله، حذف کن", callback_data=f"advertising:delete_campaign_confirm:{campaign.id}"),
        InlineKeyboardButton(text="❌ انصراف", callback_data=f"advertising:publication_status:{campaign.id}"),
    )
    await callback.answer()
    await callback.message.edit_text(
        f"⚠️ <b>حذف کمپین #{campaign.id}</b>\n\n"
        f"🏷 {campaign.title}\n\n"
        "با تأیید، کمپین از سیستم حذف می‌شود و پیام‌های منتشرشده آن در کانال نیز حذف خواهند شد.\n"
        "این عملیات قابل بازگشت نیست.\n\n"
        "آیا مطمئنی؟",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data.regexp(r"^advertising:delete_campaign_confirm:\d+$"), IsAdmin())
async def delete_campaign_confirmed(callback: CallbackQuery, session: AsyncSession) -> None:
    campaign_id = int(callback.data.rsplit(":", 1)[1])
    campaign = await session.get(AdvertisingCampaign, campaign_id)
    if not campaign:
        await callback.answer("کمپین قبلاً حذف شده است.", show_alert=True)
        return

    deleted_messages, failed_messages = await _delete_campaign_messages(callback, session, campaign_id)

    await session.execute(delete(AdvertisingEvent).where(AdvertisingEvent.campaign_id == campaign_id))
    await session.execute(delete(AdvertisingPublication).where(AdvertisingPublication.campaign_id == campaign_id))
    await session.delete(campaign)
    await session.commit()

    if failed_messages:
        result = (
            f"⚠️ کمپین #{campaign_id} از سیستم حذف شد.\n"
            f"🗑 پیام حذف‌شده از کانال: {deleted_messages}\n"
            f"⚠️ پیام‌هایی که حذفشان از کانال ممکن نشد: {failed_messages}"
        )
    else:
        result = f"✅ کمپین #{campaign_id} با موفقیت حذف شد.\n🗑 پیام‌های کانال: {deleted_messages}"

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📢 مدیریت کمپین‌ها", callback_data="advertising:manage"))
    b.row(InlineKeyboardButton(text="🔍 وضعیت انتشار کمپین‌ها", callback_data="advertising:publication_status"))
    b.row(InlineKeyboardButton(text="🔙 مرکز تبلیغات", callback_data="advertising:menu"))
    await callback.answer("کمپین حذف شد")
    await callback.message.edit_text(result, reply_markup=b.as_markup())


# Patch the existing campaign management screen without duplicating its router handlers.
# The management module is already imported before this router by routers/__init__.py.
from app.bot.routers.admin_tools import advertising_management_handler as _management

_original_campaign_menu = _management._campaign_menu


def _campaign_menu_with_delete(campaign: AdvertisingCampaign):
    markup = _original_campaign_menu(campaign)
    rows = [list(row) for row in markup.inline_keyboard]
    rows.insert(-1, [InlineKeyboardButton(text="🗑 حذف کمپین", callback_data=f"advertising:delete_campaign:{campaign.id}")])
    return type(markup)(inline_keyboard=rows)


_management._campaign_menu = _campaign_menu_with_delete
