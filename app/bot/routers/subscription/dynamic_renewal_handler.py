from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.bot.models import ServicesContainer, SubscriptionData
from app.bot.routers.my_services.handler import _status,_sync_subscriptions_with_xui
from app.bot.routers.subscription.renewal_handler import _effective_expire_date,_format_remaining_time,_format_expire,_get_user_subscription
from app.bot.utils.navigation import NavMain,NavSubscription
from app.bot.payment_gateways import GatewayFactory

from app.db.models import Server,ServicePurchasePlan,Subscription,User
from app.db.models.service_period import ServicePeriod

router=Router(name=__name__)
def _home(): return InlineKeyboardButton(text="🏠 منوی اصلی",callback_data=NavMain.MAIN_MENU)
def _services(xs):
    b=InlineKeyboardBuilder()
    for x in xs:
        icon,status=_status(x); b.row(InlineKeyboardButton(text=f"{icon} {x.config_name} | {x.volume_gb}GB | {status}",callback_data=f"dynamic_renewal:service:{x.id}"))
    b.row(InlineKeyboardButton(text="🛒 خرید سرویس جدید",callback_data=NavSubscription.BUY)); b.row(_home()); return b.as_markup()
async def _get(session,user,sid,services):
    r=await session.execute(select(Subscription).join(Server,Subscription.server_id==Server.id).options(selectinload(Subscription.server)).where(Subscription.id==sid,Subscription.user_id==user.id,Subscription.server_id.is_not(None))); x=r.scalar_one_or_none()
    if not x:return None
    z=await _sync_subscriptions_with_xui(session,[x],services); return z[0] if z else None

def _summary_keyboard(subscription_id: int, plan_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 انتخاب روش پرداخت",callback_data=f"dynamic_renewal:payment:{subscription_id}:{plan_id}")],
            [InlineKeyboardButton(text="🔙 تغییر مدت",callback_data=f"dynamic_renewal:service:{subscription_id}")],
            [_home()],
        ]
    )


def _payment_keyboard(subscription_id: int, plan_id: int, price_toman: int, gateways):
    builder = InlineKeyboardBuilder()

    for gateway in gateways:
        builder.row(
            InlineKeyboardButton(
                text=f"{gateway.name} | {price_toman:,} تومان",
                # The managed-payment handler expects the final callback
                # component to be the ServicePurchasePlan id, not the price.
                callback_data=f"mp:{gateway.callback}:{plan_id}",
            )
        )

    builder.row(
        InlineKeyboardButton(
            text=f"💰 کیف پول | {price_toman:,} تومان",
            callback_data=f"mp_wallet:{plan_id}",
        )
    )

    builder.row(
        InlineKeyboardButton(
            text=f"💳 کارت به کارت | {price_toman:,} تومان",
            callback_data=f"mp_card:{plan_id}",
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="🔙 تغییر مدت",
            callback_data=f"dynamic_renewal:service:{subscription_id}",
        )
    )

    builder.row(_home())
    return builder.as_markup()

async def _period(session,days):
    ps=await ServicePeriod.list_active(session); return min(ps,key=lambda p:abs(p.duration_days-days)) if ps else None

@router.callback_query(F.data==NavSubscription.RENEW_SERVICE)
async def entry(callback:CallbackQuery,user,session:AsyncSession,services:ServicesContainer,state:FSMContext):
    await state.clear(); r=await session.execute(select(Subscription).join(Server,Subscription.server_id==Server.id).options(selectinload(Subscription.server)).where(Subscription.user_id==user.id,Subscription.server_id.is_not(None)).order_by(Subscription.id.desc())); xs=await _sync_subscriptions_with_xui(session,list(r.scalars().all()),services); xs=[x for x in xs if _status(x)[1] in {"فعال","رو به اتمام","منقضی شده"}]; await callback.answer()
    if not xs: await callback.message.edit_text("⏳ <b>افزایش زمان سرویس</b>\n\nشما در حال حاضر سرویس فعالی برای افزایش زمان ندارید.",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_home()]])); return
    await callback.message.edit_text("⏳ <b>افزایش زمان سرویس</b>\n\nسرویسی را که می‌خواهید زمان آن افزایش یابد انتخاب کنید:",reply_markup=_services(xs))

@router.callback_query(F.data.regexp(r"^dynamic_renewal:service:\d+$"))
async def service(callback:CallbackQuery,user,session:AsyncSession,services:ServicesContainer):
    x=await _get(session,user,int(callback.data.rsplit(':',1)[1]),services)
    if not x: await callback.answer("❌ سرویس پیدا نشد.",show_alert=True); return
    p=await _period(session,x.duration_days)
    if not p: await callback.answer("❌ هیچ دوره فعالی برای این سرویس وجود ندارد.",show_alert=True); return
    plans = await ServicePurchasePlan.list_by_type(session, p.service_type)
    plans = [z for z in plans if z.volume_gb == 0 and z.duration_days > 0]
    plans.sort(key=lambda z: (z.duration_days, z.id))
    await callback.answer()
    b=InlineKeyboardBuilder()
    for z in plans: b.row(InlineKeyboardButton(text=f"📅 {z.duration_days} روز | {z.price_toman:,} تومان",callback_data=f"dynamic_renewal:plan:{x.id}:{z.id}"))
    b.row(InlineKeyboardButton(text="🔙 تغییر سرویس",callback_data=NavSubscription.RENEW_SERVICE)); b.row(_home())
    await callback.message.edit_text(f"⏳ <b>انتخاب مدت افزایش زمان {p.name}</b>\n\n📦 سرویس: <code>{x.config_name}</code>\n💾 حجم: <b>{x.volume_gb} GB</b>",reply_markup=b.as_markup())

@router.callback_query(F.data.regexp(r"^dynamic_renewal:plan:\d+:\d+$"))
async def callback_dynamic_renewal_plan_selected(callback:CallbackQuery,user:User,session:AsyncSession,services:ServicesContainer,state:FSMContext)->None:
    _, _, subscription_id_text, plan_id_text = callback.data.split(":")
    subscription_id=int(subscription_id_text); plan_id=int(plan_id_text)
    subscription=await _get(session,user,subscription_id,services); plan=await ServicePurchasePlan.get(session,plan_id)
    if not subscription or not plan or plan.volume_gb != 0 or plan.duration_days <= 0:
        await callback.answer("❌ اطلاعات افزایش زمان نامعتبر یا منقضی شده است.",show_alert=True); return
    data=SubscriptionData(state=NavSubscription.PAY,is_extend=True,user_id=user.tg_id,devices=subscription.devices,duration=plan.duration_days,price=plan.price_toman,plan_id=plan.id,volume_gb=subscription.volume_gb,config_name=subscription.config_name)
    data.subscription_id=subscription.id
    await state.update_data(subscription_data={"state":"config_name","is_extend":True,"is_change":False,"user_id":data.user_id,"devices":data.devices,"duration":data.duration,"price":data.price,"plan_id":data.plan_id,"volume_gb":data.volume_gb,"config_name":data.config_name,"subscription_id":data.subscription_id})
    current_expire=_effective_expire_date(subscription); base=current_expire if current_expire and current_expire > datetime.now(timezone.utc) else datetime.now(timezone.utc); new_expire=base+timedelta(days=plan.duration_days)
    client_data=await services.vpn.get_client_data(user,subscription_id=subscription.id); traffic_remaining=client_data.traffic_remaining_formatted if client_data else "در دسترس نیست"; remaining_time=_format_remaining_time(current_expire)
    await callback.answer()
    await callback.message.edit_text("🧾 <b>خلاصه سفارش افزایش زمان</b>\n\n"+f"📦 <b>سرویس:</b> <code>{subscription.config_name}</code>\n"+f"💾 <b>حجم کل:</b> {subscription.volume_gb} GB\n"+f"📊 <b>حجم باقی‌مانده:</b> {traffic_remaining}\n"+f"⏳ <b>زمان باقی‌مانده:</b> {remaining_time}\n"+f"📅 <b>مدت افزایش زمان:</b> {plan.duration_days} روز\n"+f"⏱ <b>انقضای فعلی:</b> {_format_expire(current_expire)}\n"+f"🆕 <b>انقضای جدید:</b> {_format_expire(new_expire)}\n"+f"💰 <b>مبلغ:</b> {plan.price_toman:,} تومان\n\n"+"حجم، سرور و مشخصات سرویس فعلی تغییر نمی‌کند.",reply_markup=_summary_keyboard(subscription.id,plan.id))

@router.callback_query(F.data.regexp(r"^dynamic_renewal:payment:\d+:\d+$"))
async def callback_renewal_payment_methods(callback:CallbackQuery,user:User,session:AsyncSession,services:ServicesContainer,state:FSMContext,gateway_factory:GatewayFactory)->None:
    _, _, subscription_id_text, plan_id_text=callback.data.split(":"); subscription_id=int(subscription_id_text); plan_id=int(plan_id_text)
    data=await state.get_data(); packed=data.get("subscription_data")
    if not isinstance(packed,dict) or int(packed.get("subscription_id",0))!=subscription_id or int(packed.get("plan_id",0))!=plan_id:
        await callback.answer("❌ اطلاعات سفارش افزایش زمان منقضی شده است.",show_alert=True); await state.clear(); return
    subscription=await _get_user_subscription(session,user,subscription_id,services); plan=await ServicePurchasePlan.get(session,plan_id)
    if not subscription or not plan or plan.volume_gb != 0 or plan.duration_days <= 0:
        await callback.answer("❌ سرویس یا پلن افزایش زمان دیگر معتبر نیست.",show_alert=True); await state.clear(); return
    packed.update({"duration":plan.duration_days,"price":plan.price_toman,"volume_gb":subscription.volume_gb,"config_name":subscription.config_name,"devices":subscription.devices,"subscription_id":subscription.id}); await state.update_data(subscription_data=packed); await callback.answer()
    await callback.message.edit_text("💳 <b>انتخاب روش پرداخت افزایش زمان</b>\n\n"+f"📦 <b>سرویس:</b> <code>{subscription.config_name}</code>\n"+f"💾 <b>حجم:</b> {subscription.volume_gb} GB\n"+f"📅 <b>مدت:</b> {plan.duration_days} روز\n"+f"💰 <b>مبلغ:</b> {plan.price_toman:,} تومان\n\n"+"روش پرداخت را انتخاب کنید:",reply_markup=_payment_keyboard(subscription.id,plan.id,plan.price_toman,gateway_factory.get_gateways()))
