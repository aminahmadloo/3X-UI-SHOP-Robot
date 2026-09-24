import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.bot.services.test_account import TestAccountService


class _FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeSession:
    def __init__(self, results):
        self.results = list(results)

    async def execute(self, _statement):
        return _FakeResult(self.results.pop(0))


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _SessionFactory:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return _SessionContext(self.session)


def _service(settings):
    service = object.__new__(TestAccountService)
    service.get_settings = AsyncMock(return_value=settings)
    return service


def _user(**overrides):
    values = {
        "tg_id": 78797797,
        "is_trial_used": True,
        "trial_reset_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _settings(**overrides):
    values = {
        "enabled": True,
        "reuse_after_days": 0,
        "reset_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _latest(created_at, status="deleted"):
    return SimpleNamespace(created_at=created_at, status=status)


class TestTestAccountReuseEligibility(unittest.IsolatedAsyncioTestCase):
    async def test_never_used_user_is_eligible(self):
        service = _service(_settings())
        service.session_factory = _SessionFactory(_FakeSession([None, None, None]))
        self.assertTrue(await service.is_test_account_available(_user(is_trial_used=False)))

    async def test_used_user_is_blocked_when_reuse_is_disabled(self):
        service = _service(_settings(reuse_after_days=0))
        service.session_factory = _SessionFactory(
            _FakeSession([None, None, _latest(datetime.utcnow() - timedelta(days=365))])
        )
        self.assertFalse(await service.is_test_account_available(_user()))

    async def test_reuse_after_days_allows_old_test(self):
        service = _service(_settings(reuse_after_days=30))
        service.session_factory = _SessionFactory(
            _FakeSession([None, None, _latest(datetime.utcnow() - timedelta(days=31))])
        )
        self.assertTrue(await service.is_test_account_available(_user()))

    async def test_reuse_after_days_blocks_recent_test(self):
        service = _service(_settings(reuse_after_days=30))
        service.session_factory = _SessionFactory(
            _FakeSession([None, None, _latest(datetime.utcnow() - timedelta(days=29, hours=23))])
        )
        self.assertFalse(await service.is_test_account_available(_user()))

    async def test_per_user_reset_allows_previous_test(self):
        reset_at = datetime.utcnow()
        service = _service(_settings())
        service.session_factory = _SessionFactory(
            _FakeSession([None, None, _latest(reset_at - timedelta(seconds=1))])
        )
        self.assertTrue(
            await service.is_test_account_available(_user(trial_reset_at=reset_at))
        )

    async def test_global_reset_allows_previous_test(self):
        reset_at = datetime.utcnow()
        service = _service(_settings(reset_at=reset_at))
        service.session_factory = _SessionFactory(
            _FakeSession([None, None, _latest(reset_at - timedelta(seconds=1))])
        )
        self.assertTrue(await service.is_test_account_available(_user()))

    async def test_active_test_still_blocks_reuse(self):
        service = _service(_settings(reuse_after_days=3650))
        service.session_factory = _SessionFactory(
            _FakeSession([None, _latest(datetime.utcnow(), status="active")])
        )
        self.assertFalse(await service.is_test_account_available(_user()))

    async def test_trial_history_flag_is_preserved(self):
        service = _service(_settings(reuse_after_days=30))
        service.session_factory = _SessionFactory(
            _FakeSession([None, None, _latest(datetime.utcnow() - timedelta(days=31))])
        )
        user = _user(is_trial_used=True)
        self.assertTrue(await service.is_test_account_available(user))
        self.assertTrue(user.is_trial_used)

    async def test_reset_does_not_make_newer_test_eligible(self):
        reset_at = datetime.utcnow()
        service = _service(_settings(reset_at=reset_at))
        service.session_factory = _SessionFactory(
            _FakeSession([None, None, _latest(reset_at + timedelta(seconds=1))])
        )
        self.assertFalse(await service.is_test_account_available(_user()))

    async def test_disabled_test_accounts_are_not_available(self):
        service = _service(_settings(enabled=False))
        service.session_factory = _SessionFactory(_FakeSession([]))
        self.assertFalse(await service.is_test_account_available(_user()))


if __name__ == "__main__":
    unittest.main()
