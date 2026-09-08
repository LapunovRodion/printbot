"""Показывает системные имена принтеров и поддержку дуплекса для printers.toml.

Запуск без аргументов — таблица для человека, с `--json` — машинный вывод для setup.ps1.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from printbot.core.printing.windows import WindowsPrinterBackend  # noqa: E402


async def collect() -> list[dict]:
    backend = WindowsPrinterBackend(sumatra_path=Path("tools/SumatraPDF.exe"))
    result: list[dict] = []
    for info in await backend.list_printers():
        status = await backend.get_status(info.system_name)
        result.append(
            {
                "system_name": info.system_name,
                "supports_duplex": info.supports_duplex,
                "available": status.available,
                "reason": status.reason.value if status.reason else None,
            }
        )
    return result


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="машинный вывод для скриптов")
    args = parser.parse_args()

    printers = await collect()

    if args.json:
        print(json.dumps(printers, ensure_ascii=False))
        return 0 if printers else 1

    if not printers:
        print("Принтеры не найдены. Запустите скрипт на Windows под учётной записью,")
        print("под которой подключены принтеры (см. research.md R5).")
        return 1

    print(f"{'system_name':<40} дуплекс  статус")
    print("-" * 70)
    for item in printers:
        state = "доступен" if item["available"] else f"недоступен ({item['reason']})"
        duplex = "да" if item["supports_duplex"] else "нет"
        print(f"{item['system_name']:<40} {duplex:<8} {state}")

    print("\nСкопируйте нужные system_name в printers.toml.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
