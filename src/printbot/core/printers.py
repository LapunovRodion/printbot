"""Реестр принтеров: конфигурация + реальная доступность (FR-012…FR-015)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from printbot.core.models import ErrorCode, PrinterConfig, PrinterView
from printbot.core.printing.base import PrinterBackend, PrinterInfo

log = logging.getLogger(__name__)

DEFAULT_CACHE_TTL = 5.0


@dataclass(slots=True)
class _CachedStatus:
    available: bool
    reason: ErrorCode | None
    at: float


class PrinterRegistry:
    """Единственный источник правды о принтерах для бота."""

    def __init__(
        self,
        configs: tuple[PrinterConfig, ...],
        backend: PrinterBackend,
        cache_ttl: float = DEFAULT_CACHE_TTL,
    ) -> None:
        self._configs = tuple(c for c in configs if c.enabled)
        self._all_configs = tuple(configs)
        self._backend = backend
        self._cache_ttl = cache_ttl
        self._status_cache: dict[str, _CachedStatus] = {}
        self._caps_cache: dict[str, PrinterInfo] = {}
        self._caps_cache_at = 0.0

    @property
    def configs(self) -> tuple[PrinterConfig, ...]:
        """Включённые принтеры из конфигурации."""
        return self._configs

    @property
    def system_names(self) -> tuple[str, ...]:
        return tuple(c.system_name for c in self._configs)

    def by_key(self, key: str) -> PrinterConfig | None:
        return next((c for c in self._configs if c.key == key), None)

    def by_system_name(self, system_name: str) -> PrinterConfig | None:
        return next((c for c in self._all_configs if c.system_name == system_name), None)

    def display_name(self, system_name: str) -> str:
        config = self.by_system_name(system_name)
        return config.display_name if config else system_name

    async def verify_at_startup(self) -> None:
        """Сверяет конфигурацию с системой; отсутствующий принтер — предупреждение, не отказ."""
        known = {info.system_name for info in await self._backend.list_printers()}
        for config in self._configs:
            if known and config.system_name not in known:
                log.warning(
                    "Принтер «%s» (system_name=%s) не найден в системе — пользователям он будет "
                    "показан недоступным",
                    config.display_name,
                    config.system_name,
                )

    async def supports_duplex(self, config: PrinterConfig) -> bool:
        """Значение из конфигурации имеет приоритет над автоопределением."""
        if config.supports_duplex is not None:
            return config.supports_duplex
        info = await self._capabilities(config.system_name)
        return info.supports_duplex if info else False

    async def supports_a3(self, config: PrinterConfig) -> bool:
        """Печатает ли принтер на A3; значение из конфигурации приоритетнее."""
        if config.supports_a3 is not None:
            return config.supports_a3
        info = await self._capabilities(config.system_name)
        return info.supports_a3 if info else False

    async def _capabilities(self, system_name: str) -> PrinterInfo | None:
        await self._refresh_caps_cache()
        return self._caps_cache.get(system_name)

    async def _refresh_caps_cache(self) -> None:
        now = time.monotonic()
        if self._caps_cache and now - self._caps_cache_at < self._cache_ttl:
            return
        try:
            infos = await self._backend.list_printers()
        except Exception:  # pragma: no cover - список не должен ронять диалог
            log.exception("Не удалось получить список принтеров")
            return
        self._caps_cache = {info.system_name: info for info in infos}
        self._caps_cache_at = now

    async def status_of(self, config: PrinterConfig) -> tuple[bool, ErrorCode | None]:
        now = time.monotonic()
        cached = self._status_cache.get(config.system_name)
        if cached is not None and now - cached.at < self._cache_ttl:
            return cached.available, cached.reason
        try:
            status = await self._backend.get_status(config.system_name)
            available, reason = status.available, status.reason
        except Exception:  # pragma: no cover - недоступность не должна ронять бота
            log.exception("Ошибка опроса принтера %s", config.system_name)
            available, reason = False, ErrorCode.PRINTER_ERROR
        self._status_cache[config.system_name] = _CachedStatus(available, reason, now)
        return available, reason

    async def view(self, config: PrinterConfig) -> PrinterView:
        available, reason = await self.status_of(config)
        return PrinterView(
            config=config,
            available=available,
            supports_duplex=await self.supports_duplex(config),
            supports_a3=await self.supports_a3(config),
            reason=reason,
        )

    async def views(self) -> list[PrinterView]:
        """Все включённые принтеры с признаком доступности (FR-015)."""
        return [await self.view(config) for config in self._configs]

    async def available_views(self) -> list[PrinterView]:
        return [view for view in await self.views() if view.available]

    async def get_view(self, key: str) -> PrinterView | None:
        config = self.by_key(key)
        return await self.view(config) if config else None

    def invalidate(self) -> None:
        self._status_cache.clear()
        self._caps_cache.clear()
        self._caps_cache_at = 0.0
