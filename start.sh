#!/usr/bin/env bash
# start.sh — jalanin bot di background pakai pidfile
# Override lewat env: APP_DIR, ENV_FILE, RUN_DIR
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")" && pwd)}"
ENV_FILE="${ENV_FILE:-$HOME/.config/railway-nat-bot.env}"
RUN_DIR="${RUN_DIR:-${DATA_DIR:-$HOME/.railway-nat-bot}}"
PID_FILE="$RUN_DIR/bot.pid"
LOG_FILE="$RUN_DIR/bot.log"

mkdir -p "$RUN_DIR"
chmod 700 "$RUN_DIR"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "sudah jalan, pid $(cat "$PID_FILE")"
  exit 0
fi

[ -f "$ENV_FILE" ] || { echo "env file nggak ada: $ENV_FILE" >&2; exit 1; }

cd "$APP_DIR"
# source env file (aman buat value berspasi, mis. CREDIT="by @user")
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

setsid python3 bot.py >>"$LOG_FILE" 2>&1 </dev/null &
echo $! > "$PID_FILE"
sleep 4

if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "started pid $(cat "$PID_FILE")"
else
  echo "gagal start, cek $LOG_FILE" >&2
  tail -5 "$LOG_FILE" >&2
  rm -f "$PID_FILE"
  exit 1
fi
