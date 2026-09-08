<#
.SYNOPSIS
    Первичная настройка PrintBot на компьютере с Windows.

.DESCRIPTION
    Делает всё, что нужно для запуска: проверяет Python и LibreOffice, скачивает
    SumatraPDF, создаёт виртуальное окружение, спрашивает токен бота и принтеры,
    записывает .env и printers.toml, при желании ставит автозапуск.

    Скрипт можно запускать повторно: он не трогает то, что уже настроено.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File setup.ps1

.PARAMETER SkipTests
    Не запускать набор тестов после установки.

.PARAMETER Reconfigure
    Переспросить настройки, даже если .env и printers.toml уже есть.
#>
[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$Reconfigure
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false) } catch {}

$Root = $PSScriptRoot
$Venv = Join-Path $Root '.venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$VenvPythonw = Join-Path $Venv 'Scripts\pythonw.exe'
$EnvFile = Join-Path $Root '.env'
$PrintersFile = Join-Path $Root 'printers.toml'
$SumatraExe = Join-Path $Root 'tools\SumatraPDF.exe'
$SumatraUrl = 'https://www.sumatrapdfreader.org/dl/rel/3.5.2/SumatraPDF-3.5.2-64.zip'

$script:Step = 0
$script:Warnings = @()

function Write-Step([string]$Text) {
    $script:Step++
    Write-Host ''
    Write-Host "[$script:Step] $Text" -ForegroundColor Cyan
}

function Write-Ok([string]$Text)   { Write-Host "    OK  $Text" -ForegroundColor Green }
function Write-Info([string]$Text) { Write-Host "        $Text" -ForegroundColor Gray }

function Write-Warn([string]$Text) {
    Write-Host "    !   $Text" -ForegroundColor Yellow
    $script:Warnings += $Text
}

function Stop-Setup([string]$Text) {
    Write-Host ''
    Write-Host "ОШИБКА: $Text" -ForegroundColor Red
    exit 1
}

function Confirm-Yes([string]$Question, [bool]$Default = $true) {
    $hint = if ($Default) { '[Д/н]' } else { '[д/Н]' }
    $answer = Read-Host "    $Question $hint"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    return $answer -match '^(д|y)'
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    # Без BOM: иначе pydantic-settings и tomllib спотыкаются о первый ключ.
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

Write-Host ''
Write-Host '=== Установка PrintBot ===' -ForegroundColor White
Write-Info "Каталог проекта: $Root"

# --- 1. Python -----------------------------------------------------------------

Write-Step 'Проверяю Python'

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Stop-Setup @'
Python не найден. Установите Python 3.11 или новее с https://www.python.org/downloads/
и обязательно отметьте галочку "Add python.exe to PATH", затем запустите скрипт заново.
Либо: winget install Python.Python.3.12
'@
}

$versionText = (& python --version 2>&1) -replace '[^\d.]', ''
$version = [version]($versionText -split '\.' | Select-Object -First 3) -join '.'
if ($version -lt [version]'3.11') {
    Stop-Setup "Нужен Python 3.11 или новее, найден $version. Обновите Python и повторите."
}
Write-Ok "Python $version"

# --- 2. Виртуальное окружение и зависимости ------------------------------------

Write-Step 'Готовлю виртуальное окружение'

if (-not (Test-Path $VenvPython)) {
    Write-Info 'Создаю .venv ...'
    & python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Stop-Setup 'Не удалось создать виртуальное окружение' }
}
Write-Ok 'Виртуальное окружение готово'

Write-Info 'Устанавливаю зависимости (может занять пару минут) ...'
& $VenvPython -m pip install --quiet --upgrade pip
& $VenvPython -m pip install --quiet -e ".[dev]"
if ($LASTEXITCODE -ne 0) { Stop-Setup 'Не удалось установить зависимости (проверьте интернет)' }
Write-Ok 'Зависимости установлены'

# --- 3. LibreOffice ------------------------------------------------------------

Write-Step 'Проверяю LibreOffice (конвертация DOCX в PDF)'

$sofficeCandidates = @(
    'C:\Program Files\LibreOffice\program\soffice.exe',
    'C:\Program Files (x86)\LibreOffice\program\soffice.exe'
)
$soffice = $sofficeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $soffice) {
    Write-Warn 'LibreOffice не найден — без него не будут печататься файлы DOCX (PDF печатать можно).'
    if ((Get-Command winget -ErrorAction SilentlyContinue) -and
        (Confirm-Yes 'Установить LibreOffice через winget сейчас?')) {
        & winget install --id TheDocumentFoundation.LibreOffice --accept-source-agreements --accept-package-agreements
        $soffice = $sofficeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    }
    if (-not $soffice) {
        Write-Info 'Скачайте вручную: https://www.libreoffice.org/download/ и запустите скрипт снова.'
    }
}
if ($soffice) { Write-Ok $soffice }

# --- 4. SumatraPDF -------------------------------------------------------------

Write-Step 'Проверяю SumatraPDF (печать PDF с дуплексом и копиями)'

if (Test-Path $SumatraExe) {
    Write-Ok $SumatraExe
} else {
    Write-Info 'SumatraPDF не найден в tools\SumatraPDF.exe'
    if (Confirm-Yes "Скачать portable-версию с sumatrapdfreader.org?") {
        try {
            $zip = Join-Path $env:TEMP 'sumatrapdf.zip'
            $unpack = Join-Path $env:TEMP 'sumatrapdf'
            Write-Info 'Скачиваю ...'
            Invoke-WebRequest -Uri $SumatraUrl -OutFile $zip -UseBasicParsing
            if (Test-Path $unpack) { Remove-Item $unpack -Recurse -Force }
            Expand-Archive -Path $zip -DestinationPath $unpack -Force
            $exe = Get-ChildItem $unpack -Filter '*.exe' -Recurse | Select-Object -First 1
            if (-not $exe) { throw 'в архиве нет .exe' }
            New-Item -ItemType Directory -Path (Split-Path $SumatraExe) -Force | Out-Null
            Copy-Item $exe.FullName $SumatraExe -Force
            Remove-Item $zip, $unpack -Recurse -Force -ErrorAction SilentlyContinue
            Write-Ok $SumatraExe
        } catch {
            Write-Warn "Не удалось скачать SumatraPDF: $_"
            Write-Info 'Скачайте portable-версию вручную с https://www.sumatrapdfreader.org/download-free-pdf-viewer'
            Write-Info "и положите файл как $SumatraExe"
        }
    } else {
        Write-Warn 'Без SumatraPDF печать работать не будет.'
    }
}

# --- 5. Токен бота и администраторы --------------------------------------------

Write-Step 'Настраиваю доступ к Telegram'

if ((Test-Path $EnvFile) -and -not $Reconfigure) {
    Write-Ok '.env уже есть — оставляю как есть (перенастроить: setup.ps1 -Reconfigure)'
} else {
    Write-Info 'Токен бота: в Telegram напишите @BotFather, команда /newbot'
    Write-Info 'Свой числовой ID: напишите @userinfobot'
    Write-Host ''

    $token = ''
    while ($token -notmatch '^\d{6,12}:[A-Za-z0-9_-]{30,}$') {
        $token = (Read-Host '    Токен бота').Trim()
        if ($token -notmatch '^\d{6,12}:[A-Za-z0-9_-]{30,}$') {
            Write-Host '    Не похоже на токен (нужен вид 123456789:AAH...). Попробуйте ещё раз.' -ForegroundColor Yellow
        }
    }

    $admins = ''
    while ($admins -notmatch '^\d+(\s*,\s*\d+)*$') {
        $admins = (Read-Host '    Telegram ID администраторов (через запятую)').Trim()
        if ($admins -notmatch '^\d+(\s*,\s*\d+)*$') {
            Write-Host '    Нужны только числа через запятую.' -ForegroundColor Yellow
        }
    }

    $envText = Get-Content (Join-Path $Root '.env.example') -Raw -Encoding UTF8
    $envText = $envText -replace '(?m)^BOT_TOKEN=.*$', "BOT_TOKEN=$token"
    $envText = $envText -replace '(?m)^ADMIN_IDS=.*$', "ADMIN_IDS=$($admins -replace '\s','')"
    if ($soffice) {
        $envText = $envText -replace '(?m)^SOFFICE_PATH=.*$', "SOFFICE_PATH=$soffice"
    }
    Write-Utf8NoBom $EnvFile $envText
    Write-Ok 'Файл .env записан'
}

# --- 6. Принтеры ---------------------------------------------------------------

Write-Step 'Настраиваю принтеры'

if ((Test-Path $PrintersFile) -and -not $Reconfigure) {
    Write-Ok 'printers.toml уже есть — оставляю как есть (перенастроить: setup.ps1 -Reconfigure)'
} else {
    Write-Info 'Опрашиваю систему ...'
    $raw = & $VenvPython (Join-Path $Root 'tools\list_printers.py') --json 2>$null
    $printers = @()
    if ($raw) { try { $printers = @($raw | ConvertFrom-Json) } catch { $printers = @() } }

    if ($printers.Count -eq 0) {
        Write-Warn 'Принтеры не найдены. Подключите их под этой учётной записью и запустите setup.ps1 -Reconfigure'
    } else {
        Write-Host ''
        for ($i = 0; $i -lt $printers.Count; $i++) {
            $p = $printers[$i]
            $duplex = if ($p.supports_duplex) { 'дуплекс есть' } else { 'дуплекса нет' }
            $state = if ($p.available) { 'доступен' } else { "недоступен ($($p.reason))" }
            Write-Host ("    {0}) {1}  —  {2}, {3}" -f ($i + 1), $p.system_name, $duplex, $state)
        }
        Write-Host ''
        $choice = (Read-Host '    Номера принтеров для бота через запятую (Enter — все)').Trim()

        if ([string]::IsNullOrWhiteSpace($choice)) {
            $selected = $printers
        } else {
            $indexes = $choice -split ',' | ForEach-Object { [int]($_.Trim()) - 1 }
            $selected = $indexes | Where-Object { $_ -ge 0 -and $_ -lt $printers.Count } |
                        ForEach-Object { $printers[$_] }
        }

        if (-not $selected -or @($selected).Count -eq 0) {
            Write-Warn 'Ничего не выбрано — printers.toml не создан'
        } else {
            $lines = @(
                '# Создано setup.ps1. system_name менять нельзя — он должен совпадать с именем в Windows.',
                ''
            )
            $n = 0
            foreach ($p in @($selected)) {
                $n++
                $display = (Read-Host "    Как назвать «$($p.system_name)» для сотрудников? (Enter — так же)").Trim()
                if ([string]::IsNullOrWhiteSpace($display)) { $display = $p.system_name }
                $lines += '[[printer]]'
                $lines += "key = `"p$n`""
                $lines += "display_name = `"$display`""
                $lines += "system_name = `"$($p.system_name)`""
                $lines += "model = `"$($p.system_name)`""
                $lines += 'enabled = true'
                $lines += ''
            }
            Write-Utf8NoBom $PrintersFile ($lines -join "`r`n")
            Write-Ok "Файл printers.toml записан, принтеров: $n"
        }
    }
}

# --- 7. Тесты ------------------------------------------------------------------

if (-not $SkipTests) {
    Write-Step 'Проверяю сборку тестами (принтер не нужен)'
    & $VenvPython -m pytest -q
    if ($LASTEXITCODE -ne 0) {
        Write-Warn 'Тесты не прошли — покажите вывод разработчику, но настройку можно продолжать'
    } else {
        Write-Ok 'Все тесты прошли'
    }
}

# --- 8. Автозапуск -------------------------------------------------------------

Write-Step 'Автозапуск при входе в систему'

$taskExists = $null -ne (Get-ScheduledTask -TaskName 'PrintBot' -ErrorAction SilentlyContinue)
if ($taskExists) {
    Write-Ok 'Задача PrintBot в планировщике уже есть'
} elseif (Confirm-Yes 'Настроить автозапуск бота при входе в систему?') {
    try {
        $action = New-ScheduledTaskAction -Execute $VenvPythonw -Argument '-m printbot' -WorkingDirectory $Root
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
        Register-ScheduledTask -TaskName 'PrintBot' -Action $action -Trigger $trigger -Settings $settings `
            -Description 'Telegram-бот печати документов' -Force | Out-Null
        Write-Ok 'Задача PrintBot создана (запуск при входе, перезапуск при сбое)'
        Write-Info 'Важно: бот работает в вашей сессии — под LOCAL SYSTEM сетевые принтеры не видны.'
    } catch {
        Write-Warn "Не удалось создать задачу: $_"
        Write-Info 'Создайте вручную командой из README.md (раздел «Автозапуск»).'
    }
}

# --- Итог ----------------------------------------------------------------------

Write-Host ''
Write-Host '=== Готово ===' -ForegroundColor White

if ($script:Warnings.Count -gt 0) {
    Write-Host ''
    Write-Host 'Осталось доделать:' -ForegroundColor Yellow
    foreach ($w in $script:Warnings) { Write-Host "  - $w" -ForegroundColor Yellow }
}

Write-Host ''
Write-Host 'Запустить бота:' -ForegroundColor White
Write-Host "    .venv\Scripts\python -m printbot" -ForegroundColor Green
Write-Host ''
Write-Info 'При первом запуске в консоли один раз появится КОД ДОСТУПА — запишите его.'
Write-Info 'Дальше код меняется командой /setcode в самом боте.'
Write-Info 'Проверьте двустороннюю печать на каждом принтере (quickstart.md, сценарий 6.2).'
Write-Host ''
