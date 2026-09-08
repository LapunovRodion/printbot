"""Команды администратора: журнал, код доступа, доступ пользователей (US5)."""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from printbot import texts
from printbot.bot.states import AdminFlow
from printbot.core.models import AuditEventType
from printbot.services import Services

log = logging.getLogger(__name__)

router = Router(name="admin")

MIN_CODE_LENGTH = 4
MAX_CODE_LENGTH = 64


def _is_admin(message: Any, services: Services) -> bool:
    return services.is_admin(message.from_user.id)


@router.message(Command("journal"))
async def cmd_journal(message: Any, services: Services) -> None:
    if not _is_admin(message, services):
        await message.answer(texts.ACCESS_DENIED_ADMIN)
        return
    parts = (message.text or "").split()
    try:
        limit = max(1, min(100, int(parts[1]))) if len(parts) > 1 else 20
    except ValueError:
        limit = 20

    jobs = await services.jobs.list_recent(limit)
    if not jobs:
        await message.answer(texts.JOURNAL_EMPTY)
        return
    lines = [texts.JOURNAL_HEADER.format(count=len(jobs))]
    for job in jobs:
        user = await services.users.get(job.user_id)
        who = user.display_name if user else str(job.user_id)
        lines.append(f"{texts.job_line(job)} · {who}")
    await message.answer("\n".join(lines))


@router.message(Command("setcode"))
async def cmd_setcode(message: Any, state: FSMContext, services: Services) -> None:
    if not _is_admin(message, services):
        await message.answer(texts.ACCESS_DENIED_ADMIN)
        return
    await state.set_state(AdminFlow.waiting_new_code)
    await message.answer(texts.SETCODE_ASK)


@router.message(AdminFlow.waiting_new_code)
async def on_new_code(message: Any, state: FSMContext, services: Services) -> None:
    if not _is_admin(message, services):  # pragma: no cover - состояние принадлежит админу
        await state.clear()
        return

    code = (message.text or "").strip()
    with suppress(Exception):
        await message.delete()

    if len(code) < MIN_CODE_LENGTH or len(code) > MAX_CODE_LENGTH:
        await message.answer(texts.SETCODE_TOO_SHORT)
        return

    await services.access.set_code(code, actor_id=message.from_user.id)
    await state.clear()
    await message.answer(texts.SETCODE_DONE)
    log.info("Администратор %s сменил код доступа", message.from_user.id)


@router.message(Command("revoke"))
async def cmd_revoke(message: Any, services: Services) -> None:
    if not _is_admin(message, services):
        await message.answer(texts.ACCESS_DENIED_ADMIN)
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer(texts.REVOKE_USAGE)
        return
    try:
        target = int(parts[1])
    except ValueError:
        await message.answer(texts.REVOKE_USAGE)
        return

    revoked = await services.access.revoke(target, actor_id=message.from_user.id)
    await message.answer(
        texts.REVOKE_DONE.format(target=target)
        if revoked
        else texts.REVOKE_NOT_FOUND.format(target=target)
    )


@router.message(Command("users"))
async def cmd_users(message: Any, services: Services) -> None:
    if not _is_admin(message, services):
        await message.answer(texts.ACCESS_DENIED_ADMIN)
        return
    users = await services.users.list_allowed()
    if not users:
        await message.answer(texts.USERS_EMPTY)
        return
    lines = [texts.USERS_HEADER.format(count=len(users))]
    for user in users:
        handle = f" @{user.username}" if user.username else ""
        role = " · админ" if user.is_admin else ""
        lines.append(f"{user.telegram_id} · {user.display_name}{handle}{role}")
    await message.answer("\n".join(lines))


@router.message(Command("purge_journal"))
async def cmd_purge_journal(message: Any, services: Services) -> None:
    """Явное удаление журнала — единственный способ его очистить (FR-027)."""
    if not _is_admin(message, services):
        await message.answer(texts.ACCESS_DENIED_ADMIN)
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or parts[1] != "CONFIRM":
        await message.answer(texts.PURGE_USAGE)
        return

    count = await services.jobs.purge()
    await services.jobs.add_event(
        AuditEventType.JOURNAL_PURGED,
        actor_id=message.from_user.id,
        detail=f"удалено записей: {count}",
    )
    await message.answer(texts.PURGE_DONE.format(count=count))
