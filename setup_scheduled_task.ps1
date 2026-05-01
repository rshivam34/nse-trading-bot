# ====================================================================
# NSE Trading Bot — Windows Task Scheduler setup
#
# Run this ONCE to register the daily auto-start task.
# Execution: right-click → "Run with PowerShell"
# Or:        powershell.exe -ExecutionPolicy Bypass -File setup_scheduled_task.ps1
#
# What it does:
#   - Registers a Windows scheduled task named "NSE-IntradayBot-Paper"
#   - Runs daily at 8:55 AM IST (bot starts before 9:15 market open)
#   - Bot self-handles weekends + holidays (returns early)
#   - Runs as current user, no admin required
# ====================================================================

$TaskName = "NSE-IntradayBot-Paper"
$BatPath  = "C:\Users\rshiv\nse-trading-bot\start_bot_paper.bat"
$WorkDir  = "C:\Users\rshiv\nse-trading-bot"

# Verify the .bat exists before registering
if (-not (Test-Path $BatPath)) {
    Write-Host "ERROR: $BatPath not found. Aborting." -ForegroundColor Red
    exit 1
}

# Remove any existing task with the same name (idempotent re-run)
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task '$TaskName'..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Action: launch the .bat file in its own window
$Action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$BatPath`"" `
    -WorkingDirectory $WorkDir

# Trigger: daily at 8:55 AM (bot needs ~10 min to auth + load watchlist before 9:15)
$Trigger = New-ScheduledTaskTrigger -Daily -At "08:55"

# Settings: tolerate startup delays, don't stop if bot is running long, max 9-hour run
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 9) `
    -MultipleInstances IgnoreNew

# Principal: run as current user with their normal token (no admin needed)
$Principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Principal $Principal `
        -Description "Auto-start NSE intraday trading bot in paper mode at 8:55 AM IST. Bot self-handles weekends + NSE holidays." `
        -Force | Out-Null

    Write-Host ""
    Write-Host "  Scheduled task '$TaskName' registered successfully." -ForegroundColor Green
    Write-Host ""
    Write-Host "  Next run: tomorrow at 8:55 AM (or whenever PC is on)" -ForegroundColor Cyan
    Write-Host "  To verify: Win+R -> taskschd.msc -> Task Scheduler Library" -ForegroundColor Cyan
    Write-Host "  To remove: Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:" -NoNewline -ForegroundColor Cyan
    Write-Host '$false' -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  IMPORTANT: Your laptop must be ON and logged in at 8:55 AM" -ForegroundColor Yellow
    Write-Host "             for the task to fire. If asleep, it triggers on next wake." -ForegroundColor Yellow
}
catch {
    Write-Host "ERROR: Failed to register task: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "Try running PowerShell as Administrator and re-run this script." -ForegroundColor Yellow
    exit 1
}
