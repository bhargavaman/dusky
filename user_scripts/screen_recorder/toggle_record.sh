#!/usr/bin/env bash
# ==============================================================================
# GPU Screen Recorder Arch Wayland Wrapper
# Targets: Bash 5.3.9+ | Hyprland | gpu-screen-recorder 5.x
# ==============================================================================

CFG="$HOME/.config/screen_recorder/config.conf"
[[ -f "$CFG" ]] && source "$CFG"

# 1. Fallbacks (Defensive defaults if INI is missing variables)
window="${window:-screen}"
container="${container:-mp4}"
output_dir="${output_dir:-$HOME/Videos}"
fps="${fps:-60}"
codec="${codec:-auto}"
quality="${quality:-very_high}"
encoder="${encoder:-gpu}"
audio="${audio:-default_output}"

# Ensure output directory exists to prevent fatal write errors
mkdir -p "$output_dir"

# 2. State Management & Signal Routing
pids=$(pidof gpu-screen-recorder)
if [[ -n "$pids" ]]; then
    for pid in $pids; do
        # The '-x' flag enforces an EXACT line match inside the null-terminated array.
        # This prevents grep from falsely matching the "r" inside "gpu-screen-recorder".
        if grep -zqxa -- '-r' "/proc/$pid/cmdline"; then
            kill -SIGUSR1 "$pid"
            notify-send -i media-record 'GSR Replay' '💾 Replay buffer saved'
        else
            kill -SIGINT "$pid"
            notify-send -i media-playback-stop 'GSR' '⏹ Recording stopped'
        fi
    done
    exit 0
fi

# 3. Wayland Region Selection (Hyprland Safe)
if [[ "$window" == "region" && -z "$region" ]]; then
    # 500ms buffer allows Hyprland to fully release the exclusive keybind input grab
    sleep 0.5 
    if ! slurp_coords=$(slurp -f "%wx%h+%x+%y"); then
        notify-send -u critical 'GSR Error' 'Region selection cancelled or failed'
        exit 1
    fi
    [[ -z "$slurp_coords" ]] && exit 1
    region="$slurp_coords"
fi

# 4. Argument Array Construction (POSIX-safe Word Splitting Bypass)
args=(gpu-screen-recorder -w "$window" -c "$container" -f "$fps" -k "$codec" -q "$quality" -encoder "$encoder")

# Target Modifiers
[[ "$window" == "focused" ]] && args+=(-s "0x0")
[[ "$window" == "region" && -n "$region" ]] && args+=(-region "$region")

# Video & Audio Modifiers
[[ -n "$audio" && "$audio" != "none" ]] && args+=(-a "$audio")
[[ -n "$audio_codec" ]] && args+=(-ac "$audio_codec")
[[ -n "$audio_bitrate" && "$audio_bitrate" != "0" ]] && args+=(-ab "$audio_bitrate")
[[ -n "$bitrate_mode" && "$bitrate_mode" != "auto" ]] && args+=(-bm "$bitrate_mode")
[[ -n "$frame_mode" ]] && args+=(-fm "$frame_mode")
[[ "$cursor" == "no" ]] && args+=(-cursor "no")

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
else
    if [[ -n "$replay_buffer" && "$replay_buffer" -gt 0 ]]; then
        notify-send -i media-record 'GSR' '🔄 Replay daemon started'
    else
        notify-send -i media-record 'GSR' '▶ Recording started'
    fi
fi
