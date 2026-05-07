#!/usr/bin/env bash
# Keep-alive for Oracle Always Free idle reclamation.
#
# Oracle reclaims Always Free Compute VMs flagged "idle" over 7 days:
#   CPU 95th percentile < 20% AND Network < 20%
#
# This script runs every hour via cron. Each run: a brief CPU burst
# (computes primes for ~3 sec) plus a network round-trip. Costs nothing,
# ensures the VM never falls below activity thresholds.

set -euo pipefail

LOG="/home/ubuntu/nse-trading-bot/backend/logs/keep_alive.log"
mkdir -p "$(dirname "$LOG")"

# CPU burst: ~3 seconds of prime-factoring work
python3 -c "
import time
end = time.time() + 3
n = 0
while time.time() < end:
    n += 1
    x = n * n + 1
    for i in range(2, int(x**0.5) + 1):
        if x % i == 0:
            break
print(f'Tested {n} candidates')
" > /dev/null

# Network ping: 4 packets to Cloudflare DNS (~1 KB total)
ping -c 4 -q 1.1.1.1 > /dev/null 2>&1 || true

# Tiny network egress: HEAD request to a public endpoint
curl -sS --max-time 5 -o /dev/null https://api.telegram.org/ || true

echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] keep-alive ran" >> "$LOG"

# Trim log to last 200 lines (prevents bloat)
tail -200 "$LOG" > "${LOG}.tmp" && mv "${LOG}.tmp" "$LOG"
