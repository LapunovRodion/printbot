"""Репозиторий пользователей и доступа (data-model.md § users)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import aiosqlite

from printbot.core.models import AccessStatus, Role, User


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _row_to_user(row: aiosqlite.Row) -> User:
    return User(
        telegram_id=row["telegram_id"],
        display_name=row["display_name"],
        username=row["username"],
        access_status=AccessStatus(row["access_status"]),
        role=Role(row["role"]),
        authorized_at=_parse_dt(row["authorized_at"]),
        failed_attempts=row["failed_attempts"],
        locked_until=_parse_dt(row["locked_until"]),
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
    )


class UserRepository:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def get(self, telegram_id: int) -> User | None:
        async with self._conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return _row_to_user(row) if row else None

    async def get_or_create(
        self, telegram_id: int, display_name: str, username: str | None = None
    ) -> User:
        """Возвращает пользователя, создавая запись при первом обращении."""
        existing = await self.get(telegram_id)
        if existing is not None:
            if existing.display_name != display_name or existing.username != username:
                await self._conn.execute(
                    "UPDATE users SET display_name = ?, username = ?, updated_at = ? "
                    "WHERE telegram_id = ?",
                    (display_name, username, _now(), telegram_id),
                )
                await self._conn.commit()
                existing.display_name = display_name
                existing.username = username
            return existing

        now = _now()
        await self._conn.execute(
            "INSERT INTO users (telegram_id, username, display_name, access_status, role, "
            "failed_attempts, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
            (telegram_id, username, display_name, AccessStatus.PENDING, Role.USER, now, now),
        )
        await self._conn.commit()
        created = await self.get(telegram_id)
        assert created is not None
        return created

    async def set_role(self, telegram_id: int, role: Role) -> None:
        await self._conn.execute(
            "UPDATE users SET role = ?, updated_at = ? WHERE telegram_id = ?",
            (role, _now(), telegram_id),
        )
        await self._conn.commit()

    async def grant_access(self, telegram_id: int) -> None:
        """Успешная авторизация: доступ выдан, счётчики сброшены."""
        now = _now()
        await self._conn.execute(
            "UPDATE users SET access_status = ?, authorized_at = ?, failed_attempts = 0, "
            "locked_until = NULL, updated_at = ? WHERE telegram_id = ?",
            (AccessStatus.ALLOWED, now, now, telegram_id),
        )
        await self._conn.commit()

    async def revoke_access(self, telegram_id: int) -> bool:
        cursor = await self._conn.execute(
            "UPDATE users SET access_status = ?, updated_at = ? WHERE telegram_id = ?",
            (AccessStatus.REVOKED, _now(), telegram_id),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def register_failed_attempt(
        self, telegram_id: int, attempts_limit: int, lockout_minutes: int
    ) -> tuple[int, datetime | None]:
        """Учитывает неверный ввод кода. Возвращает (счётчик, время окончания блокировки)."""
        user = await self.get(telegram_id)
        if user is None:
            return 0, None
        attempts = user.failed_attempts + 1
        locked_until: datetime | None = None
        if attempts >= attempts_limit:
            locked_until = datetime.now(UTC) + timedelta(minutes=lockout_minutes)
            attempts = 0
        await self._conn.execute(
            "UPDATE users SET failed_attempts = ?, locked_until = ?, updated_at = ? "
            "WHERE telegram_id = ?",
            (
                attempts,
                locked_until.isoformat() if locked_until else None,
                _now(),
                telegram_id,
            ),
        )
        await self._conn.commit()
        return attempts, locked_until

    async def list_allowed(self) -> list[User]:
        async with self._conn.execute(
            "SELECT * FROM users WHERE access_status = ? ORDER BY authorized_at DESC",
            (AccessStatus.ALLOWED,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_user(row) for row in rows]
