# Phase 1 — Data Model: Telegram-бот печати документов

**Дата**: 2026-09-08 | **Источник**: [spec.md](./spec.md) § Key Entities | **Хранилище**: SQLite (`data/printbot.db`, WAL)

Все временные метки — UTC, в формате ISO-8601 (`TEXT`). Схема применяется миграциями при старте (`storage/db.py`), версия хранится в `PRAGMA user_version`.

---

## Перечисления (домен)

| Тип | Значения | Где используется |
|---|---|---|
| `AccessStatus` | `PENDING` (не авторизован), `ALLOWED`, `REVOKED` | `users.access_status` |
| `Role` | `USER`, `ADMIN` | `users.role` |
| `DocumentFormat` | `DOCX`, `PDF` | `print_jobs.source_format` |
| `DuplexMode` | `SIMPLEX` (односторонняя), `DUPLEX_LONG` (двусторонняя, длинная кромка) | `print_jobs.duplex_mode` |
| `PaperSize` | `A4`, `A3` | `print_jobs.paper` |
| `JobStatus` | `DRAFT`, `QUEUED`, `CONVERTING`, `PRINTING`, `DONE`, `FAILED`, `CANCELLED` | `print_jobs.status` |
| `ErrorCode` | `UNSUPPORTED_FORMAT`, `FILE_TOO_LARGE`, `CORRUPT_FILE`, `ENCRYPTED_FILE`, `CONVERSION_FAILED`, `PRINTER_OFFLINE`, `PAPER_OUT`, `PAPER_JAM`, `NO_TONER`, `PRINTER_ERROR`, `TIMEOUT`, `INTERRUPTED`, `INTERNAL` | `print_jobs.error_code`, `PrintError` |
| `AuditEventType` | `ACCESS_GRANTED`, `ACCESS_DENIED`, `ACCESS_REVOKED`, `CODE_CHANGED`, `LOCKOUT_STARTED`, `PRINTER_ADDED`, `PRINTER_REMOVED`, `JOURNAL_PURGED` | `audit_events.event_type` |

Соответствие требованиям: `DuplexMode` — FR-006; `JobStatus` — FR-016/FR-017/FR-019; `ErrorCode` — FR-017 (понятная причина) и FR-005; `AccessStatus`/`Role` — FR-020…FR-025.

---

## Таблица `users`

Пользователь бота (spec § Key Entities → «Пользователь»).

| Поле | Тип | Ограничения | Назначение |
|---|---|---|---|
| `telegram_id` | INTEGER | PK | Идентификатор пользователя в Telegram |
| `username` | TEXT | NULL | `@username` на момент последнего обращения |
| `display_name` | TEXT | NOT NULL | Отображаемое имя для журнала и админ-списков |
| `access_status` | TEXT | NOT NULL, из `AccessStatus`, DEFAULT `PENDING` | FR-020, FR-024 |
| `role` | TEXT | NOT NULL, из `Role`, DEFAULT `USER` | FR-025 |
| `authorized_at` | TEXT | NULL | Момент успешного ввода кода (FR-021) |
| `failed_attempts` | INTEGER | NOT NULL, DEFAULT 0, ≥ 0 | Счётчик неверных вводов подряд (FR-022) |
| `locked_until` | TEXT | NULL | До какого времени ввод кода заблокирован (FR-022) |
| `created_at` | TEXT | NOT NULL | Первое обращение к боту |
| `updated_at` | TEXT | NOT NULL | Последнее изменение записи |

**Правила валидации**
- Печать разрешена ⟺ `access_status = ALLOWED`.
- Успешный ввод кода: `access_status → ALLOWED`, `failed_attempts = 0`, `locked_until = NULL`, `authorized_at = now`.
- Неверный ввод: `failed_attempts += 1`; при `failed_attempts >= 5` → `locked_until = now + 15 минут`, `failed_attempts = 0`, событие `LOCKOUT_STARTED`.
- Ввод при `locked_until > now` не проверяется вовсе — отказ с указанием оставшегося времени.
- Отзыв доступа администратором: `access_status → REVOKED`; повторная авторизация возможна действующим кодом.
- Роль `ADMIN` присваивается только из конфигурации при старте (список `ADMIN_IDS`), через бота не выдаётся.

**Переходы состояний доступа**

```text
PENDING --(верный код)--> ALLOWED --(отзыв админом)--> REVOKED --(верный код)--> ALLOWED
   \__(неверный код ×5)__> заблокирован на 15 мин (access_status не меняется)
```

---

## Таблица `settings`

Пары ключ-значение для изменяемых настроек. Единственная запись, которая должна существовать всегда, — код доступа.

| Поле | Тип | Ограничения |
|---|---|---|
| `key` | TEXT | PK |
| `value` | TEXT | NOT NULL |
| `updated_at` | TEXT | NOT NULL |
| `updated_by` | INTEGER | NULL, FK → `users.telegram_id` |

**Известные ключи**

| Ключ | Значение | Требование |
|---|---|---|
| `access_code_hash` | `scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>` | FR-021, FR-023 |
| `schema_version` | номер применённой миграции (дублирует `PRAGMA user_version`) | — |

Код доступа в открытом виде не хранится нигде (см. research.md R7). Смена кода: перезапись `access_code_hash` + событие `CODE_CHANGED`; ранее авторизованные пользователи доступ сохраняют (FR-023).

---

## Таблица `print_jobs`

Задание печати — центральная сущность (spec § Key Entities → «Задание печати», «Документ», «Запись журнала»). Одна и та же строка служит и рабочим состоянием, и записью бессрочного журнала (FR-026, FR-027).

| Поле | Тип | Ограничения | Назначение |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | Номер задания, показывается пользователю (FR-017) |
| `user_id` | INTEGER | NOT NULL, FK → `users.telegram_id` | Автор |
| `chat_id` | INTEGER | NOT NULL | Куда слать уведомления о статусе |
| `file_name` | TEXT | NOT NULL | Исходное имя файла |
| `source_format` | TEXT | NOT NULL, из `DocumentFormat` | FR-001, FR-002 |
| `file_size_bytes` | INTEGER | NOT NULL, > 0, ≤ лимита | FR-004 |
| `page_count` | INTEGER | NULL, ≥ 1 | Известно после конвертации (research.md R9) |
| `printer_name` | TEXT | NOT NULL | Системное имя целевого принтера |
| `duplex_mode` | TEXT | NOT NULL, из `DuplexMode` | FR-006 |
| `copies` | INTEGER | NOT NULL, 1 ≤ copies ≤ 50 | FR-007 |
| `paper` | TEXT | NOT NULL, из `PaperSize`, DEFAULT `A4` | FR-006a (миграция 2) |
| `status` | TEXT | NOT NULL, из `JobStatus` | FR-016, FR-019 |
| `error_code` | TEXT | NULL, из `ErrorCode` | Заполнено ⟺ `status = FAILED` |
| `error_detail` | TEXT | NULL | Техническая деталь для журнала, пользователю не показывается дословно |
| `created_at` | TEXT | NOT NULL | Момент подтверждения задания |
| `started_at` | TEXT | NULL | Начало обработки воркером |
| `finished_at` | TEXT | NULL | Заполнено ⟺ статус финальный |

**Индексы**: `(user_id, created_at DESC)` — история пользователя; `(status)` — выборка незавершённых при старте; `(created_at DESC)` — журнал администратора (SC-011).

**Правила валидации**
- `copies` вне диапазона 1…50 отвергается на этапе диалога, в БД не попадает (FR-007).
- `duplex_mode = DUPLEX_LONG` допустим только если у принтера `supports_duplex = true` (FR-008); `paper = A3` — только если `supports_a3 = true` (FR-006a).
- Финальные статусы: `DONE`, `FAILED`, `CANCELLED` — после них строка неизменяема (запись журнала).
- Строки не удаляются автоматически: хранение бессрочное, очистка — только явным действием администратора с записью события `JOURNAL_PURGED` (FR-027).
- Содержимое документа в БД не сохраняется — только метаданные (assumption из спеки).

**Переходы статусов**

```text
DRAFT ──подтверждение──> QUEUED ──воркер взял──> CONVERTING ──> PRINTING ──> DONE
  │                         │                        │             │
  │                         │                        └──ошибка─────┴──> FAILED (+error_code)
  └──отмена/таймаут──> CANCELLED
QUEUED | CONVERTING | PRINTING ──рестарт процесса──> FAILED (error_code = INTERRUPTED)
```

- `DRAFT` живёт только в FSM-состоянии диалога; в БД строка создаётся при подтверждении (FR-009). Отмена до подтверждения (FR-010) и таймаут диалога (FR-011) строку не создают, но фиксируются в логе приложения.
- Переход `PRINTING → DONE` означает «задание принято спулером принтера без ошибки» — формулировка сообщения пользователю это отражает (см. research.md R4).

---

## Таблица `audit_events`

События доступа и администрирования — то, что не является заданием, но нужно для разбора инцидентов (FR-022, FR-023, FR-027).

| Поле | Тип | Ограничения |
|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT |
| `event_type` | TEXT | NOT NULL, из `AuditEventType` |
| `actor_id` | INTEGER | NULL, FK → `users.telegram_id` — кто совершил |
| `target_id` | INTEGER | NULL, FK → `users.telegram_id` — над кем |
| `detail` | TEXT | NULL — например, имя добавленного принтера |
| `created_at` | TEXT | NOT NULL |

Секреты (код доступа, токен бота) в `detail` не пишутся никогда.

---

## Принтер (конфигурация, не таблица)

Список принтеров задаётся файлом конфигурации и сверяется с системой при старте и перед показом списка пользователю — в БД не дублируется, чтобы не расходиться с реальностью (FR-012…FR-015). Схема — в [contracts/configuration.md](./contracts/configuration.md).

| Поле | Источник | Назначение |
|---|---|---|
| `key` | конфиг | Короткий идентификатор для `callback_data` |
| `display_name` | конфиг | Понятное имя в списке («Принтер в бухгалтерии») |
| `system_name` | конфиг | Точное имя принтера в Windows |
| `model` | конфиг | Справочно (Pantum 5100 / GM1033ADN) |
| `enabled` | конфиг | Администратор может выключить принтер, не удаляя |
| `supports_duplex` | автоопределение (`DeviceCapabilities`), переопределяется конфигом | FR-008 |
| `supports_a3` | автоопределение (`DC_PAPERS`), переопределяется конфигом | FR-006a |
| `available` | опрос статуса при показе списка | FR-015 |
| `status_reason` | опрос статуса | Причина недоступности для сообщения пользователю |

---

## Соответствие сущностей спеки

| Сущность спеки | Реализация |
|---|---|
| Пользователь | таблица `users` |
| Код доступа | `settings.access_code_hash` + `audit_events(CODE_CHANGED)` |
| Принтер | конфигурация + опрос системы (не хранится в БД) |
| Задание печати | таблица `print_jobs` |
| Документ | временный каталог задания `%LOCALAPPDATA%\printbot\jobs\<job_id>\`, метаданные — в `print_jobs`; удаляется после завершения (FR-028) |
| Запись журнала | финальные строки `print_jobs` + `audit_events` |
