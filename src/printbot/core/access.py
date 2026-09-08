"""Код доступа: хранение хеша, проверка и защита от подбора (FR-021…FR-024)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from printbot.core.models import AuditEventType, User
from printbot.storage.jobs import JobRepository
from printbot.storage.settings import SettingsRepository
from printbot.storage.users import UserRepository

log = logging.getLogger(__name__)

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # без похожих символов
_CODE_LENGTH = 8


def generate_code(length: int = _CODE_LENGTH) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def hash_code(code: str) -> str:
    """Возвращает строку вида scrypt$n$r$p$salt$hash."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        code.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return "$".join(
        [
            "scrypt",
            str(_SCRYPT_N),
            str(_SCRYPT_R),
            str(_SCRYPT_P),
            base64.b64encode(salt).decode(),
            base64.b64encode(digest).decode(),
        ]
    )


def verify_hash(code: str, stored: str) -> bool:
    try:
        algorithm, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            code.encode("utf-8"),
            salt=base64.b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(base64.b64decode(hash_b64)),
        )
    except (ValueError, TypeError):
        log.error("Хеш кода доступа повреждён — требуется /setcode")
        return False
    return hmac.compare_digest(digest, base64.b64decode(hash_b64))


@dataclass(frozen=True, slots=True)
class AccessResult:
    granted: bool
    locked_minutes: int | None = None
    attempts_left: int | None = None


class AccessService:
    def __init__(
        self,
        users: UserRepository,
        settings: SettingsRepository,
        journal: JobRepository,
        *,
        attempts_limit: int = 5,
        lockout_minutes: int = 15,
    ) -> None:
        self._users = users
        self._settings = settings
        self._journal = journal
        self._attempts_limit = attempts_limit
        self._lockout_minutes = lockout_minutes

    async def ensure_code(self) -> str | None:
        """При первом запуске генерирует код. Возвращает его открыто ровно один раз."""
        if await self._settings.get_access_code_hash():
            return None
        code = generate_code()
        await self._settings.set_access_code_hash(hash_code(code))
        log.info("Сгенерирован новый код доступа (показан в консоли один раз)")
        return code

    async def set_code(self, code: str, actor_id: int | None = None) -> None:
        await self._settings.set_access_code_hash(hash_code(code), updated_by=actor_id)
        await self._journal.add_event(AuditEventType.CODE_CHANGED, actor_id=actor_id)

    def lock_remaining_minutes(self, user: User) -> int | None:
        """Сколько минут осталось блокировки, либо None."""
        if user.locked_until is None:
            return None
        delta = user.locked_until - datetime.now(UTC)
        if delta.total_seconds() <= 0:
            return None
        return max(1, int(delta.total_seconds() // 60) + 1)

    async def submit_code(self, user: User, code: str) -> AccessResult:
        """Проверяет введённый код с учётом блокировки (FR-021, FR-022)."""
        locked = self.lock_remaining_minutes(user)
        if locked is not None:
            return AccessResult(granted=False, locked_minutes=locked)

        stored = await self._settings.get_access_code_hash()
        if stored and verify_hash(code.strip(), stored):
            await self._users.grant_access(user.telegram_id)
            await self._journal.add_event(
                AuditEventType.ACCESS_GRANTED, actor_id=user.telegram_id
            )
            return AccessResult(granted=True)

        attempts, locked_until = await self._users.register_failed_attempt(
            user.telegram_id, self._attempts_limit, self._lockout_minutes
        )
        await self._journal.add_event(AuditEventType.ACCESS_DENIED, actor_id=user.telegram_id)
        if locked_until is not None:
            await self._journal.add_event(
                AuditEventType.LOCKOUT_STARTED,
                actor_id=user.telegram_id,
                detail=f"до {locked_until.isoformat()}",
            )
            return AccessResult(granted=False, locked_minutes=self._lockout_minutes)
        return AccessResult(granted=False, attempts_left=self._attempts_limit - attempts)

    async def revoke(self, target_id: int, actor_id: int) -> bool:
        revoked = await self._users.revoke_access(target_id)
        if revoked:
            await self._journal.add_event(
                AuditEventType.ACCESS_REVOKED, actor_id=actor_id, target_id=target_id
            )
        return revoked
