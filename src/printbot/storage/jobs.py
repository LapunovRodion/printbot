"""Репозиторий заданий печати и журнала событий (data-model.md)."""

from __future__ import annotations

from datetime import UTC, datetime

import aiosqlite

from printbot.core.models import (
    AuditEvent,
    AuditEventType,
    DocumentFormat,
    DuplexMode,
    ErrorCode,
    JobStatus,
    PaperSize,
    PrintJob,
    can_transition,
)

ACTIVE_STATUSES: tuple[JobStatus, ...] = (
    JobStatus.QUEUED,
    JobStatus.CONVERTING,
    JobStatus.PRINTING,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _row_to_job(row: aiosqlite.Row) -> PrintJob:
    return PrintJob(
        id=row["id"],
        user_id=row["user_id"],
        chat_id=row["chat_id"],
        file_name=row["file_name"],
        source_format=DocumentFormat(row["source_format"]),
        file_size_bytes=row["file_size_bytes"],
        page_count=row["page_count"],
        printer_name=row["printer_name"],
        duplex_mode=DuplexMode(row["duplex_mode"]),
        copies=row["copies"],
        paper=PaperSize(row["paper"]),
        status=JobStatus(row["status"]),
        error_code=ErrorCode(row["error_code"]) if row["error_code"] else None,
        error_detail=row["error_detail"],
        created_at=_parse_dt(row["created_at"]),
        started_at=_parse_dt(row["started_at"]),
        finished_at=_parse_dt(row["finished_at"]),
    )


class InvalidStatusTransition(RuntimeError):
    """Попытка недопустимого перехода статуса задания."""


class JobRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def create(
        self,
        *,
        user_id: int,
        chat_id: int,
        file_name: str,
        source_format: DocumentFormat,
        file_size_bytes: int,
        printer_name: str,
        duplex_mode: DuplexMode,
        copies: int,
        paper: PaperSize = PaperSize.A4,
        page_count: int | None = None,
    ) -> PrintJob:
        cursor = await self._conn.execute(
            "INSERT INTO print_jobs (user_id, chat_id, file_name, source_format, file_size_bytes,"
            " page_count, printer_name, duplex_mode, copies, paper, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                chat_id,
                file_name,
                source_format,
                file_size_bytes,
                page_count,
                printer_name,
                duplex_mode,
                copies,
                paper,
                JobStatus.QUEUED,
                _now(),
            ),
        )
        await self._conn.commit()
        job = await self.get(cursor.lastrowid)
        assert job is not None
        return job

    async def get(self, job_id: int) -> PrintJob | None:
        async with self._conn.execute("SELECT * FROM print_jobs WHERE id = ?", (job_id,)) as cur:
            row = await cur.fetchone()
        return _row_to_job(row) if row else None

    async def set_status(
        self,
        job_id: int,
        status: JobStatus,
        *,
        error_code: ErrorCode | None = None,
        error_detail: str | None = None,
        page_count: int | None = None,
    ) -> PrintJob:
        job = await self.get(job_id)
        if job is None:
            raise InvalidStatusTransition(f"Задание {job_id} не найдено")
        if not can_transition(job.status, status):
            raise InvalidStatusTransition(
                f"Недопустимый переход задания {job_id}: {job.status} → {status}"
            )

        now = _now()
        started_at = now if job.started_at is None and status is JobStatus.CONVERTING else None
        is_final = status in {JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED}
        finished_at = now if is_final else None

        await self._conn.execute(
            "UPDATE print_jobs SET status = ?,"
            " error_code = COALESCE(?, error_code),"
            " error_detail = COALESCE(?, error_detail),"
            " page_count = COALESCE(?, page_count),"
            " started_at = COALESCE(started_at, ?),"
            " finished_at = COALESCE(?, finished_at)"
            " WHERE id = ?",
            (
                status,
                error_code,
                error_detail,
                page_count,
                started_at,
                finished_at,
                job_id,
            ),
        )
        await self._conn.commit()
        updated = await self.get(job_id)
        assert updated is not None
        return updated

    async def list_for_user(self, user_id: int, limit: int = 5) -> list[PrintJob]:
        async with self._conn.execute(
            "SELECT * FROM print_jobs WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (user_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_job(row) for row in rows]

    async def list_recent(self, limit: int = 20) -> list[PrintJob]:
        async with self._conn.execute(
            "SELECT * FROM print_jobs ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_job(row) for row in rows]

    async def list_unfinished(self) -> list[PrintJob]:
        placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
        async with self._conn.execute(
            f"SELECT * FROM print_jobs WHERE status IN ({placeholders}) ORDER BY id",
            tuple(ACTIVE_STATUSES),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_job(row) for row in rows]

    async def queue_length(self, printer_name: str) -> int:
        async with self._conn.execute(
            "SELECT COUNT(*) FROM print_jobs WHERE printer_name = ? AND status IN (?, ?, ?)",
            (printer_name, *ACTIVE_STATUSES),
        ) as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def purge(self, before: datetime | None = None) -> int:
        """Явное удаление записей журнала администратором (FR-027)."""
        if before is None:
            cursor = await self._conn.execute("DELETE FROM print_jobs")
        else:
            cursor = await self._conn.execute(
                "DELETE FROM print_jobs WHERE created_at < ?", (before.isoformat(),)
            )
        await self._conn.commit()
        return cursor.rowcount

    async def add_event(
        self,
        event_type: AuditEventType,
        *,
        actor_id: int | None = None,
        target_id: int | None = None,
        detail: str | None = None,
    ) -> None:
        await self._conn.execute(
            "INSERT INTO audit_events (event_type, actor_id, target_id, detail, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (event_type, actor_id, target_id, detail, _now()),
        )
        await self._conn.commit()

    async def list_events(self, limit: int = 20) -> list[AuditEvent]:
        async with self._conn.execute(
            "SELECT * FROM audit_events ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
        return [
            AuditEvent(
                id=row["id"],
                event_type=AuditEventType(row["event_type"]),
                actor_id=row["actor_id"],
                target_id=row["target_id"],
                detail=row["detail"],
                created_at=_parse_dt(row["created_at"]),  # type: ignore[arg-type]
            )
            for row in rows
        ]
