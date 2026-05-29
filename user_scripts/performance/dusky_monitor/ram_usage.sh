#!/usr/bin/env bash
# ============================================================================
# Platinum-Grade RAM Forensics — Arch Linux + Hyprland 0.55+ / Kernel 7.x
# ============================================================================
# Covers every known RAM sink on a modern Wayland/Hyprland desktop:
#   • Correct full /proc/meminfo accounting (all kernel 7.x fields)
#   • Race-condition immune smaps_rollup PSS engine
#   • Hyprland-specific IPC diagnostics via JSON (jq) & Signature
#   • Transparent Hugepage (THP) analysis
#   • ZRAM / ZSWAP efficiency & Virtual Overcommit Pressure
#   • Wayland/tmpfs shared memory & XDG_RUNTIME sockets
#   • Universal DMA-BUF GPU buffers (Kernel 6.x and 7.x formats)
#   • Kernel slab leak detection
#   • Hyprland Headless / Render Leak known vectors & OOM History
# ============================================================================

set -euo pipefail

# ── 1. PRIVILEGE ESCALATION & ENVIRONMENT ───────────────────────────────────
if [[ "$EUID" -ne 0 ]]; then
    echo -e "\e[1;33m[!] Elevated privileges required. Auto-elevating...\e[0m"
    exec sudo ORIGINAL_USER="$USER" bash "$0" "$@"
fi

TARGET_USER="${ORIGINAL_USER:-${SUDO_USER:-$USER}}"
if [[ "$TARGET_USER" == "root" ]]; then
    TARGET_HOME="/root"
else
    TARGET_HOME=$(getent passwd "$TARGET_USER" | cut -d: -f6)
fi

REPORT_DIR="$TARGET_HOME/Documents/logs/ram_audit"
mkdir -p "$REPORT_DIR"
chown -R "$TARGET_USER":"$TARGET_USER" "$TARGET_HOME/Documents/logs" 2>/dev/null || true
REPORT="$REPORT_DIR/report_$(date +%Y%m%d_%H%M%S).md"

# ── 2. DEPENDENCY CHECK ─────────────────────────────────────────────────────
MISSING_PKGS=()
command -v zramctl  >/dev/null 2>&1 || MISSING_PKGS+=("util-linux")
command -v slabtop  >/dev/null 2>&1 || MISSING_PKGS+=("procps-ng")
command -v jq       >/dev/null 2>&1 || MISSING_PKGS+=("jq")

if [[ ${#MISSING_PKGS[@]} -gt 0 ]]; then
    echo -e "\e[1;34m[*] Missing packages: ${MISSING_PKGS[*]}. Installing...\e[0m"
    if [[ "$TARGET_USER" != "root" ]] && command -v paru >/dev/null 2>&1; then
        sudo -u "$TARGET_USER" paru -S --noconfirm --needed "${MISSING_PKGS[@]}"
    elif [[ "$TARGET_USER" != "root" ]] && command -v yay >/dev/null 2>&1; then
        sudo -u "$TARGET_USER" yay -S --noconfirm --needed "${MISSING_PKGS[@]}"
    else
        pacman -S --noconfirm --needed "${MISSING_PKGS[@]}" || true
    fi
fi

# ── 3. HELPERS ───────────────────────────────────────────────────────────────

get_mem() {
    local val
    val=$(awk -v key="$1" '$1 == key ":" {print $2; exit}' /proc/meminfo)
    echo "${val:-0}"
}

to_mb() {
    local val="${1:-0}"
    awk "BEGIN {printf \"%.0f\", $val / 1024}"
}

pss_table() {
    local top_n="${1:-20}"
    local tmp
    tmp=$(mktemp)
    
    # Subshell to protect against SIGPIPE crashes when head closes the stream
    (
        set +e +o pipefail
        for pid_dir in /proc/[0-9]*/; do
            local pid="${pid_dir//[^0-9]/}"
            [[ -z "$pid" ]] && continue
            local rollup="${pid_dir}smaps_rollup"
            
            # Safe extraction: process might die mid-read.
            local comm
            comm=$(cat "${pid_dir}comm" 2>/dev/null || echo "?")
            comm="${comm:0:20}" 
            
            local stats
            if ! stats=$(awk '/^Pss:/ {pss+=$2} /^Private_Clean:/ {pc+=$2} /^Private_Dirty:/ {pd+=$2} /^Rss:/ {rss+=$2} /^Swap:/ {swap+=$2} END {print pc+pd, pss+0, rss+0, swap+0}' "$rollup" 2>/dev/null); then
                continue
            fi
            
            [[ -z "$stats" ]] && continue
            read -r uss pss rss swap <<< "$stats"
            printf '%d\t%s\t%d\t%d\t%d\t%d\n' "$pid" "$comm" "$uss" "$pss" "$rss" "$swap"
        done | sort -t$'\t' -k4 -rn | head -n "$top_n" > "$tmp"
    )

    awk -F'\t' 'BEGIN {
        print "| PID | COMMAND | USS (MB) | PSS (MB) | RSS (MB) | SWAP (MB) |"
        print "|---|---|---|---|---|---|"
    }
    {
        printf "| %d | %s | %.1f | %.1f | %.1f | %.1f |\n", $1, $2, $3/1024, $4/1024, $5/1024, $6/1024
    }' "$tmp"
    
    rm -f "$tmp"
}

# ── 4. FORENSICS ─────────────────────────────────────────────────────────────
echo -e "\e[1;32m[*] Commencing Deep Kernel RAM Analysis (Hyprland + Arch Linux)...\e[0m"

{
echo "# Platinum System RAM Forensics Report — Hyprland Edition"
echo "**Date:** $(date)"
echo "**Kernel:** $(uname -r)"
echo "**Host:** $(hostname)"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — COMPLETE /proc/meminfo ACCOUNTING
# ─────────────────────────────────────────────────────────────────────────────
echo "## 1. Complete Memory Accounting (Kernel Absolute Truth)"
echo "---"
echo '> **Understanding this section:** This is the absolute low-level truth of your RAM. Tools like `htop` group these numbers together unpredictably. Here, you see exactly what the kernel is allocating.'
echo '> * **AnonPages:** Your running apps, browsers, and game memory.'
echo '> * **Cached:** Files kept in RAM to make the system fast. *This is automatically freed if apps need more RAM.*'
echo '> * **Shmem:** Shared Memory. On Wayland, this includes the literal pixel buffers of your visible windows.'
echo ""

MEM_TOTAL=$(get_mem MemTotal)
MEM_FREE=$(get_mem MemFree)
MEM_AVAIL=$(get_mem MemAvailable)
BUFFERS=$(get_mem Buffers)
CACHED=$(get_mem Cached)
SWAP_CACHED=$(get_mem SwapCached)
ANON_PAGES=$(get_mem AnonPages)
SHMEM=$(get_mem Shmem)
MAPPED=$(get_mem Mapped)
UNEVICTABLE=$(get_mem Unevictable)

SLAB=$(get_mem Slab)
S_RECLAIMABLE=$(get_mem SReclaimable)
S_UNRECLAIM=$(get_mem SUnreclaim)
K_RECLAIMABLE=$(get_mem KReclaimable)
K_STACK=$(get_mem KernelStack)
PAGE_TABLES=$(get_mem PageTables)
SEC_PAGE_TABLES=$(get_mem SecPageTables)
PERCPU=$(get_mem Percpu)
VMALLOC_USED=$(get_mem VmallocUsed)

ANON_HUGE=$(get_mem AnonHugePages)
SHMEM_HUGE=$(get_mem ShmemHugePages)
FILE_HUGE=$(get_mem FileHugePages)

SWAP_TOTAL=$(get_mem SwapTotal)
SWAP_FREE=$(get_mem SwapFree)
ZSWAP=$(get_mem Zswap)
ZSWAPPED=$(get_mem Zswapped)
DIRTY=$(get_mem Dirty)
WRITEBACK=$(get_mem Writeback)
COMMITTED=$(get_mem Committed_AS)
COMMIT_LIMIT=$(get_mem CommitLimit)
HW_CORRUPTED=$(get_mem HardwareCorrupted)

ACCOUNTED_KB=$(( ANON_PAGES + BUFFERS + CACHED + K_RECLAIMABLE + K_STACK \
               + PAGE_TABLES + SEC_PAGE_TABLES + SWAP_CACHED + S_UNRECLAIM \
               + UNEVICTABLE + PERCPU + VMALLOC_USED + MEM_FREE ))
UNACCOUNTED_KB=$(( MEM_TOTAL - ACCOUNTED_KB ))

echo "\`\`\`text"
printf "%-45s %8s MB\n" "Total Usable RAM (MemTotal):"       "$(to_mb $MEM_TOTAL)"
printf "%-45s %8s MB\n" "Truly Available (MemAvailable):"    "$(to_mb $MEM_AVAIL)"
printf "%-45s %8s MB\n" "Raw Free (MemFree):"                "$(to_mb $MEM_FREE)"
echo ""
echo "[ NAMED ALLOCATIONS ]"
printf "%-45s %8s MB\n" "  Userspace Anon (AnonPages):"        "$(to_mb $ANON_PAGES)"
printf "%-45s %8s MB\n" "  Page Cache / File-backed (Cached):" "$(to_mb $CACHED)"
printf "%-45s %8s MB\n" "  Shared Memory/Tmpfs (Shmem):"       "$(to_mb $SHMEM)"
printf "%-45s %8s MB\n" "  Buffer Cache (Buffers):"            "$(to_mb $BUFFERS)"
printf "%-45s %8s MB\n" "  Swap Cache (SwapCached):"           "$(to_mb $SWAP_CACHED)"
printf "%-45s %8s MB\n" "  Mapped (file+anon mmap'd):"         "$(to_mb $MAPPED)"
printf "%-45s %8s MB\n" "  Unevictable / Mlocked:"             "$(to_mb $UNEVICTABLE)"
echo ""
echo "[ KERNEL STRUCTURES ]"
printf "%-45s %8s MB\n" "  Slab Total (Slab):"                 "$(to_mb $SLAB)"
printf "%-45s %8s MB\n" "    └─ Reclaimable (KReclaimable):"   "$(to_mb $K_RECLAIMABLE)"
printf "%-45s %8s MB\n" "    └─ Unreclaimable (SUnreclaim):"   "$(to_mb $S_UNRECLAIM)"
printf "%-45s %8s MB\n" "  Kernel Stacks (KernelStack):"       "$(to_mb $K_STACK)"
printf "%-45s %8s MB\n" "  Page Tables (PageTables):"          "$(to_mb $PAGE_TABLES)"
printf "%-45s %8s MB\n" "  Secondary Page Tables (KVM/arm):"   "$(to_mb $SEC_PAGE_TABLES)"
printf "%-45s %8s MB\n" "  Per-CPU Allocations (Percpu):"      "$(to_mb $PERCPU)"
printf "%-45s %8s MB\n" "  vmalloc Used (VmallocUsed):"        "$(to_mb $VMALLOC_USED)"
echo ""
echo "[ SUMMARY ]"
printf "%-45s %8s MB\n" "  All Named Fields (Accounted):"     "$(to_mb $ACCOUNTED_KB)"
printf "%-45s %8s MB\n" "  Unaccounted (firmware/drivers):"   "$(to_mb $UNACCOUNTED_KB)"
echo "\`\`\`"

echo "> **Diagnostic Note:**"
echo "> * Unaccounted < 300 MB → Healthy (Standard firmware hardware-reserved limits)."
echo '> * Unaccounted > 600 MB → **ALERT:** A GPU driver (e.g., `amdgpu` GTT) or a rogue kernel module is leaking anonymous memory bypassing tracking.'
echo "> * SUnreclaim > 500 MB → **ALERT:** Kernel slab leak (See Section 7)."
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — COMMIT PRESSURE & VIRTUAL OVERCOMMIT
# ─────────────────────────────────────────────────────────────────────────────
echo "## 2. Virtual Memory Commit Pressure"
echo "---"
echo "> **Understanding this section:** Shows if your system is overcommitting memory and risking an Out-Of-Memory (OOM) kill."
echo ""
echo "\`\`\`text"
printf "%-45s %8s MB\n" "  CommitLimit:"   "$(to_mb $COMMIT_LIMIT)"
printf "%-45s %8s MB\n" "  Committed_AS:"  "$(to_mb $COMMITTED)"
printf "%-45s %8s MB\n" "  Dirty pages:"   "$(to_mb $DIRTY)"
printf "%-45s %8s MB\n" "  In writeback:"  "$(to_mb $WRITEBACK)"
[[ $HW_CORRUPTED -gt 0 ]] && printf "%-45s %8s MB\n" "  *** HW CORRUPTED RAM ***:" "$(to_mb $HW_CORRUPTED)"
echo "\`\`\`"
OVERCOMMIT=$(( COMMITTED * 100 / (COMMIT_LIMIT > 0 ? COMMIT_LIMIT : 1) ))
echo "- **Commit ratio:** ${OVERCOMMIT}%  *(> 90% means swap pressure likely)*"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — ZRAM & SWAP
# ─────────────────────────────────────────────────────────────────────────────
echo "## 3. Compressed RAM (ZRAM / ZSWAP)"
echo "---"
echo '> **Understanding this section:** ZRAM/ZSWAP acts as a hyper-fast SSD inside your RAM by compressing inactive memory. The "TOTAL" column shows exactly how much physical RAM this compression pool is eating.'
echo ""
if zramctl --raw 2>/dev/null | grep -q '/dev/zram'; then
    echo "\`\`\`text"
    zramctl --output NAME,ALGORITHM,DISKSIZE,DATA,COMPR,TOTAL,STREAMS 2>/dev/null || \
    zramctl --output NAME,ALGORITHM,DISKSIZE,DATA,COMPR,TOTAL 2>/dev/null
    echo "\`\`\`"
else
    echo "ZRAM is not active."
fi
echo ""
if [[ "$ZSWAP" -gt 0 ]]; then
    echo "- **Zswap is active:** \`$(to_mb $ZSWAP) MB\` physical pool, storing \`$(to_mb $ZSWAPPED) MB\` of decompressed data."
    echo "- **Zswap settings:**"
    echo "\`\`\`text"
    echo "  Enabled: $(cat /sys/module/zswap/parameters/enabled 2>/dev/null || echo 'N/A')"
    echo "  Compressor: $(cat /sys/module/zswap/parameters/compressor 2>/dev/null || echo 'N/A')"
    echo "  Pool Allocator: $(cat /sys/module/zswap/parameters/zpool 2>/dev/null || echo 'N/A')"
    echo "  Max Pool Limit: $(cat /sys/module/zswap/parameters/max_pool_percent 2>/dev/null || echo 'N/A')"
    echo "\`\`\`"
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — NATIVE PSS TABLE
# ─────────────────────────────────────────────────────────────────────────────
echo "## 4. True Process Isolation (Top 25 by PSS)"
echo "---"
echo '> **Understanding this section:** Standard system monitors look at `RSS` which wildly exaggerates memory usage by double-counting shared libraries. This table uses `PSS` (Proportional Set Size) which perfectly splits shared memory to give you the truest representation of what apps are heavy.'
echo '> * **USS:** Memory 100% unique to this app. If you kill the app, this exact amount of RAM is freed instantly.'
echo '> * **PSS:** The most accurate metric. USS plus the fair mathematical share of shared libraries for this app.'
echo ""
pss_table 25
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — HYPRLAND-SPECIFIC DIAGNOSTICS
# ─────────────────────────────────────────────────────────────────────────────
echo "## 5. Wayland & Hyprland Diagnostics"
echo "---"
echo '> **Understanding this section:** Interrogates the Wayland compositor directly (using JSON) to see if window surfaces, unmapped layers, or headless monitors are building up in the background.'
echo ""
HYPR_PID=$(pgrep -x Hyprland 2>/dev/null | head -1 || true)
if [[ -n "$HYPR_PID" ]]; then
    HYPR_USER=$(ps -o user= -p "$HYPR_PID" 2>/dev/null | tr -d ' ' || true)
    HYPR_UID=$(id -u "$HYPR_USER" 2>/dev/null || echo 1000)
    HYPR_RSS=$(awk '/^VmRSS:/{print $2}' /proc/"$HYPR_PID"/status 2>/dev/null || echo 0)
    HYPR_PSS=$(awk '/^Pss:/{sum+=$2} END{print sum+0}' /proc/"$HYPR_PID"/smaps_rollup 2>/dev/null || echo 0)
    
    echo "- **Hyprland PID:** \`$HYPR_PID\`"
    echo "- **Session User:** \`$HYPR_USER\` (UID: $HYPR_UID)"
    echo "- **Hyprland RSS:** $(to_mb $HYPR_RSS) MB"
    echo "- **Hyprland PSS:** $(to_mb $HYPR_PSS) MB"
    
    echo ""
    # Inject Signature to bypass hyprctl IPC blocks safely
    HYPR_SIG=$(ls -1 /run/user/"$HYPR_UID"/hypr/ 2>/dev/null | head -1 || true)
    HYPR_ENV="XDG_RUNTIME_DIR=/run/user/$HYPR_UID"
    [[ -n "$HYPR_SIG" ]] && HYPR_ENV="$HYPR_ENV HYPRLAND_INSTANCE_SIGNATURE=$HYPR_SIG"

    echo "### Open Clients (Windows)"
    CLIENTS_OUT=$(sudo -u "$HYPR_USER" env $HYPR_ENV hyprctl clients -j 2>/dev/null | jq -r '.[]? | "- **\(.class)** (`\(.address)`) — Size: \(.size[0])x\(.size[1]), Mapped: \(.mapped)"' 2>/dev/null || true)
    [[ -n "$CLIENTS_OUT" ]] && echo "$CLIENTS_OUT" || echo "  None or unavailable"
    
    echo ""
    echo "### Layer-shell Surfaces (Waybar, overlays, backgrounds)"
    LAYERS_OUT=$(sudo -u "$HYPR_USER" env $HYPR_ENV hyprctl layers -j 2>/dev/null | jq -r 'to_entries[]? | .value.levels[]? | .[]? | "- Layer **\(.namespace)** (`\(.address)`) — Size: \(.w)x\(.h)"' 2>/dev/null || true)
    [[ -n "$LAYERS_OUT" ]] && echo "$LAYERS_OUT" || echo "  None or unavailable"
    
    echo ""
    echo "### Active Monitors"
    MONS_OUT=$(sudo -u "$HYPR_USER" env $HYPR_ENV hyprctl monitors -j 2>/dev/null | jq -r '.[]? | "- **\(.name)** (`\(.description)`) — \(.width)x\(.height)@\(.refreshRate)Hz, Scale: \(.scale)"' 2>/dev/null || true)
    [[ -n "$MONS_OUT" ]] && echo "$MONS_OUT" || echo "  None or unavailable"
else
    echo "**Hyprland process not found.**"
fi

echo ""
echo "### Wayland Compositor & Daemon RSS Summary"
echo "| Process | PID | RSS (MB) |"
echo "|---|---|---|"
PROCS=(Hyprland waybar xdg-desktop-portal xdg-desktop-portal-hyprland pipewire wireplumber hypridle hyprlock swaybg swww-daemon mako dunst fnott eww ags)
for proc in "${PROCS[@]}"; do
    pid=$(pgrep -x "$proc" 2>/dev/null | head -1 || true)
    if [[ -n "$pid" ]]; then
        rss=$(awk '/^VmRSS:/{print $2}' /proc/"$pid"/status 2>/dev/null || echo 0)
        printf "| %s | %s | %s |\n" "$proc" "$pid" "$(to_mb $rss)"
    fi
done
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6 — SHARED MEMORY / TMPFS
# ─────────────────────────────────────────────────────────────────────────────
echo "## 6. Shared Memory & Tmpfs"
echo "---"
echo '> **Understanding this section:** Temporary filesystems (tmpfs) and `/dev/shm` live entirely inside your physical RAM. If an app crashes but fails to delete its shared memory buffer, it creates a silent memory leak here.'
echo ""
echo "### Overall Tmpfs Mounts"
echo "\`\`\`text"
df -h -t tmpfs 2>/dev/null | awk 'NR==1 || ($3+0 > 0 || $3 ~ /[0-9]/)' || true
echo "\`\`\`"
echo ""
echo "### /dev/shm Contents (Top 20 by Size)"
echo "\`\`\`text"
ls -laSh /dev/shm/ 2>/dev/null | head -20 || true
echo "\`\`\`"
echo '> **Note:** If `Hyprland` PSS is high AND `/dev/shm` is huge, a rogue Wayland client is leaking `wl_shm` texture buffers.'
echo ""
echo "### XDG_RUNTIME_DIR Socket Accounting"
for uid_dir in /run/user/*/; do
    [[ -d "$uid_dir" ]] || continue
    uid="${uid_dir%/}"
    uid="${uid##*/}"
    uname_for_uid=$(getent passwd "$uid" 2>/dev/null | cut -d: -f1 || echo "uid:$uid")
    
    # Subshell with pipefail disabled to prevent "3.3M\n?" bug
    size=$( (set +e +o pipefail; du -sh "$uid_dir" 2>/dev/null | awk '{print $1}') )
    [[ -z "$size" ]] && size="?"
    
    wl_socks=$( (set +e +o pipefail; find "$uid_dir" -maxdepth 1 -name 'wayland-*' 2>/dev/null | wc -l) )
    echo "- User **$uname_for_uid** ($uid): \`$size\` in tmpfs, \`$wl_socks\` wayland socket(s)"
done
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 7 — KERNEL SLAB LEAK DETECTION
# ─────────────────────────────────────────────────────────────────────────────
echo "## 7. Kernel Slab Objects (Top 15 by Total Memory)"
echo "---"
echo '> **Understanding this section:** The Linux Kernel maintains its own internal RAM caches (Slabs) for things like file structures, network sockets, and inodes. If a kernel driver is faulty, a specific object here will infinitely balloon in size.'
echo ""
if [[ -r /proc/slabinfo ]]; then
    echo "\`\`\`text"
    echo "NAME                       NUM_OBJS  OBJSIZE  TOTAL_MB"
    echo "------------------------------------------------------"
    
    # Subshell to prevent head -15 from throwing SIGPIPE crashes
    (
        set +e +o pipefail
        awk 'NR>2 && NF>=4 {
            total_bytes = $3 * $4
            printf "%-26s %9d  %7d  %7.1f\n", $1, $3, $4, total_bytes/1048576
        }' /proc/slabinfo | sort -k4 -rn | head -15
    ) || true
    echo "\`\`\`"
    
    SLAB_TOTAL_MB=$(awk 'NR>2 && NF>=4 {total += $3 * $4} END {printf "%.0f", total/1048576}' /proc/slabinfo)
    echo "> **Calculated Slab Total:** $SLAB_TOTAL_MB MB"
else
    echo "`/proc/slabinfo` not readable. Falling back to slabtop:"
    echo "\`\`\`text"
    slabtop -o -s c 2>/dev/null | head -20 || echo "slabtop unavailable."
    echo "\`\`\`"
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 8 — DMA-BUF GPU BUFFERS (AQUAMARINE)
# ─────────────────────────────────────────────────────────────────────────────
echo "## 8. GPU DMA-BUF Allocations (Aquamarine / Graphics)"
echo "---"
echo '> **Understanding this section:** DMA-BUFs are chunks of physical system RAM pinned securely for the GPU (for rendering the desktop, gaming, and screen-sharing). **These are completely invisible to standard tools like `htop` or `ps`.** If your RAM is disappearing without a trace, this is often the culprit.'
echo ""

MOUNTED_DEBUGFS=false
if ! mountpoint -q /sys/kernel/debug 2>/dev/null; then
    if mount -t debugfs none /sys/kernel/debug 2>/dev/null; then
        MOUNTED_DEBUGFS=true
    fi
fi

DMABUF_INFO=/sys/kernel/debug/dma_buf/bufinfo
if [[ -r "$DMABUF_INFO" ]]; then
    # Universal Parser for both Kernel 6.x (Legacy) and 7.x (Tabular) Formats
    TOTAL_BYTES=$(awk '/^[0-9]+/ {sum+=$1} /^size:/ {sum+=$2} END {print sum+0}' "$DMABUF_INFO" 2>/dev/null || echo 0)
    BUF_COUNT=$(awk '/^[0-9]+/ {count++} /^size:/ {count++} END {print count+0}' "$DMABUF_INFO" 2>/dev/null || echo 0)
    
    if [[ "$BUF_COUNT" -gt 0 ]]; then
        echo "- **Active DMA-BUF Count:** \`$BUF_COUNT\`"
        echo "- **Total DMA-BUF RAM:** **$(awk "BEGIN {printf \"%.1f\", $TOTAL_BYTES/1048576}") MB**"
        
        echo ""
        echo "### Top 10 Largest Individual GPU Buffers"
        echo "| Size (MB) | Exporter |"
        echo "|---|---|"
        
        # Subshell to prevent head -10 SIGPIPE truncation bug causing blank tables
        (
            set +e +o pipefail
            awk '
                /^[0-9]+/ {print $1, $5}
                /^size:/ {
                    sz=$2; exp="unknown"
                    for(i=1;i<=NF;i++) if($i=="exp_name:") exp=$(i+1)
                    print sz, exp
                }
            ' "$DMABUF_INFO" 2>/dev/null | sort -k1 -rn | head -n 10 | awk '{printf "| %.1f | %s |\n", $1/1048576, $2}'
        ) || true
        
        echo ""
        echo "### Buffer Breakdown by Exporter"
        echo "| Exporter Driver | Object Count |"
        echo "|---|---|"
        (
            set +e +o pipefail
            awk '
                /^[0-9]+/ {print $5}
                /^size:/ {
                    exp="unknown"
                    for(i=1;i<=NF;i++) if($i=="exp_name:") print $(i+1)
                }
            ' "$DMABUF_INFO" 2>/dev/null | sort | uniq -c | sort -rn | awk '{printf "| %s | %d |\n", $2, $1}'
        ) || true
    else
        echo "**No active DMA-BUFs tracked.** (Format mismatch or idle system)."
    fi
else
    echo "**DMA-BUF trace unavailable.** (debugfs blocked or lockdown=integrity)."
fi

# udmabuf check
if [[ -d /sys/kernel/debug/udmabuf ]]; then
    echo ""
    echo "### udmabuf pools (Zero-copy IPC)"
    echo "\`\`\`text"
    ls -la /sys/kernel/debug/udmabuf/ 2>/dev/null || true
    echo "\`\`\`"
fi

if [[ "$MOUNTED_DEBUGFS" == true ]]; then
    umount /sys/kernel/debug 2>/dev/null || true
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 9 — TRANSPARENT HUGEPAGES (THP)
# ─────────────────────────────────────────────────────────────────────────────
echo "## 9. Transparent Hugepages (THP) Inflation"
echo "---"
echo '> **Understanding this section:** To increase CPU cache hits, the kernel sometimes bundles memory into massive 2MB "Hugepages". If an app only needs 50KB but gets a 2MB Hugepage, system monitors will report it as using 2MB. This heavily distorts `RSS` readings.'
echo ""
THP_DIR=/sys/kernel/mm/transparent_hugepage
echo "- **THP Policy (Enabled):** \`$(cat $THP_DIR/enabled 2>/dev/null || echo 'N/A')\`"
echo "- **THP Defrag Policy:** \`$(cat $THP_DIR/defrag 2>/dev/null || echo 'N/A')\`"
echo "- **Khugepaged Scans:** \`$(cat $THP_DIR/khugepaged/pages_to_scan 2>/dev/null || echo 'N/A')\`"
echo ""
echo "- **AnonHugePages (2MB chunks):** $(to_mb $ANON_HUGE) MB"
echo "- **ShmemHugePages:** $(to_mb $SHMEM_HUGE) MB"
echo "- **FileHugePages:** $(to_mb $FILE_HUGE) MB"
echo ""

echo "### Active THP Allocation Tiers"
thp_found=false
for f in $THP_DIR/hugepages-*kB/nr_anon; do
    [[ -r "$f" ]] || continue
    
    # Bulletproof POSIX sed extraction (avoids grep -oP silently failing)
    sz=$(echo "$f" | sed -n 's/.*hugepages-\([0-9]*\)kB.*/\1/p' 2>/dev/null || echo 0)
    count=$(cat "$f" 2>/dev/null || echo 0)
    
    if [[ "$sz" -gt 0 && "$count" -gt 0 ]]; then
        total_mb=$(awk "BEGIN {printf \"%.1f\", ($count * $sz) / 1024}")
        echo "- **hugepages-${sz}kB:** \`$count\` active allocations (*$total_mb MB total*)"
        thp_found=true
    fi
done

if [[ "$thp_found" == false ]]; then
    echo "- *No active hugepages mapped in anon tiers.*"
fi

echo ""
echo '> **Note:** If **AnonHugePages** is extremely large (> 1 GB), standard tools will show vastly inflated RAM usage for apps like Electron and Chromium. The PSS table (Section 4) calculates this away to give you the real number.'
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 10 — HYPRLAND MEMORY LEAK CHECKLIST
# ─────────────────────────────────────────────────────────────────────────────
echo "## 10. Hyprland Known Memory Leak Checklist"
echo "---"

echo "### A. Headless Monitor Bug"
if [[ -n "${HYPR_USER:-}" ]]; then
    HEADLESS=$(sudo -u "$HYPR_USER" env $HYPR_ENV hyprctl monitors all -j 2>/dev/null | jq -r '[.[] | select(.name | ascii_downcase | contains("headless"))] | length' 2>/dev/null || echo 0)
    if [[ "$HEADLESS" -gt 0 ]]; then
        echo "🚨 **ALERT: HEADLESS MONITOR DETECTED ($HEADLESS entries).**"
        echo "This causes a catastrophic, infinite DMA-BUF leak in older Hyprland iterations."
        echo "Fix immediately: \`hyprctl output remove HEADLESS-1\`"
    else
        echo "✅ No headless monitors detected."
    fi
else
    echo "⚠️ Cannot check headless outputs (Hyprland user context missing)."
fi

echo ""
echo "### B. Xwayland Buffer Footprint"
XWPID=$(pgrep -x Xwayland 2>/dev/null | head -1 || true)
if [[ -n "$XWPID" ]]; then
    XW_RSS=$(awk '/^VmRSS:/{print $2}' /proc/"$XWPID"/status 2>/dev/null || echo 0)
    echo "✅ **Xwayland running** (PID $XWPID) — RSS: $(to_mb $XW_RSS) MB"
    echo "> *Xwayland holds DMA-BUFs per X11 window. Opening/closing X11 apps continuously can leak VRAM if misconfigured.*"
else
    echo "✅ Xwayland not running. No X11 DMA-BUF leakage possible."
fi

echo ""
echo "### C. Screencopy / OBS / Portals"
SC_PIDS=$(pgrep -f 'screencopy\|wlr-randr\|obs\|pipewire\|sunshine\|xdg-desktop-portal' 2>/dev/null || true)
if [[ -n "$SC_PIDS" ]]; then
    echo "Active screencasting/portal processes (These pin multiple 4K/1440p DMA-BUFs for sharing):"
    echo "\`\`\`text"
    for p in $SC_PIDS; do
        comm=$(cat /proc/"$p"/comm 2>/dev/null || echo '?')
        echo "  [PID $p] $comm"
    done
    echo "\`\`\`"
else
    echo "✅ No screen capturing software detected."
fi

echo ""
echo "### D. Decorations & Shadows"
HYPR_CONF_PATHS=(
    "$TARGET_HOME/.config/hypr/hyprland.conf"
    "$TARGET_HOME/.config/hypr/hyprland.lua"
)
for cfg in "${HYPR_CONF_PATHS[@]}"; do
    [[ -r "$cfg" ]] || continue
    BLUR=$(grep -iE '^\s*(blur\s*=\s*true|blur\s*\{|blurSize)' "$cfg" 2>/dev/null | head -1 || true)
    SHADOW=$(grep -iE '^\s*drop_shadow\s*=\s*true' "$cfg" 2>/dev/null | head -1 || true)
    
    [[ -n "$BLUR" ]]   && echo "⚠️ **Blur enabled:** \`$cfg\`. (Requires massive GPU/RAM framebuffers for Aquamarine)."
    [[ -n "$SHADOW" ]] && echo "⚠️ **Shadows enabled:** \`$cfg\`. (Requires additional surface FBOs per window)."
    [[ -z "$BLUR" && -z "$SHADOW" ]] && echo "✅ No blur/shadow detected in \`$cfg\`."
done
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 11 — MEMORY PRESSURE EVENTS (OOM)
# ─────────────────────────────────────────────────────────────────────────────
echo "## 11. Memory Pressure Events (OOM History)"
echo "---"

echo "### OOM Kills in Kernel Log"
echo "\`\`\`text"
(
    set +e +o pipefail
    dmesg --time-format reltime 2>/dev/null | grep -i 'oom\|killed process\|out of memory' | tail -10 || \
    journalctl -k --no-pager -q 2>/dev/null | grep -i 'oom\|killed process\|out of memory' | tail -10 || \
    echo "  No OOM events found in kernel log."
)
echo "\`\`\`"

echo "### Pressure Stall Information (PSI)"
echo "\`\`\`text"
for res in memory cpu io; do
    PSI_FILE="/proc/pressure/$res"
    [[ -r "$PSI_FILE" ]] && printf "%-8s %s\n" "$res:" "$(cat $PSI_FILE)" || true
done
echo "\`\`\`"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 12 — QUICK DIAGNOSIS GUIDE
# ─────────────────────────────────────────────────────────────────────────────
echo "## 12. Quick Diagnosis Guide"
echo "---"
cat << 'GUIDE'
**HIGH RAM — HOW TO LOCATE THE CAUSE:**

1. **High AnonPages but low DMA-BUF:**
   - Normal application RAM. Check the PSS table (Section 4) for the top consumer.
   - Browsers (Firefox/Chromium) and Electron apps heavily dominate here.

2. **High Shmem + large `/dev/shm` entries:**
   - Wayland pixel buffer leak. Check which compositor client is not releasing `wl_shm` buffers. Restart the offending app.

3. **High Unaccounted (Section 1) + high DMA-BUF total (Section 8):**
   - GPU driver holding system RAM as framebuffers. On AMD: `amdgpu` GTT. On NVIDIA: driver anonymous memory.
   - *Try:* `echo 3 > /proc/sys/vm/drop_caches` (only reclaims slab/cache, not GPU memory).

4. **High SUnreclaim (Slab, Section 7):**
   - Kernel slab leak. Run: `watch -n2 'cat /proc/meminfo | grep -E "Slab|SUnreclaim"'`
   - Note which slab object in Section 7 is largest. File a kernel bug if it grows infinitely.

5. **High Hyprland RSS/PSS (Section 5):**
   - Check for headless monitor (Section 10). If none, disable blur (Section 10).
   - Hyprland 0.55 uses Aquamarine 0.11 which allocates one FBO per layer surface.

6. **AnonHugePages is large (Section 1 & 9):**
   - THP is inflating reported RSS. This is NOT a leak but makes `ps`/`htop` show inflated values. The PSS table (Section 4) calculates this away perfectly.

7. **Memory grows over time and never returns:**
   - A. Open/close many windows and watch DMA-BUF total (Section 8). Known Hyprland bug.
   - B. Reload Hyprland config many times and watch Hyprland PSS (Section 4).
   - C. Run under Valgrind/heaptrack as a last resort.
GUIDE

echo ""
echo "***"
echo "**END OF FORENSICS REPORT**"
echo "***"

} 2>&1 | tee "$REPORT"

chown "$TARGET_USER":"$TARGET_USER" "$REPORT" 2>/dev/null || true

echo -e "\n\e[1;32m[✓] Analysis complete. Markdown report safely written to:\e[0m"
echo -e "\e[1;36m$REPORT\e[0m"
