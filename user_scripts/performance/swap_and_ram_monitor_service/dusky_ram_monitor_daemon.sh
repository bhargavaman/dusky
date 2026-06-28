#!/usr/bin/env bash
# Dusky RAM Monitor - Pure Bash Memory Monitoring Daemon
# Forensic Optimization: Zero forks, zero subshells, hysteresis-aware.

# ==============================================================================
# CONFIGURATION SETTINGS (Fully Commented for Future-Proofing)
# ==============================================================================

# Critical Physical RAM Threshold (% used)
# Unconditionally triggers a warning if RAM usage hits this limit, even if ZRAM is empty.
# This guards against sudden system lockups due to extreme out-of-memory (OOM) conditions.
THRESHOLD_RAM_CRITICAL=97

# High Physical RAM Threshold (% used)
# Evaluated in combination with THRESHOLD_ZRAM_HIGH. Both conditions must be met to trigger.
THRESHOLD_RAM_HIGH=90

# High ZRAM Swap Occupancy Threshold (% used)
# Evaluated in combination with THRESHOLD_RAM_HIGH. Prevents system stalling from swap exhaustion.
THRESHOLD_ZRAM_HIGH=90

# RAM Recovery Hysteresis Threshold (% used)
# The cooldown timer ONLY resets if physical RAM drops safely below this percentage.
# This strictly prevents notification spam if your RAM endlessly fluctuates between 96% and 97%.
THRESHOLD_RAM_RECOVERY=85

# Polling Interval (seconds)
# The wait time between memory scans.
POLL_INTERVAL=10

# Cooldown Interval (seconds)
# The minimum required wait time before a subsequent notification is allowed to fire.
COOLDOWN_SECS=120

# Internal state tracking (Do not modify)
last_alert_time=0

# ==============================================================================
# ENVIRONMENT PREPARATION
# ==============================================================================

# Load Bash's internal C-compiled sleep to prevent forking /usr/bin/sleep
if [[ -f /usr/lib/bash/sleep ]]; then
    enable -f /usr/lib/bash/sleep sleep 2>/dev/null
fi

# ==============================================================================
# MAIN POLLING LOOP
# ==============================================================================

while true; do
    MemTotal=0
    MemAvailable=0
    
    # 1. Parse RAM stats (Short-circuits at line 3 to save cycles)
    while read -r key val _; do
        case "$key" in
            MemTotal:)     MemTotal=$val ;;
            MemAvailable:) MemAvailable=$val; break ;; 
        esac
    done < /proc/meminfo
    
    if (( MemTotal > 0 )); then
        RamUsedPct=$(( (MemTotal - MemAvailable) * 100 / MemTotal ))
    else
        RamUsedPct=0
    fi
    
    # 2. Parse ZRAM stats (Direct SysFS reads, no pipes)
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
    
    # 3. Threshold Checks & Hysteresis Timer
    if (( RamUsedPct >= THRESHOLD_RAM_CRITICAL || (RamUsedPct >= THRESHOLD_RAM_HIGH && ZramUsedPct >= THRESHOLD_ZRAM_HIGH) )); then
        if (( last_alert_time == 0 || (EPOCHSECONDS - last_alert_time) >= COOLDOWN_SECS )); then
            
            /usr/bin/notify-send -a "dusky-high-ram-alert" -u critical \
                "CRITICAL MEMORY LOW" \
                "RAM: ${RamUsedPct}% | ZRAM: ${ZramUsedPct}%"
            
            last_alert_time=$EPOCHSECONDS
        fi
    elif (( RamUsedPct <= THRESHOLD_RAM_RECOVERY )); then
        # Hysteresis reset: only clear timer when memory has legitimately recovered
        last_alert_time=0
    fi
    
    # Pure Bash sleep (if loaded), falling back to binary gracefully
    sleep "$POLL_INTERVAL"
done
