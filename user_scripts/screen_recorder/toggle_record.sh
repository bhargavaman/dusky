#!/usr/bin/env bash
# ==============================================================================
# GPU Screen Recorder Arch Wayland Wrapper (Strict)
# Targets: Bash 5.3.9+ | Hyprland | gpu-screen-recorder 5.13+
# ==============================================================================
set -eo pipefail

CFG="$HOME/.config/screen_recorder/config.conf"
[[ -f "$CFG" ]] && source "$CFG"

# 1. Fallbacks & Path Expansion
window="${window:-region}"
container="${container:-mp4}"
output_dir="${output_dir:-$HOME/Videos}"

# CRITICAL FIX: Safely expand the tilde symbol if present in the config file
output_dir="${output_dir/#\~/$HOME}"

fps="${fps:-60}"
codec="${codec:-auto}"
quality="${quality:-very_high}"
encoder="${encoder:-gpu}"
audio="${audio:-default_output}"

# New Hardware/Wayland Fallbacks
color_range="${color_range:-limited}"
tune="${tune:-performance}"
low_power="${low_power:-no}"

# Guarantee output directory exists
mkdir -p "$output_dir"

# 2. State Management & Signal Routing
# If the process is running, kill it correctly based on standard vs replay mode
if pids=$(pidof gpu-screen-recorder || true); then
    if [[ -n "$pids" ]]; then
        for pid in $pids; do
            if grep -zqxa -- '-r' "/proc/$pid/cmdline"; then
                kill -SIGUSR1 "$pid"
                notify-send -u normal -i media-record 'GSR Replay' '💾 Replay buffer saved'
            else
                kill -SIGINT "$pid"
                notify-send -u normal -i media-playback-stop 'GSR' '⏹ Recording stopped'
            fi
        done
        exit 0
    fi
fi

# 3. Pure Wayland Region Selection
if [[ "$window" == "region" && -z "$region" ]]; then
    # 500ms buffer allows Hyprland to release the exclusive keybind input grab
    sleep 0.5 
    if ! slurp_coords=$(slurp -f "%wx%h+%x+%y" 2>/dev/null); then
        notify-send -u critical 'GSR Error' 'Region selection cancelled'
        exit 1
    fi
    [[ -z "$slurp_coords" ]] && exit 1
    region="$slurp_coords"
fi

# 4. Argument Array Construction
args=(
    gpu-screen-recorder
    -w "$window"
    -c "$container"
    -f "$fps"
    -k "$codec"
    -q "$quality"
    -encoder "$encoder"
)

# Target Modifiers
[[ "$window" == "region" && -n "$region" ]] && args+=(-region "$region")

# Video & Audio Modifiers
[[ -n "$audio" && "$audio" != "none" ]] && args+=(-a "$audio")
[[ -n "$audio_codec" ]] && args+=(-ac "$audio_codec")
[[ -n "$audio_bitrate" && "$audio_bitrate" != "0" ]] && args+=(-ab "$audio_bitrate")
[[ -n "$bitrate_mode" && "$bitrate_mode" != "auto" ]] && args+=(-bm "$bitrate_mode")
[[ -n "$frame_mode" ]] && args+=(-fm "$frame_mode")
[[ "$cursor" == "no" ]] && args+=(-cursor "no")

# Hardware/Wayland Modifiers
[[ -n "$color_range" && "$color_range" != "limited" ]] && args+=(-cr "$color_range")
[[ -n "$tune" && "$tune" != "performance" ]] && args+=(-tune "$tune")
[[ "$low_power" == "yes" ]] && args+=(-low-power "yes")

# 5. Routing Output Modes (Replay vs Standard)
if [[ -n "$replay_buffer" && "$replay_buffer" -gt 0 ]]; then
    args+=(-r "$replay_buffer")
    [[ -n "$replay_storage" ]] && args+=(-replay-storage "$replay_storage")
    [[ "$restart_replay" == "yes" ]] && args+=(-restart-replay-on-save "yes")
    [[ "$date_folders" == "yes" ]] && args+=(-df "yes")
    
    # Replay strictly requires a Directory for Output
    OUT="$output_dir"
else
    # Standard strictly requires a Filepath for Output
    OUT="${output_dir}/Video_$(date +%Y-%m-%d_%H-%M-%S).${container}"
fi

args+=(-o "$OUT")

# 6. Execution & Verification
"${args[@]}" > /tmp/gsr.log 2>&1 &
new_pid=$!

sleep 0.5
if ! kill -0 "$new_pid" 2>/dev/null; then
    notify-send -u critical 'GSR Error' "Failed to start. Check /tmp/gsr.log"
    exit 1
else
    if [[ -n "$replay_buffer" && "$replay_buffer" -gt 0 ]]; then
        notify-send -u normal -i media-record 'GSR' '🔄 Replay daemon started'
    else
        notify-send -u normal -i media-record 'GSR' '▶ Recording started'
    fi
fi
