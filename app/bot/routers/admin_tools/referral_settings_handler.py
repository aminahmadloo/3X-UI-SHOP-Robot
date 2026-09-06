from html import escape
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.utils.navigation import NavAdminTools
from app.db.models import ReferralSettings
from app.db.models.referral_settings import DEFAULT_REFERRAL_SHARE_TEXT

router = Router(name=__name__)

MAX_SHARE_TEXT_LENGTH = 2500
ALLOWED_SHARE_VARIABLES = {"referral_link"}
SHARE_VARIABLE_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
SAMPLE_REFERRAL_LINK = "https://t.me/ToonelVpn_bot?start=ref_12345678"


class ReferralSettingsStates(StatesGroup):
    waiting_first_percent = State()
    waiting_repeat_percent = State()
    waiting_share_text = State()


def _keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ ویرایش پاداش خرید اول", callback_data="referral_settings:edit:first")],
            [InlineKeyboardButton(text="✏️ ویرایش پاداش خریدهای بعدی", callback_data="referral_settings:edit:repeat")],
            [InlineKeyboardButton(text="✏️ ویرایش متن دعوت دوستان", callback_data="referral_settings:edit:share_text")],
            [
                InlineKeyboardButton(text="👁 پیش‌نمایش", callback_data="referral_settings:preview:share_text"),
                InlineKeyboardButton(text="📤 ارسال نمونه", callback_data="referral_settings:sample:share_text"),
            ],
            [InlineKeyboardButton(text="🔄 بازگردانی متن پیش‌فرض", callback_data="referral_settings:reset:share_text")],
            [InlineKeyboardButton(text="🔄 بازخوانی مقادیر", callback_data=NavAdminTools.REFERRAL_SETTINGS)],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)],
        ]
    )


def _share_status(share_text: str) -> str:
    status = "پیش‌فرض" if share_text == DEFAULT_REFERRAL_SHARE_TEXT else "سفارشی"
    return f"{status} • {len(share_text):,} / {MAX_SHARE_TEXT_LENGTH:,} کاراکتر"


def _render_for_admin(share_text: str, referral_link: str = SAMPLE_REFERRAL_LINK) -> str:
    rendered = share_text.replace("{referral_link}", referral_link)
    return escape(rendered)


async def _text(session: AsyncSession) -> str:
    settings = await ReferralSettings.get_or_create(session)
    return (
        "🎁 <b>تنظیمات معرفی به دوستان</b>\n\n"
        f"🛒 پاداش خرید اول: <b>{settings.reward_percent}%</b>\n"
        f"🔄 پاداش خریدهای بعدی: <b>{settings.repeat_reward_percent}%</b>\n\n"
        "📝 <b>مدیریت متن دعوت دوستان</b>\n"
        f"📊 وضعیت: <b>{_share_status(settings.share_text)}</b>\n\n"
        "متن فعلی:\n"
        f"<blockquote>{_render_for_admin(settings.share_text)}</blockquote>\n\n"
        "🔗 متغیر قابل استفاده: <code>{referral_link}</code>\n"
        "این متغیر با لینک اختصاصی هر کاربر جایگزین می‌شود.\n"
        "اگر متغیر استفاده نشود، لینک همچنان به‌عنوان URL اصلی اشتراک‌گذاری Telegram ارسال می‌شود."
    )


def _validate_share_text(value: str) -> str | None:
    if not value:
        return "متن خالی است. لطفاً متن دعوت دوستان را ارسال کنید."
    if len(value) > MAX_SHARE_TEXT_LENGTH:
        return f"متن بیش از حد طولانی است. حداکثر {MAX_SHARE_TEXT_LENGTH:,} کاراکتر مجاز است."

    variables = set(SHARE_VARIABLE_PATTERN.findall(value))
    unknown = sorted(variables - ALLOWED_SHARE_VARIABLES)
    if unknown:
        names = "، ".join(f"{{{name}}}" for name in unknown)
        return (
            f"متغیر ناشناخته در متن وجود دارد: {names}\n\n"
            "تنها متغیر مجاز فعلی: <code>{referral_link}</code>"
        )
    return None


@router.callback_query(F.data == NavAdminTools.REFERRAL_SETTINGS, IsAdmin())
async def show_referral_settings(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(await _text(session), reply_markup=_keyboard())


@router.callback_query(F.data == "referral_settings:edit:first", IsAdmin())
async def edit_first_referral_setting(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ReferralSettingsStates.waiting_first_percent)
    await callback.answer()
    await callback.message.edit_text(
        "✏️ <b>ویرایش پاداش خرید اول</b>\n\n"
        "درصد جدید را وارد کنید.\n"
        "مثلاً: <code>30</code>\n\n"
        "این نرخ فقط برای اولین خرید موفق فرد معرفی‌شده استفاده می‌شود.\n"
        "مقدار مجاز: ۰ تا ۱۰۰ درصد"
    )


@router.callback_query(F.data == "referral_settings:edit:repeat", IsAdmin())
async def edit_repeat_referral_setting(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ReferralSettingsStates.waiting_repeat_percent)
    await callback.answer()
    await callback.message.edit_text(
        "✏️ <b>ویرایش پاداش خریدهای بعدی</b>\n\n"
        "درصد جدید را وارد کنید.\n"
        "مثلاً: <code>5</code>\n\n"
        "این نرخ از خرید دوم به بعد، مادام‌العمر استفاده می‌شود.\n"
        "مقدار مجاز: ۰ تا ۱۰۰ درصد"
    )


@router.callback_query(F.data == "referral_settings:edit:share_text", IsAdmin())
async def edit_referral_share_text(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    settings = await ReferralSettings.get_or_create(session)
    await state.set_state(ReferralSettingsStates.waiting_share_text)
    await callback.answer()
    await callback.message.edit_text(
        "✏️ <b>ویرایش متن دعوت دوستان</b>\n\n"
        "کل متن پیام اشتراک‌گذاری را در یک پیام ارسال کنید.\n\n"
        "🔗 برای قرار دادن لینک اختصاصی کاربر در هر جای متن، از این متغیر استفاده کنید:\n"
        "<code>{referral_link}</code>\n\n"
        "⚠️ فقط همین متغیر فعلاً مجاز است.\n\n"
        f"📝 <b>متن فعلی:</b>\n<blockquote>{escape(settings.share_text)}</blockquote>\n\n"
        f"حداکثر طول: {MAX_SHARE_TEXT_LENGTH:,} کاراکتر."
    )


def _parse_percent(message: Message) -> int | None:
    raw = (message.text or "").strip().replace("٪", "%")
    if raw.endswith("%"):
        raw = raw[:-1].strip()
    try:
        value = int(raw)
        if not 0 <= value <= 100:
            raise ValueError
    except ValueError:
        return None
    return value


@router.callback_query(F.data == "referral_settings:preview:share_text", IsAdmin())
async def preview_referral_share_text(callback: CallbackQuery, session: AsyncSession) -> None:
    settings = await ReferralSettings.get_or_create(session)
    await callback.answer()
    await callback.message.answer(
        "👁 <b>پیش‌نمایش متن دعوت دوستان</b>\n\n"
        f"<blockquote>{_render_for_admin(settings.share_text)}</blockquote>\n\n"
        "🔗 این پیش‌نمایش از یک لینک نمونه استفاده می‌کند. لینک واقعی هر کاربر هنگام اشتراک‌گذاری به‌صورت اختصاصی جایگزین می‌شود.",
    )


@router.callback_query(F.data == "referral_settings:sample:share_text", IsAdmin())
async def send_referral_share_sample(callback: CallbackQuery, session: AsyncSession) -> None:
    settings = await ReferralSettings.get_or_create(session)
    await callback.answer("نمونه ارسال شد")
    await callback.message.answer(
        _render_for_admin(settings.share_text),
        disable_web_page_preview=False,
    )


@router.callback_query(F.data == "referral_settings:reset:share_text", IsAdmin())
async def reset_referral_share_text(callback: CallbackQuery, session: AsyncSession) -> None:
    settings = await ReferralSettings.get_or_create(session)
    settings.share_text = DEFAULT_REFERRAL_SHARE_TEXT
    await session.commit()
    await callback.answer("متن به حالت پیش‌فرض برگشت")
    await callback.message.edit_text(
        "✅ <b>متن دعوت دوستان به حالت پیش‌فرض بازگردانده شد.</b>\n\n"
        "از این پس متن اصلی پیش‌فرض برای اشتراک‌گذاری استفاده می‌شود.",
        reply_markup=_keyboard(),
    )


@router.message(ReferralSettingsStates.waiting_first_percent, IsAdmin())
async def save_first_referral_setting(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    value = _parse_percent(message)
    if value is None:
        await message.answer("❌ مقدار نامعتبر است. لطفاً یک عدد صحیح بین ۰ تا ۱۰۰ وارد کنید.")
        return

    settings = await ReferralSettings.get_or_create(session)
    settings.reward_percent = value
    await session.commit()
    await state.clear()

    await message.answer(
        "✅ <b>پاداش خرید اول با موفقیت ذخیره شد.</b>\n\n"
        f"نرخ جدید خرید اول: <b>{value}%</b>",
        reply_markup=_keyboard(),
    )


@router.message(ReferralSettingsStates.waiting_repeat_percent, IsAdmin())
async def save_repeat_referral_setting(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    value = _parse_percent(message)
    if value is None:
        await message.answer("❌ مقدار نامعتبر است. لطفاً یک عدد صحیح بین ۰ تا ۱۰۰ وارد کنید.")
        return

    settings = await ReferralSettings.get_or_create(session)
    settings.repeat_reward_percent = value
    await session.commit()
    await state.clear()

    await message.answer(
        "✅ <b>پاداش خریدهای بعدی با موفقیت ذخیره شد.</b>\n\n"
        f"نرخ جدید خریدهای بعدی: <b>{value}%</b>",
        reply_markup=_keyboard(),
    )


@router.message(ReferralSettingsStates.waiting_share_text, IsAdmin())
async def save_referral_share_text(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    value = (message.text or "").strip()
    error = _validate_share_text(value)
    if error:
        await message.answer(f"❌ {error}")
        return

    settings = await ReferralSettings.get_or_create(session)
    settings.share_text = value
    await session.commit()
    await state.clear()

    await message.answer(
        "✅ <b>متن دعوت دوستان با موفقیت ذخیره شد.</b>\n\n"
        f"📊 وضعیت: <b>{_share_status(value)}</b>\n\n"
        "می‌توانید با دکمه‌های «👁 پیش‌نمایش» یا «📤 ارسال نمونه» نتیجه را بررسی کنید.",
        reply_markup=_keyboard(),
    )
