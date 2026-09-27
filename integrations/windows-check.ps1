# One real OH check on Windows. Run it from a clone of this repository:
#   powershell -NoProfile -ExecutionPolicy Bypass -File integrations\windows-check.ps1
# It builds OH from this clone, installs it into Claude Code and Codex, sets up a sample project,
# then tells you the few steps to type in each host. Everything it prints goes to oh-windows-check.log.
# After those steps, run it again with -After to add the results to the same log.
param([switch]$After)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$data = if ($env:OH_DATA_HOME) { $env:OH_DATA_HOME } else { Join-Path $env:USERPROFILE '.local\share\o-harness' }
$work = Join-Path $env:USERPROFILE 'oh-windows-check'
$log = Join-Path $work 'oh-windows-check.log'
New-Item -ItemType Directory -Force -Path $work | Out-Null
function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
. (Join-Path $PSScriptRoot 'windows-status.ps1')

if ($After) {
    Start-Transcript -Path $log -Append | Out-Null
    $project = Join-Path $work 'sample'; $oh = Join-Path $work 'dist\claude\o-harness\scripts\oh.cmd'
    Step 'Results'
    Run 'Git results' { Native git -C $project log --format='%h %s%n%b' -6 }
    Run 'OH results' { Native $oh --root $project status }
    Get-ScheduledTask -TaskName 'OH dashboard' -ErrorAction SilentlyContinue | Format-List TaskName, State
    Get-ChildItem (Join-Path $data 'logs') -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "-- $($_.Name)"; Get-Content $_.FullName -Tail 20 }
    Stop-Transcript | Out-Null
    if ($script:Failures.Count) { exit 1 }; exit 0
}
Start-Transcript -Path $log -Force | Out-Null

Step 'Versions'
Write-Host ([Environment]::OSVersion.VersionString) $env:PROCESSOR_ARCHITECTURE
foreach ($tool in 'git', 'claude', 'codex', 'python3', 'python', 'py', 'bash') {
    $found = Get-Command $tool -ErrorAction SilentlyContinue
    Write-Host ('{0,-8} {1}' -f $tool, $(if ($found) { $found.Source } else { 'not found' }))
}
foreach ($tool in 'git', 'claude', 'codex') { Run "$tool version" { Native $tool --version } }

Step 'Python for OH'
. (Join-Path $PSScriptRoot 'windows-python.ps1')
$python = Resolve-CheckPython $data (Join-Path $repo 'plugins\o-harness\scripts\get-python.ps1')
Write-Host "Using: $python"
$pyArgs = @('-I', '-X', 'utf8')

Step 'Build and install OH from this clone'
$dist = Join-Path $work 'dist'
if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
Run 'build Claude plugin' { Native $python @pyArgs (Join-Path $repo 'oh') build-plugin (Join-Path $dist 'claude\o-harness') --host claude | Out-Null }
Run 'build Codex plugin' { Native $python @pyArgs (Join-Path $repo 'oh') build-plugin (Join-Path $dist 'codex\o-harness') --host codex | Out-Null }
New-Item -ItemType Directory -Force -Path (Join-Path $dist '.claude-plugin'), (Join-Path $dist '.agents\plugins') | Out-Null
Set-Content -Encoding ascii (Join-Path $dist '.claude-plugin\marketplace.json') '{"name":"o-harness","owner":{"name":"OH contributors"},"plugins":[{"name":"o-harness","source":"./claude/o-harness","description":"OH"}]}'
Set-Content -Encoding ascii (Join-Path $dist '.agents\plugins\marketplace.json') '{"name":"o-harness","interface":{"displayName":"OH"},"plugins":[{"name":"o-harness","source":{"source":"local","path":"./codex/o-harness"},"policy":{"installation":"AVAILABLE","authentication":"ON_INSTALL"},"category":"Productivity"}]}'
Run 'install into Claude Code' { Native claude plugin marketplace add $dist; Native claude plugin install o-harness@o-harness }
Run 'install into Codex' { Native codex plugin marketplace add $dist; Native codex plugin add o-harness@o-harness }
$oh = Join-Path $dist 'claude\o-harness\scripts\oh.cmd'
Run 'setup through oh.cmd' { Native $oh setup --development }

Step 'Sample project'
$project = Join-Path $work 'sample'
if (Test-Path $project) { Remove-Item -Recurse -Force $project }
New-Item -ItemType Directory -Path $project | Out-Null
Run 'initialize sample Git repository' {
    Native git -C $project init -q -b main
    Set-Content (Join-Path $project 'README.md') "# Sample`n"
    Native git -C $project add .
    Native git -C $project -c user.name=OH -c user.email=oh@example.invalid commit -qm start
}
Run 'register the project' { Native $oh --root $project init }
$checks = Join-Path $work 'checks.json'
Set-Content -Encoding utf8 -Path $checks -Value '[{"name":"whitespace","command":["git","diff","--check","HEAD"]}]'
Run 'save checks from a file' { Native $oh --root $project config set checks "@$checks" }
Run 'read settings back' { $settings = Native $oh --root $project config; if (-not ($settings | Select-String 'whitespace')) { throw 'Saved whitespace check is missing' }; $settings | Out-Host }
Run 'plans in the repository' { Native $oh --root $project config set plans.location repo }
Run 'dashboard at logon (Task Scheduler)' { Native $oh service-install; Start-Sleep 5; (Invoke-WebRequest -UseBasicParsing http://localhost:4318).StatusCode }

Step 'Now type these yourself (the check cannot type for you)'
Write-Host @"
1. In a new terminal: cd $project ; claude
   a. /oh-propose Add a one-line greeting to README.md
   b. /oh-deliver   -> agree to one task: add the greeting line. Type the trigger it shows.
   c. While a task is running, type /oh-pause. Check status, then type /oh-resume.
   d. At the checkpoint, type stop. Start another one-task run and let it finish.
2. Same folder in Codex: codex
   a. `$oh-deliver  -> one task: add a second greeting line. Type the trigger it shows.
   b. Repeat pause, resume, stop, and a fresh one-task run in Codex.
3. Open http://localhost:4318 and check both hosts' runs and delivered commits are listed.
4. Test an update: run "$oh" setup --development and "$oh" service-install again.
   Restart both hosts; confirm OH still works and the dashboard opens.
5. Test uninstall: run "$oh" service-uninstall. Confirm the scheduled task is absent
   and the dashboard port is closed. Remove the plugin from each host; confirm it no longer loads.
   Preserve OH data and report any failure, including the command and error.
6. Run: powershell -NoProfile -ExecutionPolicy Bypass -File "$PSCommandPath" -After
   and paste $log back into the chat.
"@
Stop-Transcript | Out-Null

if ($script:Failures.Count) { Write-Host ('Acceptance setup failed: ' + ($script:Failures -join ', ')); exit 1 }
