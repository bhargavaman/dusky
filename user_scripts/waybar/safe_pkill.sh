#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# safe_pkill.sh — Race-safe SIGRTMIN+8 delivery for Waybar
#
# Purpose:  Prevent boot-time crashes by verifying Waybar has registered its
#           SIGRTMIN+8 handler before delivering the signal. Reads the SigCgt
#           (caught signals) bitmask from /proc/<pid>/status.
#
# Execution model:
#           NOT a daemon. Invoked per-notification by Mako's on-notify hook.
#           Runs for ~3ms and exits. Zero memory/CPU usage between invocations.
#
# Kernel:   Linux 7.0+ (x86_64). SIGRTMIN=34, so SIGRTMIN+8=42, bit 41.
# ------------------------------------------------------------------------------

set -euo pipefail

# SIGRTMIN+8 = signal 42 on x86_64 Linux (glibc NPTL: SIGRTMIN=34)
# SigCgt bitmask bit position = signal_number - 1 = 41
readonly SIG=42
readonly BIT_POS=41

pids=$(pgrep -x waybar) || exit 0

for pid in $pids; do
    cgt=$(awk '/^SigCgt:/{print $2}' /proc/"$pid"/status 2>/dev/null) || continue
    [[ -n "$cgt" ]] || continue
    (( 16#${cgt} & (1 << BIT_POS) )) && kill -"${SIG}" "$pid"
done
