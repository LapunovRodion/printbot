"""Авторизация по общему коду доступа (US3)."""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext

from printbot import texts
from printbot.bot.states import AuthFlow
from printbot.core.models import Role
from printbot.services import Services

log = logging.getLogger(__name__)

router = Router(name="auth")


async def ensure_user(message: Any, services: Services):
    """Возвращает пользователя, создавая запись и назначая роль администратора."""
    user = await services.users.get_or_create(
        message.from_user.id,
        getattr(message.from_user, "full_name", None) or str(message.from_user.id),
        getattr(message.from_user, "username", None),
    )
    if services.is_admin(user.telegram_id) and user.role is not Role.ADMIN:
        await services.users.set_role(user.telegram_id, Role.ADMIN)
        user.role = Role.ADMIN
    return user


@router.message(CommandStart())
async def cmd_start_unauthorized(message: Any, state: FSMContext, services: Services) -> None:
    await ensure_user(message, services)
    await state.set_state(AuthFlow.waiting_code)
    await message.answer(texts.START_NEED_CODE)


@router.message()
async def on_any_message(message: Any, state: FSMContext, services: Services) -> None:
    """Любое сообщение неавторизованного пользователя трактуется как ввод кода."""
    user = await ensure_user(message, services)

    code = (message.text or "").strip()
    if not code:
        await state.set_state(AuthFlow.waiting_code)
        await message.answer(texts.ACCESS_ASK_CODE)
        return

    # Код не должен оставаться в переписке и в логах.
    with suppress(Exception):
        await message.delete()

    result = await services.access.submit_code(user, code)
    if result.granted:
        await state.clear()
        await message.answer(texts.ACCESS_GRANTED.format(formats=texts.SUPPORTED_FORMATS))
        log.info("Пользователю %s выдан доступ", user.telegram_id)
        return

    await state.set_state(AuthFlow.waiting_code)
    if result.locked_minutes is not None:
        await message.answer(texts.ACCESS_LOCKED.format(minutes=result.locked_minutes))
        return
    await message.answer(texts.ACCESS_WRONG_CODE.format(attempts_left=result.attempts_left))
