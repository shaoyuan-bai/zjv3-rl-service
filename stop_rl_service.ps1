$ErrorActionPreference = 'Stop'
$pidFile = Join-Path $PSScriptRoot 'runtime\rl\lan_launcher.pid'
if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Host 'RL service launcher PID file does not exist.'
    exit 0
}

$servicePid = [int](Get-Content -LiteralPath $pidFile -Raw)
$process = Get-Process -Id $servicePid -ErrorAction SilentlyContinue
if ($process) {
    # Kill only the tracked launcher and its children, including Uvicorn.
    & taskkill.exe /PID $servicePid /T /F | Out-Host
} else {
    Write-Host "No running process found for launcher PID $servicePid."
}
Remove-Item -LiteralPath $pidFile -Force
