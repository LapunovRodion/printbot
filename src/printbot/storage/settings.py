"""Репозиторий изменяемых настроек (хеш кода доступа и пр.)."""

from __future__ import annotations

from datetime import UTC, datetime

import aiosqlite

ACCESS_CODE_HASH = "access_code_hash"


class SettingsRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def get(self, key: str) -> str | None:
        async with self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
        return row["value"] if row else None

    async def set(self, key: str, value: str, updated_by: int | None = None) -> None:
        await self._conn.execute(
            "INSERT INTO settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
            " updated_at = excluded.updated_at, updated_by = excluded.updated_by",
            (key, value, datetime.now(UTC).isoformat(), updated_by),
        )
        await self._conn.commit()

    async def get_access_code_hash(self) -> str | None:
        return await self.get(ACCESS_CODE_HASH)

    async def set_access_code_hash(self, value: str, updated_by: int | None = None) -> None:
        await self.set(ACCESS_CODE_HASH, value, updated_by)
