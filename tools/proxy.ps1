<#
.SYNOPSIS
    Configure pip / git / general HTTP proxy environment for the current
    PowerShell session.

.DESCRIPTION
    Designed for the common Windows setup where v2rayN (or another local
    proxy client) exposes an HTTP proxy on 127.0.0.1.  By default the helper
    targets v2rayN's stock HTTP listener at http://127.0.0.1:10809.

    Override the port without editing this file by either:
      - passing -HttpProxy "http://127.0.0.1:<port>"
      - creating tools\proxy.local.ps1 with custom values; setup.ps1 will
        dot-source it before this script.

.PARAMETER HttpProxy
    Full proxy URL (scheme://host:port).  Default: http://127.0.0.1:10809.

.PARAMETER NoProxy
    Comma-separated list of hosts that should bypass the proxy.
    Default includes localhost and link-local ranges so the local vLLM and
    docker stays direct.

.EXAMPLE
    . .\tools\proxy.ps1
    pip install -e ".[dev]"

.EXAMPLE
    . .\tools\proxy.ps1 -HttpProxy "http://127.0.0.1:1087"
#>
param(
    [string]$HttpProxy = "http://127.0.0.1:10809",
    [string]$NoProxy   = "localhost,127.0.0.1,::1,host.docker.internal,*.local"
)

$env:HTTP_PROXY  = $HttpProxy
$env:HTTPS_PROXY = $HttpProxy
$env:ALL_PROXY   = $HttpProxy
$env:NO_PROXY    = $NoProxy

Write-Host "[proxy] HTTP_PROXY = $HttpProxy" -ForegroundColor DarkCyan
Write-Host "[proxy] NO_PROXY   = $NoProxy"   -ForegroundColor DarkCyan
