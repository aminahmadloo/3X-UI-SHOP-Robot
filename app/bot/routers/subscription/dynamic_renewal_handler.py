from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.bot.models import ServicesContainer
from app.bot.routers.my_services.handler import _status,_sync_subscriptions_with_xui
from app.bot.utils.navigation import NavMain,NavSubscription
from app.db.models import Server,ServicePurchasePlan,Subscription
from app.db.models.service_period import ServicePeriod

router=Router(name=__name__)
def _home(): return InlineKeyboardButton(text="🏠 منوی اصلی",callback_data=NavMain.MAIN_MENU)
def _services(xs):
    b=InlineKeyboardBuilder()
    for x in xs:
        icon,status=_status(x); b.row(InlineKeyboardButton(text=f"{icon} {x.config_name} | {x.volume_gb}GB | {status}",callback_data=f"renewal:service:{x.id}"))
    b.row(InlineKeyboardButton(text="🛒 خرید سرویس جدید",callback_data=NavSubscription.BUY)); b.row(_home()); return b.as_markup()
async def _get(session,user,sid,services):
    r=await session.execute(select(Subscription).join(Server,Subscription.server_id==Server.id).options(selectinload(Subscription.server)).where(Subscription.id==sid,Subscription.user_id==user.id,Subscription.server_id.is_not(None))); x=r.scalar_one_or_none()
    if not x:return None
    z=await _sync_subscriptions_with_xui(session,[x],services); return z[0] if z else None
async def _period(session,days):
    ps=await ServicePeriod.list_active(session); return min(ps,key=lambda p:abs(p.duration_days-days)) if ps else None

@router.callback_query(F.data==NavSubscription.RENEW_SERVICE)
async def entry(callback:CallbackQuery,user,session:AsyncSession,services:ServicesContainer,state:FSMContext):
    await state.clear(); r=await session.execute(select(Subscription).join(Server,Subscription.server_id==Server.id).options(selectinload(Subscription.server)).where(Subscription.user_id==user.id,Subscription.server_id.is_not(None)).order_by(Subscription.id.desc())); xs=await _sync_subscriptions_with_xui(session,list(r.scalars().all()),services); xs=[x for x in xs if _status(x)[1] in {"فعال","رو به اتمام","منقضی شده"}]; await callback.answer()
    if not xs: await callback.message.edit_text("🔄 <b>تمدید سرویس</b>\n\nشما در حال حاضر سرویس قابل تمدیدی ندارید.",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_home()]])); return
    await callback.message.edit_text("🔄 <b>تمدید سرویس</b>\n\nسرویسی را که می‌خواهید تمدید کنید انتخاب کنید:",reply_markup=_services(xs))

@router.callback_query(F.data.regexp(r"^renewal:service:\d+$"))
async def service(callback:CallbackQuery,user,session:AsyncSession,services:ServicesContainer):
    x=await _get(session,user,int(callback.data.rsplit(':',1)[1]),services)
    if not x: await callback.answer("❌ سرویس پیدا نشد.",show_alert=True); return
    p=await _period(session,x.duration_days)
    if not p: await callback.answer("❌ هیچ دوره فعالی برای این سرویس وجود ندارد.",show_alert=True); return
    plans=await ServicePurchasePlan.list_by_type(session,p.service_type); plans=[z for z in plans if z.volume_gb==x.volume_gb and z.duration_days>0]; plans.sort(key=lambda z:(z.duration_days,z.id)); await callback.answer()
    b=InlineKeyboardBuilder()
    for z in plans: b.row(InlineKeyboardButton(text=f"📅 {z.duration_days} روز | {z.price_toman:,} تومان",callback_data=f"renewal:plan:{x.id}:{z.id}"))
    b.row(InlineKeyboardButton(text="🔙 تغییر سرویس",callback_data=NavSubscription.RENEW_SERVICE)); b.row(_home())
    await callback.message.edit_text(f"🔄 <b>انتخاب مدت تمدید {p.name}</b>\n\n📦 سرویس: <code>{x.config_name}</code>\n💾 حجم: <b>{x.volume_gb} GB</b>",reply_markup=b.as_markup())
