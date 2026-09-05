from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.utils.navigation import NavAdminTools
from app.db.models import CustomerLevelSettings

router = Router(name=__name__)


class CustomerLevelSettingsStates(StatesGroup):
    waiting_percent = State()
    waiting_range = State()


FIELDS = {
    "base": ("سطح پایه", "base_discount_percent"),
    "bronze": ("سطح برنزی", "bronze_discount_percent"),
    "silver": ("سطح نقره‌ای", "silver_discount_percent"),
    "gold": ("سطح طلایی", "gold_discount_percent"),
}

RANGE_FIELDS = {
    "base": ("base_min_points", "base_max_points"),
    "bronze": ("bronze_min_points", "bronze_max_points"),
    "silver": ("silver_min_points", "silver_max_points"),
    "gold": ("gold_min_points", "gold_max_points"),
}

ICONS = {"base": "⚪️", "bronze": "🔩", "silver": "⚙️", "gold": "👑"}


def _keyboard() -> InlineKeyboardMarkup:
    rows = []
    for key, (title, _) in FIELDS.items():
        rows.append([
            InlineKeyboardButton(text=f"{ICONS[key]} {title} | ✏️ بازه", callback_data=f"customer_level_settings:edit:{key}"),
            InlineKeyboardButton(text="💰 تخفیف", callback_data=f"customer_level_settings:edit_discount:{key}"),
        ])
    rows.extend([
        [InlineKeyboardButton(text="🔄 بازخوانی مقادیر", callback_data=NavAdminTools.CUSTOMER_LEVEL_SETTINGS)],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _range_text(minimum: int, maximum: int | None) -> str:
    return f"{minimum}+" if maximum is None else f"{minimum} تا {maximum}"


async def _text(session: AsyncSession) -> str:
    settings = await CustomerLevelSettings.get_or_create(session)
    return (
        "🏆 <b>مدیریت تخفیف سطوح مشتری</b>\n\n"
        f"⚪️ سطح پایه: <b>{_range_text(settings.base_min_points, settings.base_max_points)}</b> امتیاز — تخفیف <b>{settings.base_discount_percent}%</b>\n"
        f"🔩 سطح برنزی: <b>{_range_text(settings.bronze_min_points, settings.bronze_max_points)}</b> امتیاز — تخفیف <b>{settings.bronze_discount_percent}%</b>\n"
        f"⚙️ سطح نقره‌ای: <b>{_range_text(settings.silver_min_points, settings.silver_max_points)}</b> امتیاز — تخفیف <b>{settings.silver_discount_percent}%</b>\n"
        f"👑 سطح طلایی: <b>{_range_text(settings.gold_min_points, settings.gold_max_points)}</b> امتیاز — تخفیف <b>{settings.gold_discount_percent}%</b>\n\n"
        "برای هر سطح می‌توانید هم بازه امتیاز و هم درصد تخفیف را تغییر دهید.\n"
        "بازه‌ها باید پیوسته و بدون هم‌پوشانی باشند؛ سطح طلایی می‌تواند باز باشد (مثلاً <code>21+</code>)."
    )


def _parse_int(value: str) -> int:
    translation = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    return int(value.translate(translation).strip())


def _parse_range(raw: str, key: str) -> tuple[int, int | None]:
    value = raw.strip().replace("–", "-").replace("—", "-")
    value = value.replace("تا", "-").replace("الی", "-").replace(" ", "")

    if key == "gold" and value.endswith("+"):
        return _parse_int(value[:-1]), None

    parts = value.split("-")
    if len(parts) != 2:
        raise ValueError
    minimum = _parse_int(parts[0])
    maximum = _parse_int(parts[1])
    if minimum < 0 or maximum < minimum:
        raise ValueError
    return minimum, maximum


def _validate_ranges(settings: CustomerLevelSettings) -> str | None:
    ranges = [
        ("سطح پایه", settings.base_min_points, settings.base_max_points),
        ("سطح برنزی", settings.bronze_min_points, settings.bronze_max_points),
        ("سطح نقره‌ای", settings.silver_min_points, settings.silver_max_points),
        ("سطح طلایی", settings.gold_min_points, settings.gold_max_points),
    ]

    if ranges[0][1] != 0:
        return "بازه سطح پایه باید از امتیاز ۰ شروع شود."

    previous_max: int | None = None
    for title, minimum, maximum in ranges:
        if minimum < 0:
            return f"حداقل امتیاز {title} نمی‌تواند منفی باشد."
        if maximum is not None and maximum < minimum:
            return f"حداکثر امتیاز {title} نمی‌تواند کمتر از حداقل آن باشد."
        if previous_max is not None and minimum != previous_max + 1:
            return "بازه سطوح باید پیوسته و بدون فاصله یا هم‌پوشانی باشند."
        previous_max = maximum

    if ranges[-1][2] is not None:
        return "سطح طلایی باید باز باشد؛ مثلاً ۲۱+"
    return None


@router.callback_query(F.data == NavAdminTools.CUSTOMER_LEVEL_SETTINGS, IsAdmin())
async def show_customer_level_settings(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(await _text(session), reply_markup=_keyboard())


@router.callback_query(F.data.startswith("customer_level_settings:edit:"), IsAdmin())
async def edit_customer_level_range(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    key = callback.data.rsplit(":", 1)[-1]
    if key not in RANGE_FIELDS:
        await callback.answer("مقدار نامعتبر است.", show_alert=True)
        return

    title = FIELDS[key][0]
    min_field, max_field = RANGE_FIELDS[key]
    settings = await CustomerLevelSettings.get_or_create(session)
    current_range = _range_text(getattr(settings, min_field), getattr(settings, max_field))
    await state.update_data(level_key=key)
    await state.set_state(CustomerLevelSettingsStates.waiting_range)
    await callback.answer()
    await callback.message.edit_text(
        f"✏️ <b>تنظیم بازه امتیاز {title}</b>\n\n"
        f"بازه فعلی: <b>{current_range}</b>\n\n"
        "بازه جدید را به شکل <code>از-تا</code> وارد کنید.\n"
        "مثلاً: <code>5-10</code> یا <code>۵ تا ۱۰</code>\n"
        "برای سطح طلایی، بازه باز وارد کنید؛ مثلاً <code>21+</code>."
    )


@router.message(CustomerLevelSettingsStates.waiting_range, IsAdmin())
async def save_customer_level_range(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    data = await state.get_data()
    key = data.get("level_key")
    if key not in RANGE_FIELDS:
        await state.clear()
        await message.answer("❌ سطح مشتری نامعتبر است.")
        return

    try:
        minimum, maximum = _parse_range(message.text or "", key)
    except (TypeError, ValueError):
        await message.answer(
            "❌ بازه نامعتبر است. مثال صحیح: <code>5-10</code> یا <code>۵ تا ۱۰</code>.\n"
            "برای سطح طلایی از قالب <code>21+</code> استفاده کنید."
        )
        return

    min_field, max_field = RANGE_FIELDS[key]
    settings = await CustomerLevelSettings.get_or_create(session)
    old_min, old_max = getattr(settings, min_field), getattr(settings, max_field)
    setattr(settings, min_field, minimum)
    setattr(settings, max_field, maximum)

    error = _validate_ranges(settings)
    if error:
        setattr(settings, min_field, old_min)
        setattr(settings, max_field, old_max)
        await message.answer(f"❌ {error}")
        return

    await session.commit()
    await state.clear()
    title = FIELDS[key][0]
    await message.answer(
        f"✅ <b>بازه امتیاز {title} ذخیره شد.</b>\n\n"
        f"بازه جدید: <b>{_range_text(minimum, maximum)}</b> امتیاز",
        reply_markup=_keyboard(),
    )


@router.callback_query(F.data.startswith("customer_level_settings:edit_discount:"), IsAdmin())
async def edit_customer_level_discount(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    key = callback.data.rsplit(":", 1)[-1]
    if key not in FIELDS:
        await callback.answer("مقدار نامعتبر است.", show_alert=True)
        return

    title, _ = FIELDS[key]
    await state.update_data(level_key=key)
    await state.set_state(CustomerLevelSettingsStates.waiting_percent)
    await callback.answer()
    await callback.message.edit_text(
        f"✏️ <b>ویرایش تخفیف {title}</b>\n\n"
        "درصد تخفیف جدید را وارد کنید.\n"
        "مثلاً: <code>10</code>\n\n"
        "مقدار مجاز: ۰ تا ۱۰۰ درصد"
    )


@router.message(CustomerLevelSettingsStates.waiting_percent, IsAdmin())
async def save_customer_level_setting(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    raw = (message.text or "").strip().replace("٪", "%")
    if raw.endswith("%"):
        raw = raw[:-1].strip()

    try:
        value = _parse_int(raw)
        if not 0 <= value <= 100:
            raise ValueError
    except ValueError:
        await message.answer("❌ مقدار نامعتبر است. لطفاً یک عدد صحیح بین ۰ تا ۱۰۰ وارد کنید.")
        return

    data = await state.get_data()
    key = data.get("level_key")
    if key not in FIELDS:
        await state.clear()
        await message.answer("❌ سطح مشتری نامعتبر است.")
        return

    title, field = FIELDS[key]
    settings = await CustomerLevelSettings.get_or_create(session)
    setattr(settings, field, value)
    await session.commit()
    await state.clear()

    await message.answer(
        f"✅ <b>تخفیف {title} با موفقیت ذخیره شد.</b>\n\n"
        f"درصد تخفیف جدید: <b>{value}%</b>",
        reply_markup=_keyboard(),
    )
