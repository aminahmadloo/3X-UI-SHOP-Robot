import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.bot.routers.admin_tools.card_payment_handler import manual_charge_user
from app.bot.routers.subscription.trial_handler import callback_get_trial
from app.db.models import User


class TestProductionUserFacingFixes(unittest.IsolatedAsyncioTestCase):
    async def test_manual_wallet_charge_uses_telegram_id_lookup(self):
        target = SimpleNamespace(tg_id=78797797)
        session = object()
        state = SimpleNamespace(
            update_data=AsyncMock(),
            set_state=AsyncMock(),
        )
        message = SimpleNamespace(
            text="78797797",
            answer=AsyncMock(),
        )

        with patch.object(User, "get", new=AsyncMock(return_value=target)) as user_get:
            await manual_charge_user(message, state, session)

        user_get.assert_awaited_once_with(session, 78797797)
        state.update_data.assert_awaited_once_with(manual_user_id=78797797)
        state.set_state.assert_awaited_once()
        message.answer.assert_awaited_once()
        self.assertIn("مبلغ شارژ", message.answer.await_args.args[0])

    async def test_test_account_success_message_contains_dynamic_quota_and_duration(self):
        created_at = datetime(2026, 9, 25, 10, 0, 0)
        expires_at = created_at + timedelta(days=3)
        record = SimpleNamespace(
            quota_bytes=512 * 1024 * 1024,
            created_at=created_at,
            expires_at=expires_at,
        )
        test_account_service = SimpleNamespace(
            BYTES_PER_MB=1024 * 1024,
            is_test_account_available=AsyncMock(return_value=True),
            create_test_account=AsyncMock(
                return_value=("https://sub.example.test/sub/token", record)
            ),
        )
        services = SimpleNamespace(
            test_account=test_account_service,
            notification=SimpleNamespace(
                notify_by_id=AsyncMock(),
                show_popup=AsyncMock(),
            ),
        )
        state = SimpleNamespace(
            update_data=AsyncMock(),
            get_value=AsyncMock(return_value=None),
        )
        callback = SimpleNamespace(
            answer=AsyncMock(),
            message=SimpleNamespace(
                chat=SimpleNamespace(id=78797797),
                edit_text=AsyncMock(),
            ),
        )
        user = SimpleNamespace(tg_id=78797797)

        await callback_get_trial(callback, user, state, services)

        text = callback.message.edit_text.await_args.kwargs["text"]
        self.assertIn("512 مگابایت", text)
        self.assertIn("3 روز", text)
        self.assertIn("تاریخ انقضا", text)
        self.assertIn("https://sub.example.test/sub/token", text)

    async def test_unavailable_test_message_does_not_use_old_wording(self):
        services = SimpleNamespace(
            test_account=SimpleNamespace(
                is_test_account_available=AsyncMock(return_value=False),
            ),
            notification=SimpleNamespace(
                notify_by_id=AsyncMock(),
            ),
        )
        state = SimpleNamespace(update_data=AsyncMock())
        callback = SimpleNamespace(answer=AsyncMock())
        user = SimpleNamespace(tg_id=78797797)

        await callback_get_trial(callback, user, state, services)

        text = services.notification.notify_by_id.await_args.kwargs["text"]
        self.assertIn("قبلاً اکانت تست دریافت کرده‌اید", text)
        self.assertIn("زمان انتظار", text)
        self.assertNotIn(
            "اگر زمان مجاز استفاده مجدد فرا رسیده باشد، دوباره درخواست کنید",
            text,
        )


if __name__ == "__main__":
    unittest.main()
