"""Доменные модели и перечисления (см. specs/001-telegram-print-bot/data-model.md)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AccessStatus(StrEnum):
    PENDING = "PENDING"
    ALLOWED = "ALLOWED"
    REVOKED = "REVOKED"


class Role(StrEnum):
    USER = "USER"
    ADMIN = "ADMIN"


class DocumentFormat(StrEnum):
    DOCX = "DOCX"
    PDF = "PDF"


class PaperSize(StrEnum):
    A4 = "A4"
    A3 = "A3"


class DuplexMode(StrEnum):
    SIMPLEX = "SIMPLEX"
    DUPLEX_LONG = "DUPLEX_LONG"


class JobStatus(StrEnum):
    DRAFT = "DRAFT"
    QUEUED = "QUEUED"
    CONVERTING = "CONVERTING"
    PRINTING = "PRINTING"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


FINAL_STATUSES = frozenset({JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED})

#: Допустимые переходы статусов задания (data-model.md § Переходы статусов).
ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.DRAFT: frozenset({JobStatus.QUEUED, JobStatus.CANCELLED}),
    JobStatus.QUEUED: frozenset({JobStatus.CONVERTING, JobStatus.FAILED, JobStatus.CANCELLED}),
    JobStatus.CONVERTING: frozenset({JobStatus.PRINTING, JobStatus.FAILED}),
    JobStatus.PRINTING: frozenset({JobStatus.DONE, JobStatus.FAILED}),
    JobStatus.DONE: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


def can_transition(current: JobStatus, new: JobStatus) -> bool:
    """Разрешён ли переход статуса задания."""
    return new in ALLOWED_TRANSITIONS[current]


class ErrorCode(StrEnum):
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    CORRUPT_FILE = "CORRUPT_FILE"
    ENCRYPTED_FILE = "ENCRYPTED_FILE"
    CONVERSION_FAILED = "CONVERSION_FAILED"
    PRINTER_OFFLINE = "PRINTER_OFFLINE"
    PAPER_OUT = "PAPER_OUT"
    PAPER_JAM = "PAPER_JAM"
    NO_TONER = "NO_TONER"
    PRINTER_ERROR = "PRINTER_ERROR"
    TIMEOUT = "TIMEOUT"
    INTERRUPTED = "INTERRUPTED"
    INTERNAL = "INTERNAL"


class AuditEventType(StrEnum):
    ACCESS_GRANTED = "ACCESS_GRANTED"
    ACCESS_DENIED = "ACCESS_DENIED"
    ACCESS_REVOKED = "ACCESS_REVOKED"
    CODE_CHANGED = "CODE_CHANGED"
    LOCKOUT_STARTED = "LOCKOUT_STARTED"
    PRINTER_ADDED = "PRINTER_ADDED"
    PRINTER_REMOVED = "PRINTER_REMOVED"
    JOURNAL_PURGED = "JOURNAL_PURGED"


@dataclass(slots=True)
class User:
    telegram_id: int
    display_name: str
    username: str | None = None
    access_status: AccessStatus = AccessStatus.PENDING
    role: Role = Role.USER
    authorized_at: datetime | None = None
    failed_attempts: int = 0
    locked_until: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN

    @property
    def is_allowed(self) -> bool:
        return self.access_status is AccessStatus.ALLOWED


@dataclass(slots=True)
class PrintJob:
    id: int
    user_id: int
    chat_id: int
    file_name: str
    source_format: DocumentFormat
    file_size_bytes: int
    printer_name: str
    duplex_mode: DuplexMode
    copies: int
    status: JobStatus
    paper: PaperSize = PaperSize.A4
    page_count: int | None = None
    error_code: ErrorCode | None = None
    error_detail: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PrinterConfig:
    """Принтер из printers.toml (contracts/configuration.md)."""

    key: str
    display_name: str
    system_name: str
    model: str = ""
    enabled: bool = True
    supports_duplex: bool | None = None  # None = определять автоматически
    supports_a3: bool | None = None  # None = определять автоматически


@dataclass(frozen=True, slots=True)
class PrinterView:
    """Принтер в том виде, в каком он показывается пользователю."""

    config: PrinterConfig
    available: bool
    supports_duplex: bool
    supports_a3: bool = False
    reason: ErrorCode | None = None

    @property
    def key(self) -> str:
        return self.config.key

    @property
    def display_name(self) -> str:
        return self.config.display_name

    @property
    def system_name(self) -> str:
        return self.config.system_name


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: int
    event_type: AuditEventType
    actor_id: int | None
    target_id: int | None
    detail: str | None
    created_at: datetime
