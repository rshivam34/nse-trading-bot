# ====================================================================
# NSE Trading Bot — LIVE MODE Task Scheduler setup
#
# ⚠️  CREATES SCHEDULED TASK FOR REAL-MONEY TRADING  ⚠️
#
# Run this ONCE to register the daily live-trade task.
# It also REMOVES the prior NSE-IntradayBot-Paper task.
#
# Execution: right-click → "Run with PowerShell"
# Or:        powershell.exe -ExecutionPolicy Bypass -File setup_scheduled_task_live.ps1
# ====================================================================

$LiveTaskName  = "NSE-IntradayBot-Live"
$PaperTaskName = "NSE-IntradayBot-Paper"
$BatPath       = "C:\Users\rshiv\shivam-future-plans\trading\nse-trading-bot\start_bot_live.bat"
$WorkDir       = "C:\Users\rshiv\nse-trading-bot"

# Step 1: Remove prior PAPER task if exists
$paperExists = Get-ScheduledTask -TaskName $PaperTaskName -ErrorAction SilentlyContinue
if ($paperExists) {
    Write-Host "Removing prior paper-mode task '$PaperTaskName'..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $PaperTaskName -Confirm:$false
    Write-Host "  Removed." -ForegroundColor Green
}

# Step 2: Verify .bat exists
if (-not (Test-Path $BatPath)) {
    Write-Host "ERROR: $BatPath not found. Aborting." -ForegroundColor Red
    exit 1
}

# Step 3: Remove prior live task if exists (idempotent)
$liveExists = Get-ScheduledTask -TaskName $LiveTaskName -ErrorAction SilentlyContinue
if ($liveExists) {
    Write-Host "Removing existing live task to recreate..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $LiveTaskName -Confirm:$false
}

# Step 4: Build new task
$Action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$BatPath`"" `
    -WorkingDirectory $WorkDir

$Trigger = New-ScheduledTaskTrigger -Daily -At "08:55"

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 9) `
    -MultipleInstances IgnoreNew

$Principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

try {
    Register-ScheduledTask `
        -TaskName $LiveTaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Principal $Principal `
        -Description "REAL MONEY F&O trading bot. Capital Rs.50K. Daily 8:55 AM IST. Auto-skips weekends + NSE holidays." `
        -Force | Out-Null

    Write-Host ""
    Write-Host "  LIVE task '$LiveTaskName' registered." -ForegroundColor Green
    Write-Host ""
    Write-Host "  ⚠️  THIS PLACES REAL F&O ORDERS WITH REAL MONEY  ⚠️" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Next run:    $(Get-Date -Date '08:55:00' -Format 'dd-MM-yyyy HH:mm')" -ForegroundColor Cyan
    Write-Host "  Capital:     Rs.50,000 (F&O-only mode)" -ForegroundColor Cyan
    Write-Host "  Max daily loss: 3% of capital = Rs.1,500" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  EMERGENCY STOP:" -ForegroundColor Yellow
    Write-Host "    - Dashboard kill switch (preferred)" -ForegroundColor Yellow
    Write-Host "    - Disable-ScheduledTask -TaskName '$LiveTaskName'" -ForegroundColor Yellow
    Write-Host "    - Unregister-ScheduledTask -TaskName '$LiveTaskName' -Confirm:" -NoNewline -ForegroundColor Yellow
    Write-Host '$false' -ForegroundColor Yellow
}
catch {
    Write-Host "ERROR: Failed to register task: $_" -ForegroundColor Red
    exit 1
}
