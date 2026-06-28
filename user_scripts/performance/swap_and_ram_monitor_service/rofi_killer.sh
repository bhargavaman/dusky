#!/usr/bin/env bash
# Rofi Low-Memory Process Killer
# Extremely efficient pure Bash menu.

LOCK_FILE="/tmp/rofi_killer.lock"

# Trap to ensure lock file is cleaned up on exit
cleanup() {
    rm -f "$LOCK_FILE"
}
trap cleanup EXIT

list_processes() {
    # Get top 20 processes sorting by memory, showing PMEM%, RSS (in KB converted to MB), Name, and PID
    ps -eo pid,pmem,rss,comm --sort=-pmem | tail -n +2 | head -n 20 | while read -r pid pmem rss comm; do
        rss_mb=$(( rss / 1024 ))
        printf "RAM: %-4s%% (%4s MB) | %-25s | PID: %s\n" "$pmem" "$rss_mb" "$comm" "$pid"
    done
}

while true; do
    selection=$(list_processes | rofi -dmenu -p "CRITICAL MEMORY! Select to KILL" -i -theme-str 'window { width: 680px; }')
    
    # If user hits Escape or closes rofi, exit
    [[ -z "$selection" ]] && break
    
    # Extract PID in pure Bash (no awk/sed/grep)
    if [[ "$selection" =~ PID:[[:space:]]*([0-9]+) ]]; then
        pid="${BASH_REMATCH[1]}"
        
        # Kill the process
        if kill -9 "$pid" 2>/dev/null; then
            /usr/bin/notify-send -u normal -i dialog-information \
                "Process Killed" \
                "Successfully terminated PID ${pid}."
        else
            /usr/bin/notify-send -u normal -i dialog-error \
                "Kill Failed" \
                "Could not terminate PID ${pid}."
        fi
    else
        break
    fi
done
