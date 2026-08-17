from __future__ import annotations

import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters.admin import IsAdmin
from app.bot.keyboards.admin_tools import (
    connected_device_settings_keyboard,
    service_purchase_management_keyboard,
)
from app.bot.services import ServicesContainer
from app.bot.states.connected_device_settings import ConnectedDeviceSettingsStates
from app.bot.utils.navigation import NavAdminTools
from app.db.models import ConnectedDeviceSettings

logger = logging.getLogger(__name__)

router = Router(name=__name__)


@router.callback_query(
    F.data == NavAdminTools.SERVICE_PURCHASE,
    IsAdmin(),
)
async def callback_service_purchase_management(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        text="🛒 <b>مدیریت خرید سرویس</b>",
        reply_markup=service_purchase_management_keyboard(),
    )


@router.callback_query(
    F.data == NavAdminTools.SERVICE_PURCHASE_DEVICES,
    IsAdmin(),
)
async def callback_service_purchase_devices(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()

    settings = await ConnectedDeviceSettings.get_or_create(session)

    await callback.answer()

    await callback.message.edit_text(
        "📱 <b>مدیریت تعداد دستگاه متصل</b>\n\n"
        "تعداد دستگاه‌های مجاز برای اتصال همزمان: "
        f"<b>{settings.max_connected_devices} دستگاه</b>",
        reply_markup=connected_device_settings_keyboard(),
    )


@router.callback_query(
    F.data == "connected_device_settings:edit",
    IsAdmin(),
)
async def callback_connected_device_settings_edit(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.set_state(
        ConnectedDeviceSettingsStates.waiting_max_devices
    )

    await callback.answer()

    await callback.message.edit_text(
        "✏️ <b>ویرایش تعداد دستگاه متصل</b>\n\n"
        "تعداد دستگاه‌های مجاز برای اتصال همزمان را وارد کنید.\n"
        "مثلاً: <code>3</code>"
    )


@router.message(
    ConnectedDeviceSettingsStates.waiting_max_devices,
    IsAdmin(),
)
async def process_connected_device_settings(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    raw = (message.text or "").strip()

    try:
        value = int(raw)
        if value < 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ مقدار نامعتبر است.\n"
            "لطفاً تعداد دستگاه را به صورت یک عدد صحیح صفر یا بیشتر وارد کنید."
        )
        return

    settings = await ConnectedDeviceSettings.get_or_create(session)
    settings.max_connected_devices = value

    await session.commit()
    await state.clear()

    await message.answer(
        "✅ <b>تعداد دستگاه با موفقیت ذخیره شد.</b>\n\n"
        f"تعداد دستگاه‌های مجاز برای اتصال همزمان: "
        f"<b>{settings.max_connected_devices} دستگاه</b>",
        reply_markup=connected_device_settings_keyboard(),
    )



@router.callback_query(
    F.data.in_(
        {"connected_device_settings:increase", "connected_device_settings:decrease"}
    ),
    IsAdmin(),
)
async def callback_connected_device_settings_adjust(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    settings = await ConnectedDeviceSettings.get_or_create(session)
    delta = 1 if callback.data.endswith("increase") else -1
    settings.max_connected_devices = max(0, settings.max_connected_devices + delta)
    await session.commit()
    await callback.answer()
    await callback.message.edit_text(
        "📱 <b>مدیریت تعداد دستگاه متصل</b>\n\n"
        "تعداد دستگاه‌های مجاز برای اتصال همزمان: "
        f"<b>{settings.max_connected_devices} دستگاه</b>",
        reply_markup=connected_device_settings_keyboard(),
    )
