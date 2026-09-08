"""Показывает системные имена принтеров и поддержку дуплекса для printers.toml."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from printbot.core.printing.windows import WindowsPrinterBackend  # noqa: E402


async def main() -> int:
    backend = WindowsPrinterBackend(sumatra_path=Path("tools/SumatraPDF.exe"))
    printers = await backend.list_printers()
    if not printers:
        print("Принтеры не найдены. Запустите скрипт на Windows под учётной записью,")
        print("под которой подключены принтеры (см. research.md R5).")
        return 1

    print(f"{'system_name':<40} дуплекс  статус")
    print("-" * 70)
    for info in printers:
        status = await backend.get_status(info.system_name)
        state = "доступен" if status.available else f"недоступен ({status.reason})"
        print(f"{info.system_name:<40} {'да' if info.supports_duplex else 'нет':<8} {state}")

    print("\nСкопируйте нужные system_name в printers.toml.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
