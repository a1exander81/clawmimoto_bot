#!/bin/bash
# Scheduled maintenance reboot with Telegram alerts

BOT_TOKEN=$(grep TELEGRAM_BOT_TOKEN /docker/openclaw-0jn0/data/.openclaw/workspace/clawmimoto-bot/.env | cut -d= -f2)
CHAT_ID=$(grep TELEGRAM_CHAT_ID /docker/openclaw-0jn0/data/.openclaw/workspace/clawmimoto-bot/.env | cut -d= -f2)

send_msg() {
  curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    -d chat_id="${CHAT_ID}" \
    -d parse_mode="Markdown" \
    -d text="$1" > /dev/null
}

echo "Starting maintenance sequence..."

# 1 hour warning
send_msg "🔧 *MAINTENANCE NOTICE*

⏰ Scheduled server reboot in *1 hour*
📅 $(date -u '+%Y-%m-%d %H:%M UTC')

All trading sessions will be paused.
Bot will be back online within 5 minutes after reboot.

_ClawForge Infrastructure Team_"

sleep 1800  # 30 min

# 30 min warning
send_msg "🔧 *MAINTENANCE NOTICE*

⏰ Server reboot in *30 minutes*
All open positions are safe — Bybit manages them.
No new trades will be executed during downtime."

sleep 1200  # 20 min

# 10 min warning
send_msg "⚠️ *MAINTENANCE — 10 MINUTES*

Server going dark in 10 minutes.
Bot will auto-restart after reboot.
Estimated downtime: ~3 minutes."

sleep 540  # 9 min

# 1 min warning
send_msg "🔴 *GOING DARK IN 1 MINUTE*

Server rebooting now for kernel update.
Back online shortly. Stay calm. 🦞"

sleep 60

# Final message
send_msg "🔴 *SERVER REBOOTING NOW*
_See you on the other side..._"

sleep 5

# Reboot
sudo reboot
