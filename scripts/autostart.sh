#!/bin/sh
# Start the ledger web dashboard if it isn't already running.
#
# Idempotent and safe to run repeatedly: used from a cron @reboot line (start
# on boot) and a periodic watchdog line (self-heal after a crash). systemd-user
# is unavailable under this WSL setup, so cron is the persistence mechanism.
#
# Install (once):
#   (crontab -l 2>/dev/null; \
#    echo "@reboot $PWD/scripts/autostart.sh"; \
#    echo "*/10 * * * * $PWD/scripts/autostart.sh") | crontab -
# (run from the repo root so $PWD is the repo)

PATH=/usr/local/bin:/usr/bin:/bin
LEDGER="$(cd "$(dirname "$0")/.." && pwd)/.venv/bin/ledger"
PORT=7777
LOG=/tmp/ledger-web.log

# Already reachable? Nothing to do. A port/HTTP liveness check is the right
# guard here (not a pgrep on the command line, which false-matches any process
# whose args merely contain "ledger serve") and it self-heals a hung process.
if curl -fs -o /dev/null --max-time 3 "http://localhost:${PORT}/" 2>/dev/null; then
    exit 0
fi

nohup "$LEDGER" serve --port "$PORT" >>"$LOG" 2>&1 &
