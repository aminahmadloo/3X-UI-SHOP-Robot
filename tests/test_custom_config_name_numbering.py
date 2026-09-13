import asyncio

from app.bot.services.vpn import VPNService


class _Result:
    def __init__(self, names: list[str]):
        self._names = names

    def all(self):
        return [(name,) for name in self._names]


class _Session:
    def __init__(self, names: list[str]):
        self._names = names

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, _statement):
        return _Result(self._names)


class _SessionFactory:
    def __init__(self, names: list[str]):
        self._names = names

    def __call__(self):
        return _Session(self._names)


def _service(names: list[str]) -> VPNService:
    service = object.__new__(VPNService)
    service.session = _SessionFactory(names)
    return service


def test_custom_name_numbering_is_independent_per_service_and_name():
    service = _service(
        [
            "AminAhm-20GB-30D-tg78797797-1",
            "AminAhm-20GB-30D-tg78797797-2",
            "AminAhm-30GB-30D-tg78797797-1",
            "Other-20GB-30D-tg78797797-8",
        ]
    )

    assert asyncio.run(
        service.generate_custom_config_name("AminAhm", 20, 30, 78797797)
    ) == "AminAhm-20GB-30D-tg78797797-3"

    assert asyncio.run(
        service.generate_custom_config_name("AminAhm", 30, 30, 78797797)
    ) == "AminAhm-30GB-30D-tg78797797-2"

    assert asyncio.run(
        service.generate_custom_config_name("AminAhm", 40, 30, 78797797)
    ) == "AminAhm-40GB-30D-tg78797797-1"


def test_custom_name_prefix_matching_is_exact():
    service = _service(
        [
            "AminAhm-20GB-30D-tg78797797-9",
            "A_min-20GB-30D-tg78797797-1",
            "AminAhm-20GB-60D-tg78797797-7",
        ]
    )

    assert asyncio.run(
        service.generate_custom_config_name("A_min", 20, 30, 78797797)
    ) == "A_min-20GB-30D-tg78797797-2"
