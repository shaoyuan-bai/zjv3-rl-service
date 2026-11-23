$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$runtime = Join-Path $root 'runtime\rl'
$pidFile = Join-Path $runtime 'lan_launcher.pid'
$output = Join-Path $runtime 'lan_service.out.log'
$stderrLog = Join-Path $runtime 'lan_service.err.log'

New-Item -ItemType Directory -Force -Path $runtime | Out-Null
if (Test-Path -LiteralPath $pidFile) {
    $oldPid = [int](Get-Content -LiteralPath $pidFile -Raw)
    $old = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
    if ($old) {
        Write-Host "RL service is already running (launcher PID $oldPid)."
        exit 0
    }
}

$child = Start-Process -FilePath 'powershell.exe' `
    -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $root 'start_rl_service.ps1') `
    -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput $output -RedirectStandardError $stderrLog -PassThru
$child.Id | Set-Content -LiteralPath $pidFile -NoNewline
Write-Host "RL service launcher started (PID $($child.Id))."
Write-Host 'Swagger: http://192.168.2.194:8000/docs'

