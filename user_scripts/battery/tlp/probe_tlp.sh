#!/bin/bash
# Script to probe the currently active TLP profile and mode without tlp-pd or root privileges.

PWRRUNFILE="/run/tlp/last_pwr"
MANUALMODEFILE="/run/tlp/manual_mode"

# Default format is human-readable
OUTPUT_JSON=false

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        -j|--json) OUTPUT_JSON=true ;;
        -h|--help)
            echo "Usage: $0 [options]"
            echo "Options:"
            echo "  -j, --json    Output the results in JSON format"
            echo "  -h, --help    Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
    shift
done

if [ ! -f "$PWRRUNFILE" ]; then
    if [ "$OUTPUT_JSON" = true ]; then
        echo '{"error": "TLP state file not found"}'
    else
        echo "Error: TLP state file '$PWRRUNFILE' not found. Is TLP running?" >&2
    fi
    exit 1
fi

read -r pp_code ps_code < "$PWRRUNFILE" 2>/dev/null

case "$pp_code" in
    0) profile="performance" ;;
    1) profile="balanced" ;;
    2) profile="power-saver" ;;
    *) profile="unknown" ;;
esac

case "$ps_code" in
    0) source="AC" ;;
    1) source="Battery" ;;
    128) source="Unknown" ;;
    *) source="Unknown" ;;
esac

if [ -f "$MANUALMODEFILE" ]; then
    mode="manual"
else
    mode="auto"
fi

if [ "$OUTPUT_JSON" = true ]; then
    printf '{"profile":"%s","power_source":"%s","mode":"%s"}\n' "$profile" "$source" "$mode"
else
    echo "Active Profile: $profile"
    echo "Power Source:   $source"
    echo "Mode:           $mode"
fi
