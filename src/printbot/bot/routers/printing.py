"""Диалог печати: приём файла → параметры → подтверждение (US1, US2)."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext

from printbot import texts
from printbot.bot import keyboards as kb
from printbot.bot.states import PrintFlow
from printbot.core.documents import (
    DocumentError,
    estimate_pages,
    validate_size,
    validate_source,
)
from printbot.core.models import DocumentFormat, DuplexMode, PaperSize, PrinterView
from printbot.services import Services
from printbot.util.files import remove_tree

log = logging.getLogger(__name__)

router = Router(name="printing")

_UNSAFE_NAME = re.compile(r"[^\w.\- ]+", re.UNICODE)


def _safe_name(file_name: str | None) -> str:
    name = _UNSAFE_NAME.sub("_", (file_name or "document").strip())[:120]
    return name or "document"


# --- работа с черновиком -------------------------------------------------------


async def _discard_draft(state: FSMContext, *, notify: Any = None) -> bool:
    """Удаляет незавершённый черновик вместе с файлом. True — черновик был."""
    data = await state.get_data()
    workspace = data.get("workspace")
    await state.clear()
    if not data:
        return False
    if workspace:
        remove_tree(Path(workspace))
    if notify is not None:
        await notify.answer(texts.DRAFT_REPLACED)
    return True


async def _load_draft(state: FSMContext, services: Services, reply: Any) -> dict | None:
    """Возвращает данные черновика либо None, если он пуст или истёк (FR-011)."""
    data = await state.get_data()
    if not data or "workspace" not in data:
        await reply.answer(texts.STALE_CALLBACK)
        await state.clear()
        return None

    created_at = datetime.fromisoformat(data["created_at"])
    age_min = (datetime.now(UTC) - created_at).total_seconds() / 60
    if age_min > services.config.settings.dialog_timeout_min:
        remove_tree(Path(data["workspace"]))
        await state.clear()
        await reply.answer(texts.DIALOG_EXPIRED)
        return None
    return data


# --- шаг 1: приём файла --------------------------------------------------------


@router.message(F.document)
async def on_document(message: Any, state: FSMContext, services: Services, bot: Any) -> None:
    document = message.document
    if document is None:  # pragma: no cover - фильтр роутера уже отсеял
        await message.answer(texts.FILE_NOT_DOCUMENT)
        return

    had_draft = await _discard_draft(state)
    if had_draft:
        await message.answer(texts.DRAFT_REPLACED)

    settings = services.config.settings
    try:
        validate_size(document.file_size, settings.max_file_bytes)
    except DocumentError as exc:
        await message.answer(_document_error_text(exc, settings, document.file_size))
        return

    workspace = services.jobs_root / f"draft-{message.from_user.id}-{uuid.uuid4().hex}"
    source = workspace / _safe_name(document.file_name)
    source.parent.mkdir(parents=True, exist_ok=True)
    try:
        await bot.download(document, destination=source)
    except Exception:
        log.exception("Не удалось скачать файл от пользователя %s", message.from_user.id)
        remove_tree(workspace)
        await message.answer(texts.INTERNAL_ERROR)
        return

    try:
        fmt = validate_source(source)
    except DocumentError as exc:
        remove_tree(workspace)
        await message.answer(_document_error_text(exc, settings, document.file_size))
        return

    pages = estimate_pages(source, fmt)
    await state.set_data(
        {
            "workspace": str(workspace),
            "source": str(source),
            "file_name": document.file_name or source.name,
            "file_size": source.stat().st_size,
            "format": fmt.value,
            "page_count": pages,
            "created_at": datetime.now(UTC).isoformat(),
        }
    )
    await message.answer(texts.FILE_ACCEPTED.format(file_name=document.file_name or source.name))
    await _ask_printer(message, state, services)


def _document_error_text(exc: DocumentError, settings: Any, size: int | None) -> str:
    from printbot.core.models import ErrorCode

    if exc.user_message:
        return exc.user_message
    match exc.code:
        case ErrorCode.FILE_TOO_LARGE:
            return texts.FILE_TOO_LARGE.format(
                size_mb=(size or 0) / 1024 / 1024, max_mb=settings.max_file_mb
            )
        case ErrorCode.UNSUPPORTED_FORMAT:
            return texts.FILE_UNSUPPORTED.format(formats=texts.SUPPORTED_FORMATS)
        case ErrorCode.ENCRYPTED_FILE:
            return texts.FILE_ENCRYPTED
        case _:
            return texts.FILE_CORRUPT


# --- шаг 2: принтер ------------------------------------------------------------


async def _ask_printer(reply: Any, state: FSMContext, services: Services) -> None:
    views = await services.printers.available_views()
    if not views:
        await _discard_draft(state)
        await reply.answer(texts.NO_PRINTERS)
        return
    if len(views) == 1:
        await _remember_printer(state, views[0])
        await _ask_paper(reply, state, services)
        return
    await state.set_state(PrintFlow.choosing_printer)
    await reply.answer(texts.ASK_PRINTER, reply_markup=kb.printers_keyboard(views))


async def _remember_printer(state: FSMContext, view: PrinterView) -> None:
    await state.update_data(
        printer_key=view.key,
        printer_system=view.system_name,
        printer_display=view.display_name,
        supports_duplex=view.supports_duplex,
        supports_a3=view.supports_a3,
        paper=PaperSize.A4.value,
    )


@router.callback_query(F.data.startswith(f"{kb.CB_PRINTER}:"))
async def on_printer_chosen(callback: Any, state: FSMContext, services: Services) -> None:
    data = await _load_draft(state, services, callback.message)
    if data is None:
        await callback.answer()
        return

    key = callback.data.split(":", 1)[1]
    view = await services.printers.get_view(key)
    if view is None:
        await callback.message.answer(texts.STALE_CALLBACK)
        await callback.answer()
        return
    if not view.available:
        await callback.message.answer(
            texts.PRINTER_UNAVAILABLE.format(
                printer=view.display_name, reason=texts.error_text(view.reason)
            )
        )
        await callback.answer()
        return

    await _remember_printer(state, view)
    await _ask_paper(callback.message, state, services)
    await callback.answer()


# --- шаг 3: формат бумаги (только для принтеров с A3) --------------------------


async def _ask_paper(reply: Any, state: FSMContext, services: Services) -> None:
    """У принтеров без A3 шага нет — лишний вопрос там только мешает."""
    data = await state.get_data()
    if not data.get("supports_a3"):
        await state.update_data(paper=PaperSize.A4.value)
        await _ask_duplex(reply, state, services)
        return
    await state.set_state(PrintFlow.choosing_paper)
    await reply.answer(texts.ASK_PAPER, reply_markup=kb.paper_keyboard())


@router.callback_query(F.data.startswith(f"{kb.CB_PAPER}:"))
async def on_paper_chosen(callback: Any, state: FSMContext, services: Services) -> None:
    data = await _load_draft(state, services, callback.message)
    if data is None:
        await callback.answer()
        return

    value = callback.data.split(":", 1)[1]
    paper = PaperSize.A3 if value == PaperSize.A3.value else PaperSize.A4
    if paper is PaperSize.A3 and not data.get("supports_a3"):
        await callback.message.answer(texts.PAPER_UNAVAILABLE)
        await callback.answer()
        return

    await state.update_data(paper=paper.value)
    await _ask_duplex(callback.message, state, services)
    await callback.answer()


# --- шаг 4: стороны ------------------------------------------------------------


async def _ask_duplex(reply: Any, state: FSMContext, services: Services) -> None:
    data = await state.get_data()
    supports = bool(data.get("supports_duplex"))
    await state.set_state(PrintFlow.choosing_duplex)
    if not supports:
        await reply.answer(texts.DUPLEX_UNAVAILABLE)
    await reply.answer(texts.ASK_DUPLEX, reply_markup=kb.duplex_keyboard(supports))


@router.callback_query(F.data.startswith(f"{kb.CB_DUPLEX}:"))
async def on_duplex_chosen(callback: Any, state: FSMContext, services: Services) -> None:
    data = await _load_draft(state, services, callback.message)
    if data is None:
        await callback.answer()
        return

    value = callback.data.split(":", 1)[1]
    duplex = DuplexMode.DUPLEX_LONG if value == kb.DUPLEX_LONG else DuplexMode.SIMPLEX
    if duplex is DuplexMode.DUPLEX_LONG and not data.get("supports_duplex"):
        await callback.message.answer(texts.DUPLEX_UNAVAILABLE)
        await callback.answer()
        return

    await state.update_data(duplex=duplex.value)
    await state.set_state(PrintFlow.entering_copies)
    await callback.message.answer(
        texts.ASK_COPIES.format(max_copies=services.config.settings.max_copies),
        reply_markup=kb.copies_keyboard(services.config.settings.max_copies),
    )
    await callback.answer()


# --- шаг 5: копии --------------------------------------------------------------


async def _set_copies(reply: Any, state: FSMContext, services: Services, raw: str) -> None:
    max_copies = services.config.settings.max_copies
    try:
        copies = int(raw.strip())
    except (TypeError, ValueError):
        await reply.answer(texts.COPIES_INVALID.format(max_copies=max_copies))
        return
    if not 1 <= copies <= max_copies:
        await reply.answer(texts.COPIES_INVALID.format(max_copies=max_copies))
        return

    await state.update_data(copies=copies)
    await state.set_state(PrintFlow.confirming)
    data = await state.get_data()
    await reply.answer(_summary_text(data), reply_markup=kb.confirm_keyboard())


def _summary_text(data: dict) -> str:
    pages = data.get("page_count")
    paper = PaperSize(data.get("paper", PaperSize.A4.value))
    return texts.CONFIRM_SUMMARY.format(
        file_name=data["file_name"],
        printer=data["printer_display"],
        paper=texts.PAPER_TEXTS[paper],
        duplex=texts.DUPLEX_TEXTS[DuplexMode(data["duplex"])],
        copies=data["copies"],
        pages=f"\n• Страниц: {pages}" if pages else "",
    )


@router.callback_query(F.data.startswith(f"{kb.CB_COPIES}:"))
async def on_copies_chosen(callback: Any, state: FSMContext, services: Services) -> None:
    data = await _load_draft(state, services, callback.message)
    if data is None:
        await callback.answer()
        return
    await _set_copies(callback.message, state, services, callback.data.split(":", 1)[1])
    await callback.answer()


@router.message(PrintFlow.entering_copies)
async def on_copies_text(message: Any, state: FSMContext, services: Services) -> None:
    data = await _load_draft(state, services, message)
    if data is None:
        return
    await _set_copies(message, state, services, message.text or "")


# --- шаг 6: подтверждение и постановка в очередь -------------------------------


@router.callback_query(F.data.startswith(f"{kb.CB_CONFIRM}:"))
async def on_confirm(callback: Any, state: FSMContext, services: Services) -> None:
    action = callback.data.split(":", 1)[1]
    if action == "cancel":
        await _discard_draft(state)
        await callback.message.answer(texts.CANCELLED)
        await callback.answer()
        return

    data = await _load_draft(state, services, callback.message)
    if data is None or "copies" not in data:
        if data is not None:
            await callback.message.answer(texts.STALE_CALLBACK)
        await callback.answer()
        return

    pages = data.get("page_count")
    threshold = services.config.settings.large_doc_pages
    if pages and pages * data["copies"] > threshold:
        await state.set_state(PrintFlow.confirming_large)
        await callback.message.answer(
            texts.CONFIRM_LARGE_DOC.format(
                pages=pages, copies=data["copies"], total=pages * data["copies"]
            ),
            reply_markup=kb.large_doc_keyboard(),
        )
        await callback.answer()
        return

    await _submit(callback.message, state, services, data, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith(f"{kb.CB_LARGE}:"))
async def on_large_confirm(callback: Any, state: FSMContext, services: Services) -> None:
    action = callback.data.split(":", 1)[1]
    if action == "cancel":
        await _discard_draft(state)
        await callback.message.answer(texts.CANCELLED)
        await callback.answer()
        return

    data = await _load_draft(state, services, callback.message)
    if data is None:
        await callback.answer()
        return
    await _submit(callback.message, state, services, data, callback.from_user.id)
    await callback.answer()


async def _submit(
    reply: Any, state: FSMContext, services: Services, data: dict, user_id: int
) -> None:
    """Создаёт задание и ставит его в очередь принтера (FR-009, FR-016)."""
    view = await services.printers.get_view(data["printer_key"])
    if view is None or not view.available:
        remove_tree(Path(data["workspace"]))
        await state.clear()
        reason = texts.error_text(view.reason) if view else texts.error_text(None)
        await reply.answer(
            texts.PRINTER_UNAVAILABLE.format(printer=data["printer_display"], reason=reason)
        )
        return

    job = await services.jobs.create(
        user_id=user_id,
        chat_id=reply.chat.id,
        file_name=data["file_name"],
        source_format=DocumentFormat(data["format"]),
        file_size_bytes=data["file_size"],
        printer_name=data["printer_system"],
        duplex_mode=DuplexMode(data["duplex"]),
        copies=data["copies"],
        paper=PaperSize(data.get("paper", PaperSize.A4.value)),
        page_count=data.get("page_count"),
    )
    # Владение каталогом переходит к JobService — он удалит его после печати.
    await state.clear()

    queue_length = await services.job_service.submit(
        job, Path(data["source"]), Path(data["workspace"]), data["printer_display"]
    )
    await reply.answer(
        texts.JOB_QUEUED.format(
            job_id=job.id,
            summary=texts.job_summary(job, data["printer_display"]),
            queue=queue_length,
        )
    )
