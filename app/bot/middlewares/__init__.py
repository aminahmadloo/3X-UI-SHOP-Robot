from aiogram import Dispatcher
from aiogram.utils.i18n import I18n
from sqlalchemy.ext.asyncio import async_sessionmaker

from .database import DBSessionMiddleware
from .force_join import ForceJoinMiddleware
from .garbage import GarbageMiddleware
from .maintenance import MaintenanceMiddleware
from .throttling import ThrottlingMiddleware
from .user_i18n import UserI18nMiddleware


def register(dispatcher: Dispatcher, i18n: I18n, session: async_sessionmaker) -> None:
    # Database must run before i18n so the persisted user language is available.
    # ForceJoin runs after the database/i18n layers so it can use the current
    # user/session and block all non-admin bot usage until required channels are joined.
    middlewares = [
        ThrottlingMiddleware(),
        GarbageMiddleware(),
        DBSessionMiddleware(session),
        UserI18nMiddleware(i18n),
        MaintenanceMiddleware(),
        ForceJoinMiddleware(),
    ]

    for middleware in middlewares:
        dispatcher.update.middleware.register(middleware)
