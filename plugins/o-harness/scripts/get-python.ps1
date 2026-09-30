# Fetches the official Python for OH on Windows, when no Python 3.12+ is installed. The version and each
# file's SHA-256 are pinned here; nothing is installed system-wide. Each version gets its own folder under
# <OH data>\python and the file "current" names the one to use, so a newer pin replaces it on the next setup.
# -Refresh (used by setup) updates only a Python OH fetched before.
param([switch]$Refresh)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$version = '3.14.7'
$hashes = @{
    'amd64' = 'd297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15'
    'arm64' = 'f6773983c8959d4281e48c4540cb0bdd23e42391e4e951ce17e7ceb52658f21c'
}
# Codex starts OH's tool server with few variables and no PROCESSOR_ARCHITECTURE: read the system's own then.
# Qualify the built-in command so a cold session does not scan every installed module to find it.
$machine = if ($env:PROCESSOR_ARCHITECTURE) { $env:PROCESSOR_ARCHITECTURE } else {
    (Microsoft.PowerShell.Management\Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment' -Name PROCESSOR_ARCHITECTURE -ErrorAction SilentlyContinue).PROCESSOR_ARCHITECTURE }
$arch = if ($machine -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') { 'arm64' } else { 'amd64' }
$data = if ($env:OH_DATA_HOME) { $env:OH_DATA_HOME } else { Join-Path $env:USERPROFILE '.local\share\o-harness' }
$root = Join-Path $data 'python'
$current = Join-Path $root 'current'
$target = Join-Path $root $version
# The bootstrap runs before Python's setup lock exists. An exclusive file handle also
# serializes different hosts/sessions and is released by Windows if a process dies.
New-Item -ItemType Directory -Force -Path $root | Out-Null
$lock = $null
$deadline = [DateTime]::UtcNow.AddMinutes(5)
while ($null -eq $lock) {
    try { $lock = [IO.File]::Open((Join-Path $root '.install.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
    catch [IO.IOException] {
        if ([DateTime]::UtcNow -ge $deadline) { throw 'Another OH Python setup is still running. Wait for it to finish, then run setup again.' }
        Start-Sleep -Milliseconds 100
    }
}
try {
$named = if (Test-Path $current) { (Get-Content -Raw $current).Trim() } else { '' }
if ($named -eq $version -and (Test-Path (Join-Path $target 'python.exe'))) { return }
if ($Refresh -and -not $named) { return }
# The download happens at the first setup, before OH has any settings, so an environment variable turns it off.
if ($env:OH_PYTHON_DOWNLOAD -eq '0') {
    throw 'OH_PYTHON_DOWNLOAD is 0, so OH does not download Python. Install Python 3.12 or newer yourself (python.org, or: winget install Python.Python.3.14), then run setup again.'
}
$url = "https://www.python.org/ftp/python/$version/python-$version-embed-$arch.zip"
[Console]::Error.WriteLine("OH is downloading Python $version from python.org (the official Windows embeddable package, about 12 MB, SHA-256 checked) into $target. No admin rights or PATH changes; delete $root to remove it.")
$unique = [guid]::NewGuid()
$zip = Join-Path $root ".download-$unique.zip"
$staging = Join-Path $root ".stage-$unique"
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zip
    $actual = (Get-FileHash -Algorithm SHA256 -Path $zip).Hash.ToLower()
    if ($actual -ne $hashes[$arch]) { throw "The download from $url doesn't match its pinned SHA-256 (got $actual); nothing was installed." }
    Expand-Archive -Path $zip -DestinationPath $staging
    # The lock covers the winner recheck through marker publication. Never remove an
    # interpreter another completed setup published, including after a marker-write failure.
    if (-not (Test-Path (Join-Path $target 'python.exe'))) {
        if (Test-Path $target) { Remove-Item -Recurse -Force -Path $target }
        [IO.Directory]::Move($staging, $target)
    }
    if (-not (Test-Path (Join-Path $target 'python.exe'))) { throw "Python $version is not complete in $target; run setup again." }
    $next = Join-Path $root ".current-$unique"
    Set-Content -NoNewline -Encoding ascii -Path $next -Value $version
    if (Test-Path $current) { [IO.File]::Replace($next, $current, [NullString]::Value) }
    else { [IO.File]::Move($next, $current) }
    # Keep older complete versions: an installed dashboard task or an in-flight batch
    # may still name that interpreter even when no process currently has it open.
} finally {
    Remove-Item -Force -ErrorAction SilentlyContinue -Path $zip
    if (Test-Path $staging) { Remove-Item -Recurse -Force -Path $staging -ErrorAction SilentlyContinue }
}
} finally {
    $lock.Dispose()
}
