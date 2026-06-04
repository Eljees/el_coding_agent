param(
    [string[]]$RepoUrl,
    [string]$RepoFile,
    [string]$GitUser = $env:GITLAB_USER,
    [string]$GitToken = $env:GITLAB_TOKEN,
    [string]$Image = $env:TRUFFLEHOG_IMAGE,
    [string]$CacheRoot = $env:TRUFFLEHOG_CACHE_ROOT,
    [string]$OutRoot = $env:TRUFFLEHOG_OUT_ROOT,
    [switch]$KeepClones
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$args = @("tools\trufflehog_scan_gitlab.py")
foreach ($url in $RepoUrl) {
    $args += @("--repo-url", $url)
}
if ($RepoFile) { $args += @("--repo-file", $RepoFile) }
if ($GitUser) { $args += @("--git-user", $GitUser) }
if ($GitToken) { $args += @("--git-token", $GitToken) }
if ($Image) { $args += @("--image", $Image) }
if ($CacheRoot) { $args += @("--cache-root", $CacheRoot) }
if ($OutRoot) { $args += @("--out-root", $OutRoot) }
if ($KeepClones) { $args += "--keep-clones" }

python @args
