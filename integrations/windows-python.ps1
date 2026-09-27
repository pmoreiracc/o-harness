# Python selection for the real-Windows acceptance check. Dot-source to define the resolver.
function Resolve-CheckPython($Data, $Downloader) {
    $candidates = @(
        @{ Command = 'python3'; Arguments = @() },
        @{ Command = 'python'; Arguments = @() },
        @{ Command = 'py'; Arguments = @('-3') }
    )
    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate.Command -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) {
            $arguments = $candidate.Arguments
            $resolved = & $command.Source @arguments -I -c 'import sys; sys.version_info >= (3, 11) and print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $resolved -and (Test-Path -LiteralPath $resolved -PathType Leaf)) { return $resolved }
        }
    }
    Write-Host 'No Python 3.11+: testing the download OH does during setup.'
    & $Downloader
    $root = Join-Path $Data 'python'
    $version = (Get-Content -Raw -LiteralPath (Join-Path $root 'current')).Trim()
    if ($version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') { throw 'OH Python current marker is invalid; run setup again.' }
    $python = Join-Path (Join-Path $root $version) 'python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "OH Python is missing at $python; run setup again." }
    return $python
}
