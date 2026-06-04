param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Question
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
python -m local_codex_lite ask $Question
