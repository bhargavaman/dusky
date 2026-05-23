#!/usr/bin/env bash
# ==============================================================================
# ARCH LINUX :: UWSM :: MATUGEN & AWWW ROFI UI
# ==============================================================================
# Description: Advanced interactive Rofi interface for theme_ctl.sh.
#              - Wizard-style state-machine navigation
#              - Fluid "Back" and "Cancel" propagation
#              - Real-time state awareness via strict secure parsing
#              - Logical submenus for Wallpapers and Color Presets
#              - Frontend validation and notification feedback
#              - Theme & Animation Preset management system
# ==============================================================================

set -Eeuo pipefail
shopt -s inherit_errexit

# --- CONFIGURATION ---
readonly THEME_CTL="${HOME}/user_scripts/theme_matugen/theme_ctl.sh"
readonly PRESETS_FILE="${HOME}/.config/dusky/settings/dusky_theme/rofi_theme_presets"
readonly APP_NAME="theme-ui"
readonly ROFI_THEME_STR='window { width: 500px; } listview { lines: 12; }'

readonly -a REQUIRED_CMDS=(uwsm-app rofi)

# --- MENU DATA ARRAYS ---
readonly -a OPTS_MODE=(dark light)
readonly -a OPTS_SCHEME=(scheme-tonal-spot scheme-vibrant scheme-fruit-salad scheme-expressive scheme-fidelity scheme-rainbow scheme-neutral scheme-monochrome scheme-content disable)
readonly -a OPTS_CONTRAST=(0 -0.8 -0.6 -0.4 -0.2 0.2 0.4 0.6 0.8 1.0 disable)
readonly -a OPTS_INDEX=(0 1 2 3)
readonly -a OPTS_BASE16=(disable wal)

readonly -a OPTS_TRANS_TYPE=(random simple fade left right top bottom wipe wave grow center any outer none disable)
readonly -a OPTS_TRANS_DUR=(disable 0.5 1 2 3 5 10)
readonly -a OPTS_TRANS_FPS=(disable 30 60 90 120 144)
readonly -a OPTS_TRANS_BEZ=(disable ".54,0,.34,.99" "0,0,1,1" ".85,0,.15,1" ".17,.67,.83,.67")
readonly -a OPTS_TRANS_ANG=(disable 0 45 90 135 180 225 270 315)
readonly -a OPTS_TRANS_POS=(disable center top left right bottom top-left top-right bottom-left bottom-right)

# 16 Comprehensive Color Presets (Cleaned of repetitive icons)
readonly -A OPTS_COLORS=(
    ["Red"]="#FF0000"
    ["Blue"]="#0000FF"
    ["Yellow"]="#FFFF00"
    ["Green"]="#00FF00"
    ["Cyan"]="#00FFFF"
    ["Purple"]="#800080"
    ["Orange"]="#FFA500"
    ["Pink"]="#FFC0CB"
    ["Brown"]="#A52A2A"
    ["Golden"]="#FFD700"
    ["Light Green"]="#90EE90"
    ["Bright Yellow"]="#FFFFE0"
    ["Bright Green"]="#66FF00"
    ["Sky Blue"]="#87CEEB"
    ["White"]="#FFFFFF"
    ["Black"]="#000000"
)

# Keys array to maintain logical order in Rofi
readonly -a OPTS_COLOR_KEYS=(
    "Red" "Blue" "Yellow" "Green" "Cyan" "Purple"
    "Orange" "Pink" "Brown" "Golden" "Light Green"
    "Bright Yellow" "Bright Green" "Sky Blue" "White" "Black"
)

# --- GLOBAL STATE VARIABLES ---
CUR_MODE="dark"; CUR_TYPE="scheme-tonal-spot"; CUR_CONTRAST="0"; CUR_INDEX="0"; CUR_BASE16="disable"
CUR_T_TYPE="random"; CUR_T_DUR="2"; CUR_T_FPS="60"; CUR_T_BEZ=".54,0,.34,.99"; CUR_T_ANG="30"; CUR_T_POS="center"

# --- ERROR HANDLING & LOGGING ---
have_cmd() { command -v "$1" >/dev/null 2>&1; }
log_info() { have_cmd logger && logger -p user.info -t "$APP_NAME" -- "$1" || true; }
log_error() { have_cmd logger && logger -p user.err -t "$APP_NAME" -- "$1" || true; }
notify() { have_cmd notify-send && notify-send -u "$1" -- "$2" "$3" >/dev/null 2>&1 || true; }

fatal() {
    log_error "$1"
    notify critical "Theme UI Error" "${2:-$1}"
    exit 1
}

on_unexpected_error() {
    local exit_code=$1
    local line_no=$2
    log_error "Unhandled error at line ${line_no} (exit ${exit_code})."
    notify critical "Theme UI Error" "Unexpected failure. Check journalctl."
    exit "$exit_code"
}
trap 'on_unexpected_error $? $LINENO' ERR

require_commands() {
    local cmd
    for cmd in "${REQUIRED_CMDS[@]}"; do
        have_cmd "$cmd" || fatal "Missing required command: $cmd" "Missing dependency: $cmd"
    done
    [[ -f $THEME_CTL && -x $THEME_CTL ]] || fatal "Controller script missing/non-executable: $THEME_CTL"
}

# --- ROFI WRAPPERS ---
is_rofi_abort_exit() {
    local exit_code=$1
    [[ $exit_code -eq 1 || $exit_code -eq 130 || $exit_code -eq 143 ]] && return 0
    (( exit_code >= 10 && exit_code <= 28 ))
}

# Core interface engine (Now supports automatic item highlighting)
run_menu() {
    local prompt="$1"
    local allow_custom="$2"
    local default_selection="${3:-}"
    shift 3
    local options=("$@")
    local selected exit_code=0
    
    local -a rofi_cmd=(uwsm-app -- rofi -dmenu -i -p "$prompt" -theme-str "$ROFI_THEME_STR" -format s)
    [[ "$allow_custom" == "false" ]] && rofi_cmd+=("-no-custom")
    
    # Automatically highlight the currently applied state
    [[ -n "$default_selection" ]] && rofi_cmd+=("-select" "$default_selection")

    # If options were passed, pipe them into rofi. Otherwise, open an empty input field.
    if (( ${#options[@]} > 0 )); then
        selected=$(printf '%s\n' "${options[@]}" | "${rofi_cmd[@]}") || exit_code=$?
    else
        selected=$("${rofi_cmd[@]}" </dev/null) || exit_code=$?
    fi

    if [[ $exit_code -eq 0 ]]; then
        printf "%s" "$selected"
        return 0
    fi

    # Return 1 triggers a graceful back/abort to the previous state loop
    if is_rofi_abort_exit "$exit_code"; then
        return 1 
    fi
    fatal "Rofi failed at '$prompt' with exit code $exit_code"
}

# --- STATE SYNC ---
get_current_state() {
    # Securely parse the live state without eval
    while IFS='=' read -r key val; do
        val="${val%\"}"; val="${val#\"}" # Strip double quotes
        val="${val%\'}"; val="${val#\'}" # Strip single quotes
        case "$key" in
            THEME_MODE)          CUR_MODE="$val" ;;
            MATUGEN_TYPE)        CUR_TYPE="$val" ;;
            MATUGEN_CONTRAST)    CUR_CONTRAST="$val" ;;
            SOURCE_COLOR_INDEX)  CUR_INDEX="$val" ;;
            BASE16_BACKEND)      CUR_BASE16="$val" ;;
            AWWW_TRANS_TYPE)     CUR_T_TYPE="$val" ;;
            AWWW_TRANS_DURATION) CUR_T_DUR="$val" ;;
            AWWW_TRANS_FPS)      CUR_T_FPS="$val" ;;
            AWWW_TRANS_BEZIER)   CUR_T_BEZ="$val" ;;
            AWWW_TRANS_ANGLE)    CUR_T_ANG="$val" ;;
            AWWW_TRANS_POS)      CUR_T_POS="$val" ;;
        esac
    done < <("$THEME_CTL" get | grep -E '^[A-Z_]+=' 2>/dev/null || true)
}

# --- WIZARDS (STATE MACHINES) ---

wizard_theme() {
    local state="mode"
    local -A cfg=()
    local choice

    while true; do
        case "$state" in
            "mode")
                choice=$(run_menu "Mode" false "$CUR_MODE" "  Cancel" "${OPTS_MODE[@]}") || return 1
                if [[ "$choice" == "  Cancel" ]]; then return 1; fi
                cfg[mode]="$choice"
                state="type"
                ;;
            "type")
                choice=$(run_menu "Matugen Scheme" false "$CUR_TYPE" "  Back" "${OPTS_SCHEME[@]}") || return 1
                if [[ "$choice" == "  Back" ]]; then state="mode"; continue; fi
                cfg[type]="$choice"
                state="contrast"
                ;;
            "contrast")
                choice=$(run_menu "Contrast" true "$CUR_CONTRAST" "  Back" "${OPTS_CONTRAST[@]}") || return 1
                if [[ "$choice" == "  Back" ]]; then state="type"; continue; fi
                cfg[contrast]="$choice"
                state="index"
                ;;
            "index")
                choice=$(run_menu "Color Index" false "$CUR_INDEX" "  Back" "${OPTS_INDEX[@]}") || return 1
                if [[ "$choice" == "  Back" ]]; then state="contrast"; continue; fi
                cfg[index]="$choice"
                state="base16"
                ;;
            "base16")
                choice=$(run_menu "Base16 Backend" false "$CUR_BASE16" "  Back" "${OPTS_BASE16[@]}") || return 1
                if [[ "$choice" == "  Back" ]]; then state="index"; continue; fi
                cfg[base16]="$choice"
                state="apply"
                ;;
            "apply")
                notify normal "Applying Theme" "Mode: ${cfg[mode]} | Type: ${cfg[type]}"
                if ! "$THEME_CTL" set --no-wall \
                    --mode "${cfg[mode]}" \
                    --type "${cfg[type]}" \
                    --contrast "${cfg[contrast]}" \
                    --index "${cfg[index]}" \
                    --base16 "${cfg[base16]}"; then
                    notify critical "Theme Failed" "Check system logs for details."
                    log_error "Theme Backend Failed."
                fi
                return 0
                ;;
        esac
    done
}

wizard_animation() {
    local state="type"
    local -A cfg=()
    local choice

    while true; do
        case "$state" in
            "type")
                choice=$(run_menu "Trans Type" false "$CUR_T_TYPE" "  Cancel" "${OPTS_TRANS_TYPE[@]}") || return 1
                if [[ "$choice" == "  Cancel" ]]; then return 1; fi
                cfg[type]="$choice"
                state="duration"
                ;;
            "duration")
                choice=$(run_menu "Duration (sec)" true "$CUR_T_DUR" "  Back" "${OPTS_TRANS_DUR[@]}") || return 1
                if [[ "$choice" == "  Back" ]]; then state="type"; continue; fi
                cfg[duration]="$choice"
                state="fps"
                ;;
            "fps")
                choice=$(run_menu "FPS" true "$CUR_T_FPS" "  Back" "${OPTS_TRANS_FPS[@]}") || return 1
                if [[ "$choice" == "  Back" ]]; then state="duration"; continue; fi
                cfg[fps]="$choice"
                state="bezier"
                ;;
            "bezier")
                choice=$(run_menu "Bezier Curve" true "$CUR_T_BEZ" "  Back" "${OPTS_TRANS_BEZ[@]}") || return 1
                if [[ "$choice" == "  Back" ]]; then state="fps"; continue; fi
                cfg[bezier]="$choice"
                state="angle"
                ;;
            "angle")
                choice=$(run_menu "Angle (Deg)" true "$CUR_T_ANG" "  Back" "${OPTS_TRANS_ANG[@]}") || return 1
                if [[ "$choice" == "  Back" ]]; then state="bezier"; continue; fi
                cfg[angle]="$choice"
                state="position"
                ;;
            "position")
                choice=$(run_menu "Position" true "$CUR_T_POS" "  Back" "${OPTS_TRANS_POS[@]}") || return 1
                if [[ "$choice" == "  Back" ]]; then state="angle"; continue; fi
                cfg[pos]="$choice"
                state="apply"
                ;;
            "apply")
                notify normal "Applying Animation" "Type: ${cfg[type]} | Dur: ${cfg[duration]}"
                if ! "$THEME_CTL" set --no-wall --no-regen \
                    --trans-type "${cfg[type]}" \
                    --trans-duration "${cfg[duration]}" \
                    --trans-fps "${cfg[fps]}" \
                    --trans-bezier "${cfg[bezier]}" \
                    --trans-angle "${cfg[angle]}" \
                    --trans-pos "${cfg[pos]}"; then
                    notify critical "Animation Failed" "Check system logs for details."
                    log_error "Animation Backend Failed."
                fi
                return 0
                ;;
        esac
    done
}

# --- PRESET MANAGEMENT ENGINE ---

ensure_presets_file() {
    if [[ ! -f "$PRESETS_FILE" ]]; then
        mkdir -p -- "$(dirname "$PRESETS_FILE")"
        touch -- "$PRESETS_FILE"
    fi
}

save_preset() {
    ensure_presets_file
    local preset_name
    preset_name=$(run_menu "Enter Preset Name [ESC to Cancel]" true "") || return 1
    
    # Secure Validation
    if [[ -z "$preset_name" ]]; then
        notify critical "Invalid Name" "Preset name cannot be empty."
        return 1
    fi
    
    if grep -q -F "${preset_name}|" "$PRESETS_FILE" 2>/dev/null; then
        notify critical "Duplicate Preset" "A preset with that name already exists."
        return 1
    fi

    if [[ "$preset_name" == *"|"* ]]; then
        notify critical "Invalid Character" "Preset name cannot contain '|'."
        return 1
    fi

    get_current_state

    # Flatten active configuration to arguments payload
    local args="--mode ${CUR_MODE} --type ${CUR_TYPE} --contrast ${CUR_CONTRAST} --index ${CUR_INDEX} --base16 ${CUR_BASE16} --trans-type ${CUR_T_TYPE} --trans-duration ${CUR_T_DUR} --trans-fps ${CUR_T_FPS} --trans-bezier ${CUR_T_BEZ} --trans-angle ${CUR_T_ANG} --trans-pos ${CUR_T_POS}"

    printf '%s|%s\n' "$preset_name" "$args" >> "$PRESETS_FILE"
    notify normal "Preset Saved" "Successfully saved preset: $preset_name"
}

load_preset() {
    ensure_presets_file
    
    local -a preset_names=()
    while IFS='|' read -r name _rest; do
        [[ -n "$name" ]] && preset_names+=("$name")
    done < "$PRESETS_FILE"
    
    if (( ${#preset_names[@]} == 0 )); then
        notify normal "No Presets" "No saved presets found."
        return 1
    fi
    
    local -a opts=("  Back")
    opts+=("${preset_names[@]}")
    
    local choice
    choice=$(run_menu "Load Preset" false "" "${opts[@]}") || return 1
    [[ "$choice" == "  Back" ]] && return 1
    
    local args=""
    while IFS='|' read -r name rest; do
        if [[ "$name" == "$choice" ]]; then
            args="$rest"
            break
        fi
    done < "$PRESETS_FILE"
    
    if [[ -n "$args" ]]; then
        notify normal "Loading Preset" "Applying: $choice"
        # Temporarily disable globbing to ensure bezier params or negatives apply strictly as args
        set -f
        if ! "$THEME_CTL" set --no-wall $args; then
            set +f
            notify critical "Preset Failed" "Failed to apply preset: $choice"
            log_error "Failed to apply preset: $choice with args: $args"
            return 1
        fi
        set +f
    else
        notify critical "Error" "Could not find configurations for preset: $choice"
    fi
}

delete_preset() {
    ensure_presets_file
    
    local -a preset_names=()
    while IFS='|' read -r name _rest; do
        [[ -n "$name" ]] && preset_names+=("$name")
    done < "$PRESETS_FILE"
    
    if (( ${#preset_names[@]} == 0 )); then
        notify normal "No Presets" "No saved presets found to delete."
        return 1
    fi
    
    local -a opts=("  Back")
    opts+=("${preset_names[@]}")
    
    local choice
    choice=$(run_menu "Delete Preset" false "" "${opts[@]}") || return 1
    [[ "$choice" == "  Back" ]] && return 1
    
    local temp_file
    temp_file=$(mktemp)
    while IFS='|' read -r name rest; do
        if [[ "$name" != "$choice" ]]; then
            printf '%s|%s\n' "$name" "$rest" >> "$temp_file"
        fi
    done < "$PRESETS_FILE"
    mv -f -- "$temp_file" "$PRESETS_FILE"
    
    notify normal "Preset Deleted" "Removed preset: $choice"
}

submenu_presets() {
    local choice
    local -a opts=(
        "  Back to Main"
        "  Save Current State as Preset"
        "  Load Preset"
        "  Delete Preset"
    )

    while true; do
        choice=$(run_menu "Theme Presets" false "" "${opts[@]}") || return 1

        case "$choice" in
            "  Back"*) return 1 ;;
            "  Save"*) save_preset ;;
            "  Load"*) load_preset ;;
            "  Delete"*) delete_preset ;;
        esac
    done
}

# --- SUBMENUS ---

submenu_regen() {
    local action="$1"
    local choice
    local -a opts=(
        "  Back"
        "  Yes (Regenerate Colors)"
        "󰹹  No (Just Change Wallpaper)"
    )

    choice=$(run_menu "Regenerate Colors?" false "" "${opts[@]}") || return 1

    case "$choice" in
        "  Back"*) return 1 ;;
        "  "*) 
            notify normal "Wallpaper & Theme" "Applying $action and extracting colors..."
            "$THEME_CTL" "$action" || { notify critical "Failed" "Could not apply $action."; log_error "Failed: $action"; return 0; }
            return 0 ;;
        "󰹹  "*) 
            notify normal "Wallpaper Only" "Applying $action without regeneration..."
            "$THEME_CTL" "$action" --no-regen || { notify critical "Failed" "Could not apply $action."; log_error "Failed: $action --no-regen"; return 0; }
            return 0 ;;
    esac
}

submenu_solid_color() {
    local choice hex
    local -a opts=(
        "  Back"
        "  Custom Hex Code..."
    )

    # Populate preset colors cleanly
    local k
    for k in "${OPTS_COLOR_KEYS[@]}"; do
        opts+=("$k (${OPTS_COLORS[$k]})")
    done

    while true; do
        choice=$(run_menu "Select Solid Color" false "" "${opts[@]}") || return 1

        case "$choice" in
            "  Back"*) return 1 ;;
            "  Custom"*)
                # Empty array passed to run_menu gives a clean UI with NO list items. Just a typing bar.
                # ESC cancels and continues the loop, bringing back the color preset list.
                hex=$(run_menu "Enter Hex (e.g. FF0000) [ESC to Cancel]" true "") || continue
                
                if [[ -n "$hex" ]]; then
                    # Rofi-side validation before hitting the backend
                    if [[ ! "$hex" =~ ^#?[a-fA-F0-9]{6}$ ]]; then
                        notify critical "Invalid Hex" "The input '$hex' is not a valid hex color."
                        continue
                    fi
                    
                    notify normal "Applying Solid Color" "Hex: $hex"
                    "$THEME_CTL" color "$hex" || { notify critical "Failed" "Could not apply color."; log_error "Failed to apply color"; }
                    return 0
                fi
                ;;
            *)
                # Extract the hex code hidden in parenthesis (e.g. "Red (#FF0000)" -> "#FF0000")
                if [[ "$choice" =~ \((#[A-Fa-f0-9]{6})\) ]]; then
                    hex="${BASH_REMATCH[1]}"
                    notify normal "Applying Preset" "Color: $hex"
                    "$THEME_CTL" color "$hex" || { notify critical "Failed" "Could not apply preset."; log_error "Failed to apply preset color"; }
                    return 0
                fi
                ;;
        esac
    done
}

submenu_wallpapers() {
    local choice
    local -a opts=(
        "  Back to Main"
        "  Next Wallpaper"
        "  Prev Wallpaper"
        "  Random Wallpaper"
        "  Apply Solid Color"
    )

    while true; do
        choice=$(run_menu "Wallpaper Controls" false "" "${opts[@]}") || return 1

        case "$choice" in
            "  Back"*) return 1 ;;
            "  "*) submenu_regen "next" && return 0 || continue ;;
            "  "*) submenu_regen "prev" && return 0 || continue ;;
            "  "*) submenu_regen "random" && return 0 || continue ;;
            "  "*) submenu_solid_color && return 0 || continue ;;
        esac
    done
}

# --- MAIN LOOP ---
main() {
    require_commands

    local choice
    local -a main_opts=(
        "  Theme Config Wizard (Matugen)"
        "󰹹  Animation Config Wizard (awww)"
        "  Theme & Animation Presets"
        "  Wallpaper & Color Controls"
        "  Refresh Current Colors"
        "  Reset Theme to Defaults"
        "  Exit"
    )

    # Persistent execution loop. It only breaks entirely on 'Exit' or 'Escape'.
    while true; do
        get_current_state

        choice=$(run_menu "Dusky Theme Manager" false "" "${main_opts[@]}") || exit 0

        case "$choice" in
            "  Theme"*) wizard_theme || true ;;
            "󰹹  Animation"*) wizard_animation || true ;;
            "  Theme & Animation"*) submenu_presets || true ;;
            "  Wallpaper"*) submenu_wallpapers || true ;;
            "  Refresh"*) 
                notify normal "Refreshing..." "Regenerating colors for current wallpaper."
                "$THEME_CTL" refresh || { notify critical "Refresh Failed" "Check system logs."; log_error "Refresh failed"; }
                ;;
            "  Reset"*) 
                notify normal "Resetting Theme..." "Applying default configuration."
                "$THEME_CTL" set --defaults || { notify critical "Reset Failed" "Check system logs."; log_error "Reset failed"; }
                ;;
            "  Exit"*) exit 0 ;;
        esac
    done
}

main "$@"
