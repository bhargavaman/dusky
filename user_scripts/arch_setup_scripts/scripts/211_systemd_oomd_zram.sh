#!/usr/bin/env bash
# =============================================================================
# Elite Arch Linux OOM Prevention & Compositor Shielding Configurator
# Target: Arch Linux Cutting-Edge (Kernel 7.1+, Bash 5.3+, systemd 261+)
# Scope: Platinum Grade. High-Performance Userspace OOM Reclaim.
# =============================================================================

set -euo pipefail

readonly SCRIPT_NAME="${0##*/}"
readonly SELF_PATH="$(realpath -e -- "${BASH_SOURCE[0]}")"

# --- Formatting ---
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    C_RESET=$'\033[0m'
    C_GREEN=$'\033[1;32m'
    C_BLUE=$'\033[1;34m'
    C_RED=$'\033[1;31m'
    C_YELLOW=$'\033[1;33m'
    C_BOLD=$'\033[1m'
else
    C_RESET='' C_GREEN='' C_BLUE='' C_RED='' C_YELLOW='' C_BOLD=''
fi

log_info()    { printf '%s[INFO]%s %s\n'  "$C_BLUE"   "$C_RESET" "$1"; }
log_success() { printf '%s[OK]%s %s\n'    "$C_GREEN"  "$C_RESET" "$1"; }
log_warn()    { printf '%s[WARN]%s %s\n'  "$C_YELLOW" "$C_RESET" "$1"; }
log_error()   { printf '%s[ERROR]%s %s\n' "$C_RED"    "$C_RESET" "$1" >&2; }
die()         { log_error "$1"; exit "${2:-1}"; }

print_help() {
    cat <<HELP
${C_BOLD}Usage:${C_RESET} ${SCRIPT_NAME} [OPTIONS]

  --dry-run, -n        Print the generated configuration and exit without applying
  --help, -h           Show this help menu
HELP
}

usage_error() { log_error "$1"; print_help >&2; exit 2; }

# --- 1. CLI Parsing ---
declare -i DRY_RUN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run|-n)        DRY_RUN=1; shift ;;
        --help|-h)           print_help; exit 0 ;;
        *)                   log_warn "Ignoring unknown argument: $1"; shift ;;
    esac
done

# --- 2. Privilege Escalation ---
if [[ $EUID -ne 0 && $DRY_RUN -eq 0 ]]; then
    log_info "Root privileges required. Escalating..."
    command -v sudo >/dev/null 2>&1 || die "'sudo' is not available."
    exec sudo -- /usr/bin/bash "$SELF_PATH" "$@"
fi

log_info "Initializing Platinum systemd-oomd 261 optimizer..."

# =============================================================================
# --- 3. PURGE LEGACY EARLYOOM & BASH SHIELD ---
# =============================================================================
log_info "Scanning and removing legacy earlyoom/bash shield configurations..."

legacy_configs=(
    "/etc/default/earlyoom"
    "/usr/local/bin/compositor-oom-shield.sh"
    "/etc/systemd/system/compositor-oom-shield.service"
    "/etc/systemd/oomd.conf.d/99-zram-tuning.conf"
    "/etc/systemd/system/user@.service.d/99-oomd-kill-policy.conf"
    "/etc/systemd/system/user-.slice.d/99-oomd.conf"
    "/etc/systemd/user/session.slice.d/99-oomd-avoid.conf"
    "/etc/systemd/user/scope.d/99-oom-adjust.conf"
    "/etc/systemd/user/wayland-wm@.service.d/99-oomd-avoid.conf"
    "/usr/local/bin/hyprland-oom-shield.sh"
    "/etc/systemd/system/hyprland-oom-shield.service"
)

for conf in "${legacy_configs[@]}"; do
    if [[ -f "$conf" || -L "$conf" ]]; then
        if (( DRY_RUN == 0 )); then
            # Stop services if they are running
            if [[ "$conf" == *compositor-oom-shield.service ]]; then
                systemctl disable --now compositor-oom-shield.service >/dev/null 2>&1 || true
            elif [[ "$conf" == *hyprland-oom-shield.service ]]; then
                systemctl disable --now hyprland-oom-shield.service >/dev/null 2>&1 || true
            fi
            rm -f "$conf"
            log_success "Cleaned up legacy file: ${conf}"
        else
            log_info "Would clean up legacy file: ${conf}"
        fi
    fi
done

if (( DRY_RUN == 0 )); then
    # Purge earlyoom package if installed
    if command -v earlyoom >/dev/null 2>&1; then
        log_info "Uninstalling legacy earlyoom package..."
        pacman -Rns --noconfirm earlyoom >/dev/null 2>&1 || log_warn "Failed to remove earlyoom package."
    fi
else
    log_info "Would uninstall earlyoom package if present."
fi

# =============================================================================
# --- 4. SYSTEMD-OOMD CONFIGURATION (SYSTEMD 261+) ---
# =============================================================================
log_info "Configuring native systemd-oomd rules for ZRAM and UWSM isolation..."

tmp_oomrule="$(umask 077 && mktemp)"
tmp_app_slice="$(umask 077 && mktemp)"
tmp_session_slice="$(umask 077 && mktemp)"
tmp_wayland_wm="$(umask 077 && mktemp)"
trap 'rm -f "$tmp_oomrule" "$tmp_app_slice" "$tmp_session_slice" "$tmp_wayland_wm"' EXIT

# Generate ZRAM-aware OOM rule
cat > "$tmp_oomrule" <<'OOMRULE'
[Rule]
MemoryPressureAbove=10%
SwapUsageMax=80%
Action=kill-by-pgscan
LastingSec=2s
OOMRULE

# Bind to user applications via app-graphical.slice (UWSM app target)
cat > "$tmp_app_slice" <<'APPSLICE'
[Slice]
OOMRules=10-zram-desktop
APPSLICE

# Protect the graphical session slice
cat > "$tmp_session_slice" <<'SESSIONSLICE'
[Slice]
ManagedOOMPreference=avoid
SESSIONSLICE

# =============================================================================
# --- 5. SYSTEM-LEVEL OOM SCORE INHERITANCE FIX ---
# =============================================================================
# systemd --user cannot set a child's OOMScoreAdjust lower than its own.
# By default, user@.service has OOMScoreAdjust=100.
# We must set user@.service to -500 so it has privileges to spawn critical daemons at -500.
# We simultaneously set DefaultOOMScoreAdjust=200 so normal user apps don't inherit -500.

tmp_user_service="$(umask 077 && mktemp)"
tmp_user_conf="$(umask 077 && mktemp)"
trap 'rm -f "$tmp_oomrule" "$tmp_app_slice" "$tmp_session_slice" "$tmp_wayland_wm" "$tmp_user_service" "$tmp_user_conf"' EXIT

cat > "$tmp_user_service" <<'USERSERVICE'
[Service]
OOMScoreAdjust=-500
USERSERVICE

cat > "$tmp_user_conf" <<'USERCONF'
[Manager]
DefaultOOMScoreAdjust=200
USERCONF

# Failsafe: Protect critical session components from kernel OOM killer
# and prevent systemd from killing them if a child dies
cat > "$tmp_wayland_wm" <<'WAYLANDWM'
[Service]
OOMScoreAdjust=-500
OOMPolicy=continue
WAYLANDWM

critical_services=(
    "wayland-wm@.service"
    "wayland-wm-app-daemon.service"
    "wayland-wm-env@.service"
    "wayland-session-bindpid@.service"
    "wireplumber.service"
    "pipewire.service"
    "pipewire-pulse.service"
    "xdg-desktop-portal.service"
    "xdg-desktop-portal-gtk.service"
    "xdg-desktop-portal-hyprland.service"
    "dbus-broker.service"
    "dbus.service"
    "mako.service"
)

system_critical_services=(
    "systemd-logind.service"
    "NetworkManager.service"
    "polkit.service"
    "systemd-resolved.service"
    "systemd-timesyncd.service"
    "getty@.service"
    "udisks2.service"
    "systemd-userdbd.service"
)

if (( DRY_RUN == 1 )); then
    log_info "DRY RUN EXECUTED."
    echo -e "\n${C_BOLD}[ /etc/systemd/oomd/rules.d/10-zram-desktop.oomrule ]${C_RESET}"
    cat "$tmp_oomrule"
    echo -e "\n${C_BOLD}[ /etc/systemd/user/app-graphical.slice.d/10-oomd.conf ]${C_RESET}"
    cat "$tmp_app_slice"
    echo -e "\n${C_BOLD}[ /etc/systemd/user/session-graphical.slice.d/10-oomd-avoid.conf ]${C_RESET}"
    cat "$tmp_session_slice"
    
    echo -e "\n${C_BOLD}[ Shield applied to critical services: ]${C_RESET}"
    for svc in "${critical_services[@]}"; do
        echo "/etc/systemd/user/${svc}.d/10-oom-shield.conf"
    done
    cat "$tmp_wayland_wm"
    exit 0
fi

install_file() {
    local src="$1" dest="$2" perm="$3"
    local dir
    dir="$(dirname "$dest")"
    if [[ ! -d "$dir" ]]; then
        install -d -m 0755 "$dir"
    fi
    if [[ -f "$dest" ]] && cmp -s "$src" "$dest"; then
        log_info "${dest} is already up to date."
        return 1
    else
        install -m "$perm" "$src" "$dest"
        log_success "Updated ${dest}"
        return 0
    fi
}

install_file "$tmp_oomrule" "/etc/systemd/oomd/rules.d/10-zram-desktop.oomrule" "0644" || true
install_file "$tmp_app_slice" "/etc/systemd/user/app-graphical.slice.d/10-oomd.conf" "0644" || true
install_file "$tmp_session_slice" "/etc/systemd/user/session-graphical.slice.d/10-oomd-avoid.conf" "0644" || true
install_file "$tmp_user_service" "/etc/systemd/system/user@.service.d/10-oom-score.conf" "0644" || true
install_file "$tmp_user_conf" "/etc/systemd/user.conf.d/10-oom-default.conf" "0644" || true

for svc in "${critical_services[@]}"; do
    install_file "$tmp_wayland_wm" "/etc/systemd/user/${svc}.d/10-oom-shield.conf" "0644" || true
done

for svc in "${system_critical_services[@]}"; do
    install_file "$tmp_wayland_wm" "/etc/systemd/system/${svc}.d/10-oom-shield.conf" "0644" || true
done

# =============================================================================
# --- 5. ENABLE AND START NATIVE SYSTEMD-OOMD ---
# =============================================================================
log_info "Restoring and activating native systemd-oomd service..."
systemctl unmask systemd-oomd.service systemd-oomd.socket >/dev/null 2>&1 || true
systemctl enable systemd-oomd.service systemd-oomd.socket >/dev/null 2>&1 || log_warn "Failed to enable systemd-oomd."
systemctl restart systemd-oomd.service systemd-oomd.socket >/dev/null 2>&1 || log_warn "Failed to restart systemd-oomd."

log_info "Reloading systemd daemon to ingest OOM policies..."
systemctl daemon-reload >/dev/null 2>&1 || true

log_info "Reloading active user managers..."
declare -a uids=()
while read -r line; do
    if [[ "$line" =~ user@([0-9]+)\.service ]]; then
        uids+=("${BASH_REMATCH[1]}")
    fi
done < <(systemctl list-units --type=service --state=active --plain 'user@*.service' 2>/dev/null || true)

for uid in "${uids[@]:-}"; do
    user="$(id -un "$uid" 2>/dev/null || true)"
    [[ -z "$user" ]] && continue
    if systemctl --user -M "${user}@" daemon-reload >/dev/null 2>&1; then
        log_success "Reloaded user manager for ${user}."
    fi
done

log_success "Platinum OOM architecture successfully deployed via systemd 261."
exit 0
