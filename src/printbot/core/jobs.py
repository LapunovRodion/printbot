"""Очередь заданий и их выполнение: по одному воркеру на принтер (research.md R8)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from printbot import texts
from printbot.core.conversion.base import ConversionError, DocumentConverter
from printbot.core.documents import page_count
from printbot.core.models import ErrorCode, JobStatus, PrintJob
from printbot.core.printing.base import PrinterBackend, PrintError, PrintOptions
from printbot.storage.jobs import JobRepository
from printbot.util.files import remove_tree

log = logging.getLogger(__name__)

Notifier = Callable[[int, str], Awaitable[None]]


@dataclass(slots=True)
class QueuedJob:
    job_id: int
    chat_id: int
    source: Path
    workspace: Path
    printer_display: str


async def _null_notifier(chat_id: int, text: str) -> None:  # pragma: no cover - заглушка
    log.debug("Уведомление в чат %s: %s", chat_id, text)


class JobService:
    """Ставит задания в очередь принтера и доводит их до финального статуса."""

    def __init__(
        self,
        repo: JobRepository,
        converter: DocumentConverter,
        backend: PrinterBackend,
        *,
        convert_timeout_s: float = 120.0,
        print_timeout_s: float = 180.0,
        notifier: Notifier | None = None,
    ) -> None:
        self._repo = repo
        self._converter = converter
        self._backend = backend
        self._convert_timeout = convert_timeout_s
        self._print_timeout = print_timeout_s
        self._notify = notifier or _null_notifier
        self._queues: dict[str, asyncio.Queue[QueuedJob]] = {}
        self._workers: list[asyncio.Task] = []
        self._running = False

    # --- жизненный цикл ---------------------------------------------------------

    async def start(self, printer_names: tuple[str, ...]) -> None:
        """Поднимает по одной очереди и одному воркеру на каждый принтер (FR-016)."""
        if self._running:
            return
        self._running = True
        for name in printer_names:
            queue: asyncio.Queue[QueuedJob] = asyncio.Queue()
            self._queues[name] = queue
            self._workers.append(
                asyncio.create_task(self._worker(name, queue), name=f"printbot-worker-{name}")
            )
        log.info("Запущены воркеры печати: %s", ", ".join(printer_names) or "нет принтеров")

    async def stop(self) -> None:
        self._running = False
        for task in self._workers:
            task.cancel()
        for task in self._workers:
            with suppress(asyncio.CancelledError):
                await task
        self._workers.clear()
        self._queues.clear()

    async def recover_unfinished(self) -> int:
        """После перезапуска незавершённые задания помечаются прерванными (FR-019)."""
        jobs = await self._repo.list_unfinished()
        for job in jobs:
            await self._repo.set_status(
                job.id,
                JobStatus.FAILED,
                error_code=ErrorCode.INTERRUPTED,
                error_detail="бот был перезапущен",
            )
            await self._safe_notify(
                job.chat_id,
                texts.JOB_INTERRUPTED.format(job_id=job.id, file_name=job.file_name),
            )
        if jobs:
            log.warning("Прервано перезапуском заданий: %s", len(jobs))
        return len(jobs)

    # --- постановка в очередь ---------------------------------------------------

    async def submit(
        self, job: PrintJob, source: Path, workspace: Path, printer_display: str
    ) -> int:
        """Ставит задание в очередь принтера. Возвращает длину очереди."""
        queue = self._queues.get(job.printer_name)
        if queue is None:
            remove_tree(workspace)
            await self._fail(
                job,
                ErrorCode.PRINTER_OFFLINE,
                f"нет воркера для принтера {job.printer_name}",
            )
            raise PrintError(ErrorCode.PRINTER_OFFLINE, "принтер не обслуживается")
        queue.put_nowait(
            QueuedJob(
                job_id=job.id,
                chat_id=job.chat_id,
                source=source,
                workspace=workspace,
                printer_display=printer_display,
            )
        )
        return queue.qsize()

    # --- выполнение -------------------------------------------------------------

    async def _worker(self, printer_name: str, queue: asyncio.Queue[QueuedJob]) -> None:
        while True:
            item = await queue.get()
            try:
                await self._process(item)
            except asyncio.CancelledError:  # pragma: no cover - остановка бота
                raise
            except Exception:
                log.exception("Непредвиденная ошибка при обработке задания %s", item.job_id)
                with suppress(Exception):
                    job = await self._repo.get(item.job_id)
                    if job is not None and job.status not in {JobStatus.DONE, JobStatus.FAILED}:
                        await self._fail(job, ErrorCode.INTERNAL, "непредвиденная ошибка")
            finally:
                remove_tree(item.workspace)
                queue.task_done()

    async def _process(self, item: QueuedJob) -> None:
        job = await self._repo.get(item.job_id)
        if job is None or job.status is not JobStatus.QUEUED:
            log.warning("Задание %s пропущено: неподходящий статус", item.job_id)
            return

        try:
            await self._repo.set_status(job.id, JobStatus.CONVERTING)
            pdf = await self._converter.to_pdf(
                item.source, item.workspace / "pdf", self._convert_timeout
            )
        except ConversionError as exc:
            await self._fail(job, exc.code, exc.detail)
            return

        pages = page_count(pdf)
        try:
            await self._repo.set_status(job.id, JobStatus.PRINTING, page_count=pages)
            await self._backend.print_pdf(
                pdf,
                PrintOptions(
                    system_name=job.printer_name,
                    duplex=job.duplex_mode,
                    copies=job.copies,
                    paper=job.paper,
                ),
                self._print_timeout,
            )
        except PrintError as exc:
            await self._fail(job, exc.code, exc.detail)
            return

        await self._repo.set_status(job.id, JobStatus.DONE)
        await self._safe_notify(
            job.chat_id,
            texts.JOB_DONE.format(job_id=job.id, printer=item.printer_display),
        )
        log.info("Задание %s напечатано на %s", job.id, job.printer_name)

    async def _fail(self, job: PrintJob, code: ErrorCode, detail: str) -> None:
        with suppress(Exception):
            await self._repo.set_status(
                job.id, JobStatus.FAILED, error_code=code, error_detail=detail or None
            )
        log.warning("Задание %s завершилось ошибкой %s: %s", job.id, code, detail)
        await self._safe_notify(
            job.chat_id,
            texts.JOB_FAILED.format(job_id=job.id, reason=texts.error_text(code)),
        )

    async def _safe_notify(self, chat_id: int, text: str) -> None:
        try:
            await self._notify(chat_id, text)
        except Exception:  # pragma: no cover - падение уведомления не ломает задание
            log.exception("Не удалось отправить уведомление в чат %s", chat_id)

    async def wait_idle(self) -> None:
        """Ожидание опустошения всех очередей — используется в тестах."""
        for queue in self._queues.values():
            await queue.join()
