"""Показывает системные имена принтеров и поддержку дуплекса для printers.toml.

Запуск без аргументов — таблица для человека, с `--json` — машинный вывод для setup.ps1.
Если принтеров не видно, скрипт объясняет причину, а не просто печатает пустой список.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from printbot.core.printing import windows as windows_backend  # noqa: E402
from printbot.core.printing.windows import WindowsPrinterBackend  # noqa: E402

HINTS = """
Что проверить:
  1. Открывается ли список принтеров в Windows: Параметры → Bluetooth и устройства → Принтеры.
     Если принтера нет и там — переподключите USB-кабель и установите драйвер.
  2. Печатается ли пробная страница из Windows (Свойства принтера → Пробная печать).
     Пока она не печатается, бот тоже печатать не сможет.
  3. Запущены ли скрипт и бот под той же учётной записью Windows, под которой
     подключены принтеры. Под другой учётной записью (и тем более под службой
     LOCAL SYSTEM) чужие принтеры не видны.
  4. Работает ли служба «Диспетчер печати»: в PowerShell `Get-Service Spooler`
     должна показать Running; если нет — `Start-Service Spooler`.
"""


async def collect() -> list[dict]:
    backend = WindowsPrinterBackend(sumatra_path=Path("tools/SumatraPDF.exe"))
    result: list[dict] = []
    for info in await backend.list_printers():
        status = await backend.get_status(info.system_name)
        result.append(
            {
                "system_name": info.system_name,
                "supports_duplex": info.supports_duplex,
                "supports_a3": info.supports_a3,
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
        # JSON — в stdout, диагностика — в stderr, чтобы не ломать разбор.
        print(json.dumps(printers, ensure_ascii=False))
        if not printers and (reason := windows_backend.last_error()):
            print(reason, file=sys.stderr)
        return 0 if printers else 1

    if not printers:
        print("Принтеры не найдены.")
        if reason := windows_backend.last_error():
            print(f"Причина: {reason}")
        print(HINTS)
        return 1

    print(f"{'system_name':<40} дуплекс  A3   статус")
    print("-" * 76)
    for item in printers:
        state = "доступен" if item["available"] else f"недоступен ({item['reason']})"
        duplex = "да" if item["supports_duplex"] else "нет"
        a3 = "да" if item["supports_a3"] else "нет"
        print(f"{item['system_name']:<40} {duplex:<8} {a3:<4} {state}")

    print("\nСкопируйте нужные system_name в printers.toml.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
