#!/usr/bin/env bash
# ==============================================================================
# ARCH LINUX :: WAYLAND :: ROFI DUSKY RECORDER
# ==============================================================================
# Description: Interactive Rofi interface for gpu-screen-recorder.
#              - State-aware Start/Stop/Replay controls
#              - Full Screen vs Region selection
#              - Quick settings editor (FPS, Cursor, Audio, Indicator)
#              - Async blinking Mako red-dot indicator
#              - Dynamic Split Audio Device Discovery
# ==============================================================================

set -Eeuo pipefail

# --- CONFIGURATION ---
readonly CFG="$HOME/.config/dusky_recorder/config.conf"
readonly ROFI_THEME_STR='window { width: 450px; } listview { lines: 8; }'
readonly INDICATOR_TMP="/tmp/dusky_recorder_notif_id"
readonly INDICATOR_PID="/tmp/dusky_recorder_daemon.pid"

# Ensure config exists and load it
[[ -f "$CFG" ]] && source "$CFG"

# Fallbacks
fps="${fps:-60}"
cursor="${cursor:-yes}"
container="${container:-mp4}"
output_dir="${output_dir:-$HOME/Videos}"
output_dir="${output_dir/#\~/$HOME}"
replay_buffer="${replay_buffer:-0}"
show_indicator="${show_indicator:-yes}"

# --- AUDIO STATE MIGRATION ---
# Silently migrate old single 'audio' config to split 'audio_output' and 'audio_input'
if [[ -n "${audio:-}" && -z "${audio_output:-}" && -z "${audio_input:-}" ]]; then
    if [[ "$audio" == *"|"* ]]; then
        audio_output="${audio%|*}"
        audio_input="${audio#*|}"
    elif [[ "$audio" == *"input"* ]]; then
        audio_output="none"
        audio_input="$audio"
    elif [[ "$audio" == *"output"* ]]; then
        audio_output="$audio"
        audio_input="none"
    elif [[ "$audio" == "none" ]]; then
        audio_output="none"
        audio_input="none"
    else
        audio_output="default_output"
        audio_input="none"
    fi
    # Remove legacy key and save new keys
    sed -i '/^audio=/d' "$CFG" 2>/dev/null || true
    # We don't call update_config here to avoid sourcing loops, just append
    echo "audio_output=${audio_output}" >> "$CFG"
    echo "audio_input=${audio_input}" >> "$CFG"
fi

audio_output="${audio_output:-default_output}"
audio_input="${audio_input:-none}"

# --- HELPERS ---
run_menu() {
    local prompt="$1"
    shift
    local options=("$@")
    printf '%s\n' "${options[@]}" | rofi -dmenu -i -p "$prompt" -theme-str "$ROFI_THEME_STR" -format s
}

update_config() {
    local key="$1"
    local value="$2"
    # Using ~ as delimiter so pipe characters (|) in hardware strings don't crash sed
    if grep -q "^${key}=" "$CFG"; then
        sed -i "s~^${key}=.*~${key}=${value}~" "$CFG"
    else
        echo "${key}=${value}" >> "$CFG"
    fi
    export "$key"="$value"
}

get_audio_name() {
    local target_id="$1"
    [[ "$target_id" == "none" ]] && echo "None" && return
    [[ "$target_id" == "default_output" ]] && echo "Default Desktop" && return
    [[ "$target_id" == "default_input" ]] && echo "Default Mic" && return
    
    local name
    # Exact string match the ID to pull the friendly name
    name=$(gpu-screen-recorder --list-audio-devices 2>/dev/null | grep -F "${target_id}|" | cut -d'|' -f2 | head -n1)
    if [[ -n "$name" ]]; then
        echo "$name"
    else
        # Fallback to ID if device was unplugged but still in config
        echo "Disconnected Device"
    fi
}

manage_indicator() {
    local action="$1"
    
    if [[ "$action" == "start" ]]; then
        [[ "$show_indicator" != "yes" ]] && return 0

        (
            local notif_id
            notif_id=$(notify-send -a "dusky-recorder" -p "" "")
            echo "$notif_id" > "$INDICATOR_TMP"
            
            local visible=true
            while true; do
                sleep 1
                if $visible; then
                    notify-send -a "dusky-recorder" -r "$notif_id" " " ""
                    visible=false
                else
                    notify-send -a "dusky-recorder" -r "$notif_id" "" ""
                    visible=true
                fi
            done
        ) & 
        echo $! > "$INDICATOR_PID"
        
    elif [[ "$action" == "stop" ]]; then
        if [[ -f "$INDICATOR_PID" ]]; then
            kill "$(cat "$INDICATOR_PID")" 2>/dev/null || true
            rm -f "$INDICATOR_PID"
        fi
        
        if [[ -f "$INDICATOR_TMP" ]]; then
            local notif_id
            notif_id=$(cat "$INDICATOR_TMP")
            makoctl dismiss -n "$notif_id" 2>/dev/null || true
            rm -f "$INDICATOR_TMP"
        fi
    fi
}

# --- RECORDING LOGIC ---
stop_recording() {
    local pids
    if pids=$(pidof gpu-screen-recorder || true); then
        if [[ -n "$pids" ]]; then
            for pid in $pids; do
                kill -SIGINT "$pid"
            done
            notify-send -u normal -i media-playback-stop 'Dusky Recorder' '  Recording stopped'
            manage_indicator "stop"
        fi
    fi
}

save_replay() {
    local pids
    if pids=$(pidof gpu-screen-recorder || true); then
        if [[ -n "$pids" ]]; then
            for pid in $pids; do
                kill -SIGUSR1 "$pid"
            done
            notify-send -u normal -i media-record 'Dusky Replay' '  Replay buffer saved'
        fi
    fi
}

start_recording() {
    local target_mode="$1"
    
    local region_coords=""
    if [[ "$target_mode" == "region" ]]; then
        sleep 0.5 
        if ! region_coords=$(slurp -f "%wx%h+%x+%y" 2>/dev/null); then
            notify-send -u critical 'Dusky Recorder Error' 'Region selection cancelled'
            exit 1
        fi
        [[ -z "$region_coords" ]] && exit 1
    fi

    mkdir -p "$output_dir"

    local -a args=(
        gpu-screen-recorder
        -w "$target_mode"
        -c "$container"
        -f "$fps"
    )

    [[ "$target_mode" == "region" && -n "$region_coords" ]] && args+=(-region "$region_coords")
    [[ "$cursor" == "no" ]] && args+=(-cursor "no")
    
    # --- DYNAMIC AUDIO INJECTION ---
    local final_audio=""
    if [[ "$audio_output" != "none" && "$audio_input" != "none" ]]; then
        final_audio="${audio_output}|${audio_input}"
    elif [[ "$audio_output" != "none" ]]; then
        final_audio="${audio_output}"
    elif [[ "$audio_input" != "none" ]]; then
        final_audio="${audio_input}"
    fi
    [[ -n "$final_audio" ]] && args+=(-a "$final_audio")

    # Hardware/backend variables
    [[ -n "${codec:-}" ]] && args+=(-k "$codec")
    [[ -n "${quality:-}" ]] && args+=(-q "$quality")
    [[ -n "${encoder:-}" ]] && args+=(-encoder "$encoder")
    [[ -n "${bitrate_mode:-}" ]] && args+=(-bm "$bitrate_mode")
    [[ -n "${frame_mode:-}" ]] && args+=(-fm "$frame_mode")

    local OUT=""
    if [[ -n "$replay_buffer" && "$replay_buffer" -gt 0 ]]; then
        args+=(-r "$replay_buffer")
        OUT="$output_dir"
    else
        OUT="${output_dir}/Video_$(date +%Y-%m-%d_%H-%M-%S).${container}"
    fi
    args+=(-o "$OUT")

    "${args[@]}" > /tmp/gsr.log 2>&1 &
    local new_pid=$!

    sleep 0.5
    if ! kill -0 "$new_pid" 2>/dev/null; then
        notify-send -u critical 'Dusky Recorder Error' "Failed to start. Check /tmp/gsr.log"
        exit 1
    else
        if [[ -n "$replay_buffer" && "$replay_buffer" -gt 0 ]]; then
            notify-send -u normal -i media-record 'Dusky Recorder' '  Replay daemon started'
        else
            notify-send -u normal -i media-record 'Dusky Recorder' '  Recording started'
        fi
        manage_indicator "start"
    fi
}

# --- SUBMENUS ---
settings_menu() {
    while true; do
        # Fetch friendly display names and truncate to prevent UI breakage
        local disp_out; disp_out=$(get_audio_name "$audio_output")
        [[ ${#disp_out} -gt 18 ]] && disp_out="${disp_out:0:15}..."
        
        local disp_in; disp_in=$(get_audio_name "$audio_input")
        [[ ${#disp_in} -gt 18 ]] && disp_in="${disp_in:0:15}..."

        local -a opts=(
            "  Back"
            "󰣖  FPS         [${fps}]"
            "󰇀  Cursor      [${cursor}]"
            "󰓃  Output      [${disp_out}]"
            "  Input       [${disp_in}]"
            "󰂚  Indicator   [${show_indicator}]"
            "  Replay Buf  [${replay_buffer}s]"
        )
        local choice
        choice=$(run_menu "  Quick Settings" "${opts[@]}") || return 0

        case "$choice" in
            "  Back"*) return 0 ;;
            "󰣖  FPS"*)
                local new_fps
                new_fps=$(run_menu "Select FPS" "30" "60" "120" "144") || continue
                [[ -n "$new_fps" ]] && { fps="$new_fps"; update_config "fps" "$fps"; }
                ;;
            "󰇀  Cursor"*)
                local new_cursor
                new_cursor=$(run_menu "Record Cursor?" "yes" "no") || continue
                [[ -n "$new_cursor" ]] && { cursor="$new_cursor"; update_config "cursor" "$cursor"; }
                ;;
                
            # --- OUTPUT AUDIO SUBMENU ---
            "󰓃  Output"*)
                local -a rofi_out_list=()
                local -A out_map=()

                rofi_out_list+=("  None")
                out_map["  None"]="none"
                rofi_out_list+=("  Default Desktop Audio")
                out_map["  Default Desktop Audio"]="default_output"

                while IFS='|' read -r dev_id dev_name; do
                    [[ -z "$dev_id" || "$dev_id" == "default_output" || "$dev_id" == "default_input" ]] && continue
                    [[ -z "$dev_name" ]] && dev_name="$dev_id"
                    
                    if [[ "$dev_id" == *"output"* ]]; then
                        local entry="  $dev_name"
                        # Handle duplicate device names
                        local count=2
                        while [[ -n "${out_map[$entry]:-}" ]]; do
                            entry="  $dev_name ($count)"
                            ((count++))
                        done
                        
                        rofi_out_list+=("$entry")
                        out_map["$entry"]="$dev_id"
                    fi
                done < <(gpu-screen-recorder --list-audio-devices 2>/dev/null)

                local choice_out
                choice_out=$(run_menu "Select Output (Desktop)" "${rofi_out_list[@]}") || continue
                if [[ -n "$choice_out" && -n "${out_map[$choice_out]:-}" ]]; then
                    audio_output="${out_map[$choice_out]}"
                    update_config "audio_output" "$audio_output"
                fi
                ;;
                
            # --- INPUT AUDIO SUBMENU ---
            "  Input"*)
                local -a rofi_in_list=()
                local -A in_map=()

                rofi_in_list+=("  None")
                in_map["  None"]="none"
                rofi_in_list+=("  Default Microphone")
                in_map["  Default Microphone"]="default_input"

                while IFS='|' read -r dev_id dev_name; do
                    [[ -z "$dev_id" || "$dev_id" == "default_output" || "$dev_id" == "default_input" ]] && continue
                    [[ -z "$dev_name" ]] && dev_name="$dev_id"
                    
                    if [[ "$dev_id" == *"input"* ]]; then
                        local entry="  $dev_name"
                        # Handle duplicate device names
                        local count=2
                        while [[ -n "${in_map[$entry]:-}" ]]; do
                            entry="  $dev_name ($count)"
                            ((count++))
                        done
                        
                        rofi_in_list+=("$entry")
                        in_map["$entry"]="$dev_id"
                    fi
                done < <(gpu-screen-recorder --list-audio-devices 2>/dev/null)

                local choice_in
                choice_in=$(run_menu "Select Input (Mic)" "${rofi_in_list[@]}") || continue
                if [[ -n "$choice_in" && -n "${in_map[$choice_in]:-}" ]]; then
                    audio_input="${in_map[$choice_in]}"
                    update_config "audio_input" "$audio_input"
                fi
                ;;
                
            "󰂚  Indicator"*)
                local new_ind
                new_ind=$(run_menu "Show Red Dot Indicator?" "yes" "no") || continue
                [[ -n "$new_ind" ]] && { show_indicator="$new_ind"; update_config "show_indicator" "$show_indicator"; }
                ;;
            "  Replay"*)
                local new_buf
                new_buf=$(run_menu "Replay Buffer (0 to disable)" "0" "30" "60" "120" "300") || continue
                [[ -n "$new_buf" ]] && { replay_buffer="$new_buf"; update_config "replay_buffer" "$replay_buffer"; }
                ;;
        esac
    done
}

# --- MAIN LOOP ---
main() {
    local is_running=false
    local is_replay=false
    local pids
    
    if pids=$(pidof gpu-screen-recorder || true); then
        if [[ -n "$pids" ]]; then
            is_running=true
            if grep -zqxa -- '-r' "/proc/$(echo "$pids" | awk '{print $1}')/cmdline" 2>/dev/null; then
                is_replay=true
            fi
        fi
    fi

    local -a main_opts=()
    if $is_running; then
        $is_replay && main_opts+=("  Save Replay Buffer")
        main_opts+=("  Stop Recording")
        main_opts+=("  Cancel")
    else
        main_opts+=("  Record Full Screen")
        main_opts+=("  Record Region")
        main_opts+=("  Quick Settings")
        main_opts+=("  Cancel")
    fi

    local choice
    choice=$(run_menu "Dusky Recorder" "${main_opts[@]}") || exit 0

    case "$choice" in
        "  Stop"*) stop_recording ;;
        "  Save"*) save_replay ;;
        "  Record"*) start_recording "screen" ;;
        "  Record"*) start_recording "region" ;;
        "  Quick"*) settings_menu; main ;;
        "  Cancel"*) exit 0 ;;
    esac
}

main
