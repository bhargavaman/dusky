#!/usr/bin/env bash
# Dusky RAM Monitor - Pure Bash Memory Monitoring Daemon
# Extremely efficient: zero subshells or binaries spawned during normal polling (except sleep).

# ==============================================================================
# CONFIGURATION SETTINGS (Edit as needed)
# ==============================================================================

# Critical physical RAM threshold (% used).
# Triggers warning unconditionally if RAM goes above this limit, even if ZRAM is empty.
THRESHOLD_RAM_CRITICAL=97

# High physical RAM threshold (% used).
# Combined with THRESHOLD_ZRAM_HIGH; both must be met to trigger the warning.
THRESHOLD_RAM_HIGH=90

# High ZRAM Swap occupancy threshold (% used).
# Combined with THRESHOLD_RAM_HIGH; both must be met to trigger the warning.
THRESHOLD_ZRAM_HIGH=90

# Polling interval (seconds) between memory scans.
POLL_INTERVAL=10

# Cooldown interval (seconds) to prevent spamming notifications.
COOLDOWN_SECS=120

# Timestamp of the last sent alert (uses built-in EPOCHSECONDS)
last_alert_time=0

while true; do
    # 1. Parse RAM stats from /proc/meminfo in pure Bash
    MemTotal=0
    MemAvailable=0
    
    while read -r key val _; do
        case "$key" in
            MemTotal:) MemTotal=$val ;;
            MemAvailable:) MemAvailable=$val ;;
        esac
    done < /proc/meminfo
    
    if (( MemTotal > 0 )); then
        RamUsedPct=$(( (MemTotal - MemAvailable) * 100 / MemTotal ))
    else
        RamUsedPct=0
    fi
    
    # 2. Parse ZRAM stats directly from sysfs in pure Bash (no processes spawned)
    ZramTotal=0
    ZramUsed=0
    
    if [[ -f "/sys/block/zram0/disksize" && -f "/sys/block/zram0/mm_stat" ]]; then
        read -r ZramTotal < /sys/block/zram0/disksize
        read -r ZramUsed _ < /sys/block/zram0/mm_stat
    fi
    
    if (( ZramTotal > 0 )); then
        ZramUsedPct=$(( ZramUsed * 100 / ZramTotal ))
    else
        ZramUsedPct=0
    fi
    
    # 3. Check if thresholds are exceeded (RAM >= 97% OR [RAM >= 90% AND ZRAM >= 90%])
    if (( RamUsedPct >= THRESHOLD_RAM_CRITICAL || (RamUsedPct >= THRESHOLD_RAM_HIGH && ZramUsedPct >= THRESHOLD_ZRAM_HIGH) )); then
        if (( last_alert_time == 0 || (EPOCHSECONDS - last_alert_time) >= COOLDOWN_SECS )); then
            # Threshold crossed! Send critical notification.
            /usr/bin/notify-send -a "dusky-high-ram-alert" -u critical \
                "CRITICAL MEMORY LOW" \
                "RAM: ${RamUsedPct}% | ZRAM: ${ZramUsedPct}%"
            last_alert_time=$EPOCHSECONDS
        fi
    else
        # Reset alert timer when memory recovers below thresholds
        last_alert_time=0
    fi
    
    # Sleep safely
    sleep "$POLL_INTERVAL"
done
