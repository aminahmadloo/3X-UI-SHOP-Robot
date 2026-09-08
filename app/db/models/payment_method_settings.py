from __future__ import annotations

from typing import Iterable, Self

from sqlalchemy import Boolean, Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class PaymentMethodSettings(Base):
    """Persistent visibility/order settings for customer payment methods."""

    __tablename__ = "payment_method_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    method_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100, index=True)

    @classmethod
    async def get_by_key(cls, session: AsyncSession, method_key: str) -> Self | None:
        result = await session.execute(select(cls).where(cls.method_key == method_key))
        return result.scalar_one_or_none()

    @classmethod
    async def ensure_defaults(cls, session: AsyncSession, gateways: Iterable[object] = ()) -> list[Self]:
        defaults: list[tuple[str, str, int]] = [
            ("pay_zarinpal", "🏦 زرین‌پال", 10),
            ("mp_card", "💳 کارت به کارت", 20),
            ("mp_wallet", "💰 کیف پول", 30),
            ("pay_aban", "💳 پرداخت خودکار کارت به کارت", 40),
            ("pay_blupal", "💳 کارت به کارت هوشمند بلوپال", 50),
        ]

        for gateway in gateways:
            callback = getattr(gateway, "callback", "")
            callback = getattr(callback, "value", callback)
            callback = str(callback or "").strip()
            if not callback:
                continue
            name = str(getattr(gateway, "name", callback) or callback)
            if not any(key == callback for key, _, _ in defaults):
                defaults.append((callback, name, 100 + len(defaults)))

        existing = {
            item.method_key: item
            for item in (await session.execute(select(cls).order_by(cls.sort_order, cls.id))).scalars().all()
        }

        for key, name, sort_order in defaults:
            item = existing.get(key)
            if item is None:
                item = cls(method_key=key, display_name=name, enabled=True, sort_order=sort_order)
                session.add(item)
                existing[key] = item
            elif key in {"pay_zarinpal", "pay_aban", "pay_blupal"} and name and item.display_name != name:
                item.display_name = name

        await session.flush()
        return sorted(existing.values(), key=lambda item: (item.sort_order, item.id))

    @classmethod
    async def get_enabled_keys(cls, session: AsyncSession, gateways: Iterable[object] = ()) -> set[str]:
        items = await cls.ensure_defaults(session, gateways)
        await session.commit()
        return {item.method_key for item in items if item.enabled}

    @classmethod
    async def get_manageable(cls, session: AsyncSession, gateways: Iterable[object] = ()) -> list[Self]:
        items = await cls.ensure_defaults(session, gateways)
        await session.commit()
        return items
