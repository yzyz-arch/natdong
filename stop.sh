#!/usr/bin/env bash
# stop.sh — matiin supervisor + bot (satu process group)
# Override lewat env: RUN_DIR
set -euo pipefail

RUN_DIR="${RUN_DIR:-${DATA_DIR:-$HOME/.railway-nat-bot}}"
PID_FILE="$RUN_DIR/bot.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "nggak ada pidfile di $RUN_DIR, bot mungkin nggak jalan"
  exit 0
fi

PID="$(cat "$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
  # bunuh seluruh group (supervisor + python), bukan cuma process pertama
  kill -TERM -- -"$PID" 2>/dev/null || kill -TERM "$PID" 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    kill -0 "$PID" 2>/dev/null || break
    sleep 1
  done
  kill -0 "$PID" 2>/dev/null && kill -9 -- -"$PID" 2>/dev/null || true
  echo "stopped pid $PID"
else
  echo "pid $PID udah nggak ada"
fi
rm -f "$PID_FILE"
