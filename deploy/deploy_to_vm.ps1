# Run this from C:\Users\rshiv\nse-trading-bot after the new Ampere A1 has been provisioned.
# It SCPs secrets to the new VM, then runs the bootstrap script via SSH.

param(
    [Parameter(Mandatory=$true)]
    [string]$VmIp
)

$ErrorActionPreference = "Stop"
$key = "C:\Users\rshiv\shivam-future-plans\trading\nse-trading-bot\secrets\oracle-vm-private.key"
$user = "ubuntu"
$target = "$user@${VmIp}"

Write-Host "==> Fixing key permissions for SSH"
icacls $key /inheritance:r /grant:r "${env:USERNAME}:F" 2>&1 | Out-Null

Write-Host "==> Bootstrapping VM (clones repo, installs deps, sets up systemd)"
ssh -i $key -o StrictHostKeyChecking=accept-new $target "bash -s" `
    < (Get-Content -Raw "C:\Users\rshiv\shivam-future-plans\trading\nse-trading-bot\deploy\vm_setup.sh") `
    -ErrorAction SilentlyContinue

Write-Host "==> Copying secrets to VM (.env + firebase-credentials.json)"
scp -i $key -o StrictHostKeyChecking=accept-new `
    "C:\Users\rshiv\shivam-future-plans\trading\nse-trading-bot\backend\.env" `
    "${target}:nse-trading-bot/backend/.env"

scp -i $key `
    "C:\Users\rshiv\shivam-future-plans\trading\nse-trading-bot\backend\firebase-credentials.json" `
    "${target}:nse-trading-bot/backend/firebase-credentials.json"

Write-Host "==> Re-running bootstrap to enable timers (now that secrets are present)"
ssh -i $key $target "bash /home/ubuntu/nse-trading-bot/deploy/vm_setup.sh"

Write-Host ""
Write-Host "============================================"
Write-Host "  Deployment complete. New VM is set up."
Write-Host "============================================"
Write-Host ""
Write-Host "Verify with:"
Write-Host "  ssh -i $key $target 'systemctl list-timers --all | grep nse'"
Write-Host ""
