from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.bot.models import ServicesContainer
from app.bot.payment_gateways import GatewayFactory
from app.bot.routers.my_services.handler import _status,_sync_subscriptions_with_xui
from app.bot.routers.subscription.dynamic_renewal_handler import _original_plan
from app.bot.routers.subscription.keyboard import managed_payment_method_keyboard_traffic
from app.bot.services.renewal import is_traffic_addon_type
from app.bot.utils.navigation import NavMain,NavSubscription
from app.db.models import Server,ServicePurchasePlan,Subscription
from app.db.models.service_period import ServicePeriod

router=Router(name=__name__)
def _home(): return InlineKeyboardButton(text="🏠 منوی اصلی",callback_data=NavMain.MAIN_MENU)
def _services(xs):
    b=InlineKeyboardBuilder()
    for x in xs:
        icon,status=_status(x); b.row(InlineKeyboardButton(text=f"{icon} {x.config_name} | {x.volume_gb}GB | {status}",callback_data=f"traffic:add:{x.id}"))
    b.row(_home()); return b.as_markup()
async def _sub(session,user,sid,services):
    r=await session.execute(select(Subscription).join(Server,Subscription.server_id==Server.id).options(selectinload(Subscription.server)).where(Subscription.id==sid,Subscription.user_id==user.id,Subscription.server_id.is_not(None))); x=r.scalar_one_or_none()
    if not x:return None
    z=await _sync_subscriptions_with_xui(session,[x],services); return z[0] if z else None
async def _period(session,days):
    ps=await ServicePeriod.list_active(session); return min(ps,key=lambda p:abs(p.duration_days-days)) if ps else None
async def _plans(session,p): return sorted([x for x in await ServicePurchasePlan.list_by_type(session,p.traffic_addon_service_type) if is_traffic_addon_type(x.service_type) and x.duration_days==0 and x.volume_gb>0 and x.price_toman>0],key=lambda x:(x.volume_gb,x.price_toman,x.id))

def _plans_kb(sid,xs):
    b=InlineKeyboardBuilder()
    for x in xs:b.row(InlineKeyboardButton(text=f"➕ {x.volume_gb:,} GB | {x.price_toman:,} تومان",callback_data=f"traffic:plan:{sid}:{x.id}"))
    b.row(InlineKeyboardButton(text="🔙 بازگشت به سرویس",callback_data=f"my_services:view:{sid}")); b.row(_home()); return b.as_markup()

def _summary(sid,pid): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 انتخاب روش پرداخت",callback_data=f"traffic:payment:{sid}:{pid}")],[InlineKeyboardButton(text="🔙 تغییر حجم",callback_data=f"traffic:add:{sid}")],[_home()]])

@router.callback_query(F.data==NavSubscription.ADD_TRAFFIC)
async def entry(callback:CallbackQuery,user,session:AsyncSession,services:ServicesContainer):
    r=await session.execute(select(Subscription).join(Server,Subscription.server_id==Server.id).options(selectinload(Subscription.server)).where(Subscription.user_id==user.id,Subscription.server_id.is_not(None)).order_by(Subscription.id.desc())); xs=await _sync_subscriptions_with_xui(session,list(r.scalars().all()),services); xs=[x for x in xs if x.status=="active" and _status(x)[1] in {"فعال","رو به اتمام"}]; await callback.answer()
    if not xs: await callback.message.edit_text("📈 <b>افزایش حجم سرویس</b>\n\nشما در حال حاضر هیچ سرویس فعالی برای افزایش حجم ندارید.",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_home()]])); return
    lines=[]
    for p in await ServicePeriod.list_active(session):
        ps=await _plans(session,p); lines.append(f"💰 مبلغ هر گیگابایت حجم {p.name.replace('سرویس‌های ','')}: <b>{min((x.price_toman/x.volume_gb for x in ps),default=0):,.0f} تومان/GB</b>" if ps else f"💰 مبلغ هر گیگابایت حجم {p.name.replace('سرویس‌های ','')}: <b>فعال نیست</b>")
    await callback.message.edit_text("📈 <b>افزایش حجم سرویس</b>\n\n"+"\n".join(lines)+"\n\nسرویسی را که می‌خواهید حجم آن را افزایش دهید انتخاب کنید:",reply_markup=_services(xs))

@router.callback_query(F.data.regexp(r"^traffic:add:\d+$"))
async def add(callback:CallbackQuery,user,session:AsyncSession,services:ServicesContainer):
    x=await _sub(session,user,int(callback.data.rsplit(':',1)[1]),services)
    if not x or x.status!="active" or _status(x)[1]=="منقضی شده": await callback.answer("❌ این سرویس فعال نیست.",show_alert=True); return
    original_plan=await _original_plan(session,x)
    if not original_plan: await callback.answer("❌ پلن اولیه این سرویس قابل تشخیص نیست. لطفاً اطلاعات خرید اولیه سرویس را بررسی کنید.",show_alert=True); return
    if x.plan_id != original_plan.id:
        x.plan_id=original_plan.id
        await session.commit()
    p=await _period(session,original_plan.duration_days)
    if not p: await callback.answer("❌ دوره پلن اولیه این سرویس فعال نیست.",show_alert=True); return
    ps=await _plans(session,p); await callback.answer()
    if not ps: await callback.message.edit_text(f"📈 <b>افزایش حجم {p.name}</b>\n\nدر حال حاضر هیچ بسته افزایش حجمی برای این دوره فعال نشده است.",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت به سرویس",callback_data=f"my_services:view:{x.id}")],[_home()]])); return
    cd=await services.vpn.get_client_data(user,subscription_id=x.id); total=cd.traffic_total_formatted if cd else f"{x.volume_gb} GB"; remain=cd.traffic_remaining_formatted if cd else "در دسترس نیست"
    await callback.message.edit_text(f"📈 <b>افزایش حجم سرویس {p.name.replace('سرویس‌های ','')}</b>\n\n📦 سرویس: <code>{x.config_name}</code>\n💾 حجم کل فعلی: {total}\n📊 حجم باقی‌مانده: {remain}\n\nمقدار حجمی که می‌خواهید اضافه شود را انتخاب کنید:",reply_markup=_plans_kb(x.id,ps))

@router.callback_query(F.data.regexp(r"^traffic:plan:\d+:\d+$"))
async def plan(callback:CallbackQuery,user,session:AsyncSession,services:ServicesContainer,state:FSMContext):
    _,_,sid,pid=callback.data.split(':'); x=await _sub(session,user,int(sid),services); original_plan=await _original_plan(session,x) if x else None; p=await _period(session,original_plan.duration_days) if original_plan else None; z=await ServicePurchasePlan.get(session,int(pid))
    if not x or not original_plan or not p or not z or z.service_type!=p.traffic_addon_service_type or z.duration_days!=0: await callback.answer("❌ بسته افزایش حجم نامعتبر است.",show_alert=True); return
    if x.plan_id != original_plan.id:
        x.plan_id=original_plan.id
        await session.commit()
    await state.update_data(subscription_data={"state":"config_name","is_extend":True,"is_change":False,"user_id":user.tg_id,"devices":x.devices,"duration":0,"price":z.price_toman,"plan_id":z.id,"volume_gb":z.volume_gb,"config_name":x.config_name,"subscription_id":x.id}); cd=await services.vpn.get_client_data(user,subscription_id=x.id); total=cd.traffic_total_formatted if cd else f"{x.volume_gb} GB"; remain=cd.traffic_remaining_formatted if cd else "در دسترس نیست"; await callback.answer(); await callback.message.edit_text("🧾 <b>خلاصه سفارش افزایش حجم</b>\n\n"+f"📦 سرویس: <code>{x.config_name}</code>\n💾 حجم کل فعلی: {total}\n📊 حجم باقی‌مانده: {remain}\n➕ حجم افزوده‌شده: <b>{z.volume_gb} GB</b>\n💰 مبلغ: <b>{z.price_toman:,} تومان</b>\n\nزمان انقضا و مشخصات اتصال تغییر نمی‌کند.",reply_markup=_summary(x.id,z.id))

@router.callback_query(F.data.regexp(r"^traffic:payment:\d+:\d+$"))
async def payment(callback:CallbackQuery,user,session:AsyncSession,services:ServicesContainer,state:FSMContext,gateway_factory:GatewayFactory):
    _,_,sid,pid=callback.data.split(':'); data=(await state.get_data()).get('subscription_data');
    if not isinstance(data,dict) or int(data.get('subscription_id',0))!=int(sid) or int(data.get('plan_id',0))!=int(pid): await state.clear(); await callback.answer("❌ اطلاعات سفارش منقضی شده است.",show_alert=True); return
    x=await _sub(session,user,int(sid),services); original_plan=await _original_plan(session,x) if x else None; p=await _period(session,original_plan.duration_days) if original_plan else None; z=await ServicePurchasePlan.get(session,int(pid))
    if not x or not original_plan or not p or not z or z.service_type!=p.traffic_addon_service_type: await state.clear(); await callback.answer("❌ سرویس یا بسته دیگر معتبر نیست.",show_alert=True); return
    if x.plan_id != original_plan.id:
        x.plan_id=original_plan.id
        await session.commit()
    data.update(price=z.price_toman,volume_gb=z.volume_gb,duration=0,config_name=x.config_name,devices=x.devices,subscription_id=x.id); await state.update_data(subscription_data=data); await callback.answer(); await callback.message.edit_text("💳 <b>انتخاب روش پرداخت افزایش حجم</b>\n\n"+f"📦 سرویس: <code>{x.config_name}</code>\n➕ حجم افزوده: <b>{z.volume_gb} GB</b>\n💰 مبلغ: <b>{z.price_toman:,} تومان</b>\n\nروش پرداخت را انتخاب کنید:",reply_markup=managed_payment_method_keyboard_traffic(x.id,z.id,z.price_toman,gateway_factory.get_gateways()))
