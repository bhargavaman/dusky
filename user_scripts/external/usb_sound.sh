#!/usr/bin/env bash
# Modern USB Sound Notification (Arch Linux / Systemd 260+)
set -euo pipefail

export PATH="/usr/local/bin:/usr/bin:/bin"
readonly LOG_TAG="usb-sound"

# System sounds
readonly SOUND_CONNECT="/usr/share/sounds/freedesktop/stereo/device-added.oga"
readonly SOUND_DISCONNECT="/usr/share/sounds/freedesktop/stereo/device-removed.oga"

log_info()  { logger -t "$LOG_TAG" -- "$*"; }
log_error() { logger -t "$LOG_TAG" -p user.err -- "ERROR: $*"; }

get_active_user() {
    local sid state user_name
    while read -r sid; do
        state=$(loginctl show-session "$sid" -p State --value 2>/dev/null || true)
        if [[ "$state" == "active" ]]; then
            user_name=$(loginctl show-session "$sid" -p Name --value 2>/dev/null || true)
            if [[ -n "$user_name" ]]; then
                printf '%s' "$user_name"
                return 0
            fi
        fi
    done < <(loginctl list-sessions --no-legend | awk '{print $1}')
    return 1
}

main() {
    local action="${1:-}"
    local target_user sound_file

    case "$action" in
        connect)
            sound_file="$SOUND_CONNECT"
            ;;
        disconnect)
            sound_file="$SOUND_DISCONNECT"
            ;;
        -h|--help)
            echo "Usage: ${0##*/} <connect|disconnect>"
            exit 0
            ;;
        *)
            echo "Error: Invalid or missing action." >&2
            echo "Usage: ${0##*/} <connect|disconnect>" >&2
            exit 1
            ;;
    esac

    if [[ ! -f "$sound_file" ]]; then
        log_error "Sound file missing: $sound_file"
        exit 1
    fi

    if ! target_user=$(get_active_user); then
        log_info "No active user session found. Exiting quietly."
        exit 0
    fi

    if ! command -v pw-play >/dev/null 2>&1; then
        log_error "pw-play is not installed."
        exit 1
    fi

    log_info "Dispatching $action sound to $target_user via pw-play"

    systemd-run -M "${target_user}@.host" --user --quiet --collect \
        --unit="usb_audio_${action}" \
        --description="USB Audio ${action}" \
        pw-play "$sound_file" 2>/dev/null || true

    exit 0
}

main "$@"
