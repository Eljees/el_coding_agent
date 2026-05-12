$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

