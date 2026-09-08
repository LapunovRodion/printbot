"""Сборка Dispatcher: middlewares, фильтры доступа и порядок роутеров."""

from __future__ import annotations

from typing import Any

from aiogram import Dispatcher
from aiogram.filters import BaseFilter
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import TelegramObject

from printbot.bot.middlewares.auth import AccessMiddleware
from printbot.bot.middlewares.errors import ErrorMiddleware
from printbot.bot.routers import admin, auth, common, printing
from printbot.services import Services


class IsAuthorized(BaseFilter):
    async def __call__(self, event: TelegramObject, is_authorized: bool = False) -> bool:
        return bool(is_authorized)


class IsAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject, user: Any = None) -> bool:
        return bool(user is not None and user.is_admin)


def create_dispatcher(services: Services) -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["services"] = services

    dispatcher.update.outer_middleware(AccessMiddleware())
    dispatcher.message.middleware(ErrorMiddleware())
    dispatcher.callback_query.middleware(ErrorMiddleware())

    admin.router.message.filter(IsAdmin())

    for router in (common.router, printing.router):
        router.message.filter(IsAuthorized())
        router.callback_query.filter(IsAuthorized())

    # Порядок важен: auth.router содержит catch-all для неавторизованных.
    dispatcher.include_routers(admin.router, common.router, printing.router, auth.router)
    return dispatcher
