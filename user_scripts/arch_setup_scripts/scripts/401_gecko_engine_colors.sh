#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Script: 500_firefox_matugenfox.sh
# Description: Zero-touch, permanent autonomous setup for MatugenFox
# Environment: Arch Linux / Hyprland (Firefox / Zen / LibreWolf / Floorp)
# -----------------------------------------------------------------------------

# --- Safety & Error Handling ---
set -euo pipefail
IFS=$'\n\t'

# Cleanly kill the background sudo keepalive on exit
trap '[[ -n "${KEEPALIVE_PID:-}" ]] && kill "$KEEPALIVE_PID" 2>/dev/null; printf "\n[INFO] Script exiting.\n"' EXIT
trap 'printf "\n[WARN] Script interrupted. Exiting.\n" >&2; exit 130' INT TERM

# --- Configuration Paths ---
readonly EXT_DIR="${HOME}/.config/firefox_extentions/matugenfox"
readonly XPI_PATH="${EXT_DIR}/matugenfox.xpi"
readonly HOST_PATH="${EXT_DIR}/matugenfox_host.py"
readonly EXT_ID="matugenfox@ubaid.com"

# --- Visual Styling ---
if command -v tput &>/dev/null && (( $(tput colors 2>/dev/null || echo 0) >= 8 )); then
    readonly C_RESET=$'\033[0m'
    readonly C_BOLD=$'\033[1m'
    readonly C_BLUE=$'\033[38;5;45m'
    readonly C_GREEN=$'\033[38;5;46m'
    readonly C_WARN=$'\033[38;5;214m'
    readonly C_ERR=$'\033[38;5;196m'
else
    readonly C_RESET='' C_BOLD='' C_BLUE='' C_GREEN='' C_WARN='' C_ERR=''
fi

# --- Logging Utilities ---
log_info()    { printf '%b[INFO]%b %s\n' "${C_BLUE}" "${C_RESET}" "$1"; }
log_success() { printf '%b[SUCCESS]%b %s\n' "${C_GREEN}" "${C_RESET}" "$1"; }
log_warn()    { printf '%b[WARNING]%b %s\n' "${C_WARN}" "${C_RESET}" "$1" >&2; }
die()         { printf '%b[ERROR]%b %s\n' "${C_ERR}" "${C_RESET}" "$1" >&2; exit 1; }

# --- Pre-flight Checks ---
preflight() {
    if ((EUID == 0)); then die 'Run as normal user, not Root.'; fi
    
    if [[ ! -d "$EXT_DIR" ]]; then
        die "Extension directory not found at $EXT_DIR. Check your dotfiles mapping."
    fi
    
    local missing_deps=()
    if ! command -v zip &>/dev/null; then missing_deps+=("zip"); fi
    if ! command -v jq &>/dev/null; then missing_deps+=("jq (required for safe policy merging)"); fi
    
    if ((${#missing_deps[@]} > 0)); then
        die "Missing required packages: ${missing_deps[*]}. Please install them."
    fi

    # Secure sudo caching for zero-touch flow
    log_info "Caching sudo credentials for uninterrupted deployment..."
    sudo -v || die "Sudo authentication failed."
    
    # Keep sudo alive in the background
    (while true; do sudo -n true 2>/dev/null; sleep 50; done) &
    KEEPALIVE_PID=$!
}

# --- Core Modules ---

package_extension() {
    log_info "Packaging local source files into MatugenFox .xpi..."
    
    cd "$EXT_DIR" || die "Failed to enter $EXT_DIR"
    rm -f "$XPI_PATH"
    
    if zip -r -q "$XPI_PATH" . \
        -x "*.git*" \
        -x "*.sh" \
        -x "matugenfox_host.py" \
        -x "config.json" \
        -x "*.xpi" \
        -x "Website Templates/*"; then
        log_success "Packaged $XPI_PATH successfully."
    else
        die "Failed to create the .xpi archive."
    fi
}

install_native_host() {
    log_info "Configuring MatugenFox Native Messaging Host..."
    
    chmod +x "$HOST_PATH"
    
    # Targets expanded for Arch Linux / AUR / Flatpak
    local targets=(
        "${HOME}/.mozilla/native-messaging-hosts"
        "${HOME}/.librewolf/native-messaging-hosts"
        "${HOME}/.zen/native-messaging-hosts"
        "${HOME}/.waterfox/native-messaging-hosts"
        "${HOME}/.floorp/native-messaging-hosts"
        "${HOME}/.var/app/io.github.zen_browser.zen/.zen/native-messaging-hosts"
        "${HOME}/.var/app/org.mozilla.firefox/.mozilla/native-messaging-hosts"
        "${HOME}/.var/app/io.gitlab.librewolf-community/.librewolf/native-messaging-hosts"
        "${HOME}/.var/app/one.ablaze.floorp/.floorp/native-messaging-hosts"
    )

    local installed=0
    for target_dir in "${targets[@]}"; do
        if [[ -d "$(dirname "$target_dir")" ]]; then
            mkdir -p "$target_dir"
            cat <<EOF > "${target_dir}/matugenfox.json"
{
  "name": "matugenfox",
  "description": "MatugenFox Native Messaging Host",
  "path": "${HOST_PATH}",
  "type": "stdio",
  "allowed_extensions": [
    "${EXT_ID}"
  ]
}
EOF
            installed=$((installed + 1))
        fi
    done

    if (( installed > 0 )); then
        log_success "Native Messaging Host wired to $installed browser profile directories."
    else
        log_warn "No browser profiles detected. Ensure you've launched your browser at least once."
    fi
}

deploy_enterprise_policy() {
    log_info "Deploying permanent Enterprise Policy for MatugenFox..."
    
    # Target standard paths PLUS user-level managed paths for Flatpaks
    local policy_dirs=(
        "/usr/lib/firefox/distribution"
        "/etc/firefox/policies"
        "/usr/lib/librewolf/distribution"
        "/etc/librewolf/policies"
        "/opt/zen-browser/distribution"
        "/usr/lib/zen-browser/distribution"
        "/etc/zen/policies"
        "/usr/lib/floorp/distribution"
        "/etc/floorp/policies"
        "/usr/lib/waterfox/distribution"
        "/etc/waterfox/policies"
        "${HOME}/.mozilla/managed"
        "${HOME}/.var/app/org.mozilla.firefox/.mozilla/managed"
        "${HOME}/.var/app/io.github.zen_browser.zen/.zen/managed"
    )

    local deployed=0
    for p_dir in "${policy_dirs[@]}"; do
        local parent_dir
        parent_dir="$(dirname "$p_dir")"
        
        if [[ -d "$parent_dir" ]]; then
            # If the path is under $HOME, no sudo needed; otherwise use sudo
            local cmd_prefix=""
            [[ "$p_dir" != "${HOME}"* ]] && cmd_prefix="sudo"
            
            $cmd_prefix mkdir -p "$p_dir"
            $cmd_prefix chmod 755 "$p_dir"
            
            local p_file="${p_dir}/policies.json"
            
            if [[ -f "$p_file" ]] && [[ -s "$p_file" ]]; then
                log_info "Safely merging policy into existing $p_file..."
                local tmp_json
                tmp_json=$(mktemp)
                
                # JQ setpath safely creates nested paths without overwriting existing data.
                # Prepending cat with $cmd_prefix ensures we can read the file even if locked to 600 root:root.
                if $cmd_prefix cat "$p_file" | jq --arg ext_id "$EXT_ID" --arg xpi_url "file://${XPI_PATH}" \
                    'setpath(["policies", "ExtensionSettings", $ext_id]; {"installation_mode": "normal_installed", "install_url": $xpi_url})' > "$tmp_json"; then
                    
                    $cmd_prefix mv "$tmp_json" "$p_file"
                    
                    # Prevent ownership vulnerability
                    if [[ -n "$cmd_prefix" ]]; then
                        $cmd_prefix chown root:root "$p_file"
                    fi
                    $cmd_prefix chmod 644 "$p_file"
                    deployed=$((deployed + 1))
                else
                    log_warn "Failed to safely parse $p_file. Skipping to prevent system corruption."
                    rm -f "$tmp_json"
                fi
            else
                log_info "Creating new policy file at $p_file..."
                $cmd_prefix tee "$p_file" > /dev/null <<EOF
{
  "policies": {
    "ExtensionSettings": {
      "${EXT_ID}": {
        "installation_mode": "normal_installed",
        "install_url": "file://${XPI_PATH}"
      }
    }
  }
}
EOF
                if [[ -n "$cmd_prefix" ]]; then
                    $cmd_prefix chown root:root "$p_file"
                fi
                $cmd_prefix chmod 644 "$p_file"
                deployed=$((deployed + 1))
            fi
        fi
    done

    if (( deployed == 0 )); then
        log_warn "No standard browser root found. Forcing creation at /usr/lib/firefox/distribution..."
        local p_dir="/usr/lib/firefox/distribution"
        local p_file="${p_dir}/policies.json"
        
        sudo mkdir -p "$p_dir"
        sudo chmod 755 "$p_dir"
        sudo tee "$p_file" > /dev/null <<EOF
{
  "policies": {
    "ExtensionSettings": {
      "${EXT_ID}": {
        "installation_mode": "normal_installed",
        "install_url": "file://${XPI_PATH}"
      }
    }
  }
}
EOF
        sudo chown root:root "$p_file"
        sudo chmod 644 "$p_file"
        deployed=$((deployed + 1))
    fi

    log_success "Enterprise policy successfully injected into $deployed location(s)."
}

finish_setup() {
    printf '%b%b' "${C_BOLD}" "${C_BLUE}"
    cat <<'BANNER'
   ╔═══════════════════════════════════════╗
   ║      MATUGENFOX SETUP COMPLETED       ║
   ║      Autonomous 0-Day Injection       ║
   ╚═══════════════════════════════════════╝
BANNER
    printf '%b\n' "${C_RESET}"
    log_success "MatugenFox is permanently provisioned."
    log_warn "Note: Ensure signature enforcement is disabled in your browser's about:config"
    log_warn "(xpinstall.signatures.required = false) if using an unsigned local .xpi file."
}

# --- Main Execution ---
main() {
    printf '\n%b>>> AUTONOMOUS DEPLOYMENT: MATUGENFOX%b\n' "${C_BLUE}" "${C_RESET}"
    
    preflight
    package_extension
    install_native_host
    deploy_enterprise_policy
    finish_setup
}

main "$@"
