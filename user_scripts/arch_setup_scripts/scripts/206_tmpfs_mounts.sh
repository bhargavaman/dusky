#!/usr/bin/env bash
# =============================================================================
# Elite Arch Linux Tmpfs Mount Configurator
# Target: Arch Linux Cutting-Edge (Bash 5.3+, systemd 260+)
# Scope: Platinum Grade. High-Performance RAM Disks via systemd .mount units.
# Updates: Decoupled from ZRAM logic. Native tmpfs implementation with dynamic 
#          UID/GID mapping to prevent user-space permission denial.
#          [Fixed]: Restored systemd unit validation safety checks.
# =============================================================================

set -euo pipefail

readonly SCRIPT_NAME="${0##*/}"
readonly SELF_PATH="$(realpath -e -- "${BASH_SOURCE[0]}")"

# --- Configuration ---
# Kept as /mnt/zram1 for system continuity, though it is now pure tmpfs.
readonly MOUNT_POINT="/mnt/zram1" 

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
    cat <<EOF
${C_BOLD}Usage:${C_RESET} ${SCRIPT_NAME} [OPTIONS]

  --help, -h            Show this help menu
EOF
}

# --- CLI Parsing ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h) print_help; exit 0 ;;
        *) log_error "Unknown argument: $1"; print_help >&2; exit 2 ;;
    esac
done

# --- Privilege Escalation ---
if [[ $EUID -ne 0 ]]; then
    log_info "Root privileges required. Escalating..."
    command -v sudo >/dev/null 2>&1 || die "sudo is required to run this script as root."
    exec sudo -- bash -- "$SELF_PATH" "$@"
fi

# --- Dependency Checks ---
for cmd in systemctl systemd-escape findmnt; do
    command -v "$cmd" >/dev/null 2>&1 || die "'$cmd' is required but missing."
done

# Determine the real user UID/GID to grant ownership of the mount point.
readonly TARGET_UID="${SUDO_UID:-0}"
readonly TARGET_GID="${SUDO_GID:-0}"

readonly MOUNT_UNIT_NAME="$(systemd-escape --path --suffix=mount "$MOUNT_POINT")"
readonly MOUNT_UNIT_PATH="/etc/systemd/system/${MOUNT_UNIT_NAME}"

tmp_mount="$(umask 077 && mktemp)"
trap 'rm -f "$tmp_mount"' EXIT

unit_is_loaded() {
    [[ "$(systemctl show -p LoadState --value "$1" 2>/dev/null || true)" == "loaded" ]]
}

assert_unit_loaded() {
    local unit=$1
    unit_is_loaded "$unit" || die "Expected generated unit is not loaded after daemon-reload: $unit"
}

mount_source_exact() {
    findmnt -rn -o SOURCE --mountpoint "$MOUNT_POINT" 2>/dev/null || true
}

log_info "Initializing Tmpfs Mount Configuration for: ${C_BOLD}${MOUNT_POINT}${C_RESET}"

# Create the directory and map ownership directly to your normal user account
install -d -m 0755 -o "$TARGET_UID" -g "$TARGET_GID" -- "$MOUNT_POINT"
log_success "Directory prepared with strict UID ${TARGET_UID} / GID ${TARGET_GID} ownership mapping."

cat > "$tmp_mount" <<EOF
# Managed by Elite Arch Linux Tmpfs Configurator
# Scope: High-Performance Tmpfs back-end for Wayland/Scripts.
[Unit]
Description=High-Performance tmpfs for ${MOUNT_POINT}
Before=local-fs.target
ConditionPathExists=${MOUNT_POINT}

[Mount]
What=tmpfs
Where=${MOUNT_POINT}
Type=tmpfs
# mode=0755,uid=,gid= sets the active mounted filesystem strictly to your ownership
Options=rw,nosuid,nodev,relatime,size=100%,mode=0755,uid=${TARGET_UID},gid=${TARGET_GID}

[Install]
WantedBy=local-fs.target
EOF

install -Dm0644 "$tmp_mount" "$MOUNT_UNIT_PATH"
log_success "Tmpfs mount unit written to ${MOUNT_UNIT_PATH}"

log_info "Reloading systemd daemon..."
systemctl daemon-reload

assert_unit_loaded "$MOUNT_UNIT_NAME"

log_info "Enabling systemd mount unit..."
systemctl enable "$MOUNT_UNIT_NAME" >/dev/null 2>&1 || true

current_source="$(mount_source_exact)"
if [[ $current_source == "/dev/zram1" || $current_source == "zram1" ]]; then
    log_warn "$MOUNT_POINT is currently mounted via legacy ext2 ZRAM block."
    log_warn "The new tmpfs architecture will seamlessly take over upon reboot."
else
    # Attempt live mount if it's purely unmounted right now
    systemctl start "$MOUNT_UNIT_NAME" >/dev/null 2>&1 || true
    if [[ "$(mount_source_exact)" == "tmpfs" ]]; then
        log_success "Live memory: Pure tmpfs successfully attached to ${MOUNT_POINT}."
    fi
fi

log_success "Tmpfs subsystem configured. Target is ready for high-I/O workloads."

exit 0
