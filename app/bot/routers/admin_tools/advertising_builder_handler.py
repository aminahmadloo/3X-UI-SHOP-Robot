import asyncio
import logging
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.states.advertising import AdvertisingStates
from app.bot.utils.constants import TransactionStatus
from app.bot.utils.navigation import NavAdminTools
from app.db.models import AdvertisingCampaign, AdvertisingChannel, AdvertisingEvent, AdvertisingPublication, ServicePeriod, ServicePurchasePlan, Transaction

logger = logging.getLogger(__name__)
router = Router(name=__name__)
BUTTON_STYLES = {"green": "success", "red": "danger", "blue": "primary", "none": None}
STYLE_NAMES = {"green": "🟢 سبز", "red": "🔴 قرمز", "blue": "🔵 آبی", "none": "⚪ بدون رنگ"}
AUTO_DELETE_SECONDS = 4


def fmt(value: int) -> str:
    return f"{value:,}".translate(str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬"))


def offer_key(period_id: int, plan_id: int) -> str:
    return f"{period_id}:{plan_id}"


def valid_url(value: str) -> bool:
    try:
        value = value.strip()
        if value.startswith("@"): return True
        if value.startswith("t.me/"): value = "https://" + value
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https", "tg"} and bool(parsed.netloc or parsed.scheme == "tg")
    except ValueError:
        return False


def normalize_url(value: str) -> str:
    value = value.strip()
    if value.startswith("@"): return f"https://t.me/{value[1:]}"
    if value.startswith("t.me/"): return f"https://{value}"
    return value


def menu_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➕ افزودن کانال", callback_data="advertising:add_channel"))
    b.row(InlineKeyboardButton(text="📣 ساخت تبلیغ", callback_data="advertising:create"))
    b.row(InlineKeyboardButton(text="📊 گزارش تبلیغات", callback_data="advertising:stats"))
    b.row(InlineKeyboardButton(text="📋 مدیریت کانال‌ها", callback_data="advertising:channels"))
    b.row(InlineKeyboardButton(text="🏠 منوی مدیریت", callback_data=NavAdminTools.MAIN))
    return b.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ لغو", callback_data="advertising:cancel")]])


def content_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 فقط متن", callback_data="advertising:content:text")],
        [InlineKeyboardButton(text="🖼 عکس + متن", callback_data="advertising:content:photo")],
        [InlineKeyboardButton(text="🎬 ویدئو + متن", callback_data="advertising:content:video")],
        [InlineKeyboardButton(text="❌ لغو", callback_data="advertising:cancel")],
    ])


async def delete_later(message: Message | None, delay: float = AUTO_DELETE_SECONDS) -> None:
    if not message: return
    await asyncio.sleep(delay)
    try: await message.delete()
    except Exception: pass


async def delete_prompt(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    chat_id, message_id = data.get("prompt_chat_id"), data.get("prompt_message_id")
    if chat_id and message_id:
        try: await message.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception: pass


async def set_prompt(state: FSMContext, message: Message) -> None:
    await state.update_data(prompt_chat_id=message.chat.id, prompt_message_id=message.message_id)


async def get_offers(session: AsyncSession) -> list[tuple[ServicePeriod, ServicePurchasePlan]]:
    result = []
    for period in await ServicePeriod.list_active(session):
        for plan in await ServicePurchasePlan.list_by_type(session, period.service_type): result.append((period, plan))
    return result


async def build_ad_markup(campaign_id: int, bot_username: str, channel_id: int, session: AsyncSession, buttons: list[dict], selected_offers: list[str], show_services: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder(); row = []
    for item in buttons:
        url = str(item.get("url", ""))
        if not url: continue
        style = BUTTON_STYLES.get(str(item.get("color", "none")))
        row.append(InlineKeyboardButton(text=str(item.get("label", "دکمه"))[:64], url=url, style=style))
        if len(row) == 2: b.row(*row); row = []
    if row: b.row(*row)
    if show_services:
        selected = set(selected_offers)
        for period, plan in await get_offers(session):
            key = offer_key(period.id, plan.id)
            if selected and key not in selected: continue
            url = f"https://t.me/{bot_username}?start=ad_{campaign_id}_{period.id}_{plan.id}_{channel_id}"
            b.row(InlineKeyboardButton(text=f"📦 {fmt(plan.volume_gb)} گیگ / {fmt(plan.duration_days)} روز", url=url), InlineKeyboardButton(text=f"💰 {fmt(plan.price_toman)} تومان", url=url))
    return b.as_markup()


@router.callback_query(F.data == "advertising:menu", IsAdmin())
async def menu(callback: CallbackQuery):
    await callback.answer(); await callback.message.edit_text("📣 <b>مرکز تبلیغات ToonelVPN</b>\n\nساخت تبلیغ با متن، عکس، ویدئو، دکمه‌های رنگی واقعی Telegram، انتخاب سرویس و پیش‌نمایش.", reply_markup=menu_keyboard())


@router.callback_query(F.data == "advertising:add_channel", IsAdmin())
async def add_channel_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdvertisingStates.waiting_channel); await callback.answer()
    msg = await callback.message.edit_text("📢 یوزرنیم یا chat_id کانال را ارسال کنید.\nمثال: <code>@ToonelVPN_Official</code>", reply_markup=cancel_keyboard()); await set_prompt(state, msg)


@router.message(AdvertisingStates.waiting_channel, IsAdmin())
async def add_channel(message: Message, state: FSMContext, session: AsyncSession):
    raw = (message.text or "").strip()
    try: chat = await message.bot.get_chat(raw)
    except Exception: await message.answer("❌ کانال پیدا نشد یا ربات دسترسی ندارد."); return
    channel = await AdvertisingChannel.get_by_chat_id(session, chat.id)
    if channel: channel.username, channel.title, channel.is_active = chat.username, chat.title or chat.username or str(chat.id), True
    else: session.add(AdvertisingChannel(chat_id=chat.id, username=chat.username, title=chat.title or chat.username or str(chat.id)))
    await session.commit(); await state.clear(); await message.answer(f"✅ کانال <b>{chat.title or chat.username or chat.id}</b> فعال شد.", reply_markup=menu_keyboard()); asyncio.create_task(delete_later(message))


@router.callback_query(F.data == "advertising:channels", IsAdmin())
async def channels(callback: CallbackQuery, session: AsyncSession):
    rows = list((await session.execute(select(AdvertisingChannel).order_by(AdvertisingChannel.id))).scalars().all()); b = InlineKeyboardBuilder(); lines = ["📋 <b>کانال‌های تبلیغاتی</b>", ""]
    for channel in rows:
        status = "🟢" if channel.is_active else "🔴"; lines.append(f"{status} {channel.title} — <code>{channel.chat_id}</code>"); b.row(InlineKeyboardButton(text=f"{status} {channel.title}", callback_data=f"advertising:toggle:{channel.id}"))
    if not rows: lines.append("هنوز کانالی ثبت نشده است.")
    b.row(InlineKeyboardButton(text="➕ افزودن کانال", callback_data="advertising:add_channel")); b.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="advertising:menu")); await callback.answer(); await callback.message.edit_text("\n".join(lines),reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^advertising:toggle:\d+$"), IsAdmin())
async def toggle_channel(callback: CallbackQuery, session: AsyncSession):
    channel = await session.get(AdvertisingChannel, int(callback.data.rsplit(":",1)[1]))
    if not channel: await callback.answer("کانال پیدا نشد.", show_alert=True); return
    channel.is_active = not channel.is_active; await session.commit(); await callback.answer("وضعیت تغییر کرد"); await channels(callback, session)


@router.callback_query(F.data == "advertising:create", IsAdmin())
async def create_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await AdvertisingChannel.list_active(session): await callback.answer("ابتدا حداقل یک کانال فعال اضافه کنید.", show_alert=True); return
    await state.clear(); await state.update_data(custom_buttons=[], selected_offers=[], show_services=True, content_type="text", media_file_id=None, show_caption_above_media=False); await state.set_state(AdvertisingStates.waiting_campaign_title); await callback.answer()
    msg = await callback.message.edit_text("🧩 <b>سازنده تبلیغ</b>\n\n<b>مرحله ۱/۵</b> — عنوان داخلی کمپین را ارسال کنید.", reply_markup=cancel_keyboard()); await set_prompt(state,msg)


@router.message(AdvertisingStates.waiting_campaign_title, IsAdmin())
async def title(message: Message, state: FSMContext):
    value=(message.text or "").strip()
    if not value or len(value)>255: await message.answer("❌ عنوان نامعتبر است."); return
    await delete_prompt(message,state); await state.update_data(campaign_title=value); await state.set_state(AdvertisingStates.waiting_campaign_body)
    prompt=await message.answer("📦 <b>مرحله ۲/۵ — نوع محتوا</b>\n\nانتخاب کن تبلیغ فقط متن باشد یا همراه عکس/ویدئو.", reply_markup=content_keyboard()); await set_prompt(state,prompt); asyncio.create_task(delete_later(message))


@router.callback_query(F.data.regexp(r"^advertising:content:(text|photo|video)$"), IsAdmin())
async def content_type(callback: CallbackQuery, state: FSMContext):
    kind=callback.data.rsplit(":",1)[1]; await state.update_data(content_type=kind); await callback.answer(); await state.set_state(AdvertisingStates.waiting_campaign_body)
    if kind=="text": prompt=await callback.message.edit_text("📝 <b>متن تبلیغ</b>\n\nمتن کامل تبلیغ را ارسال کن.", reply_markup=cancel_keyboard())
    else: prompt=await callback.message.edit_text(("🖼 <b>عکس تبلیغ</b>" if kind=="photo" else "🎬 <b>ویدئوی تبلیغ</b>")+"\n\nرسانه را ارسال کن. اگر کپشن داشته باشد، همان متن زیر رسانه نمایش داده می‌شود.", reply_markup=cancel_keyboard())
    await set_prompt(state,prompt)


@router.message(AdvertisingStates.waiting_campaign_body, IsAdmin())
async def body(message: Message, state: FSMContext):
    data=await state.get_data(); kind=data.get("content_type","text"); await delete_prompt(message,state)
    if kind=="text":
        value=(message.text or "").strip()
        if not value: await message.answer("❌ متن تبلیغ خالی است."); return
        await state.update_data(campaign_body=value)
    elif kind=="photo" and message.photo:
        await state.update_data(media_file_id=message.photo[-1].file_id,campaign_body=(message.caption or "").strip())
    elif kind=="video" and message.video:
        await state.update_data(media_file_id=message.video.file_id,campaign_body=(message.caption or "").strip())
    else: await message.answer("❌ لطفاً رسانه صحیح را ارسال کن."); return
    await state.set_state(AdvertisingStates.waiting_button_title); prompt=await message.answer("🔘 <b>مرحله ۳/۵ — دکمه‌های سفارشی</b>\n\nعنوان دکمه را بفرست. هر تعداد دکمه که لازم داری بساز.\n\nبرای پایان: <code>رد کردن</code>", reply_markup=cancel_keyboard()); await set_prompt(state,prompt); asyncio.create_task(delete_later(message))


@router.message(AdvertisingStates.waiting_button_title, IsAdmin())
async def button_title(message: Message, state: FSMContext, session: AsyncSession):
    value=(message.text or "").strip()
    if value in {"رد کردن","رد","skip","Skip"}:
        await delete_prompt(message,state); await state.set_state(AdvertisingStates.waiting_service_selection); await show_services(message,state,session); asyncio.create_task(delete_later(message)); return
    if not value or len(value)>64: await message.answer("❌ عنوان دکمه باید حداکثر ۶۴ کاراکتر باشد."); return
    await delete_prompt(message,state); await state.update_data(pending_button_title=value); await state.set_state(AdvertisingStates.waiting_button_url)
    prompt=await message.answer("🔗 <b>لینک دکمه تبلیغ را انتخاب کنید</b>\n\nاز بین لینک‌های آماده زیر، لینک موردنظر را کپی و ارسال کنید.\n\n🛒 <b>خرید سرویس</b>\n<code>https://t.me/ToonelVpn_bot?start=buy</code>\n\n⚙️ <b>خرید با مشخصات دلخواه</b>\n<code>https://t.me/ToonelVpn_bot?start=custom_service</code>\n\n🔄 <b>تمدید سرویس</b>\n<code>https://t.me/ToonelVpn_bot?start=renew</code>\n\n📦 <b>سرویس‌های من</b>\n<code>https://t.me/ToonelVpn_bot?start=my_services</code>\n\n👤 <b>حساب کاربری</b>\n<code>https://t.me/ToonelVpn_bot?start=profile</code>\n\n💰 <b>کیف پول</b>\n<code>https://t.me/ToonelVpn_bot?start=wallet</code>\n\n🤝 <b>معرفی به دوستان</b>\n<code>https://t.me/ToonelVpn_bot?start=referral</code>\n\n🏆 <b>سطح من</b>\n<code>https://t.me/ToonelVpn_bot?start=customer_level</code>\n\n🎁 <b>اکانت تست</b>\n<code>https://t.me/ToonelVpn_bot?start=trial</code>\n\n🎧 <b>پشتیبانی</b>\n<code>https://t.me/ToonelVpn_bot?start=support</code>\n\n📌 <b>یا هر لینک معتبر دیگری</b> را مثل قبل ارسال کنید.\nمثال: <code>https://example.com</code> یا <code>https://t.me/ToonelVPN</code> یا <code>t.me/ToonelVPN</code> یا <code>@ToonelVPN</code>", reply_markup=cancel_keyboard()); await set_prompt(state,prompt); asyncio.create_task(delete_later(message))


@router.message(AdvertisingStates.waiting_button_url, IsAdmin())
async def button_url(message: Message, state: FSMContext):
    value=normalize_url((message.text or "").strip())
    if not valid_url(value): await message.answer("❌ لینک معتبر نیست. نمونه: https://example.com یا https://t.me/ToonelVPN یا @ToonelVPN"); return
    await delete_prompt(message,state); await state.update_data(pending_button_url=value); await state.set_state(AdvertisingStates.waiting_button_color)
    b=InlineKeyboardBuilder()
    for color in ("green","red","blue","none"): b.row(InlineKeyboardButton(text=STYLE_NAMES[color],callback_data=f"advertising:button_color:{color}"))
    b.row(InlineKeyboardButton(text="❌ لغو",callback_data="advertising:cancel")); prompt=await message.answer("🎨 <b>رنگ واقعی دکمه را انتخاب کن</b>\n\nرنگ روی خود دکمه اعمال می‌شود، نه به‌صورت علامت کنار متن.",reply_markup=b.as_markup()); await set_prompt(state,prompt); asyncio.create_task(delete_later(message))


@router.callback_query(F.data.regexp(r"^advertising:button_color:(green|red|blue|none)$"), IsAdmin())
async def button_color(callback:CallbackQuery,state:FSMContext):
    data=await state.get_data(); buttons=list(data.get("custom_buttons",[])); buttons.append({"label":data.get("pending_button_title","دکمه"),"url":data.get("pending_button_url", ""),"color":callback.data.rsplit(":",1)[1]}); await state.update_data(custom_buttons=buttons,pending_button_title=None,pending_button_url=None); await callback.answer(f"دکمه {len(buttons)} ذخیره شد"); await state.set_state(AdvertisingStates.waiting_button_title); await callback.message.edit_text(f"✅ دکمه {len(buttons)} ذخیره شد.\n\nدکمه بعدی را بساز یا «رد کردن» را بفرست.",reply_markup=cancel_keyboard()); await set_prompt(state,callback.message); asyncio.create_task(delete_later(callback.message))


async def show_services(message: Message,state:FSMContext,session:AsyncSession):
    offers=await get_offers(session)
    if not offers:
        await state.update_data(show_services=False,selected_offers=[]); prompt=await message.answer("⚠️ سرویس فعالی وجود ندارد؛ تبلیغ بدون سرویس ساخته می‌شود.",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👁 پیش‌نمایش",callback_data="advertising:preview")]])); await set_prompt(state,prompt); return
    selected=set((await state.get_data()).get("selected_offers",[])); b=InlineKeyboardBuilder()
    for period,plan in offers:
        key=offer_key(period.id,plan.id); mark="☑️" if key in selected else "⬜"; b.row(InlineKeyboardButton(text=f"{mark} {period.name} | {fmt(plan.volume_gb)}GB | {fmt(plan.duration_days)}روز | {fmt(plan.price_toman)}"[:64],callback_data=f"advertising:offer:{period.id}:{plan.id}"))
    b.row(InlineKeyboardButton(text="🚫 بدون سرویس",callback_data="advertising:services_off")); b.row(InlineKeyboardButton(text="👁 پیش‌نمایش",callback_data="advertising:preview")); b.row(InlineKeyboardButton(text="❌ لغو",callback_data="advertising:cancel")); prompt=await message.answer("🛒 <b>مرحله ۴/۵ — انتخاب سرویس‌ها</b>\n\nبا هر کلیک فقط همین پیام به‌روزرسانی می‌شود.",reply_markup=b.as_markup()); await set_prompt(state,prompt)


@router.callback_query(F.data.regexp(r"^advertising:offer:\d+:\d+$"), IsAdmin())
async def offer_toggle(callback:CallbackQuery,state:FSMContext,session:AsyncSession):
    _,_,period_id,plan_id=callback.data.split(":"); key=offer_key(int(period_id),int(plan_id)); data=await state.get_data(); selected=set(data.get("selected_offers",[])); selected.remove(key) if key in selected else selected.add(key); await state.update_data(selected_offers=sorted(selected),show_services=True); await callback.answer("انتخاب به‌روزرسانی شد")
    offers=await get_offers(session); selected=set((await state.get_data()).get("selected_offers",[])); b=InlineKeyboardBuilder()
    for period,plan in offers:
        k=offer_key(period.id,plan.id); mark="☑️" if k in selected else "⬜"; b.row(InlineKeyboardButton(text=f"{mark} {period.name} | {fmt(plan.volume_gb)}GB | {fmt(plan.duration_days)}روز | {fmt(plan.price_toman)}"[:64],callback_data=f"advertising:offer:{period.id}:{plan.id}"))
    b.row(InlineKeyboardButton(text="🚫 بدون سرویس",callback_data="advertising:services_off")); b.row(InlineKeyboardButton(text="👁 پیش‌نمایش",callback_data="advertising:preview")); b.row(InlineKeyboardButton(text="❌ لغو",callback_data="advertising:cancel")); await callback.message.edit_reply_markup(reply_markup=b.as_markup())


@router.callback_query(F.data == "advertising:services_off", IsAdmin())
async def services_off(callback:CallbackQuery,state:FSMContext):
    await state.update_data(show_services=False,selected_offers=[]); await callback.answer("سرویس‌ها حذف شدند"); await callback.message.edit_text("🚫 سرویس‌ها نمایش داده نمی‌شوند.",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👁 پیش‌نمایش",callback_data="advertising:preview")],[InlineKeyboardButton(text="❌ لغو",callback_data="advertising:cancel")]]))


async def save_draft(session:AsyncSession,data:dict,username:str)->AdvertisingCampaign:
    c=AdvertisingCampaign(title=data["campaign_title"],body=data.get("campaign_body", ""),bot_username=username,show_services=bool(data.get("show_services",True)),content_type=data.get("content_type","text"),media_file_id=data.get("media_file_id"),show_caption_above_media=bool(data.get("show_caption_above_media",False))); c.custom_buttons=list(data.get("custom_buttons",[])); c.selected_offers=list(data.get("selected_offers",[])); session.add(c); await session.flush(); return c


@router.callback_query(F.data == "advertising:preview", IsAdmin())
async def preview(callback:CallbackQuery,state:FSMContext,session:AsyncSession):
    data=await state.get_data()
    if data.get("content_type") in {"photo","video"} and not data.get("media_file_id"): await callback.answer("رسانه تبلیغ ناقص است.",show_alert=True); return
    if data.get("content_type")=="text" and not data.get("campaign_body"): await callback.answer("متن تبلیغ خالی است.",show_alert=True); return
    me=await callback.message.bot.get_me(); channels=await AdvertisingChannel.list_active(session)
    if not me.username or not channels: await callback.answer("ربات username یا کانال فعال ندارد.",show_alert=True); return
    c=await save_draft(session,data,me.username); await session.commit(); await state.update_data(draft_campaign_id=c.id); markup=await build_ad_markup(c.id,me.username,channels[0].id,session,c.custom_buttons,c.selected_offers,c.show_services)
    try: await callback.message.delete()
    except Exception: pass
    if c.content_type=="photo": await callback.message.bot.send_photo(chat_id=callback.from_user.id,photo=c.media_file_id,caption=c.body or None,show_caption_above_media=c.show_caption_above_media,reply_markup=markup)
    elif c.content_type=="video": await callback.message.bot.send_video(chat_id=callback.from_user.id,video=c.media_file_id,caption=c.body or None,show_caption_above_media=c.show_caption_above_media,reply_markup=markup)
    else: await callback.message.bot.send_message(chat_id=callback.from_user.id,text=c.body,reply_markup=markup)
    await callback.message.bot.send_message(chat_id=callback.from_user.id,text="اگر مورد تأیید است منتشر کن:",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚀 انتشار در کانال‌های فعال",callback_data=f"advertising:publish:{c.id}")],[InlineKeyboardButton(text="❌ لغو",callback_data=f"advertising:discard:{c.id}")]])); await callback.answer()


@router.callback_query(F.data.regexp(r"^advertising:publish:\d+$"), IsAdmin())
async def publish(callback:CallbackQuery,state:FSMContext,session:AsyncSession):
    c=await session.get(AdvertisingCampaign,int(callback.data.rsplit(":",1)[1]))
    if not c or not c.is_active: await callback.answer("کمپین پیدا نشد یا غیرفعال است.",show_alert=True); return
    channels=await AdvertisingChannel.list_active(session); ok=[]; failed=[]
    for channel in channels:
        try:
            markup=await build_ad_markup(c.id,c.bot_username or "",channel.id,session,c.custom_buttons,c.selected_offers,c.show_services)
            if c.content_type=="photo": sent=await callback.message.bot.send_photo(chat_id=channel.chat_id,photo=c.media_file_id,caption=c.body or None,show_caption_above_media=c.show_caption_above_media,reply_markup=markup)
            elif c.content_type=="video": sent=await callback.message.bot.send_video(chat_id=channel.chat_id,video=c.media_file_id,caption=c.body or None,show_caption_above_media=c.show_caption_above_media,reply_markup=markup)
            else: sent=await callback.message.bot.send_message(chat_id=channel.chat_id,text=c.body,reply_markup=markup)
            session.add(AdvertisingPublication(campaign_id=c.id,channel_id=channel.id,message_id=sent.message_id)); ok.append(channel.title)
        except Exception as exc: failed.append(f"{channel.title}: {exc}"); logger.exception("Advertising publish failed: campaign=%s channel=%s",c.id,channel.chat_id)
    await session.commit(); await state.clear(); await callback.answer("انتشار انجام شد"); lines=[f"✅ <b>کمپین #{c.id} منتشر شد.</b>",f"🟢 موفق: {len(ok)}",f"🔴 ناموفق: {len(failed)}"]
    if ok: lines.append("\n"+"\n".join(f"🟢 {x}" for x in ok))
    if failed: lines.append("\n"+"\n".join(f"🔴 {x}" for x in failed[:5]))
    await callback.message.edit_text("\n".join(lines),reply_markup=menu_keyboard())


@router.callback_query(F.data.regexp(r"^advertising:discard:\d+$"), IsAdmin())
async def discard(callback:CallbackQuery,state:FSMContext,session:AsyncSession):
    c=await session.get(AdvertisingCampaign,int(callback.data.rsplit(":",1)[1]))
    if c: c.is_active=False; await session.commit()
    await state.clear(); await callback.answer("لغو شد"); await callback.message.edit_text("❌ تبلیغ منتشر نشد.",reply_markup=menu_keyboard())


@router.callback_query(F.data == "advertising:cancel", IsAdmin())
async def cancel(callback:CallbackQuery,state:FSMContext):
    await state.clear(); await callback.answer("لغو شد"); await callback.message.edit_text("❌ ساخت تبلیغ لغو شد.",reply_markup=menu_keyboard())


@router.callback_query(F.data == "advertising:stats", IsAdmin())
async def stats(callback:CallbackQuery,session:AsyncSession):
    campaigns=list((await session.execute(select(AdvertisingCampaign).where(AdvertisingCampaign.is_active.is_(True)).order_by(AdvertisingCampaign.id.desc()).limit(20))).scalars().all()); lines=["📊 <b>گزارش کمپین‌های تبلیغاتی فعال</b>",""]
    for c in campaigns:
        leads=await session.scalar(select(func.count()).select_from(AdvertisingEvent).where(AdvertisingEvent.campaign_id==c.id,AdvertisingEvent.event_type=="start")) or 0
        buyers=await session.scalar(select(func.count(func.distinct(AdvertisingEvent.tg_id))).select_from(AdvertisingEvent).join(Transaction,Transaction.tg_id==AdvertisingEvent.tg_id).where(AdvertisingEvent.campaign_id==c.id,AdvertisingEvent.event_type=="start",Transaction.status==TransactionStatus.COMPLETED)) or 0
        pubs=await session.scalar(select(func.count()).select_from(AdvertisingPublication).where(AdvertisingPublication.campaign_id==c.id,AdvertisingPublication.is_active.is_(True))) or 0
        if pubs: lines.append(f"#{c.id} — <b>{c.title}</b> | انتشار: <b>{pubs}</b> | ورودی: <b>{leads}</b> | خریدار: <b>{buyers}</b>")
    if len(lines)==2: lines.append("کمپین فعال و منتشرشده‌ای وجود ندارد.")
    await callback.answer(); await callback.message.edit_text("\n".join(lines),reply_markup=menu_keyboard())
