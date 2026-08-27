from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.utils.navigation import NavSupport

from .keyboard import training_app_keyboard, training_detail_keyboard, training_keyboard
from .training_content import APP_OVERVIEWS, PAGES

router = Router(name="support_training")


@router.callback_query(F.data == NavSupport.TRAINING)
async def callback_training(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        text=(
            "📚 <b>مرکز آموزش ToonelVPN</b>\n\n"
            "برنامه‌ای را که می‌خواهی با آن به سرویس ToonelVPN متصل شوی انتخاب کن.\n\n"
            "داخل هر برنامه، آموزش جداگانه برای سیستم‌عامل‌های پشتیبانی‌شده، روش افزودن لینک/Subscription، فعال‌سازی اتصال و عیب‌یابی قرار داده شده است."
        ),
        reply_markup=training_keyboard(),
    )


@router.callback_query(F.data == NavSupport.TRAINING_HAPP)
async def callback_training_happ(callback: CallbackQuery) -> None:
    await _show_app(callback, "happ")


@router.callback_query(F.data == NavSupport.TRAINING_V2RAY)
async def callback_training_v2ray(callback: CallbackQuery) -> None:
    await _show_app(callback, "v2ray")


@router.callback_query(F.data == NavSupport.TRAINING_V2BOX)
async def callback_training_v2box(callback: CallbackQuery) -> None:
    await _show_app(callback, "v2box")


async def _show_app(callback: CallbackQuery, app: str) -> None:
    overview = APP_OVERVIEWS.get(app)
    if not overview:
        await callback.answer("❌ آموزش پیدا نشد.", show_alert=True)
        return
    title, text = overview
    await callback.answer()
    await callback.message.edit_text(
        text=f"{title}\n\n{text}\n\n👇 سیستم‌عامل را انتخاب کن:",
        reply_markup=training_app_keyboard(app),
    )


@router.callback_query(F.data.startswith(NavSupport.TRAINING_APP_PLATFORM))
async def callback_training_platform(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")

    # support:training:app:happ -> app menu
    if len(parts) == 4 and parts[3] in {"happ", "v2ray", "v2box"}:
        await _show_app(callback, parts[3])
        return

    # support:training:app:happ:android -> platform detail
    if len(parts) != 5:
        await callback.answer("❌ مسیر آموزش نامعتبر است.", show_alert=True)
        return

    app = parts[3]
    platform = parts[4]
    page = PAGES.get((app, platform))
    if not page:
        await callback.answer(
            "❌ آموزش این سیستم‌عامل هنوز تعریف نشده است.", show_alert=True
        )
        return

    await callback.answer()
    await callback.message.edit_text(
        text=f"{page.title}\n\n{page.text}",
        reply_markup=training_detail_keyboard(app, platform, page.download_url),
    )
