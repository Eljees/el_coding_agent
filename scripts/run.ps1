param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Task,
    [switch]$DryRun,
    [switch]$Apply,
    [switch]$Exec
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$args = @("run", $Task)
if ($DryRun) { $args += "--dry-run" }
if ($Apply) { $args += "--apply" }
if ($Exec) { $args += "--exec" }

python -m local_codex_lite @args
