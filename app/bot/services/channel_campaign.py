from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import SubscriptionData
from app.db.models import ChannelCampaign, ChannelCampaignMember, ChannelMemberSnapshot, CampaignEvent, Referral, Transaction

CAMPAIGN_PREFIX = "campaign_"


class ChannelCampaignService:
    """Campaign attribution layer. It never replaces the existing Referral relation."""

    @staticmethod
    def start_payload(slug: str) -> str:
        return f"{CAMPAIGN_PREFIX}{slug}"

    @staticmethod
    def build_link(bot_username: str, slug: str) -> str:
        return f"https://t.me/{bot_username}?start={ChannelCampaignService.start_payload(slug)}"

    @staticmethod
    async def get_by_slug(session: AsyncSession, slug: str) -> ChannelCampaign | None:
        return (await session.execute(select(ChannelCampaign).where(ChannelCampaign.slug == slug))).scalar_one_or_none()

    @staticmethod
    async def register_start(session: AsyncSession, campaign: ChannelCampaign, telegram_user_id: int, *, referrer_id: int | None = None, joined_channel: bool = False, source: str = "campaign") -> ChannelCampaignMember:
        member = (await session.execute(select(ChannelCampaignMember).where(ChannelCampaignMember.campaign_id == campaign.id, ChannelCampaignMember.telegram_user_id == telegram_user_id))).scalar_one_or_none()
        if member is None:
            member = ChannelCampaignMember(campaign_id=campaign.id, telegram_user_id=telegram_user_id, source=source, joined_channel=joined_channel, started_bot=True)
            session.add(member)
            await session.flush()
        else:
            member.started_bot = True
            member.joined_channel = member.joined_channel or joined_channel
        event = (await session.execute(select(CampaignEvent).where(CampaignEvent.campaign_id == campaign.id, CampaignEvent.telegram_user_id == telegram_user_id, CampaignEvent.event_type == "started_bot"))).scalar_one_or_none()
        if event is None:
            session.add(CampaignEvent(campaign_id=campaign.id, telegram_user_id=telegram_user_id, event_type="started_bot", source=source, referrer_id=referrer_id))
        elif referrer_id and not event.referrer_id:
            event.referrer_id = referrer_id
        await session.commit()
        return member

    @staticmethod
    async def mark_converted(session: AsyncSession, telegram_user_id: int) -> int:
        result = await session.execute(update(ChannelCampaignMember).where(ChannelCampaignMember.telegram_user_id == telegram_user_id).values(converted_to_customer=True))
        await session.commit()
        return result.rowcount or 0

    @staticmethod
    async def sync_conversions(session: AsyncSession, campaign_id: int | None = None) -> int:
        stmt = select(ChannelCampaignMember.id).join(Transaction, Transaction.tg_id == ChannelCampaignMember.telegram_user_id).where(Transaction.status == "completed")
        if campaign_id is not None:
            stmt = stmt.where(ChannelCampaignMember.campaign_id == campaign_id)
        ids = {row[0] for row in (await session.execute(stmt)).all()}
        if ids:
            await session.execute(update(ChannelCampaignMember).where(ChannelCampaignMember.id.in_(ids)).values(converted_to_customer=True))
            await session.commit()
        return len(ids)

    @staticmethod
    async def report(session: AsyncSession, campaign_id: int) -> dict[str, Any]:
        await ChannelCampaignService.sync_conversions(session, campaign_id)
        campaign = await session.get(ChannelCampaign, campaign_id)
        if not campaign:
            return {}
        joined = (await session.execute(select(func.count(ChannelCampaignMember.id)).where(ChannelCampaignMember.campaign_id == campaign_id, ChannelCampaignMember.joined_channel.is_(True)))).scalar() or 0
        started = (await session.execute(select(func.count(ChannelCampaignMember.id)).where(ChannelCampaignMember.campaign_id == campaign_id, ChannelCampaignMember.started_bot.is_(True)))).scalar() or 0
        customers = (await session.execute(select(func.count(ChannelCampaignMember.id)).where(ChannelCampaignMember.campaign_id == campaign_id, ChannelCampaignMember.converted_to_customer.is_(True)))).scalar() or 0
        rows = (await session.execute(select(Transaction).join(ChannelCampaignMember, ChannelCampaignMember.telegram_user_id == Transaction.tg_id).where(ChannelCampaignMember.campaign_id == campaign_id, Transaction.status == "completed"))).scalars().all()
        revenue = 0.0
        for tx in rows:
            try:
                revenue += float(SubscriptionData.unpack(tx.subscription).price)
            except Exception:
                continue
        referrers = (await session.execute(select(Referral.referrer_tg_id, func.count(Referral.id)).join(ChannelCampaignMember, ChannelCampaignMember.telegram_user_id == Referral.referred_tg_id).where(ChannelCampaignMember.campaign_id == campaign_id).group_by(Referral.referrer_tg_id).order_by(func.count(Referral.id).desc()).limit(10))).all()
        return {"campaign": campaign, "members": joined, "started": started, "customers": customers, "conversion_rate": (customers / started * 100) if started else 0, "revenue": revenue, "top_referrers": referrers}


class ChannelAnalyticsService:
    @staticmethod
    async def snapshot_channel(session: AsyncSession, bot, channel_id: int) -> ChannelMemberSnapshot | None:
        count = await bot.get_chat_member_count(channel_id)
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        snapshot = (await session.execute(select(ChannelMemberSnapshot).where(ChannelMemberSnapshot.channel_id == channel_id, ChannelMemberSnapshot.snapshot_date == today))).scalar_one_or_none()
        if snapshot:
            snapshot.member_count = count
        else:
            snapshot = ChannelMemberSnapshot(channel_id=channel_id, member_count=count, snapshot_date=today)
            session.add(snapshot)
        await session.commit()
        return snapshot

    @staticmethod
    async def growth(session: AsyncSession, channel_id: int) -> dict[str, int]:
        rows = list((await session.execute(select(ChannelMemberSnapshot).where(ChannelMemberSnapshot.channel_id == channel_id).order_by(ChannelMemberSnapshot.snapshot_date.desc()).limit(31))).scalars())
        if len(rows) < 2:
            return {"today": 0, "week": 0, "month": 0}
        latest = rows[0].member_count
        return {"today": latest - rows[1].member_count, "week": latest - rows[min(7, len(rows)-1)].member_count, "month": latest - rows[-1].member_count}
