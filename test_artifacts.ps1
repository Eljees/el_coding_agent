<#
.SYNOPSIS
    Ручное тестирование распаковки артефактов на реальных файлах.

.DESCRIPTION
    Два сценария:
      1. Распаковка В ТУ ЖЕ директорию, где лежат артефакты (по умолчанию).
      2. Распаковка В ЯВНО УКАЗАННУЮ директорию (второй аргумент).

.PARAMETER SourceDir
    Директория с архивами для теста.
    Default: D:\!ya_drive_sync\YandexDisk\rostel\to_analyze\__old

.PARAMETER DestDir
    Директория для сценария 2 (явный destination).
    Default: D:\!ya_drive_sync\YandexDisk\rostel\to_analyze\_test_unpack_output

.PARAMETER Scenario
    Какой сценарий запустить: 1, 2, или "all" (оба).
    Default: all

.EXAMPLE
    # Оба сценария с дефолтными путями
    .\test_artifacts.ps1

.EXAMPLE
    # Только сценарий 2, свои пути
    .\test_artifacts.ps1 -Scenario 2 `
        -SourceDir "D:\!ya_drive_sync\YandexDisk\rostel\to_analyze\_to_verify_logic_CYBERSEC-11531" `
        -DestDir   "D:\!ya_drive_sync\YandexDisk\rostel\to_analyze\_to_verify_logic_CYBERSEC-1153"
#>
param(
    [string] $SourceDir = "D:\!ya_drive_sync\YandexDisk\rostel\to_analyze\__old",
    [string] $DestDir   = "D:\!ya_drive_sync\YandexDisk\rostel\to_analyze\_test_unpack_output",
    [string] $Scenario  = "all"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── helpers ────────────────────────────────────────────────────────────────
function Write-Header([string]$text) {
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor Cyan
}

function Write-Ok([string]$text)   { Write-Host "  [OK]  $text" -ForegroundColor Green }
function Write-Fail([string]$text) { Write-Host "  [FAIL] $text" -ForegroundColor Red  }
function Write-Info([string]$text) { Write-Host "  ...   $text" -ForegroundColor Gray  }

function Get-CLI {
    # Ищем исполняемый файл агента
    $candidates = @(
        "local-codex-lite",
        "$PSScriptRoot\.venv\Scripts\local-codex-lite.exe",
        "$PSScriptRoot\.venv\Scripts\local-codex-lite"
    )
    foreach ($c in $candidates) {
        if (Get-Command $c -ErrorAction SilentlyContinue) { return $c }
    }
    throw "local-codex-lite not found. Run: pip install -e '.[dev]' in the project directory."
}

function Assert-ArchivesFound([string]$dir) {
    $archives = Get-ChildItem -Path $dir -Recurse -Include "*.zip","*.tar","*.tar.gz","*.tgz","*.rar","*.7z","*.gz" -ErrorAction SilentlyContinue
    if (-not $archives) {
        throw "No supported archives found in: $dir"
    }
    Write-Info "Found $($archives.Count) archive(s) in $dir"
    $archives | ForEach-Object { Write-Info "  - $($_.Name)" }
}

function Show-ExtractedTree([string]$root, [int]$limit = 20) {
    $files = Get-ChildItem -Path $root -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First $limit
    if ($files) {
        Write-Info "Extracted files:"
        $files | ForEach-Object { Write-Info "  $($_.FullName.Replace($root, '.'))" }
    }
}

# ── prerequisite checks ────────────────────────────────────────────────────
$cli = Get-CLI
Write-Info "Using CLI: $cli"

if (-not (Test-Path $SourceDir)) {
    throw "Source directory not found: $SourceDir"
}

# ── scenario 1: extract to SAME directory ─────────────────────────────────
function Run-Scenario1 {
    Write-Header "Scenario 1: Unpack INTO the source directory (default)"
    Write-Info "Source:  $SourceDir"
    Write-Info "Extract: to same directory (no --extract-to)"

    Assert-ArchivesFound $SourceDir

    $evidenceDir = Join-Path $env:TEMP "lcl_test_evidence_s1_$(Get-Random)"

    # Сохраняем список файлов ДО распаковки
    $before = Get-ChildItem -Path $SourceDir -Recurse -File | Select-Object -ExpandProperty FullName | Sort-Object

    $result = & $cli evidence artifacts inspect $SourceDir --extract 2>&1
    $exitCode = $LASTEXITCODE

    Write-Info "Exit code: $exitCode"
    Write-Info "Output:"
    $result | ForEach-Object { Write-Info "  $_" }

    if ($exitCode -eq 0) {
        Write-Ok "CLI exited 0"
    } else {
        Write-Fail "CLI exited $exitCode"
        return
    }

    # Проверяем, что появились новые файлы ВНУТРИ SourceDir
    $after = Get-ChildItem -Path $SourceDir -Recurse -File | Select-Object -ExpandProperty FullName | Sort-Object
    $newFiles = $after | Where-Object { $_ -notin $before }

    if ($newFiles) {
        Write-Ok "New files extracted inside source dir ($($newFiles.Count) file(s)):"
        $newFiles | Select-Object -First 10 | ForEach-Object { Write-Ok "  $_" }
    } else {
        Write-Fail "No new files found inside source directory after extraction."
    }
}

# ── scenario 2: extract to EXPLICIT destination ────────────────────────────
function Run-Scenario2 {
    Write-Header "Scenario 2: Unpack into explicit destination directory"
    Write-Info "Source: $SourceDir"
    Write-Info "Dest:   $DestDir"

    Assert-ArchivesFound $SourceDir

    # Создаём чистую директорию назначения
    if (Test-Path $DestDir) {
        Write-Info "Cleaning existing destination: $DestDir"
        Remove-Item -Recurse -Force $DestDir
    }

    $result = & $cli evidence artifacts inspect $SourceDir $DestDir --extract 2>&1
    $exitCode = $LASTEXITCODE

    Write-Info "Exit code: $exitCode"
    Write-Info "Output:"
    $result | ForEach-Object { Write-Info "  $_" }

    if ($exitCode -eq 0) {
        Write-Ok "CLI exited 0"
    } else {
        Write-Fail "CLI exited $exitCode"
        return
    }

    # Проверяем, что файлы появились В DestDir, а не в SourceDir
    if (Test-Path $DestDir) {
        $extractedFiles = Get-ChildItem -Path $DestDir -Recurse -File
        if ($extractedFiles) {
            Write-Ok "Files extracted to destination ($($extractedFiles.Count) file(s)):"
            Show-ExtractedTree $DestDir
        } else {
            Write-Fail "Destination directory is empty."
        }
    } else {
        Write-Fail "Destination directory was not created: $DestDir"
        return
    }

    # Убеждаемся, что в SourceDir НЕТ новых директорий с распакованным контентом
    $sourceDirs = Get-ChildItem -Path $SourceDir -Directory -ErrorAction SilentlyContinue
    if ($sourceDirs) {
        Write-Fail "Unexpected new directories appeared in source: $($sourceDirs.Name -join ', ')"
    } else {
        Write-Ok "Source directory is unchanged (no leaked extraction)"
    }
}

# ── scenario 3: single file as source ─────────────────────────────────────
function Run-Scenario3 {
    Write-Header "Scenario 3: Single archive file — extract next to it"

    $archives = Get-ChildItem -Path $SourceDir -Recurse -Include "*.zip","*.tar.gz","*.tgz" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $archives) {
        Write-Info "No zip/tar.gz found in $SourceDir, skipping."
        return
    }

    $archive = $archives.FullName
    $parentDir = Split-Path $archive -Parent
    Write-Info "Archive: $archive"
    Write-Info "Expected extraction root: $parentDir"

    $result = & $cli evidence artifacts inspect $archive --extract 2>&1
    $exitCode = $LASTEXITCODE
    Write-Info "Exit code: $exitCode"

    if ($exitCode -eq 0) {
        Write-Ok "CLI exited 0"
        $stemDir = Join-Path $parentDir ([System.IO.Path]::GetFileNameWithoutExtension($archive).TrimEnd(".tar"))
        if (Test-Path $stemDir) {
            Write-Ok "Extraction directory created next to archive: $stemDir"
        } else {
            Write-Info "Note: extraction directory not found at expected path $stemDir (may vary by archive name)"
        }
    } else {
        Write-Fail "CLI exited $exitCode"
    }
}

# ── run ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "local-codex-lite artifact unpack tests" -ForegroundColor Yellow
Write-Host "Source: $SourceDir" -ForegroundColor Yellow
Write-Host "Dest:   $DestDir" -ForegroundColor Yellow

switch ($Scenario) {
    "1"   { Run-Scenario1 }
    "2"   { Run-Scenario2 }
    "3"   { Run-Scenario3 }
    "all" { Run-Scenario1; Run-Scenario2; Run-Scenario3 }
    default { throw "Unknown scenario: $Scenario. Use 1, 2, 3, or all." }
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
