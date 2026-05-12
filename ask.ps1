param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Question
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m local_codex_lite ask $Question

