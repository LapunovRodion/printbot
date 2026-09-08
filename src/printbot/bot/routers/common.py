"""Общие команды: /start, /help, /cancel, /status, /printers."""

from __future__ import annotations

from typing import Any

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext

from printbot import texts
from printbot.bot.routers.printing import _discard_draft
from printbot.services import Services

router = Router(name="common")


@router.message(CommandStart())
async def cmd_start(message: Any, state: FSMContext, services: Services) -> None:
    await _discard_draft(state)
    await message.answer(texts.START_AUTHORIZED.format(formats=texts.SUPPORTED_FORMATS))


@router.message(Command("help"))
async def cmd_help(message: Any, services: Services) -> None:
    settings = services.config.settings
    text = texts.HELP.format(
        formats=texts.SUPPORTED_FORMATS,
        max_copies=settings.max_copies,
        max_mb=settings.max_file_mb,
    )
    if services.is_admin(message.from_user.id):
        text += texts.HELP_ADMIN_EXTRA
    await message.answer(text)


@router.message(Command("cancel"))
async def cmd_cancel(message: Any, state: FSMContext) -> None:
    await _discard_draft(state)
    await message.answer(texts.CANCELLED)


@router.message(Command("status"))
async def cmd_status(message: Any, services: Services) -> None:
    jobs = await services.jobs.list_for_user(message.from_user.id, limit=5)
    if not jobs:
        await message.answer(texts.NO_JOBS)
        return
    await message.answer("\n".join(texts.job_line(job) for job in jobs))


@router.message(Command("printers"))
async def cmd_printers(message: Any, services: Services) -> None:
    views = await services.printers.views()
    if not views:
        await message.answer(texts.NO_PRINTERS)
        return
    lines = []
    for view in views:
        mark = "✅" if view.available else "⛔"
        duplex = ", двусторонняя" if view.supports_duplex else ""
        reason = "" if view.available else f" — {texts.error_text(view.reason)}"
        title = view.config.model or view.system_name
        lines.append(f"{mark} {view.display_name} ({title}{duplex}){reason}")
    await message.answer("\n".join(lines))
