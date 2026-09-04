import asyncio
from datetime import datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.services.channel_campaign import ChannelAnalyticsService, ChannelCampaignService
from app.db.models import Base, CampaignEvent, ChannelCampaign, ChannelCampaignMember, ChannelMemberSnapshot, Transaction, User


def _run(coro):
    return asyncio.run(coro)


def _session_runner(test_coro):
    async def runner():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        tables = [User.__table__, Transaction.__table__, ChannelCampaign.__table__, ChannelCampaignMember.__table__, ChannelMemberSnapshot.__table__, CampaignEvent.__table__]
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables))
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await test_coro(session)
        await engine.dispose()
    _run(runner())


def test_create_campaign():
    campaign = ChannelCampaign(name="کمپین تابستانی", slug="summer_2026", channel_id=-100123, campaign_type="referral", status="active", start_date=datetime.utcnow(), created_by=1)
    assert campaign.slug == "summer_2026"
    assert campaign.is_active_now()


def test_generate_campaign_link():
    assert ChannelCampaignService.build_link("ToonelVpn_bot", "summer_2026") == "https://t.me/ToonelVpn_bot?start=campaign_summer_2026"


def test_register_campaign_member():
    async def check(session):
        campaign = ChannelCampaign(name="Summer", slug="summer", channel_id=-1001, campaign_type="referral", status="active", start_date=datetime.utcnow(), created_by=1)
        session.add(campaign); await session.commit()
        member = await ChannelCampaignService.register_start(session, campaign, 12345, referrer_id=77, joined_channel=True)
        assert member.telegram_user_id == 12345 and member.started_bot and member.joined_channel
        event = (await session.execute(__import__('sqlalchemy').select(CampaignEvent).where(CampaignEvent.telegram_user_id == 12345))).scalar_one()
        assert event.referrer_id == 77
    _session_runner(check)


def test_referral_integration_is_additive():
    async def check(session):
        from app.db.models import Referral
        campaign = ChannelCampaign(name="Summer", slug="summer-ref", channel_id=-1001, campaign_type="referral", status="active", start_date=datetime.utcnow(), created_by=1)
        session.add_all([User(tg_id=77, vpn_id="00000000-0000-0000-0000-000000000077", first_name="Referrer"), User(tg_id=123, vpn_id="00000000-0000-0000-0000-000000000123", first_name="Invitee"), campaign]); await session.commit()
        session.add(Referral(referrer_tg_id=77, referred_tg_id=123)); await session.commit()
        referral = await Referral.get_referral(session, 123)
        await ChannelCampaignService.register_start(session, campaign, 123, referrer_id=referral.referrer_tg_id)
        assert (await Referral.get_referral(session, 123)).referrer_tg_id == 77
    _session_runner(check)


def test_conversion_tracking():
    async def check(session):
        campaign = ChannelCampaign(name="Summer", slug="summer-convert", channel_id=-1001, campaign_type="promo", status="active", start_date=datetime.utcnow(), created_by=1)
        session.add_all([campaign, User(tg_id=123, vpn_id="00000000-0000-0000-0000-000000000123", first_name="Buyer")]); await session.commit()
        await ChannelCampaignService.register_start(session, campaign, 123)
        session.add(Transaction(tg_id=123, payment_id="p1", subscription="legacy", status="completed")); await session.commit()
        assert await ChannelCampaignService.sync_conversions(session, campaign.id) == 1
        member = (await session.execute(__import__('sqlalchemy').select(ChannelCampaignMember).where(ChannelCampaignMember.campaign_id == campaign.id))).scalar_one()
        assert member.converted_to_customer is True
    _session_runner(check)


def test_analytics_calculation():
    async def check(session):
        session.add_all([ChannelMemberSnapshot(channel_id=-1001, member_count=100, snapshot_date=datetime(2026, 9, 1)), ChannelMemberSnapshot(channel_id=-1001, member_count=120, snapshot_date=datetime(2026, 9, 2)), ChannelMemberSnapshot(channel_id=-1001, member_count=150, snapshot_date=datetime(2026, 9, 3))]); await session.commit()
        growth = await ChannelAnalyticsService.growth(session, -1001)
        assert growth["today"] == 30 and growth["week"] == 50
    _session_runner(check)
