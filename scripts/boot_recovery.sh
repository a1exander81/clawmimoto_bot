nohup python3 /docker/openclaw-0jn0/data/.openclaw/workspace/clawmimoto-bot/scripts/supabase_sync.py >> /docker/openclaw-0jn0/data/.openclaw/workspace/clawmimoto-bot/logs/supabase_sync.log 2>&1 &
#!/usr/bin/env bash
set -euo pipefail

SCRIPT="/docker/openclaw-0jn0/data/.openclaw/workspace/clawmimoto-bot/scripts/supabase_sync.py"
LOG="/docker/openclaw-0jn0/data/.openclaw/workspace/clawmimoto-bot/logs/supabase_sync.log"
PIDFILE="/docker/openclaw-0jn0/data/.openclaw/workspace/clawmimoto-bot/logs/supabase_sync.pid"

if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "supabase_sync already running (pid $(cat "$PIDFILE"))" >> "$LOG"
  exit 0
fi

nohup python3 "$SCRIPT" >> "$LOG" 2>&1 &
echo $! > "$PIDFILE"
disown
