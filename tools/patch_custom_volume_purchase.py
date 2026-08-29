from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def edit(path: str, replacements: list[tuple[str, str]]) -> None:
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    for old, new in replacements:
        if old not in text:
            raise SystemExit(
                f"PATCH FAILED: expected text not found in {path}: {old[:120]!r}"
            )
        if text.count(old) != 1:
            raise SystemExit(
                f"PATCH FAILED: expected text is not unique in {path}: {old[:120]!r}"
            )
        text = text.replace(old, new, 1)
    file.write_text(text, encoding="utf-8")


# 1) Store custom-volume pricing rules on each dynamic service period.
edit(
    "app/db/models/service_period.py",
    [
        (
            '    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")\n',
            '    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")\n'
            '    custom_price_per_gb_toman: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")\n'
            '    custom_min_volume_gb: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")\n'
            '    custom_max_volume_gb: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")\n',
        )
    ],
)


# 2) Mark generated custom-order plans so they never appear as ordinary plans.
edit(
    "app/db/models/service_purchase_plan.py",
    [
        (
            'from sqlalchemy import Integer, String, select\n',
            'from sqlalchemy import Boolean, Integer, String, select\n',
        ),
        (
            '    price_toman: Mapped[int] = mapped_column(Integer, nullable=False)\n',
            '    price_toman: Mapped[int] = mapped_column(Integer, nullable=False)\n'
            '    is_custom: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0", index=True)\n',
        ),
        (
            '''    async def list_by_type(
        cls,
        session: AsyncSession,
        service_type: str,
    ) -> list[Self]:
        result = await session.execute(
            select(cls)
            .where(cls.service_type == service_type)
            .order_by(cls.id)
        )
''',
            '''    async def list_by_type(
        cls,
        session: AsyncSession,
        service_type: str,
        *,
        include_custom: bool = False,
    ) -> list[Self]:
        query = select(cls).where(cls.service_type == service_type)
        if not include_custom:
            query = query.where(cls.is_custom.is_(False))
        result = await session.execute(query.order_by(cls.id))
''',
        ),
    ],
)


# 3) Add admin controls.
edit(
    "app/bot/routers/admin_tools/dynamic_service_period_handler.py",
    [
        (
            '''class PeriodStates(StatesGroup):
    months = State()
    volume = State()
    price = State()
    edit_volume = State()
    edit_price = State()
''',
            '''class PeriodStates(StatesGroup):
    months = State()
    volume = State()
    price = State()
    edit_volume = State()
    edit_price = State()
    custom_price = State()
    custom_min = State()
    custom_max = State()
''',
        ),
        (
            '''def _plans_kb(p, plans):
    b=InlineKeyboardBuilder()
    for x in plans: b.row(InlineKeyboardButton(text=f"{x.volume_gb:,} GB | {x.price_toman:,} تومان | {x.duration_days} روز", callback_data=f"sp:plan:{p.id}:{x.id}"))
    b.row(InlineKeyboardButton(text="➕ ساخت سرویس جدید", callback_data=f"sp:create_plan:{p.id}")); b.row(InlineKeyboardButton(text="🔙 جزئیات دوره", callback_data=f"sp:view:{p.id}")); b.row(_back()); return b.as_markup()
''',
            '''def _plans_kb(p, plans):
    b=InlineKeyboardBuilder()
    for x in plans:
        b.row(InlineKeyboardButton(
            text=f"{x.volume_gb:,} GB | {x.price_toman:,} تومان | {x.duration_days} روز",
            callback_data=f"sp:plan:{p.id}:{x.id}"
        ))
    b.row(InlineKeyboardButton(text="➕ ساخت سرویس جدید", callback_data=f"sp:create_plan:{p.id}"))
    b.row(InlineKeyboardButton(text=f"💰 مبلغ پایه هر گیگ دوره | {p.custom_price_per_gb_toman:,} تومان", callback_data=f"sp:custom_price:{p.id}"))
    b.row(InlineKeyboardButton(text=f"📦 حداقل حجم دلخواه | {p.custom_min_volume_gb:,} GB", callback_data=f"sp:custom_min:{p.id}"))
    max_text = "نامحدود" if p.custom_max_volume_gb <= 0 else f"{p.custom_max_volume_gb:,} GB"
    b.row(InlineKeyboardButton(text=f"📦 حداکثر حجم دلخواه | {max_text}", callback_data=f"sp:custom_max:{p.id}"))
    b.row(InlineKeyboardButton(text="🔙 جزئیات دوره", callback_data=f"sp:view:{p.id}"))
    b.row(_back())
    return b.as_markup()
''',
        ),
        (
            '''@router.callback_query(F.data.regexp(r"^sp:create_plan:\\d+$"),IsAdmin())
''',
            '''@router.callback_query(F.data.regexp(r"^sp:custom_price:\\d+$"),IsAdmin())
async def custom_price(callback:CallbackQuery,state:FSMContext,session:AsyncSession):
    p=await ServicePeriod.get(session,int(callback.data.rsplit(":",1)[1]))
    if not p or p.is_archived:
        await callback.answer("❌ دوره پیدا نشد.",show_alert=True)
        return
    await state.clear()
    await state.update_data(period_id=p.id)
    await state.set_state(PeriodStates.custom_price)
    await callback.answer()
    await callback.message.edit_text(
        f"💰 <b>مبلغ پایه هر گیگ دوره</b>\\n\\n"
        f"دوره: <b>{p.name}</b>\\n"
        f"مقدار فعلی: <b>{p.custom_price_per_gb_toman:,} تومان</b>\\n\\n"
        "مبلغ پایه هر گیگ را به تومان وارد کنید:"
    )

@router.message(PeriodStates.custom_price,IsAdmin())
async def save_custom_price(message:Message,state:FSMContext,session:AsyncSession):
    try:
        value=int((message.text or "").replace(",","").replace("٬",""))
        assert value>0
    except:
        await message.answer("❌ مبلغ نامعتبر است. مبلغ باید عدد صحیح بزرگ‌تر از صفر باشد.")
        return
    d=await state.get_data()
    p=await ServicePeriod.get(session,int(d["period_id"]))
    if not p:
        await state.clear()
        await message.answer("❌ دوره پیدا نشد.")
        return
    p.custom_price_per_gb_toman=value
    await session.commit()
    await state.clear()
    await message.answer(
        f"✅ مبلغ پایه هر گیگ دوره <b>{p.name}</b> روی <b>{value:,} تومان</b> تنظیم شد.",
        reply_markup=_plans_kb(p,await ServicePurchasePlan.list_by_type(session,p.service_type))
    )

@router.callback_query(F.data.regexp(r"^sp:custom_min:\\d+$"),IsAdmin())
async def custom_min(callback:CallbackQuery,state:FSMContext,session:AsyncSession):
    p=await ServicePeriod.get(session,int(callback.data.rsplit(":",1)[1]))
    if not p or p.is_archived:
        await callback.answer("❌ دوره پیدا نشد.",show_alert=True)
        return
    await state.clear()
    await state.update_data(period_id=p.id)
    await state.set_state(PeriodStates.custom_min)
    await callback.answer()
    await callback.message.edit_text(
        f"📦 <b>حداقل حجم دلخواه</b>\\n\\n"
        f"دوره: <b>{p.name}</b>\\n"
        f"مقدار فعلی: <b>{p.custom_min_volume_gb:,} GB</b>\\n\\n"
        "حداقل حجم را به GB وارد کنید:"
    )

@router.message(PeriodStates.custom_min,IsAdmin())
async def save_custom_min(message:Message,state:FSMContext,session:AsyncSession):
    try:
        value=int((message.text or "").replace(",","").replace("٬",""))
        assert value>0
    except:
        await message.answer("❌ حجم نامعتبر است. حداقل حجم باید عدد صحیح بزرگ‌تر از صفر باشد.")
        return
    d=await state.get_data()
    p=await ServicePeriod.get(session,int(d["period_id"]))
    if not p:
        await state.clear()
        await message.answer("❌ دوره پیدا نشد.")
        return
    if p.custom_max_volume_gb>0 and value>p.custom_max_volume_gb:
        await message.answer(
            f"❌ حداقل حجم نمی‌تواند از حداکثر فعلی ({p.custom_max_volume_gb:,} GB) بیشتر باشد."
        )
        return
    p.custom_min_volume_gb=value
    await session.commit()
    await state.clear()
    await message.answer(
        f"✅ حداقل حجم دلخواه دوره <b>{p.name}</b> روی <b>{value:,} GB</b> تنظیم شد.",
        reply_markup=_plans_kb(p,await ServicePurchasePlan.list_by_type(session,p.service_type))
    )

@router.callback_query(F.data.regexp(r"^sp:custom_max:\\d+$"),IsAdmin())
async def custom_max(callback:CallbackQuery,state:FSMContext,session:AsyncSession):
    p=await ServicePeriod.get(session,int(callback.data.rsplit(":",1)[1]))
    if not p or p.is_archived:
        await callback.answer("❌ دوره پیدا نشد.",show_alert=True)
        return
    await state.clear()
    await state.update_data(period_id=p.id)
    await state.set_state(PeriodStates.custom_max)
    await callback.answer()
    await callback.message.edit_text(
        f"📦 <b>حداکثر حجم دلخواه</b>\\n\\n"
        f"دوره: <b>{p.name}</b>\\n"
        f"مقدار فعلی: <b>{'نامحدود' if p.custom_max_volume_gb<=0 else f'{p.custom_max_volume_gb:,} GB'}</b>\\n\\n"
        "حداکثر حجم را به GB وارد کنید.\\n"
        "برای نامحدود عدد <code>0</code> را وارد کنید:"
    )

@router.message(PeriodStates.custom_max,IsAdmin())
async def save_custom_max(message:Message,state:FSMContext,session:AsyncSession):
    try:
        value=int((message.text or "").replace(",","").replace("٬",""))
        assert value>=0
    except:
        await message.answer("❌ حجم نامعتبر است. عدد صفر یا بیشتر وارد کنید.")
        return
    d=await state.get_data()
    p=await ServicePeriod.get(session,int(d["period_id"]))
    if not p:
        await state.clear()
        await message.answer("❌ دوره پیدا نشد.")
        return
    if value>0 and value<p.custom_min_volume_gb:
        await message.answer(
            f"❌ حداکثر حجم نمی‌تواند از حداقل فعلی ({p.custom_min_volume_gb:,} GB) کمتر باشد."
        )
        return
    p.custom_max_volume_gb=value
    await session.commit()
    await state.clear()
    await message.answer(
        f"✅ حداکثر حجم دلخواه دوره <b>{p.name}</b> روی "
        f"<b>{'نامحدود' if value<=0 else f'{value:,} GB'}</b> تنظیم شد.",
        reply_markup=_plans_kb(p,await ServicePurchasePlan.list_by_type(session,p.service_type))
    )

@router.callback_query(F.data.regexp(r"^sp:create_plan:\\d+$"),IsAdmin())
''',
        ),
    ],
)


# 4) Custom-volume button in customer keyboard.
edit(
    "app/bot/routers/subscription/keyboard.py",
    [
        (
            "def service_purchase_plan_keyboard(plans: list, callback_data: SubscriptionData) -> InlineKeyboardMarkup:\n",
            "def service_purchase_plan_keyboard(plans: list, callback_data: SubscriptionData, custom_period_id: int | None = None) -> InlineKeyboardMarkup:\n",
        ),
        (
            '    builder.adjust(1)\n    builder.row(back_button(NavSubscription.BUY, text="🔙 تغییر نوع سرویس"))\n',
            '    builder.adjust(1)\n    if custom_period_id is not None:\n        builder.row(InlineKeyboardButton(text="📦 حجم دلخواه", callback_data=f"subscription_custom:{custom_period_id}"))\n    builder.row(back_button(NavSubscription.BUY, text="🔙 تغییر نوع سرویس"))\n',
        ),
    ],
)


# 4b) Pass period ID from dynamic purchase handler.
edit(
    "app/bot/routers/subscription/dynamic_service_purchase_handler.py",
    [
        (
            "reply_markup=service_purchase_plan_keyboard(plans,data))\n",
            "reply_markup=service_purchase_plan_keyboard(plans,data,p.id))\n",
        ),
        (
            "reply_markup=service_purchase_plan_keyboard(plans,data))\n",
            "reply_markup=service_purchase_plan_keyboard(plans,data,p.id))\n",
        ),
    ],
)


# 5) Refactor ordinary purchase flow and add custom-volume purchase.
edit(
    "app/bot/routers/subscription/subscription_handler.py",
    [
        (
            "from app.db.models import ConnectedDeviceSettings, ServicePurchasePlan, User\n",
            "from app.db.models import ConnectedDeviceSettings, ServicePurchasePlan, ServicePeriod, User\n",
        ),
        (
            '''class PurchaseConfigState(StatesGroup):
    waiting_config_name = State()
    selecting_payment = State()
''',
            '''class PurchaseConfigState(StatesGroup):
    waiting_config_name = State()
    selecting_payment = State()
    waiting_custom_volume = State()
''',
        ),
    ],
)


file = ROOT / "app/bot/routers/subscription/subscription_handler.py"
text = file.read_text(encoding="utf-8")

old_start = '''@router.callback_query(F.data.regexp(r"^subscription_plan:\\d+$"))
async def callback_subscription_plan_selected(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    plan = await ServicePurchasePlan.get(session, int(callback.data.rsplit(":", 1)[1]))

    if not plan:
        await callback.answer("این پلن دیگر وجود ندارد.", show_alert=True)
        return

    auto_name = await services.vpn._generate_unique_config_name(
        volume_gb=plan.volume_gb,
        duration_days=plan.duration_days,
        tg_id=user.tg_id,
    )

    customer_level, purchase_count, discounted_price = await get_discounted_plan_price(
        session,
        user.tg_id,
        plan.price_toman,
    )

    discount_percent = int(getattr(customer_level, "discount_percent", 0) or 0)

    data = SubscriptionData(
        state=NavSubscription.CONFIG_NAME,
        user_id=user.tg_id,
        devices=(await ConnectedDeviceSettings.get_or_create(session)).max_connected_devices,
        duration=plan.duration_days,
        price=discounted_price,
        original_price=plan.price_toman,
        discount_percent=int(discount_percent or 0),
        discount_level_title=str(
            getattr(customer_level, "title", "")
            or getattr(customer_level, "name", "")
            or ""
        ),
        plan_id=plan.id,
        volume_gb=plan.volume_gb,
        config_name=auto_name,
    )

    await state.update_data(
        subscription_data={
            "state": NavSubscription.CONFIG_NAME.value,
            "is_extend": data.is_extend,
            "is_change": data.is_change,
            "user_id": data.user_id,
            "devices": data.devices,
            "duration": data.duration,
            "price": data.price,
            "original_price": data.original_price,
            "discount_percent": data.discount_percent,
            "discount_level_title": data.discount_level_title,
            "plan_id": data.plan_id,
            "volume_gb": data.volume_gb,
            "config_name": data.config_name,
        }
    )
    await state.set_state(PurchaseConfigState.waiting_config_name)

    await callback.answer()

    await callback.message.edit_text(
        "⚙️ <b>نام کانفیگ</b>\\n\\n"
        f"نام خودکار:\\n<code>{auto_name}</code>\\n\\n"
        "یا نام دلخواه خود را وارد کنید <b>(فقط انگلیسی)</b>:\\n\\n"
        "نام انتخابی باید فقط شامل حروف انگلیسی، عدد، <code>_</code> یا <code>-</code> باشد.",
        reply_markup=config_name_keyboard(data),
    )

'''

new_start = '''async def _start_plan_purchase(
    *,
    event: CallbackQuery | Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
    plan: ServicePurchasePlan,
) -> None:
    auto_name = await services.vpn._generate_unique_config_name(
        volume_gb=plan.volume_gb,
        duration_days=plan.duration_days,
        tg_id=user.tg_id,
    )

    customer_level, purchase_count, discounted_price = await get_discounted_plan_price(
        session,
        user.tg_id,
        plan.price_toman,
    )

    discount_percent = int(getattr(customer_level, "discount_percent", 0) or 0)

    data = SubscriptionData(
        state=NavSubscription.CONFIG_NAME,
        user_id=user.tg_id,
        devices=(await ConnectedDeviceSettings.get_or_create(session)).max_connected_devices,
        duration=plan.duration_days,
        price=discounted_price,
        original_price=plan.price_toman,
        discount_percent=discount_percent,
        discount_level_title=str(
            getattr(customer_level, "title", "")
            or getattr(customer_level, "name", "")
            or ""
        ),
        plan_id=plan.id,
        volume_gb=plan.volume_gb,
        config_name=auto_name,
    )

    await state.update_data(
        subscription_data={
            "state": NavSubscription.CONFIG_NAME.value,
            "is_extend": data.is_extend,
            "is_change": data.is_change,
            "user_id": data.user_id,
            "devices": data.devices,
            "duration": data.duration,
            "price": data.price,
            "original_price": data.original_price,
            "discount_percent": data.discount_percent,
            "discount_level_title": data.discount_level_title,
            "plan_id": data.plan_id,
            "volume_gb": data.volume_gb,
            "config_name": data.config_name,
        }
    )
    await state.set_state(PurchaseConfigState.waiting_config_name)

    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.edit_text(
            "⚙️ <b>نام کانفیگ</b>\\n\\n"
            f"نام خودکار:\\n<code>{auto_name}</code>\\n\\n"
            "یا نام دلخواه خود را وارد کنید <b>(فقط انگلیسی)</b>:\\n\\n"
            "نام انتخابی باید فقط شامل حروف انگلیسی، عدد، <code>_</code> یا <code>-</code> باشد.",
            reply_markup=config_name_keyboard(data),
        )
    else:
        await event.answer(
            "⚙️ <b>نام کانفیگ</b>\\n\\n"
            f"نام خودکار:\\n<code>{auto_name}</code>\\n\\n"
            "یا نام دلخواه خود را وارد کنید <b>(فقط انگلیسی)</b>:\\n\\n"
            "نام انتخابی باید فقط شامل حروف انگلیسی، عدد، <code>_</code> یا <code>-</code> باشد.",
            reply_markup=config_name_keyboard(data),
        )


@router.callback_query(F.data.regexp(r"^subscription_plan:\\d+$"))
async def callback_subscription_plan_selected(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    plan = await ServicePurchasePlan.get(
        session,
        int(callback.data.rsplit(":", 1)[1]),
    )

    if not plan or plan.is_custom:
        await callback.answer("این پلن دیگر وجود ندارد.", show_alert=True)
        return

    await _start_plan_purchase(
        event=callback,
        user=user,
        session=session,
        state=state,
        services=services,
        plan=plan,
    )


@router.callback_query(F.data.regexp(r"^subscription_custom:\\d+$"))
async def callback_subscription_custom_volume(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    period_id = int(callback.data.rsplit(":", 1)[1])
    period = await ServicePeriod.get(session, period_id)

    if not period or not period.is_active or period.is_archived:
        await callback.answer("❌ این دوره دیگر فعال نیست.", show_alert=True)
        return

    if period.custom_price_per_gb_toman <= 0:
        await callback.answer(
            "❌ مبلغ پایه هر گیگ برای این دوره هنوز توسط مدیر تنظیم نشده است.",
            show_alert=True,
        )
        return

    if period.custom_min_volume_gb <= 0:
        await callback.answer(
            "❌ حداقل حجم دلخواه برای این دوره هنوز توسط مدیر تنظیم نشده است.",
            show_alert=True,
        )
        return

    await state.clear()
    await state.update_data(custom_period_id=period.id)
    await state.set_state(PurchaseConfigState.waiting_custom_volume)

    max_text = (
        "نامحدود"
        if period.custom_max_volume_gb <= 0
        else f"{period.custom_max_volume_gb:,} GB"
    )

    await callback.answer()
    await callback.message.edit_text(
        "📦 <b>حجم دلخواه</b>\\n\\n"
        f"📅 دوره: <b>{period.name}</b>\\n"
        f"⏱ مدت: <b>{period.duration_days} روز</b>\\n"
        f"💰 مبلغ پایه هر گیگ: <b>{period.custom_price_per_gb_toman:,} تومان</b>\\n"
        f"📦 حداقل حجم: <b>{period.custom_min_volume_gb:,} GB</b>\\n"
        f"📦 حداکثر حجم: <b>{max_text}</b>\\n\\n"
        "حجم دلخواه خود را به GB وارد کنید:",
    )


@router.message(PurchaseConfigState.waiting_custom_volume)
async def message_subscription_custom_volume(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    raw = (message.text or "").replace(",", "").replace("٬", "").strip()

    try:
        volume = int(raw)
        if volume <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ حجم نامعتبر است. لطفاً یک عدد صحیح بزرگ‌تر از صفر وارد کنید."
        )
        return

    data = await state.get_data()

    period = await ServicePeriod.get(
        session,
        int(data.get("custom_period_id", 0) or 0),
    )

    if not period or not period.is_active or period.is_archived:
        await state.clear()
        await message.answer(
            "❌ این دوره دیگر فعال نیست. لطفاً دوباره دوره را انتخاب کنید."
        )
        return

    if period.custom_price_per_gb_toman <= 0 or period.custom_min_volume_gb <= 0:
        await state.clear()
        await message.answer(
            "❌ تنظیمات حجم دلخواه این دوره کامل نیست. لطفاً بعداً دوباره تلاش کنید."
        )
        return

    if volume < period.custom_min_volume_gb:
        await message.answer(
            f"❌ حداقل حجم قابل سفارش برای این دوره "
            f"<b>{period.custom_min_volume_gb:,} GB</b> است."
        )
        return

    if period.custom_max_volume_gb > 0 and volume > period.custom_max_volume_gb:
        await message.answer(
            f"❌ حداکثر حجم قابل سفارش برای این دوره "
            f"<b>{period.custom_max_volume_gb:,} GB</b> است."
        )
        return

    price = volume * period.custom_price_per_gb_toman

    custom_plan = ServicePurchasePlan(
        service_type=period.service_type,
        volume_gb=volume,
        duration_days=period.duration_days,
        price_toman=price,
        is_custom=True,
    )

    session.add(custom_plan)
    await session.commit()
    await state.clear()

    await _start_plan_purchase(
        event=message,
        user=user,
        session=session,
        state=state,
        services=services,
        plan=custom_plan,
    )

'''

if old_start not in text:
    raise SystemExit("PATCH FAILED: subscription plan-selection block not found")

file.write_text(text.replace(old_start, new_start, 1), encoding="utf-8")


# 6) Migration.
new_migration = '''"""add per-period custom volume pricing settings

Revision ID: 20260829_custom_volume_purchase
Revises: 20260829_custom_service_button_visibility
"""

from alembic import op
import sqlalchemy as sa

revision: str = "20260829_custom_volume_purchase"
down_revision: str | None = "20260829_custom_service_button_visibility"
branch_labels = None
depends_on = None


def _columns(table: str):
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table)
    }


def upgrade() -> None:
    period_columns = _columns("service_periods")

    if "custom_price_per_gb_toman" not in period_columns:
        op.add_column(
            "service_periods",
            sa.Column(
                "custom_price_per_gb_toman",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

    if "custom_min_volume_gb" not in period_columns:
        op.add_column(
            "service_periods",
            sa.Column(
                "custom_min_volume_gb",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

    if "custom_max_volume_gb" not in period_columns:
        op.add_column(
            "service_periods",
            sa.Column(
                "custom_max_volume_gb",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

    plan_columns = _columns("service_purchase_plans")

    if "is_custom" not in plan_columns:
        op.add_column(
            "service_purchase_plans",
            sa.Column(
                "is_custom",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    plan_columns = _columns("service_purchase_plans")

    if "is_custom" in plan_columns:
        op.drop_column("service_purchase_plans", "is_custom")

    period_columns = _columns("service_periods")

    for name in (
        "custom_max_volume_gb",
        "custom_min_volume_gb",
        "custom_price_per_gb_toman",
    ):
        if name in period_columns:
            op.drop_column("service_periods", name)
'''

migration = ROOT / "app/db/migration/versions/20260829_custom_volume_purchase.py"

if migration.exists():
    raise SystemExit(
        f"PATCH FAILED: migration already exists: {migration}"
    )

migration.write_text(new_migration, encoding="utf-8")

print("PATCHED: dynamic custom-volume purchase")
print(
    "Files changed: ServicePeriod model, ServicePurchasePlan model, "
    "dynamic period admin, subscription keyboard, dynamic purchase handler, "
    "subscription handler, Alembic migration"
)
