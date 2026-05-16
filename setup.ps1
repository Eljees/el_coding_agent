<#
.SYNOPSIS
    Create .venv and install local-codex-lite editable.

.DESCRIPTION
    Optional proxy handling:
      - If tools\proxy.local.ps1 exists, it is dot-sourced before pip runs,
        which lets a developer route pip through a local proxy (e.g. v2rayN)
        without committing personal endpoints.  Use
        tools\proxy.local.ps1.example as a starting point.
      - Pass -WithPipIni to also copy tools\pip.ini.template into
        .venv\pip.ini (with $env:HTTPS_PROXY substituted).  After that any
        pip invocation that uses this venv picks up the proxy automatically.
#>
param(
    [switch]$WithPipIni
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Per-developer proxy override (gitignored).
$proxyLocal = Join-Path $PSScriptRoot "tools\proxy.local.ps1"
if (Test-Path $proxyLocal) {
    Write-Host "[setup] applying tools\proxy.local.ps1" -ForegroundColor DarkCyan
    . $proxyLocal
}

python -m venv .venv
.\.venv\Scripts\Activate.ps1

if ($WithPipIni) {
    $template = Join-Path $PSScriptRoot "tools\pip.ini.template"
    $target   = Join-Path $PSScriptRoot ".venv\pip.ini"
    if (-not $env:HTTPS_PROXY) {
        Write-Warning "-WithPipIni was passed but `$env:HTTPS_PROXY is empty; create tools\proxy.local.ps1 first."
    } elseif (-not (Test-Path $template)) {
        Write-Warning "Template not found: $template"
    } else {
        $content = (Get-Content $template -Raw) -replace '\$\{PROXY_URL\}', $env:HTTPS_PROXY
        Set-Content -Path $target -Value $content -Encoding UTF8
        Write-Host "[setup] wrote $target with proxy = $env:HTTPS_PROXY" -ForegroundColor DarkCyan
    }
}

python -m pip install -e ".[dev]"
