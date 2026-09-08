"""Пропускает к печати только авторизованных пользователей (FR-020)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from printbot.core.models import Role
from printbot.services import Services


class AccessMiddleware(BaseMiddleware):
    """Кладёт в контекст текущего пользователя и отсекает неавторизованных."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        services: Services = data["services"]
        tg_user = data.get("event_from_user")
        if tg_user is None:
            return await handler(event, data)

        user = await services.users.get_or_create(
            tg_user.id, tg_user.full_name or str(tg_user.id), tg_user.username
        )
        if services.is_admin(user.telegram_id) and user.role is not Role.ADMIN:
            await services.users.set_role(user.telegram_id, Role.ADMIN)
            user.role = Role.ADMIN

        data["user"] = user
        data["is_authorized"] = user.is_allowed
        return await handler(event, data)
