# Fetches the official Python for OH on Windows, only when no Python 3.11+ is installed.
# The version and each file's SHA-256 are pinned here; nothing is installed system-wide.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$version = '3.14.7'
$hashes = @{
    'amd64' = 'd297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15'
    'arm64' = 'f6773983c8959d4281e48c4540cb0bdd23e42391e4e951ce17e7ceb52658f21c'
}
$arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') { 'arm64' } else { 'amd64' }
# The download happens at the first setup, before OH has any settings, so an environment variable turns it off.
if ($env:OH_PYTHON_DOWNLOAD -eq '0') {
    throw 'OH_PYTHON_DOWNLOAD is 0, so OH does not download Python. Install Python 3.11 or newer yourself (python.org, or: winget install Python.Python.3.14), then run setup again.'
}
$data = if ($env:OH_DATA_HOME) { $env:OH_DATA_HOME } else { Join-Path $env:USERPROFILE '.local\share\o-harness' }
$target = Join-Path $data 'python'
if (Test-Path (Join-Path $target 'python.exe')) { return }
$url = "https://www.python.org/ftp/python/$version/python-$version-embed-$arch.zip"
[Console]::Error.WriteLine("OH is downloading Python $version from python.org (the official Windows embeddable package, about 12 MB, SHA-256 checked) into $target. No admin rights or PATH changes; delete that folder to remove it.")
New-Item -ItemType Directory -Force -Path $data | Out-Null
$zip = Join-Path $data ".python-$version-$arch.zip"
$staging = Join-Path $data (".python-" + [guid]::NewGuid())
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zip
    $actual = (Get-FileHash -Algorithm SHA256 -Path $zip).Hash.ToLower()
    if ($actual -ne $hashes[$arch]) { throw "The download from $url doesn't match its pinned SHA-256 (got $actual); nothing was installed." }
    Expand-Archive -Path $zip -DestinationPath $staging
    try { Move-Item -Path $staging -Destination $target } catch { if (-not (Test-Path (Join-Path $target 'python.exe'))) { throw } }
} finally {
    Remove-Item -Force -ErrorAction SilentlyContinue -Path $zip
    if (Test-Path $staging) { Remove-Item -Recurse -Force -Path $staging }
}
