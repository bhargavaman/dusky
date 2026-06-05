#!/usr/bin/env bash
# ~/user_scripts/rofi/dusky_launcher.sh
# Unified All-in-One Launcher & Data Provider

# ==============================================================================
# 1. DATA PROVIDER MODE (Populates the "Dusky" tab)
# This executes ONLY when Rofi calls the script back looking for data.
# ==============================================================================
if [[ "$1" == "--rofi-mode" ]]; then
    # ROFI_RETV state: 0 = Initial load, 1 = User selected an item
    if [[ -z "$ROFI_RETV" || "$ROFI_RETV" -eq 0 ]]; then
        # Find all .desktop files with "dusky" in the name
        find ~/.local/share/applications /usr/share/applications -type f -iname "*dusky*.desktop" 2>/dev/null | while read -r file; do
            # Extract attributes
            name=$(grep -m1 -i '^Name=' "$file" | cut -d'=' -f2)
            desc=$(grep -m1 -i '^GenericName=' "$file" | cut -d'=' -f2)
            icon=$(grep -m1 -i '^Icon=' "$file" | cut -d'=' -f2)
            
            # Format text: "Name (Description)" using Pango markup
            if [[ -n "$desc" ]]; then
                display_text="${name} <span alpha='60%'><i>(${desc})</i></span>"
            else
                display_text="${name}"
            fi
            
            # Send to Rofi: Display Text + Icon payload + Hidden File Path (info)
            echo -e "${display_text}\0icon\x1f${icon}\x1finfo\x1f${file}"
        done
    elif [[ "$ROFI_RETV" -eq 1 ]]; then
        # The user hit enter. Extract the hidden file path from ROFI_INFO
        if [[ -n "$ROFI_INFO" ]]; then
            # Extract the execution command and strip out standard XDG flags like %U or %f
            exec_cmd=$(grep -m1 -i '^Exec=' "$ROFI_INFO" | cut -d'=' -f2 | sed 's/ %[a-zA-Z]//g')
            
            # Execute cleanly and detach from the script
            nohup bash -c "$exec_cmd" >/dev/null 2>&1 &
        fi
    fi
    exit 0
fi

# ==============================================================================
# 2. UI LAUNCHER MODE
# ==============================================================================

# Toggle Logic: Kill Rofi if it's already open
if pidof rofi >/dev/null; then
    pkill rofi
    exit 0
fi

# Cache Management
CACHE_DIR="$HOME/.config/dusky/settings/rofi/main"
mkdir -p "$CACHE_DIR"

# Get absolute path to this script so Rofi knows exactly what to call back
SCRIPT_PATH="$(realpath "$0")"

# Dynamic UI Injection (Leaves config.rasi absolutely pristine)
THEME_INJECTION='
mainbox { 
    children: [ inputbar, mode-switcher, message, listview ]; 
}
mode-switcher { 
    orientation: horizontal; 
    spacing: 10px; 
    background-color: transparent; 
}
button { 
    padding: 8px 12px; 
    border-radius: 8px; 
    background-color: @var-input-bg; 
    text-color: @var-text-def; 
    cursor: pointer; 
}
button selected { 
    background-color: @var-active-bg; 
    text-color: @var-text-active; 
}
listview { 
    fixed-height: true; 
}
'

# Execute Rofi with strictly scoped configurations
# Note the -markup-rows flag is required to render the <span alpha> tags
rofi -show combi \
     -modi "combi,drun,Dusky:${SCRIPT_PATH} --rofi-mode" \
     -combi-modi "drun,Dusky" \
     -combi-hide-mode-prefix true \
     -display-combi "󰜉 All" \
     -display-drun "󰀻 Apps" \
     -display-Dusky "󰒓 Dusky" \
     -drun-match-fields "name,generic" \
     -cache-dir "$CACHE_DIR" \
     -disable-history false \
     -max-history-size 1000 \
     -markup-rows \
     -theme-str "$THEME_INJECTION"
