
# Send reboot recovery message if uptime < 10 min
UPTIME_MIN=$(awk '{print int($1/60)}' /proc/uptime)
if [ "$UPTIME_MIN" -lt 10 ]; then
  BOT_TOKEN=$(grep TELEGRAM_BOT_TOKEN /docker/openclaw-0jn0/data/.openclaw/workspace/clawmimoto-bot/.env | cut -d= -f2)
  CHAT_ID=$(grep TELEGRAM_CHAT_ID /docker/openclaw-0jn0/data/.openclaw/workspace/clawmimoto-bot/.env | cut -d= -f2)
  curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    -d chat_id="${CHAT_ID}" \
    -d parse_mode="Markdown" \
    -d text="✅ *CLAWFORGE BACK ONLINE*

Server reboot complete.
All systems operational.
Bot resuming normal operations. 🦞" > /dev/null
fi
