$ErrorActionPreference = "Stop"

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Task,
    [switch]$DryRun,
    [switch]$Apply,
    [switch]$Exec
)

Set-Location $PSScriptRoot

$args = @("run", $Task)
if ($DryRun) { $args += "--dry-run" }
if ($Apply) { $args += "--apply" }
if ($Exec) { $args += "--exec" }

python -m local_codex_lite @args
