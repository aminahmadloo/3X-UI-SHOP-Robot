from aiogram import Dispatcher
from aiogram.utils.i18n import I18n
from sqlalchemy.ext.asyncio import async_sessionmaker

from .database import DBSessionMiddleware
from .garbage import GarbageMiddleware
from .maintenance import MaintenanceMiddleware
from .throttling import ThrottlingMiddleware
from .user_i18n import UserI18nMiddleware


def register(dispatcher: Dispatcher, i18n: I18n, session: async_sessionmaker) -> None:
    # Database must run before i18n so the persisted user language is available.
    middlewares = [
        ThrottlingMiddleware(),
        GarbageMiddleware(),
        DBSessionMiddleware(session),
        UserI18nMiddleware(i18n),
        MaintenanceMiddleware(),
    ]

    for middleware in middlewares:
        dispatcher.update.middleware.register(middleware)
