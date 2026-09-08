"""Подключение к SQLite и миграции схемы (data-model.md)."""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2

_MIGRATION_1 = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id     INTEGER PRIMARY KEY,
    username        TEXT,
    display_name    TEXT    NOT NULL,
    access_status   TEXT    NOT NULL DEFAULT 'PENDING',
    role            TEXT    NOT NULL DEFAULT 'USER',
    authorized_at   TEXT,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by INTEGER
);

CREATE TABLE IF NOT EXISTS print_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    chat_id         INTEGER NOT NULL,
    file_name       TEXT    NOT NULL,
    source_format   TEXT    NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    page_count      INTEGER,
    printer_name    TEXT    NOT NULL,
    duplex_mode     TEXT    NOT NULL,
    copies          INTEGER NOT NULL,
    status          TEXT    NOT NULL,
    error_code      TEXT,
    error_detail    TEXT,
    created_at      TEXT    NOT NULL,
    started_at      TEXT,
    finished_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_user_created ON print_jobs (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status       ON print_jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_created      ON print_jobs (created_at DESC);

CREATE TABLE IF NOT EXISTS audit_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    actor_id   INTEGER,
    target_id  INTEGER,
    detail     TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events (created_at DESC);
"""

#: Выбор формата бумаги (A4/A3) появился позже — старые базы дополняются колонкой.
_MIGRATION_2 = """
ALTER TABLE print_jobs ADD COLUMN paper TEXT NOT NULL DEFAULT 'A4';
"""

MIGRATIONS: tuple[str, ...] = (_MIGRATION_1, _MIGRATION_2)


async def connect(db_path: Path) -> aiosqlite.Connection:
    """Открывает соединение, включает WAL и применяет миграции."""
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await migrate(conn)
    return conn


async def migrate(conn: aiosqlite.Connection) -> int:
    """Применяет недостающие миграции. Возвращает итоговую версию схемы."""
    async with conn.execute("PRAGMA user_version") as cursor:
        row = await cursor.fetchone()
    current = int(row[0]) if row else 0

    for version, script in enumerate(MIGRATIONS, start=1):
        if version <= current:
            continue
        await conn.executescript(script)
        await conn.execute(f"PRAGMA user_version = {version}")
        await conn.commit()
        log.info("Применена миграция схемы БД до версии %s", version)
        current = version
    return current
