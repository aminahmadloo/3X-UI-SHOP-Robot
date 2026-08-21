from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.utils.navigation import NavAdminTools
from app.db.models import ServicePurchasePlan
from app.db.models.service_period import ServicePeriod

router = Router(name=__name__)


def month_label(months: int):
    labels = {
        1: "یک ماهه",
        2: "دو ماهه",
        3: "سه ماهه",
        6: "شش ماهه",
        12: "دوازده ماهه",
    }
    return labels.get(months, f"{months} ماهه")


class PeriodStates(StatesGroup):
    months = State()
    volume = State()
    price = State()
    edit_volume = State()
    edit_price = State()


def _home(): return InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavAdminTools.MAIN)
def _back(): return InlineKeyboardButton(text="🔙 تنظیمات خرید سرویس|حجم سرویس|زمان سرویس", callback_data=NavAdminTools.SERVICE_PURCHASE_MANAGEMENT)

def _periods_kb(periods):
    b=InlineKeyboardBuilder()
    for p in periods:
        b.row(InlineKeyboardButton(text=f"{'🟢' if p.is_active else '🔴'} {p.name}", callback_data=f"sp:view:{p.id}"))
    b.row(InlineKeyboardButton(text="➕ ایجاد دوره جدید", callback_data="sp:create")); b.row(_back()); b.row(_home())
    return b.as_markup()

def _details_kb(p):
    b=InlineKeyboardBuilder(); b.row(InlineKeyboardButton(text="🔴 غیرفعال کردن" if p.is_active else "🟢 فعال کردن", callback_data=f"sp:toggle:{p.id}")); b.row(InlineKeyboardButton(text="⚙️ مدیریت پلن‌ها", callback_data=f"sp:plans:{p.id}")); b.row(InlineKeyboardButton(text="🗑 حذف / آرشیو دوره", callback_data=f"sp:archive:{p.id}")); b.row(InlineKeyboardButton(text="🔙 دوره‌های سرویس", callback_data="sp:management")); return b.as_markup()

def _plans_kb(p, plans):
    b=InlineKeyboardBuilder()
    for x in plans: b.row(InlineKeyboardButton(text=f"{x.volume_gb:,} GB | {x.price_toman:,} تومان | {x.duration_days} روز", callback_data=f"sp:plan:{p.id}:{x.id}"))
    b.row(InlineKeyboardButton(text="➕ ساخت سرویس جدید", callback_data=f"sp:create_plan:{p.id}")); b.row(InlineKeyboardButton(text="🔙 جزئیات دوره", callback_data=f"sp:view:{p.id}")); b.row(_back()); return b.as_markup()

def _plan_details_kb(p,x): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✏️ ویرایش",callback_data=f"sp:edit:{p.id}:{x.id}")],[InlineKeyboardButton(text="🗑 حذف",callback_data=f"sp:delete:{p.id}:{x.id}")],[InlineKeyboardButton(text="🔙 لیست پلن‌ها",callback_data=f"sp:plans:{p.id}")]])

async def _show(callback,session):
    await callback.message.edit_text("🛒 <b>تنظیمات خرید سرویس|حجم سرویس|زمان سرویس</b>\n\n📅 <b>مدیریت دوره‌های سرویس</b>\n\nدوره موردنظر را انتخاب کنید:",reply_markup=_periods_kb(await ServicePeriod.list_manageable(session)))



@router.callback_query(F.data=="service_purchase:periods", IsAdmin())
async def entry(c:CallbackQuery,session:AsyncSession):
    await c.answer()
    await _show(c, session)


@router.callback_query(F.data=="sp:management",IsAdmin())
async def back(callback:CallbackQuery,session:AsyncSession): await callback.answer(); await _show(callback,session)

@router.callback_query(F.data=="sp:create",IsAdmin())
async def create(callback:CallbackQuery,state:FSMContext): await state.clear(); await state.set_state(PeriodStates.months); await callback.answer(); await callback.message.edit_text("➕ <b>ایجاد مدیریت سرویس جدید</b>\n\nتعداد ماه را وارد کنید. مثال: <code>2</code>")

@router.message(PeriodStates.months,IsAdmin())
async def save_period(message:Message,state:FSMContext,session:AsyncSession):
    try: months=int((message.text or '').strip()); assert 1<=months<=120
    except: await message.answer("❌ مدت نامعتبر است."); return
    existing = await ServicePeriod.get_any_by_months(session, months)

    if existing:
        if existing.is_archived:
            existing.is_archived = False
            existing.is_active = True
            await session.commit()
            await message.answer(
                f"✅ دوره <b>{existing.name}</b> دوباره فعال شد."
            )
            return

        await message.answer("❌ این دوره قبلاً ایجاد شده است.")
        return
    st="one_month" if months==1 else "three_month" if months==3 else f"period_{months}m"
    tt="traffic_addon_30" if months==1 else "traffic_addon_90" if months==3 else f"traffic_addon_{months}m"
    p=ServicePeriod(name=f"سرویس‌های {month_label(months)}",months=months,duration_days=months*30,service_type=st,traffic_addon_service_type=tt,is_active=True,is_archived=False,sort_order=months)
    session.add(p); await session.commit(); await state.clear(); await message.answer(f"✅ مدیریت <b>{p.name}</b> ایجاد شد.\n⏱ مدت پایه: <b>{p.duration_days} روز</b>",reply_markup=_details_kb(p))

@router.callback_query(F.data.regexp(r"^sp:view:\d+$"),IsAdmin())
async def view(callback:CallbackQuery,session:AsyncSession):
    p=await ServicePeriod.get(session,int(callback.data.rsplit(':',1)[1]));
    if not p or p.is_archived: await callback.answer("❌ دوره پیدا نشد.",show_alert=True); return
    plans=await ServicePurchasePlan.list_by_type(session,p.service_type); await callback.answer(); await callback.message.edit_text(f"📅 <b>{p.name}</b>\n\n⏱ مدت: <b>{p.duration_days} روز</b>\n📦 تعداد پلن‌ها: <b>{len(plans)}</b>\n{'🟢 فعال' if p.is_active else '🔴 غیرفعال'}",reply_markup=_details_kb(p))

@router.callback_query(F.data.regexp(r"^sp:toggle:\d+$"),IsAdmin())
async def toggle(callback:CallbackQuery,session:AsyncSession):
    p=await ServicePeriod.get(session,int(callback.data.rsplit(':',1)[1]));
    if not p: await callback.answer("❌ دوره پیدا نشد.",show_alert=True); return
    p.is_active=not p.is_active; await session.commit(); await callback.answer("✅ وضعیت تغییر کرد"); await callback.message.edit_text(f"📅 <b>{p.name}</b>\n\n{'🟢 فعال' if p.is_active else '🔴 غیرفعال'}",reply_markup=_details_kb(p))

@router.callback_query(F.data.regexp(r"^sp:archive:\d+$"),IsAdmin())
async def archive(callback:CallbackQuery,session:AsyncSession):
    p=await ServicePeriod.get(session,int(callback.data.rsplit(':',1)[1]));
    if not p: await callback.answer("❌ دوره پیدا نشد.",show_alert=True); return
    p.is_active=False; p.is_archived=True; await session.commit(); await callback.answer("✅ دوره آرشیو شد"); await _show(callback,session)

@router.callback_query(F.data.regexp(r"^sp:plans:\d+$"),IsAdmin())
async def plans(callback:CallbackQuery,session:AsyncSession):
    p=await ServicePeriod.get(session,int(callback.data.rsplit(':',1)[1]));
    if not p or p.is_archived: await callback.answer("❌ دوره پیدا نشد.",show_alert=True); return
    xs=await ServicePurchasePlan.list_by_type(session,p.service_type); await callback.answer(); await callback.message.edit_text(f"📦 <b>مدیریت پلن‌های {p.name}</b>\n\nتعداد: <b>{len(xs)}</b>",reply_markup=_plans_kb(p,xs))

@router.callback_query(F.data.regexp(r"^sp:create_plan:\d+$"),IsAdmin())
async def create_plan(callback:CallbackQuery,state:FSMContext,session:AsyncSession):
    p=await ServicePeriod.get(session,int(callback.data.rsplit(':',1)[1]));
    if not p or p.is_archived: await callback.answer("❌ دوره پیدا نشد.",show_alert=True); return
    await state.clear(); await state.update_data(period_id=p.id); await state.set_state(PeriodStates.volume); await callback.answer(); await callback.message.edit_text(f"➕ <b>ساخت پلن {p.name}</b>\n\nمدت به‌صورت خودکار <b>{p.duration_days} روز</b> است.\nحجم را به GB وارد کنید:")

@router.message(PeriodStates.volume,IsAdmin())
async def plan_volume(message:Message,state:FSMContext):
    try: v=int((message.text or '').replace(',','').replace('٬','')); assert v>0
    except: await message.answer("❌ حجم نامعتبر است."); return
    await state.update_data(volume=v); await state.set_state(PeriodStates.price); await message.answer("💰 قیمت را به تومان وارد کنید:")

@router.message(PeriodStates.price,IsAdmin())
async def plan_price(message:Message,state:FSMContext,session:AsyncSession):
    try: price=int((message.text or '').replace(',','').replace('٬','')); assert price>=0
    except: await message.answer("❌ قیمت نامعتبر است."); return
    d=await state.get_data(); p=await ServicePeriod.get(session,int(d['period_id']))
    if not p: await state.clear(); await message.answer("❌ دوره پیدا نشد."); return
    x=ServicePurchasePlan(service_type=p.service_type,volume_gb=int(d['volume']),duration_days=p.duration_days,price_toman=price); session.add(x); await session.commit(); await state.clear(); await message.answer("✅ پلن ساخته شد.",reply_markup=_plans_kb(p,await ServicePurchasePlan.list_by_type(session,p.service_type)))

@router.callback_query(F.data.regexp(r"^sp:plan:\d+:\d+$"),IsAdmin())
async def plan_details(callback:CallbackQuery,session:AsyncSession):
    _,_,pid,xid=callback.data.split(':'); p=await ServicePeriod.get(session,int(pid)); x=await ServicePurchasePlan.get(session,int(xid))
    if not p or not x or x.service_type!=p.service_type: await callback.answer("❌ پلن پیدا نشد.",show_alert=True); return
    await callback.answer(); await callback.message.edit_text(f"📦 <b>{p.name}</b>\n\n➕ حجم: <b>{x.volume_gb} GB</b>\n⏱ مدت: <b>{x.duration_days} روز</b>\n💰 قیمت: <b>{x.price_toman:,} تومان</b>",reply_markup=_plan_details_kb(p,x))

@router.callback_query(F.data.regexp(r"^sp:edit:\d+:\d+$"),IsAdmin())
async def edit(callback:CallbackQuery,state:FSMContext,session:AsyncSession):
    _,_,pid,xid=callback.data.split(':'); p=await ServicePeriod.get(session,int(pid)); x=await ServicePurchasePlan.get(session,int(xid))
    if not p or not x or x.service_type!=p.service_type: await callback.answer("❌ پلن پیدا نشد.",show_alert=True); return
    await state.clear(); await state.update_data(period_id=p.id,plan_id=x.id); await state.set_state(PeriodStates.edit_volume); await callback.answer(); await callback.message.edit_text(f"✏️ حجم فعلی: <b>{x.volume_gb} GB</b>\n\nحجم جدید را وارد کنید:")

@router.message(PeriodStates.edit_volume,IsAdmin())
async def edit_volume(message:Message,state:FSMContext):
    try: v=int((message.text or '').replace(',','').replace('٬','')); assert v>0
    except: await message.answer("❌ حجم نامعتبر است."); return
    await state.update_data(volume=v); await state.set_state(PeriodStates.edit_price); await message.answer("💰 قیمت جدید را وارد کنید:")

@router.message(PeriodStates.edit_price,IsAdmin())
async def edit_price(message:Message,state:FSMContext,session:AsyncSession):
    try: price=int((message.text or '').replace(',','').replace('٬','')); assert price>=0
    except: await message.answer("❌ قیمت نامعتبر است."); return
    d=await state.get_data(); p=await ServicePeriod.get(session,int(d['period_id'])); x=await ServicePurchasePlan.get(session,int(d['plan_id']))
    if not p or not x or x.service_type!=p.service_type: await state.clear(); await message.answer("❌ پلن پیدا نشد."); return
    x.volume_gb=int(d['volume']); x.price_toman=price; x.duration_days=p.duration_days; await session.commit(); await state.clear(); await message.answer("✅ پلن ویرایش شد.",reply_markup=_plan_details_kb(p,x))

@router.callback_query(F.data.regexp(r"^sp:delete:\d+:\d+$"),IsAdmin())
async def delete_plan(callback:CallbackQuery,session:AsyncSession):
    _,_,pid,xid=callback.data.split(':'); p=await ServicePeriod.get(session,int(pid)); x=await ServicePurchasePlan.get(session,int(xid))
    if not p or not x or x.service_type!=p.service_type: await callback.answer("❌ پلن پیدا نشد.",show_alert=True); return
    await session.delete(x); await session.commit(); await callback.answer("✅ پلن حذف شد"); await callback.message.edit_text(f"📦 <b>مدیریت پلن‌های {p.name}</b>",reply_markup=_plans_kb(p,await ServicePurchasePlan.list_by_type(session,p.service_type)))
