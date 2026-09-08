"""Единый перехват необработанных исключений в хендлерах (FR-017)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from printbot import texts

log = logging.getLogger(__name__)


class ErrorMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception:
            log.exception("Необработанная ошибка в хендлере")
            message = event if isinstance(event, Message) else None
            if isinstance(event, CallbackQuery):
                message = event.message
                with suppress(Exception):
                    await event.answer()
            if message is not None:
                with suppress(Exception):
                    await message.answer(texts.INTERNAL_ERROR)
            return None
