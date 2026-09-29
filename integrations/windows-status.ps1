# Shared by the manual acceptance script and its causal regression.
$script:Failures = @()
function Native($command) {
    & $command @args
    if ($LASTEXITCODE -ne 0) { throw "$command exited with status $LASTEXITCODE" }
}
function Run($what, [scriptblock]$block) {
    try { & $block; Write-Host "OK   $what" -ForegroundColor Green }
    catch {
        $script:Failures += $what
        Write-Host "FAIL $what : $_" -ForegroundColor Red
    }
}
