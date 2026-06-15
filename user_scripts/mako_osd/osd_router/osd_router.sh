#!/usr/bin/env bash
# Hyprland Native OSD Router - Stateless IPC Edition
# Optimized for Bash 5.3.9+ and Wayland/UWSM environments

SYNC_ID="sys-osd"

# Core notification wrapper
notify() {
    local icon="$1"
    local title="$2"
    local val="$3"
    
    if [[ -n "$val" ]]; then
        notify-send -a "OSD" -h string:x-canonical-private-synchronous:"$SYNC_ID" -h int:value:"$val" -i "$icon" "$title"
    else
        notify-send -a "OSD" -h string:x-canonical-private-synchronous:"$SYNC_ID" -i "$icon" "$title"
    fi
}

# Atomic write to entirely eliminate torn reads by the async worker
atomic_write() {
    local file="$1"
    local data="$2"
    echo "$data" > "${file}.tmp"
    mv "${file}.tmp" "$file"
}

main() {
    local action="$1"
    local step="${2:-5}"

    case "$action" in
        --vol-up|--vol-down)
            exec {lock_fd}> "${XDG_RUNTIME_DIR:-/tmp}/osd_audio.lock"
            flock -x "$lock_fd"

            local icon title vol
            if [[ "$action" == "--vol-up" ]]; then
                wpctl set-volume -l 1.0 @DEFAULT_AUDIO_SINK@ "${step}%+"
                icon="audio-volume-high"
            else
                wpctl set-volume @DEFAULT_AUDIO_SINK@ "${step}%-"
                icon="audio-volume-low"
            fi
            
            vol=$(wpctl get-volume @DEFAULT_AUDIO_SINK@ | awk '{print int($2 * 100 + 0.5)}')
            title="Volume: ${vol}%"
            
            # Write target state atomically while holding hardware lock
            atomic_write "${XDG_RUNTIME_DIR:-/tmp}/osd_audio_state.txt" "$icon|$title|$vol"
            exec {lock_fd}>&-
            
            # Asynchronous Single Worker Loop
            (
                flock -n 9 || exit 0
                while true; do
                    IFS='|' read -r c_icon c_title c_vol < "${XDG_RUNTIME_DIR:-/tmp}/osd_audio_state.txt"
                    [[ -z "$c_title" ]] && break 
                    
                    notify "$c_icon" "$c_title" "$c_vol"
                    
                    IFS='|' read -r n_icon n_title n_vol < "${XDG_RUNTIME_DIR:-/tmp}/osd_audio_state.txt"
                    if [[ "$c_vol" == "$n_vol" && "$c_icon" == "$n_icon" && "$c_title" == "$n_title" ]]; then
                        break # State caught up, exit worker cleanly
                    fi
                done
            ) 9>> "${XDG_RUNTIME_DIR:-/tmp}/osd_audio_ui.lock" &
            ;;

        --vol-mute)
            exec {lock_fd}> "${XDG_RUNTIME_DIR:-/tmp}/osd_audio.lock"
            flock -x "$lock_fd"

            wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle
            
            local icon title vol
            if wpctl get-volume @DEFAULT_AUDIO_SINK@ | grep -q "MUTED"; then
                icon="audio-volume-muted"
                title="Audio Muted"
                vol=""
            else
                icon="audio-volume-high"
                vol=$(wpctl get-volume @DEFAULT_AUDIO_SINK@ | awk '{print int($2 * 100 + 0.5)}')
                title="Audio Unmuted"
            fi
            
            atomic_write "${XDG_RUNTIME_DIR:-/tmp}/osd_audio_state.txt" "$icon|$title|$vol"
            exec {lock_fd}>&-

            (
                flock -n 9 || exit 0
                while true; do
                    IFS='|' read -r c_icon c_title c_vol < "${XDG_RUNTIME_DIR:-/tmp}/osd_audio_state.txt"
                    [[ -z "$c_title" ]] && break
                    
                    notify "$c_icon" "$c_title" "$c_vol"
                    
                    IFS='|' read -r n_icon n_title n_vol < "${XDG_RUNTIME_DIR:-/tmp}/osd_audio_state.txt"
                    if [[ "$c_vol" == "$n_vol" && "$c_icon" == "$n_icon" && "$c_title" == "$n_title" ]]; then
                        break
                    fi
                done
            ) 9>> "${XDG_RUNTIME_DIR:-/tmp}/osd_audio_ui.lock" &
            ;;

        --mic-mute)
            wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle
            if wpctl get-volume @DEFAULT_AUDIO_SOURCE@ | grep -q "MUTED"; then
                notify "microphone-sensitivity-muted" "Microphone Muted" ""
            else
                notify "audio-input-microphone" "Microphone Live" ""
            fi
            ;;

        --bright-up|--bright-down)
            exec {lock_fd}> "${XDG_RUNTIME_DIR:-/tmp}/osd_display.lock"
            flock -x "$lock_fd"

            local icon="gpm-brightness-lcd" title bright
            local warn_msg="Swipe again to turn off"
            
            # Read the last known UI state to determine if we already warned the user
            local last_title=""
            if [[ -f "${XDG_RUNTIME_DIR:-/tmp}/osd_display_state.txt" ]]; then
                last_title=$(awk -F'|' '{print $2}' "${XDG_RUNTIME_DIR:-/tmp}/osd_display_state.txt")
            fi

            local current_bright
            current_bright=$(brightnessctl -m | awk -F, '{print int($4 + 0.5)}')

            if [[ "$action" == "--bright-down" ]]; then
                # Robust regex: catches both 'false' and '0' regardless of Hyprland sub-version
                local dpms_off=0
                if hyprctl monitors all | grep -Eiq "dpmsstatus:\s*(0|false)"; then
                    dpms_off=1
                fi

                if [[ "$dpms_off" -eq 1 ]]; then
                    # Monitor is already off, just update OSD passively
                    icon="display-brightness-off"
                    title="Screen Off"
                    bright=0
                elif [[ "$current_bright" -le 1 ]]; then
                    # We are at the 1% floor. Check if we already warned them.
                    if [[ "$last_title" == "$warn_msg" ]]; then
                        # Warning was acknowledged. Execute DPMS off via Hyprland Lua eval.
                        hyprctl eval 'hl.dispatch(hl.dsp.dpms({ action = "disable" }))' &>/dev/null
                        icon="display-brightness-off"
                        title="Screen Off"
                        bright=0
                    else
                        # Issue the warning notification. Keep brightness at 1%.
                        brightnessctl set 1% -q
                        title="$warn_msg"
                        bright=1
                    fi
                else
                    # We are > 1%. Calculate if the step would take us below the 1% floor.
                    local target=$((current_bright - step))
                    if [[ "$target" -le 1 ]]; then
                        brightnessctl set 1% -q
                        bright=1
                        title="Brightness: 1%"
                    else
                        brightnessctl set "${step}%-" -q
                        bright=$(brightnessctl -m | awk -F, '{print int($4 + 0.5)}')
                        title="Brightness: ${bright}%"
                    fi
                fi
            else
                # --bright-up
                # Unconditionally dispatch DPMS enable. Swiping up inherently means "I want to see the screen."
                hyprctl eval 'hl.dispatch(hl.dsp.dpms({ action = "enable" }))' &>/dev/null
                
                # Hardware Race Condition Fix: If waking from 0/1%, give the backlight controller
                # 150ms to initialize before blasting it with brightness increments.
                if [[ "$current_bright" -le 1 || "$last_title" == "Screen Off" ]]; then
                    sleep 0.15
                fi

                brightnessctl set "${step}%+" -q
                bright=$(brightnessctl -m | awk -F, '{print int($4 + 0.5)}')
                
                if [[ "$current_bright" -le 1 || "$last_title" == "Screen Off" ]]; then
                    title="Screen On: ${bright}%"
                else
                    title="Brightness: ${bright}%"
                fi
            fi
            
            atomic_write "${XDG_RUNTIME_DIR:-/tmp}/osd_display_state.txt" "$icon|$title|$bright"
            exec {lock_fd}>&-
            
            (
                flock -n 9 || exit 0
                while true; do
                    IFS='|' read -r c_icon c_title c_bright < "${XDG_RUNTIME_DIR:-/tmp}/osd_display_state.txt"
                    [[ -z "$c_title" ]] && break
                    
                    notify "$c_icon" "$c_title" "$c_bright"
                    
                    IFS='|' read -r n_icon n_title n_bright < "${XDG_RUNTIME_DIR:-/tmp}/osd_display_state.txt"
                    if [[ "$c_bright" == "$n_bright" && "$c_icon" == "$n_icon" && "$c_title" == "$n_title" ]]; then
                        break
                    fi
                done
            ) 9>> "${XDG_RUNTIME_DIR:-/tmp}/osd_display_ui.lock" &
            ;;

        --kbd-bright-up|--kbd-bright-down)
            exec {lock_fd}> "${XDG_RUNTIME_DIR:-/tmp}/osd_kbd.lock"
            flock -x "$lock_fd"

            local kbd_dev
            kbd_dev=$(brightnessctl -l | awk -F"'" '/kbd_backlight/ {print $2; exit}')

            if [[ -z "$kbd_dev" ]]; then
                notify "dialog-error" "No Kbd Backlight Found" ""
                exec {lock_fd}>&-
                exit 1
            fi

            if [[ "$action" == "--kbd-bright-up" ]]; then
                brightnessctl --device="$kbd_dev" set "${step}%+" -q
            else
                brightnessctl --device="$kbd_dev" set "${step}%-" -q
            fi

            local icon="keyboard-brightness" title kbd_bright
            kbd_bright=$(brightnessctl --device="$kbd_dev" -m 2>/dev/null | awk -F, '{print int($4 + 0.5)}')
            [[ -z "$kbd_bright" ]] && kbd_bright=0
            title="Kbd Brightness: ${kbd_bright}%"

            atomic_write "${XDG_RUNTIME_DIR:-/tmp}/osd_kbd_state.txt" "$icon|$title|$kbd_bright"
            exec {lock_fd}>&-

            (
                flock -n 9 || exit 0
                while true; do
                    IFS='|' read -r c_icon c_title c_bright < "${XDG_RUNTIME_DIR:-/tmp}/osd_kbd_state.txt"
                    [[ -z "$c_title" ]] && break
                    
                    notify "$c_icon" "$c_title" "$c_bright"
                    
                    IFS='|' read -r n_icon n_title n_bright < "${XDG_RUNTIME_DIR:-/tmp}/osd_kbd_state.txt"
                    if [[ "$c_bright" == "$n_bright" && "$c_icon" == "$n_icon" && "$c_title" == "$n_title" ]]; then
                        break
                    fi
                done
            ) 9>> "${XDG_RUNTIME_DIR:-/tmp}/osd_kbd_ui.lock" &
            ;;

        --kbd-bright-show)
            local kbd_dev
            kbd_dev=$(brightnessctl -l | awk -F"'" '/kbd_backlight/ {print $2; exit}')
            
            if [[ -z "$kbd_dev" ]]; then
                exit 0
            fi

            local kbd_bright
            kbd_bright=$(brightnessctl --device="$kbd_dev" -m 2>/dev/null | awk -F, '{print int($4 + 0.5)}')
            [[ -z "$kbd_bright" ]] && kbd_bright=0

            notify "keyboard-brightness" "Kbd Brightness: ${kbd_bright}%" "$kbd_bright"
            ;;

        --play-pause|--next|--prev|--stop)
            local old_meta old_status
            old_meta=$(playerctl metadata --format "{{ artist }} - {{ title }}" 2>/dev/null)
            old_status=$(playerctl status 2>/dev/null)

            case "$action" in
                --play-pause) playerctl play-pause ;;
                --next)       playerctl next ;;
                --prev)       playerctl previous ;;
                --stop)       playerctl stop ;;
            esac
            
            local status metadata
            for ((i=0; i<100; i++)); do
                status=$(playerctl status 2>/dev/null)
                metadata=$(playerctl metadata --format "{{ artist }} - {{ title }}" 2>/dev/null)
                
                case "$action" in
                    --play-pause)
                        [[ "$status" != "$old_status" && -n "$status" ]] && break
                        ;;
                    --next|--prev)
                        [[ "$metadata" != "$old_meta" ]] && break
                        ;;
                    --stop)
                        [[ "$status" == "Stopped" || -z "$status" ]] && break
                        ;;
                esac
                
                read -r -t 0.01 <> <(:)
            done
            
            [[ -z "$metadata" || "$metadata" == " - " ]] && metadata="Unknown Track"

            if [[ "$status" == "Playing" ]]; then
                icon="media-playback-start"
                title="$metadata"
            elif [[ "$status" == "Paused" ]]; then
                icon="media-playback-pause"
                title="Paused: $metadata"
            elif [[ "$status" == "Stopped" || -z "$status" ]] && metadata="Unknown Track"; then
                icon="media-playback-stop"
                title="Stopped"
            else
                icon="dialog-error"
                title="No Active Player"
            fi
            
            notify "$icon" "$title" ""
            ;;

        *)
            echo "Usage: $0 {--vol-up|--vol-down|--vol-mute|--mic-mute|--bright-up|--bright-down|--kbd-bright-up|--kbd-bright-down|--kbd-bright-show|--play-pause|--next|--prev|--stop} [step_value]"
            exit 1
            ;;
    esac
}

main "$@"
