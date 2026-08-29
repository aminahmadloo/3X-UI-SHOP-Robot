from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from app.bot.models import SubscriptionData
from app.bot.routers.subscription.keyboard import service_purchase_plan_keyboard
from app.bot.utils.navigation import NavMain, NavSubscription
from app.db.models import ConnectedDeviceSettings, ServicePurchasePlan
from app.db.models.service_period import ServicePeriod

router=Router(name=__name__)

def _home(): return InlineKeyboardButton(text="🏠 منوی اصلی",callback_data=NavMain.MAIN_MENU)

def _periods_kb(periods,devices):
    b=InlineKeyboardBuilder(); user_text="کاربر نامحدود" if devices==0 else f"{devices} کاربره"
    for p in periods: b.row(InlineKeyboardButton(text=f"🚀 {p.name.replace('سرویس‌های ','')} | {user_text}",callback_data=f"dynamic_purchase:period:{p.id}"))
    b.row(_home()); return b.as_markup()

async def _show(callback,session,user):
    settings=await ConnectedDeviceSettings.get_or_create(session); active=[]
    for p in await ServicePeriod.list_active(session):
        if await ServicePurchasePlan.list_by_type(session,p.service_type): active.append(p)
    if not active:
        await callback.message.edit_text("🛒 <b>خرید سرویس جدید</b>\n\nدر حال حاضر هیچ دوره فعالی با پلن فروش ثبت‌شده وجود ندارد.",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_home()]])); return
    await callback.message.edit_text("🛒 <b>خرید سرویس جدید</b>\n\nمدت سرویس مورد نظر را انتخاب کنید:",reply_markup=_periods_kb(active,settings.max_connected_devices))

@router.callback_query(F.data==NavSubscription.BUY)
async def entry(callback:CallbackQuery,session:AsyncSession,user,state:FSMContext): await state.clear(); await callback.answer(); await _show(callback,session,user)

@router.callback_query(F.data.regexp(r"^dynamic_purchase:period:\d+$"))
async def period(callback:CallbackQuery,session:AsyncSession,user):
    p=await ServicePeriod.get(session,int(callback.data.rsplit(':',1)[1]))
    if not p or not p.is_active or p.is_archived: await callback.answer("❌ این دوره دیگر فعال نیست.",show_alert=True); return
    plans=await ServicePurchasePlan.list_by_type(session,p.service_type)
    if not plans: await callback.answer("برای این دوره هنوز پلنی ثبت نشده است.",show_alert=True); return
    settings=await ConnectedDeviceSettings.get_or_create(session); data=SubscriptionData(state=NavSubscription.PLAN,user_id=user.tg_id,devices=settings.max_connected_devices)
    await callback.answer(); await callback.message.edit_text(f"📅 <b>پلن‌های {p.name}</b>\n\nمدت پایه: <b>{p.duration_days} روز</b>\n\nلطفاً پلن مورد نظر را انتخاب کنید:",reply_markup=service_purchase_plan_keyboard(plans,data,p.id))

@router.callback_query(F.data.regexp(r"^subscription_back_plan:\d+$"))
async def back_plan(callback:CallbackQuery,session:AsyncSession,user):
    x=await ServicePurchasePlan.get(session,int(callback.data.rsplit(':',1)[1]));
    if not x: await callback.answer("این پلن دیگر وجود ندارد.",show_alert=True); return
    p=next((p for p in await ServicePeriod.list_active(session) if p.service_type==x.service_type),None)
    if not p: await callback.answer("این دوره دیگر فعال نیست.",show_alert=True); return
    plans=await ServicePurchasePlan.list_by_type(session,p.service_type); settings=await ConnectedDeviceSettings.get_or_create(session); data=SubscriptionData(state=NavSubscription.PLAN,user_id=user.tg_id,devices=settings.max_connected_devices)
    await callback.answer(); await callback.message.edit_text(f"📅 <b>پلن‌های {p.name}</b>\n\nلطفاً پلن مورد نظر را انتخاب کنید:",reply_markup=service_purchase_plan_keyboard(plans,data,p.id))
