from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State,StatesGroup
from aiogram.types import CallbackQuery,InlineKeyboardButton,InlineKeyboardMarkup,Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from app.bot.filters import IsAdmin
from app.bot.utils.navigation import NavAdminTools
from app.db.models import ServicePurchasePlan
from app.db.models.service_period import ServicePeriod
router=Router(name=__name__)
class TrafficStates(StatesGroup): volume=State(); price=State(); edit_volume=State(); edit_price=State()
def _home(): return InlineKeyboardButton(text="🏠 منوی اصلی",callback_data=NavAdminTools.MAIN)
def _purchase(): return InlineKeyboardButton(text="🔙 مدیریت خرید سرویس",callback_data=NavAdminTools.SERVICE_PURCHASE_MANAGEMENT)
async def _plans(s,p): return sorted([x for x in await ServicePurchasePlan.list_by_type(s,p.traffic_addon_service_type) if x.duration_days==0 and x.volume_gb>0 and x.price_toman>0],key=lambda x:(x.volume_gb,x.price_toman,x.id))
def _periods(ps):
 b=InlineKeyboardBuilder()
 for p in ps:b.row(InlineKeyboardButton(text=f"{'🟢' if p.is_active else '🔴'} {p.name}",callback_data=f"ta:period:{p.id}"))
 b.row(_purchase());b.row(_home());return b.as_markup()
def _plans_kb(p,xs):
 b=InlineKeyboardBuilder()
 for x in xs:b.row(InlineKeyboardButton(text=f"{x.volume_gb:,} GB | {x.price_toman:,} تومان",callback_data=f"ta:plan:{p.id}:{x.id}"))
 b.row(InlineKeyboardButton(text="➕ ساخت بسته افزایش حجم",callback_data=f"ta:create:{p.id}"));b.row(InlineKeyboardButton(text="🔙 دوره‌ها",callback_data="ta:management"));return b.as_markup()
def _detail(p,x): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✏️ ویرایش حجم",callback_data=f"ta:ev:{p.id}:{x.id}")],[InlineKeyboardButton(text="💰 ویرایش قیمت",callback_data=f"ta:ep:{p.id}:{x.id}")],[InlineKeyboardButton(text="🗑 حذف",callback_data=f"ta:del:{p.id}:{x.id}")],[InlineKeyboardButton(text="🔙 لیست",callback_data=f"ta:period:{p.id}")]])
async def _show(c,s): await c.message.edit_text("📈 <b>مدیریت افزایش حجم</b>\n\nدوره موردنظر را انتخاب کنید:",reply_markup=_periods(await ServicePeriod.list_manageable(s)))
@router.callback_query(F.data=="traffic_admin:management",IsAdmin())
async def entry(c:CallbackQuery,s:AsyncSession): await c.answer();await _show(c,s)
@router.callback_query(F.data=="ta:management",IsAdmin())
async def back(c:CallbackQuery,s:AsyncSession): await c.answer();await _show(c,s)
@router.callback_query(F.data.regexp(r"^ta:period:\d+$"),IsAdmin())
async def period(c:CallbackQuery,s:AsyncSession,state:FSMContext):
 p=await ServicePeriod.get(s,int(c.data.rsplit(':',1)[1]));
 if not p or p.is_archived: await c.answer("❌ دوره پیدا نشد.",show_alert=True);return
 xs=await _plans(s,p);await c.answer();await c.message.edit_text(f"📈 <b>مدیریت افزایش حجم {p.name}</b>\n\nتعداد بسته‌ها: <b>{len(xs)}</b>",reply_markup=_plans_kb(p,xs))
@router.callback_query(F.data.regexp(r"^ta:create:\d+$"),IsAdmin())
async def create(c:CallbackQuery,s:AsyncSession,state:FSMContext):
 p=await ServicePeriod.get(s,int(c.data.rsplit(':',1)[1]));
 if not p: await c.answer("❌ دوره پیدا نشد.",show_alert=True);return
 await state.clear();await state.update_data(period_id=p.id);await state.set_state(TrafficStates.volume);await c.answer();await c.message.edit_text(f"➕ <b>ساخت بسته افزایش حجم {p.name}</b>\n\nحجم را به GB وارد کنید:")
@router.message(TrafficStates.volume,IsAdmin())
async def vol(m:Message,state:FSMContext):
 try:v=int((m.text or '').replace(',','').replace('٬',''));assert v>0
 except:await m.answer("❌ حجم نامعتبر است.");return
 await state.update_data(volume=v);await state.set_state(TrafficStates.price);await m.answer("💰 قیمت را به تومان وارد کنید:")
@router.message(TrafficStates.price,IsAdmin())
async def price(m:Message,state:FSMContext,s:AsyncSession):
 try:price=int((m.text or '').replace(',','').replace('٬',''));assert price>0
 except:await m.answer("❌ قیمت نامعتبر است.");return
 d=await state.get_data();p=await ServicePeriod.get(s,int(d['period_id']));x=ServicePurchasePlan(service_type=p.traffic_addon_service_type,volume_gb=int(d['volume']),duration_days=0,price_toman=price);s.add(x);await s.commit();await state.clear();await m.answer("✅ بسته ساخته شد.",reply_markup=_plans_kb(p,await _plans(s,p)))
@router.callback_query(F.data.regexp(r"^ta:plan:\d+:\d+$"),IsAdmin())
async def detail(c:CallbackQuery,s:AsyncSession):
 _,_,pid,xid=c.data.split(':');p=await ServicePeriod.get(s,int(pid));x=await ServicePurchasePlan.get(s,int(xid));
 if not p or not x or x.service_type!=p.traffic_addon_service_type:await c.answer("❌ بسته پیدا نشد.",show_alert=True);return
 await c.answer();await c.message.edit_text(f"📈 <b>{p.name}</b>\n\n➕ {x.volume_gb} GB\n💰 {x.price_toman:,} تومان",reply_markup=_detail(p,x))
@router.callback_query(F.data.regexp(r"^ta:ev:\d+:\d+$"),IsAdmin())
async def ev(c:CallbackQuery,s:AsyncSession,state:FSMContext):
 _,_,pid,xid=c.data.split(':');p=await ServicePeriod.get(s,int(pid));x=await ServicePurchasePlan.get(s,int(xid));
 if not p or not x or x.service_type!=p.traffic_addon_service_type:await c.answer("❌ بسته پیدا نشد.",show_alert=True);return
 await state.clear();await state.update_data(period_id=p.id,plan_id=x.id);await state.set_state(TrafficStates.edit_volume);await c.answer();await c.message.edit_text(f"حجم فعلی: <b>{x.volume_gb} GB</b>\n\nحجم جدید:")
@router.message(TrafficStates.edit_volume,IsAdmin())
async def save_ev(m:Message,state:FSMContext,s:AsyncSession):
 try:v=int((m.text or '').replace(',','').replace('٬',''));assert v>0
 except:await m.answer("❌ حجم نامعتبر است.");return
 d=await state.get_data();x=await ServicePurchasePlan.get(s,int(d['plan_id']));x.volume_gb=v;await s.commit();p=await ServicePeriod.get(s,int(d['period_id']));await state.clear();await m.answer("✅ حجم تغییر کرد.",reply_markup=_plans_kb(p,await _plans(s,p)))
@router.callback_query(F.data.regexp(r"^ta:ep:\d+:\d+$"),IsAdmin())
async def ep(c:CallbackQuery,s:AsyncSession,state:FSMContext):
 _,_,pid,xid=c.data.split(':');p=await ServicePeriod.get(s,int(pid));x=await ServicePurchasePlan.get(s,int(xid));
 if not p or not x or x.service_type!=p.traffic_addon_service_type:await c.answer("❌ بسته پیدا نشد.",show_alert=True);return
 await state.clear();await state.update_data(period_id=p.id,plan_id=x.id);await state.set_state(TrafficStates.edit_price);await c.answer();await c.message.edit_text(f"قیمت فعلی: <b>{x.price_toman:,}</b> تومان\n\nقیمت جدید:")
@router.message(TrafficStates.edit_price,IsAdmin())
async def save_ep(m:Message,state:FSMContext,s:AsyncSession):
 try:v=int((m.text or '').replace(',','').replace('٬',''));assert v>0
 except:await m.answer("❌ قیمت نامعتبر است.");return
 d=await state.get_data();x=await ServicePurchasePlan.get(s,int(d['plan_id']));x.price_toman=v;await s.commit();p=await ServicePeriod.get(s,int(d['period_id']));await state.clear();await m.answer("✅ قیمت تغییر کرد.",reply_markup=_plans_kb(p,await _plans(s,p)))
@router.callback_query(F.data.regexp(r"^ta:del:\d+:\d+$"),IsAdmin())
async def delete(c:CallbackQuery,s:AsyncSession):
 _,_,pid,xid=c.data.split(':');p=await ServicePeriod.get(s,int(pid));x=await ServicePurchasePlan.get(s,int(xid));
 if not p or not x or x.service_type!=p.traffic_addon_service_type:await c.answer("❌ بسته پیدا نشد.",show_alert=True);return
 await s.delete(x);await s.commit();await c.answer("✅ حذف شد");await c.message.edit_text(f"📈 <b>مدیریت افزایش حجم {p.name}</b>",reply_markup=_plans_kb(p,await _plans(s,p)))
