#!/bin/bash
# Clawmimoto Bot Watchdog — keeps Freqtrade + Telegram bot running
# Run this in a screen/tmux session or as a background loop

WORKSPACE="/data/.openclaw/workspace"
BOT_DIR="$WORKSPACE/clawmimoto-bot"
FREQTRADE_DIR="$WORKSPACE/clawforge-repo"
LOG_FILE="$BOT_DIR/watchdog.log"

echo "Watchdog started at $(date)" >> "$LOG_FILE"

while true; do
    # Check Freqtrade
    if ! pgrep -f "freqtrade trade" > /dev/null; then
        echo "$(date): Freqtrade down — restarting..." >> "$LOG_FILE"
        cd "$FREQTRADE_DIR" && sudo -u node nohup python3 -m freqtrade trade --dry-run \
            --config "configs/config.json" \
            --config "configs/config.local.json" \
            --strategy Claw5MSniper > "logs/freqtrade.log" 2>&1 &
        sleep 10
    fi

    # Check Telegram bot
    if ! pgrep -f "clawforge.telegram_ui" > /dev/null; then
        echo "$(date): Telegram bot down — restarting..." >> "$LOG_FILE"
        cd "$BOT_DIR" && sudo -u node nohup python3 -u -m clawforge.telegram_ui \
            > logs/telegram_ui.log 2>&1 &
        sleep 5
    fi

    # Wait before next check
    sleep 30
done
