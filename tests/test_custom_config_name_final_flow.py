import asyncio
from types import SimpleNamespace

from app.bot.services.vpn import VPNService


class _Session:
    def __init__(self):
        self.added = None
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def add(self, value):
        self.added = value

    async def commit(self):
        self.committed = True


class _SessionFactory:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self.session


def test_first_custom_name_ending_in_one_reaches_xui_unchanged(monkeypatch):
    service = object.__new__(VPNService)
    session = _Session()
    service.session = _SessionFactory(session)

    captured = {}

    async def fake_create_client(**kwargs):
        captured.update(kwargs)
        return "client-uuid"

    service.create_client = fake_create_client

    async def fake_user_get(*, session, tg_id):
        return SimpleNamespace(id=123, server_id=7, tg_id=tg_id)

    monkeypatch.setattr("app.bot.services.vpn.User.get", fake_user_get)

    user = SimpleNamespace(tg_id=78797797)
    requested_name = "AminAhm-20GB-30D-tg78797797-1"

    result = asyncio.run(
        service.create_subscription(
            user=user,
            devices=1,
            duration=30,
            total_gb=20,
            config_name=requested_name,
        )
    )

    assert result is True
    assert captured["config_name"] == requested_name
    assert session.added.config_name == requested_name
    assert session.committed is True


def test_missing_custom_name_still_uses_automatic_naming(monkeypatch):
    service = object.__new__(VPNService)
    session = _Session()
    service.session = _SessionFactory(session)

    captured = {}

    async def fake_auto_name(**kwargs):
        return "20GB-30D-tg78797797-101"

    async def fake_create_client(**kwargs):
        captured.update(kwargs)
        return "client-uuid"

    service._generate_unique_config_name = fake_auto_name
    service.create_client = fake_create_client

    async def fake_user_get(*, session, tg_id):
        return SimpleNamespace(id=123, server_id=7, tg_id=tg_id)

    monkeypatch.setattr("app.bot.services.vpn.User.get", fake_user_get)

    user = SimpleNamespace(tg_id=78797797)

    result = asyncio.run(
        service.create_subscription(
            user=user,
            devices=1,
            duration=30,
            total_gb=20,
            config_name=None,
        )
    )

    assert result is True
    assert captured["config_name"] == "20GB-30D-tg78797797-101"
