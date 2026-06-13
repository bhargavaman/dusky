#!/usr/bin/env python3
"""
Dusky BTRFS Controller
Advanced TUI for Native BTRFS Subvolumes, Snapper Snapshots, External Backups (Send/Receive), and NOCOW Management.
Engineered for strict safety, coordinated subvolume swapping, and interactive TUI on Arch Linux.
"""

import argparse
import csv
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# Modern Type Aliases (Python 3.12+)
type BtrfsMount = dict[str, Any]
type SubvolMeta = dict[str, Any]
type SnapperMeta = dict[str, Any]

# =============================================================================
# CORE SYSTEM UTILITIES
# =============================================================================

def ensure_root() -> None:
    if os.geteuid() != 0:
        print("\033[1;38;5;220m[*] Elevating to root privileges via sudo...\033[0m", file=sys.stderr)
        sys.stdout.flush()
        sys.stderr.flush()
        try:
            os.execvp("sudo", ["sudo", sys.executable] + sys.argv)
        except OSError as exc:
            fail(f"[!] Failed to elevate privileges: {exc}")

def fail(message: str, exit_code: int = 1) -> None:
    print(f"\033[1;38;5;196m{message}\033[0m", file=sys.stderr)
    sys.exit(exit_code)

def error_text(result: subprocess.CompletedProcess[str]) -> str:
    return result.stderr.strip() or result.stdout.strip() or "<no error output>"

def run_cmd(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except OSError as exc:
        fail(f"[!] Command execution failed: {shlex.join(cmd)}\n{exc}")

    if check and result.returncode != 0:
        fail(f"[!] Command failed: {shlex.join(cmd)}\n{error_text(result)}", result.returncode)
    return result

def run_cmd_raise(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except OSError as exc:
        raise RuntimeError(f"Command execution failed: {shlex.join(cmd)}\n{exc}") from exc

    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {shlex.join(cmd)}\n{error_text(result)}")
    return result

def confirm_prompt(prompt: str) -> bool:
    while True:
        try:
            choice = input(f"\n\033[1;38;5;220m{prompt} [y/N]: \033[0m").strip().lower()
        except KeyboardInterrupt:
            print("\nAborted.")
            sys.exit(130)
        
        if choice in ('y', 'yes'): return True
        if choice in ('', 'n', 'no'): return False
        print("Please answer y or n.")

# =============================================================================
# UI RENDERING UTILITIES
# =============================================================================

def strip_ansi(text: str) -> str:
    """Removes ANSI escape sequences to accurately calculate visual string width."""
    return re.sub(r'\x1b\[[0-9;]*m', '', text)

def draw_tui_panel(title: str, lines: list[str], width: int = 48) -> None:
    """Renders a pixel-perfect boxed panel regardless of ANSI color codes."""
    title_clean = strip_ansi(title)
    dash_count = max(0, width - len(title_clean) - 5)
    print(f"\033[1;38;5;220m╭─ {title} \033[1;38;5;220m{'─' * dash_count}╮\033[0m")
    
    for line in lines:
        line_clean = strip_ansi(line)
        pad = max(0, width - len(line_clean) - 4)
        print(f"\033[1;38;5;220m│\033[0m {line}{' ' * pad} \033[1;38;5;220m│\033[0m")
        
    print(f"\033[1;38;5;220m╰{'─' * (width - 2)}╯\033[0m\n")

def print_snapper_shortcuts():
    lines = [
        "\033[1;38;5;114m[ENTER]\033[0m   \033[38;5;253m󰁯 Restore Snapshot\033[0m",
        "\033[1;38;5;81m[CTRL-B]\033[0m  \033[38;5;253m󰆗 Backup to Ext. Drive\033[0m",
        "\033[1;38;5;213m[CTRL-S]\033[0m  \033[38;5;253m󰎈 Create New Snapshot\033[0m",
        "\033[1;38;5;196m[DEL]\033[0m     \033[38;5;253m󰆴 Delete Snapshot\033[0m",
        "\033[1;38;5;246m[TAB]\033[0m     \033[38;5;253m󰓡 Switch to Subvolumes\033[0m"
    ]
    draw_tui_panel("\033[1;38;5;39m󰏖 SNAPPER SHORTCUTS\033[0m", lines)

def print_subvolume_shortcuts():
    lines = [
        "\033[1;38;5;114m[CTRL-N]\033[0m  \033[38;5;253m󰐕 Create Subvol (NOCOW)\033[0m",
        "\033[1;38;5;81m[CTRL-S]\033[0m  \033[38;5;253m󰎈 Create Native Snapshot\033[0m",
        "\033[1;38;5;213m[CTRL-G]\033[0m  \033[38;5;253m󰒓 Init Snapper Config\033[0m",
        "\033[1;38;5;81m[CTRL-B]\033[0m  \033[38;5;253m󰆗 Backup to Ext. Drive\033[0m",
        "\033[1;38;5;196m[DEL]\033[0m     \033[38;5;253m󰆴 Delete Subvolume\033[0m",
        "\033[1;38;5;246m[TAB]\033[0m     \033[38;5;253m󰓡 Switch to Snapshots\033[0m"
    ]
    draw_tui_panel("\033[1;38;5;213m󰏖 SUBVOLUME SHORTCUTS\033[0m", lines)

# =============================================================================
# ADVANCED BTRFS ROLLBACK & RESTORATION LOGIC
# =============================================================================

def get_btrfs_device(path: str) -> str:
    result = run_cmd(["findmnt", "-n", "-v", "-e", "-o", "SOURCE", "-T", path])
    device = result.stdout.strip()
    if not device.startswith("/dev/"):
        fail(f"[!] Fatal: Could not resolve physical block device for {path}. Found: {device}")
    return os.path.realpath(device)

def get_active_subvol(mountpoint: str) -> str:
    result = run_cmd(["findmnt", "--fstab", "-n", "-o", "OPTIONS", "-M", mountpoint], check=False)
    if result.returncode == 0:
        match = re.search(r"(?:^|,)subvol=([^,]+)(?:,|$)", result.stdout.strip())
        if match: return match.group(1).lstrip("/")

    result = run_cmd(["findmnt", "-n", "-o", "OPTIONS", "-M", mountpoint], check=False)
    if result.returncode == 0:
        match = re.search(r"(?:^|,)subvol=([^,]+)(?:,|$)", result.stdout.strip())
        if match: return match.group(1).lstrip("/")

    result = run_cmd(["btrfs", "subvolume", "show", mountpoint], check=False)
    if result.returncode == 0:
        match = re.search(r"^[ \t]*Path:[ \t]*(.+)$", result.stdout, re.MULTILINE)
        if match:
            path = match.group(1).strip().lstrip("/")
            if path and path not in ("<FS_TREE>", ""): return path

    fail(f"[!] Fatal: Could not determine active Btrfs subvolume path for {mountpoint}. No 'subvol=' option found.")

def get_target_mount_from_snapper_config(config: str) -> str:
    result = run_cmd(["snapper", "-c", config, "get-config"])
    for line in result.stdout.splitlines():
        sanitized_line = line.replace("│", "|")
        key, sep, value = sanitized_line.partition("|")
        if sep and key.strip() == "SUBVOLUME":
            target_mnt = value.strip()
            if target_mnt: return target_mnt
            break
    fail(f"[!] Fatal: Could not determine SUBVOLUME for snapper config '{config}'.")

def validate_snapshot_id(snap_id: str) -> str:
    snap_id = snap_id.strip()
    if not snap_id.isdigit(): fail(f"[!] Fatal: Invalid snapshot ID: {snap_id!r}")
    return snap_id

@contextmanager
def mount_top_level(device: str) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="btrfs_top_level_mgmt_", dir="/mnt", ignore_cleanup_errors=True) as tmpdir:
        mnt_point = Path(tmpdir)
        print(f"\033[1;38;5;81m[*] Mounting top-level tree (subvolid=5) for {device}...\033[0m", file=sys.stderr)
        run_cmd(["mount", "-o", "subvolid=5", device, str(mnt_point)])
        active_exception: BaseException | None = None
        try:
            yield mnt_point
        except BaseException as exc:
            active_exception = exc
            raise
        finally:
            print("\033[1;38;5;81m[*] Unmounting top-level tree...\033[0m", file=sys.stderr)
            result = run_cmd(["umount", str(mnt_point)], check=False)
            if result.returncode != 0:
                message = error_text(result)
                if active_exception is None: fail(f"[!] Command failed: umount {mnt_point}\n{message}", result.returncode)
                print(f"\033[1;38;5;220m[!] Warning: Failed to unmount top-level tree {mnt_point}: {message}\033[0m", file=sys.stderr)

@dataclass(slots=True)
class RestoreSpec:
    config: str
    snap_id: str
    target_mnt: str
    device: str
    active_subvol: str
    snapshots_subvol: str

@dataclass(slots=True)
class PreparedRestore:
    spec: RestoreSpec
    source_snapshot: Path
    target_path: Path
    temp_delete_path: Path
    staging_path: Path
    staging_created: bool = False
    active_moved: bool = False
    activated: bool = False

def resolve_restore_spec(config: str, snap_id: str) -> RestoreSpec:
    snap_id = validate_snapshot_id(snap_id)
    target_mnt = get_target_mount_from_snapper_config(config)
    snapshots_mnt = "/.snapshots" if target_mnt == "/" else f"{target_mnt}/.snapshots"
    device = get_btrfs_device(target_mnt)
    active_subvol = get_active_subvol(target_mnt)
    snapshots_subvol = get_active_subvol(snapshots_mnt)

    if not active_subvol: fail(f"[!] Fatal: Empty active subvolume path is not supported for {target_mnt}.")
    if not snapshots_subvol: fail(f"[!] Fatal: Empty snapshots subvolume path is not supported for {snapshots_mnt}.")

    return RestoreSpec(config, snap_id, target_mnt, device, active_subvol, snapshots_subvol)

def prepare_restore(spec: RestoreSpec, top_mnt: Path, timestamp: str) -> PreparedRestore:
    target_path = top_mnt / spec.active_subvol
    source_snapshot = top_mnt / spec.snapshots_subvol / spec.snap_id / "snapshot"
    temp_delete_path = target_path.with_name(f"{target_path.name}_to_delete_{timestamp}")
    staging_path = target_path.with_name(f"{target_path.name}_restore_{spec.snap_id}_{timestamp}")

    return PreparedRestore(spec, source_snapshot, target_path, temp_delete_path, staging_path)

def ensure_no_nested_subvolumes(plan: PreparedRestore) -> None:
    result = run_cmd(["btrfs", "subvolume", "list", "-o", str(plan.target_path)], check=False)
    if result.returncode != 0:
        fail(f"[!] Fatal: Failed to inspect nested subvolumes inside '{plan.spec.active_subvol}' for config '{plan.spec.config}'.\n{error_text(result)}")
    nested_output = result.stdout.strip()
    if nested_output:
        fail(f"\n[!] CRITICAL HALT: Nested subvolumes detected physically inside '{plan.spec.active_subvol}' for config '{plan.spec.config}'!\n\nOffending subvolumes:\n{nested_output}\n\n[!] An atomic rollback would trap these inside the subvolume slated for deletion.\n[!] Please check what these are. You may need to flatten your Btrfs topology.")

def rollback_prepared_restores(plans: list[PreparedRestore], original_exc: Exception) -> None:
    rollback_errors: list[str] = []
    for plan in reversed(plans):
        if plan.activated and plan.target_path.exists() and not plan.staging_path.exists():
            try: plan.target_path.rename(plan.staging_path)
            except OSError as exc: rollback_errors.append(f"{plan.spec.config}: failed to move restored subvolume out of the way: {exc}")

    for plan in reversed(plans):
        if plan.active_moved and plan.temp_delete_path.exists() and not plan.target_path.exists():
            try: plan.temp_delete_path.rename(plan.target_path)
            except OSError as exc: rollback_errors.append(f"{plan.spec.config}: failed to restore original active subvolume: {exc}")

    for plan in reversed(plans):
        if plan.staging_path.exists():
            result = run_cmd(["btrfs", "subvolume", "delete", str(plan.staging_path)], check=False)
            if result.returncode != 0: rollback_errors.append(f"{plan.spec.config}: failed to delete staging subvolume '{plan.staging_path.name}': {error_text(result)}")

    if rollback_errors:
        joined = "\n".join(f"- {item}" for item in rollback_errors)
        fail(f"[!] Fatal: Restore failed and rollback was incomplete.\n{original_exc}\n{joined}")
    fail(f"[!] Fatal: Restore failed. Rolled back successfully.\n{original_exc}")

def apply_prepared_restores(plans: list[PreparedRestore]) -> None:
    seen_targets: set[str] = set()
    for plan in plans:
        target_key = str(plan.target_path)
        if target_key in seen_targets: fail(f"[!] Fatal: Multiple restore targets resolve to the same path: {target_key}")
        seen_targets.add(target_key)
        if not plan.source_snapshot.is_dir(): fail(f"[!] Fatal: Snapshot ID {plan.spec.snap_id} does not exist at {plan.source_snapshot}")
        if not plan.target_path.is_dir(): fail(f"[!] Fatal: Active subvolume path does not exist for config '{plan.spec.config}': {plan.target_path}")
        if plan.temp_delete_path.exists(): fail(f"[!] Fatal: Deletion path already exists for config '{plan.spec.config}': {plan.temp_delete_path}")
        if plan.staging_path.exists(): fail(f"[!] Fatal: Staging path already exists for config '{plan.spec.config}': {plan.staging_path}")
        ensure_no_nested_subvolumes(plan)

    try:
        for plan in plans:
            print(f"\033[1;38;5;81m[*] Creating staged restore subvolume for '{plan.spec.config}': {plan.staging_path.name}...\033[0m")
            run_cmd_raise(["btrfs", "subvolume", "snapshot", str(plan.source_snapshot), str(plan.staging_path)])
            plan.staging_created = True

        for plan in plans:
            print(f"\033[1;38;5;81m[*] Unlinking current active subvolume for '{plan.spec.config}'...\033[0m")
            plan.target_path.rename(plan.temp_delete_path)
            plan.active_moved = True

        for plan in plans:
            print(f"\033[1;38;5;81m[*] Activating restored snapshot for '{plan.spec.config}' as {plan.target_path.name}...\033[0m")
            plan.staging_path.rename(plan.target_path)
            plan.activated = True
            
        for plan in plans:
            print(f"\033[1;38;5;81m[*] Permanently deleting previous system state for '{plan.spec.config}'...\033[0m")
            deleted = False
            for attempt in range(3):
                del_res = run_cmd(["btrfs", "subvolume", "delete", str(plan.temp_delete_path)], check=False)
                if del_res.returncode == 0:
                    deleted = True
                    break
                time.sleep(1)

            if not deleted:
                print(f"\033[1;38;5;220m[!] Warning: Immediate deletion failed. Scheduling aggressive background cleanup on next boot...\033[0m", file=sys.stderr)
                try:
                    uuid_res = run_cmd(["findmnt", "-n", "-e", "-o", "UUID", "-M", plan.spec.target_mnt], check=False)
                    uuid = uuid_res.stdout.strip()
                    if not uuid or uuid == "-":
                        device_res = run_cmd(["findmnt", "-n", "-v", "-e", "-o", "SOURCE", "-M", plan.spec.target_mnt], check=False)
                        device = device_res.stdout.strip()
                        if device.startswith("/dev/"):
                            blkid_res = run_cmd(["blkid", "-s", "UUID", "-o", "value", device], check=False)
                            uuid = blkid_res.stdout.strip()

                    if not uuid: continue
                    subvol_name = plan.temp_delete_path.name
                    service_name = f"dusky-cleanup-{subvol_name}.service"
                    service_path = Path("/etc/systemd/system") / service_name
                    
                    service_content = f"""[Unit]
Description=Dusky Btrfs Cleanup ({subvol_name})
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/usr/bin/bash -c "/usr/bin/mkdir -p /run/dusky_mnt && /usr/bin/mount -t btrfs -o subvolid=5 UUID={uuid} /run/dusky_mnt && {{ /usr/bin/btrfs subvolume delete '/run/dusky_mnt/{subvol_name}'; /usr/bin/umount /run/dusky_mnt; }}"
ExecStartPost=/usr/bin/systemctl disable {service_name}
ExecStartPost=/usr/bin/rm -f /etc/systemd/system/{service_name}

[Install]
WantedBy=multi-user.target
"""
                    service_path.write_text(service_content)
                    run_cmd(["systemctl", "daemon-reload"])
                    run_cmd(["systemctl", "enable", service_name])
                    print(f"\033[1;38;5;114m[+] Scheduled one-shot systemd service '{service_name}' to eradicate subvolume on next boot.\033[0m")
                except Exception as e:
                    print(f"\033[1;38;5;196m[!] Failed to schedule boot cleanup: {e}\n[!] Manual deletion of '{plan.temp_delete_path.name}' required.\033[0m", file=sys.stderr)

    except (OSError, RuntimeError) as exc:
        rollback_prepared_restores(plans, exc)

def is_mountpoint(path: str) -> bool:
    return run_cmd(["mountpoint", "-q", "--", path], check=False).returncode == 0

def activate_nonroot_restore(target_mnt: str) -> None:
    if not is_mountpoint(target_mnt):
        print(f"\033[1;38;5;81m[*] {target_mnt} is not currently mounted as its own mountpoint. Restored subvolume will be used on the next mount.\033[0m")
        return
    print(f"\033[1;38;5;81m[*] Attempting to live-remount {target_mnt} to activate restored snapshot...\033[0m")
    if run_cmd(["umount", target_mnt], check=False).returncode != 0:
        print(f"\n\033[1;38;5;220m[!] Notice: {target_mnt} is currently in use (target is busy).\n[!] The restore was successful on disk, but the live filesystem cannot be swapped.\n[\033[1;38;5;196m!\033[1;38;5;220m] WARNING: Any changes made to {target_mnt} right now will be lost upon reboot.\n[!] Please REBOOT IMMEDIATELY to activate the restored snapshot.\033[0m")
        return
    if run_cmd(["mount", target_mnt], check=False).returncode != 0:
        fail(f"[!] CRITICAL: Restore completed on disk, but remount of {target_mnt} failed!\n[!] Your {target_mnt} directory is currently unmounted. Please resolve manually before rebooting.")
    print(f"\033[1;38;5;114m[+] {target_mnt} successfully remounted live.\033[0m")

def handle_restore(config: str, snap_id: str, no_remount: bool = False) -> None:
    spec = resolve_restore_spec(config, snap_id)
    with mount_top_level(spec.device) as top_mnt:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        plan = prepare_restore(spec, top_mnt, timestamp)
        apply_prepared_restores([plan])

    print(f"\n\033[1;38;5;114m[+] Restoration of '{config}' complete.\033[0m")
    if spec.target_mnt == "/":
        print("\033[1;38;5;196m[!] ROOT FILESYSTEM RESTORED. You MUST reboot immediately for changes to take effect.\033[0m")
        return
    if no_remount:
        print(f"\033[1;38;5;220m[!] {spec.target_mnt} was restored on disk without live remount.\n[!] Reboot or manually remount to activate.\033[0m")
        return
    activate_nonroot_restore(spec.target_mnt)

# =============================================================================
# BTRFS SUBVOLUMES & EXTERNAL BACKUP LOGIC
# =============================================================================

def get_btrfs_mounts() -> list[BtrfsMount]:
    res = run_cmd(["findmnt", "-t", "btrfs", "-J", "-e"], check=False)
    if res.returncode != 0 or not res.stdout.strip(): return []
    try: return json.loads(res.stdout).get("filesystems", [])
    except json.JSONDecodeError: return []

def get_all_subvolumes() -> list[SubvolMeta]:
    mounts = get_btrfs_mounts()
    seen_uuids = set()
    subvols: list[SubvolMeta] = []
    
    subvol_regex = re.compile(r"^ID\s+(\d+).*?path\s+(.+)$")
    
    for m in mounts:
        dev = m.get("source")
        if not dev or dev in seen_uuids: continue
        seen_uuids.add(dev)
        
        target = m.get("target", "/")
        res = run_cmd(["btrfs", "subvolume", "list", "-a", "-p", target], check=False)
        if res.returncode != 0: continue
            
        for line in res.stdout.splitlines():
            match = subvol_regex.match(line.strip())
            if match:
                sv_id = match.group(1)
                sv_path = match.group(2)
                clean_path = sv_path.replace("<FS_TREE>/", "")
                full_mount_path = Path(target) / clean_path.lstrip("/")
                ro_check = run_cmd(["btrfs", "property", "get", "-t", "subvol", str(full_mount_path), "ro"], check=False)
                is_ro = "ro=true" in ro_check.stdout.lower()
                
                subvols.append({
                    "id": sv_id,
                    "path": clean_path,
                    "mount_target": target,
                    "full_path": str(full_mount_path),
                    "is_ro": is_ro
                })
    return subvols

def create_nocow_subvolume(parent_dir: str, name: str, disable_cow: bool) -> None:
    full_path = Path(parent_dir) / name
    if full_path.exists(): fail(f"[!] Target path already exists: {full_path}")
        
    print(f"\033[1;38;5;81m[*] Creating BTRFS subvolume at {full_path}...\033[0m")
    run_cmd(["btrfs", "subvolume", "create", str(full_path)])
    
    if disable_cow:
        print(f"\033[1;38;5;220m[*] Applying NOCOW attribute (chattr +C)...\033[0m")
        run_cmd(["chattr", "+C", str(full_path)])
        print("\033[1;38;5;114m[+] Subvolume created with Copy-On-Write DISABLED.\033[0m")
    else:
        print("\033[1;38;5;114m[+] Subvolume created (Standard COW).\033[0m")

def backup_snapshot_to_external(src_full_path: str, external_dest: str) -> None:
    """Enforces absolute strict Flat-Topology on the external drive via subvolid=5 mounting."""
    dest_path = Path(external_dest)
    src_path = Path(src_full_path)
    
    if not dest_path.is_dir(): fail(f"[!] External destination does not exist or is not a directory: {dest_path}")
    fs_check = run_cmd(["stat", "-f", "-c", "%T", str(dest_path)], check=False)
    if fs_check.returncode != 0 or "btrfs" not in fs_check.stdout.lower(): fail(f"[!] Destination {dest_path} is not recognized as a BTRFS filesystem.")

    ro_check = run_cmd(["btrfs", "property", "get", "-t", "subvol", str(src_path), "ro"], check=False)
    is_ro = "ro=true" in ro_check.stdout.lower()

    ephemeral_snap = None
    if not is_ro:
        print(f"\033[1;38;5;220m[*] Source {src_path.name} is writable. Creating ephemeral Read-Only snapshot for secure stream...\033[0m")
        ephemeral_snap = src_path.parent / f".tmp_send_{src_path.name}_{int(time.time())}"
        run_cmd_raise(["btrfs", "subvolume", "snapshot", "-r", str(src_path), str(ephemeral_snap)])
        src_path = ephemeral_snap

    print(f"\033[1;38;5;81m[*] Resolving physical block device for top-level BTRFS stream to {dest_path}...\033[0m")
    ext_dev = get_btrfs_device(str(dest_path))
    
    try:
        # Mount the exact top-level of the external drive to guarantee a flat topology
        with mount_top_level(ext_dev) as top_mnt:
            staging_dir = Path(tempfile.mkdtemp(dir=top_mnt, prefix=".btrfs_recv_"))
            
            try:
                print(f"\033[38;5;246mExecuting stream: btrfs send {src_path} | btrfs receive {staging_dir}\033[0m")
                with subprocess.Popen(["btrfs", "send", str(src_path)], stdout=subprocess.PIPE) as send_proc:
                    recv_proc = subprocess.run(["btrfs", "receive", str(staging_dir)], stdin=send_proc.stdout, capture_output=True, text=True)
                    send_proc.wait() 
                    
                if send_proc.returncode != 0 or recv_proc.returncode != 0: 
                    fail(f"[!] Send/Receive stream failed:\n{recv_proc.stderr}")
                    
                received_items = list(staging_dir.iterdir())
                if not received_items: 
                    fail("[!] Stream completed but no subvolume was found in staging.")
                    
                src_item = received_items[0]
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                
                original_name = Path(src_full_path).name
                final_dest = top_mnt / f"backup_snap_{original_name}_{timestamp}"
                
                if final_dest.exists():
                    fail(f"[!] Fatal: Target top-level subvolume already exists: {final_dest}")
                    
                src_item.rename(final_dest)
                print(f"\033[1;38;5;114m[+] Backup successful!\033[0m")
                print(f"\033[1;38;5;114m[+] Top-level Subvolume safely created at: {ext_dev} -> {final_dest.name}\033[0m")
            finally:
                try: staging_dir.rmdir()
                except OSError: pass 
    finally:
        if ephemeral_snap and ephemeral_snap.exists():
            print(f"\033[38;5;246m[*] Cleaning up ephemeral snapshot...\033[0m")
            run_cmd(["btrfs", "subvolume", "delete", str(ephemeral_snap)], check=False)

# =============================================================================
# SNAPPER JSON PARSING & DATA ABSTRACTIONS
# =============================================================================

def get_snapper_configs() -> list[dict[str, str]]:
    """
    Bulletproof parser that totally bypasses IPC piping and Ncurses/Unicode
    breaking by extracting the exact configurations natively from the host OS.
    """
    configs = []
    
    # Primary Method: Direct File Read (Fastest, zero subprocess overhead)
    config_dir = Path("/etc/snapper/configs")
    if config_dir.is_dir():
        for cfg_file in config_dir.iterdir():
            if cfg_file.is_file() and not cfg_file.name.startswith('.'):
                cfg_name = cfg_file.name
                sub = "/"
                try:
                    content = cfg_file.read_text(errors="ignore")
                    match = re.search(r'^SUBVOLUME="?([^"\n]+)"?', content, re.MULTILINE)
                    if match:
                        sub = match.group(1)
                except Exception:
                    pass
                configs.append({"config": cfg_name, "subvolume": sub})
        if configs:
            return configs

    # Fallback Method: Subprocess call with CSV extraction
    res = run_cmd(["snapper", "--csvout", "--no-headers", "list-configs"], check=False)
    if res.returncode == 0:
        reader = csv.reader(res.stdout.splitlines())
        for row in reader:
            if len(row) >= 2:
                cfg = row[0].strip()
                sub = row[1].strip()
                if cfg: configs.append({"config": cfg, "subvolume": sub})
                
    return configs

def first_present(mapping: dict[str, object], *keys: str) -> object | None:
    for key in keys:
        if key in mapping and mapping[key] is not None: return mapping[key]
    return None

def normalize_json_key(value: str) -> str:
    raw = value.strip()
    if raw == "#": return "number"
    normalized = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")
    aliases = {"num": "number", "number": "number", "id": "id", "snapshot_id": "id", "type": "type", "snapshot_type": "snapshot_type", "date": "date", "timestamp": "timestamp", "time": "time", "description": "description", "desc": "description"}
    return aliases.get(normalized, normalized)

def looks_like_snapshot_record(obj: object) -> bool:
    if not isinstance(obj, dict): return False
    id_value = first_present(obj, "number", "id", "num", "#")
    aux_value = first_present(obj, "date", "timestamp", "time", "description", "desc", "type", "snapshot_type")
    return id_value is not None and aux_value is not None

def find_snapshot_records(obj: object) -> list[dict[str, object]] | None:
    if isinstance(obj, list):
        if obj and all(isinstance(item, dict) for item in obj) and any(looks_like_snapshot_record(item) for item in obj): return list(obj)
        for item in obj:
            found = find_snapshot_records(item)
            if found is not None: return found
        return None
    if isinstance(obj, dict):
        for key in ("snapshots", "entries", "data", "list"):
            if key in obj:
                found = find_snapshot_records(obj[key])
                if found is not None: return found
        for value in obj.values():
            found = find_snapshot_records(value)
            if found is not None: return found
    return None

def find_tabular_snapshot_records(obj: object) -> list[dict[str, object]] | None:
    if isinstance(obj, dict):
        columns = obj.get("columns")
        rows = obj.get("rows")
        if rows is None: rows = obj.get("data")
        if isinstance(columns, list) and isinstance(rows, list):
            column_names: list[str] = []
            for column in columns:
                if isinstance(column, str): column_names.append(normalize_json_key(column))
                elif isinstance(column, dict):
                    label = None
                    for candidate in ("name", "key", "id", "title", "label"):
                        if candidate in column and column[candidate] is not None:
                            label = str(column[candidate])
                            break
                    column_names.append(normalize_json_key("" if label is None else label))
                else: column_names.append("")
            if rows and all(isinstance(row, dict) for row in rows):
                candidate_rows = [dict(row) for row in rows]
                if any(looks_like_snapshot_record(row) for row in candidate_rows): return candidate_rows
            if rows and all(isinstance(row, (list, tuple)) for row in rows):
                records: list[dict[str, object]] = []
                for row in rows:
                    record: dict[str, object] = {}
                    for index, value in enumerate(row):
                        key = column_names[index] if index < len(column_names) and column_names[index] else f"col_{index}"
                        record[key] = value
                    records.append(record)
                if records and any(looks_like_snapshot_record(record) for record in records): return records
        for value in obj.values():
            found = find_tabular_snapshot_records(value)
            if found is not None: return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_tabular_snapshot_records(item)
            if found is not None: return found
    return None

def extract_snapshot_records(payload: object) -> list[dict[str, object]] | None:
    records = find_snapshot_records(payload)
    if records is not None: return records
    return find_tabular_snapshot_records(payload)

def parse_snapshot_datetime(raw_value: object) -> datetime | None:
    if raw_value is None: return None
    if isinstance(raw_value, int | float):
        try: return datetime.fromtimestamp(raw_value)
        except (OverflowError, OSError, ValueError): return None
    raw = str(raw_value).strip()
    if not raw: return None
    iso_candidates = [raw]
    if " " in raw: iso_candidates.append(raw.replace(" ", "T", 1))
    for candidate in iso_candidates:
        try: return datetime.fromisoformat(candidate)
        except ValueError: pass
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try: return datetime.strptime(raw, pattern)
        except ValueError: continue
    tokens = raw.split()
    if len(tokens) >= 7 and tokens[-1].isalpha():
        try:
            clean_date = " ".join(tokens[:-1])
            return datetime.strptime(clean_date, "%a %d %b %Y %I:%M:%S %p")
        except ValueError: pass
    return None

def format_snapshot_date(raw_value: object) -> str:
    dt = parse_snapshot_datetime(raw_value)
    if dt is not None: return dt.strftime("%m/%d/%y %I:%M %p")
    return str(raw_value).strip() if raw_value is not None else ""

def time_ago(dt: datetime) -> str:
    now = datetime.now()
    diff = now - dt
    seconds = int(diff.total_seconds())
    if seconds < 0: return "Just now"
    if seconds < 60: return f"{seconds}s ago"
    if seconds < 3600: return f"{seconds // 60}m ago"
    if seconds < 86400: return f"{seconds // 3600}h ago"
    if seconds < 2592000: return f"{seconds // 86400}d ago"
    return f"{seconds // 2592000}mo ago"

def snapshot_records_to_gui(records: list[dict[str, object]]) -> list[dict[str, str]]:
    gui_data: list[dict[str, str]] = []
    for record in records:
        snap_id_value = first_present(record, "number", "id", "num", "#")
        if snap_id_value is None: continue
        
        snap_id_raw = str(snap_id_value).strip()
        snap_id = re.sub(r'[*+-]+$', '', snap_id_raw)
        
        if snap_id == "0" or not snap_id.isdigit(): continue
        raw_date_value = first_present(record, "date", "timestamp", "time")
        raw_date = "" if raw_date_value is None else str(raw_date_value)
        
        dt = parse_snapshot_datetime(raw_date_value)
        age_str = time_ago(dt) if dt else "Unknown"

        gui_data.append({
            "id": snap_id,
            "type": str(first_present(record, "type", "snapshot_type") or ""),
            "date": format_snapshot_date(raw_date_value),
            "raw_date": raw_date,
            "description": str(first_present(record, "description", "desc") or ""),
            "age": age_str,
            "user": str(first_present(record, "user", "creator") or "root"),
            "cleanup": str(first_present(record, "cleanup", "cleanup_algorithm") or "")
        })
    return gui_data

def parse_snapper_table(stdout: str) -> list[dict[str, str]]:
    gui_data: list[dict[str, str]] = []
    for line in stdout.splitlines():
        if not line.strip(): continue
        parts = [part.strip() for part in re.split(r"[|│]", line)]
        if len(parts) < 7: continue
        
        snap_id_raw = parts[0]
        snap_id = re.sub(r'[*+-]+$', '', snap_id_raw)
        
        if snap_id == "0" or not snap_id.isdigit(): continue
        
        dt = parse_snapshot_datetime(parts[3])
        age_str = time_ago(dt) if dt else "Unknown"
        
        gui_data.append({
            "id": snap_id,
            "type": parts[1],
            "date": format_snapshot_date(parts[3]),
            "raw_date": parts[3],
            "description": parts[6] if len(parts) > 6 else "",
            "age": age_str,
            "user": parts[4] if len(parts) > 4 else "root",
            "cleanup": parts[5] if len(parts) > 5 else ""
        })
    return gui_data

def load_snapshot_list_for_gui(config: str) -> list[dict[str, str]]:
    result = run_cmd(["snapper", "--jsonout", "-c", config, "list", "--disable-used-space"], check=False)
    if result.returncode != 0: return []
    try: payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        result = run_cmd(["snapper", "-c", config, "list", "--disable-used-space"], check=False)
        return parse_snapper_table(result.stdout) if result.returncode == 0 else []
    records = extract_snapshot_records(payload)
    if records is None:
        result = run_cmd(["snapper", "-c", config, "list", "--disable-used-space"], check=False)
        return parse_snapper_table(result.stdout) if result.returncode == 0 else []
    return snapshot_records_to_gui(records)

def load_all_snapper_data() -> list[dict[str, str]]:
    configs = get_snapper_configs()
    all_snaps = []
    for cfg_info in configs:
        cfg = cfg_info["config"]
        base_path = cfg_info["subvolume"]
        gui_snaps = load_snapshot_list_for_gui(cfg)
        for s in gui_snaps:
            s["config_name"] = cfg
            s["location"] = str(Path(base_path) / ".snapshots" / s["id"] / "snapshot")
            all_snaps.append(s)
    return all_snaps

# =============================================================================
# TUI PREVIEW HANDLER
# =============================================================================

def handle_tui_preview(view: str, line: str) -> None:
    try:
        parts = line.split('\x1f')
        meta = json.loads(parts[1]) if len(parts) > 1 else {}
        
        if meta.get("empty"):
            print("\033[1;38;5;196m[!] No items available in this view.\033[0m")
            if view == "snapper": print("\033[1;38;5;246mGo to the BTRFS Subvolumes tab (TAB) and press CTRL-G to initialize a config.\033[0m")
            return
        
        match view:
            case "snapper":
                print_snapper_shortcuts()
                print(f"\033[1;38;5;81m󰆑 SNAPSHOT DETAILS\033[0m")
                print(f"\033[38;5;238m" + "─" * 48 + "\033[0m")
                print(f" \033[1;38;5;246mConfig \033[0m │ \033[1;38;5;253m{meta.get('config', 'Unknown')}\033[0m")
                print(f" \033[1;38;5;246mID     \033[0m │ \033[1;38;5;39m{meta.get('id', 'N/A')}\033[0m")
                print(f" \033[1;38;5;246mDate   \033[0m │ \033[38;5;220m{meta.get('date', 'N/A')}\033[0m")
                
                age = meta.get('age')
                if age and age != "Unknown":
                    print(f" \033[1;38;5;246mAge    \033[0m │ \033[38;5;114m{age}\033[0m")
                    
                print(f" \033[1;38;5;246mUser   \033[0m │ \033[38;5;114m{meta.get('user', 'root')}\033[0m")
                
                cleanup = meta.get('cleanup')
                if cleanup:
                    print(f" \033[1;38;5;246mCleanup\033[0m │ \033[38;5;216m{cleanup}\033[0m")
                    
                print(f" \033[1;38;5;246mPath   \033[0m │ \033[38;5;114m{meta.get('location', 'Unknown')}\033[0m")
                print(f" \033[1;38;5;246mDesc   \033[0m │ \033[38;5;253m{meta.get('desc', 'N/A')}\033[0m\n")
                
            case "subvolumes":
                print_subvolume_shortcuts()
                is_ro = "\033[1;38;5;196mRead-Only\033[0m" if meta.get("is_ro") else "\033[1;38;5;114mRead-Write\033[0m"
                print(f"\033[1;38;5;213m󰋊 SUBVOLUME METADATA\033[0m")
                print(f"\033[38;5;238m" + "─" * 48 + "\033[0m")
                print(f" \033[1;38;5;246mID     \033[0m │ \033[1;38;5;39m{meta.get('id', 'N/A')}\033[0m")
                print(f" \033[1;38;5;246mStatus \033[0m │ {is_ro}")
                print(f" \033[1;38;5;246mMount  \033[0m │ \033[38;5;220m{meta.get('mount_target', 'N/A')}\033[0m")
                print(f" \033[1;38;5;246mTarget \033[0m │ \033[38;5;253m{meta.get('full_path', 'N/A')}\033[0m")

    except Exception as e:
        print(f"\033[1;38;5;196mError rendering preview:\n{e}\033[0m")

# =============================================================================
# MAIN TUI ENGINE
# =============================================================================

def launch_tui() -> None:
    if not shutil.which("fzf"): fail("[!] Fatal: 'fzf' is required. Install via: pacman -S fzf")

    views = ["snapper", "subvolumes"]
    view_idx = 0
    
    fzf_colors = (
        "bg+:#1e1e2e,bg:#11111b,spinner:#f5e0dc,fg:#cdd6f4,fg+:#cdd6f4,"
        "header:#89b4fa,info:#cba6f7,pointer:#f5e0dc,marker:#a6e3a1,"
        "prompt:#cba6f7,hl:#f38ba8,hl+:#f38ba8,border:#585b70,label:#a6e3a1"
    )

    executable = shlex.quote(sys.executable)
    script_path = shlex.quote(os.path.abspath(sys.argv[0]))

    while True:
        current_view = views[view_idx]
        lines_for_fzf = []
        c_sep = "\033[38;5;238m│\033[0m"
        hr = "\033[38;5;238m" + "─" * 500 + "\033[0m"

        tab_snapper = "\033[1;38;5;232;48;5;39m 󰆑 SYSTEM SNAPSHOTS \033[0m" if current_view == "snapper" else "\033[38;5;246m 󰆑 SYSTEM SNAPSHOTS \033[0m"
        tab_subvols = "\033[1;38;5;232;48;5;213m 󰋊 BTRFS SUBVOLUMES \033[0m" if current_view == "subvolumes" else "\033[38;5;246m 󰋊 BTRFS SUBVOLUMES \033[0m"
        mode_hdr = f"  {tab_snapper}  {tab_subvols}"

        match current_view:
            case "snapper":
                table_hdr = f"\033[1;38;5;242m{'CFG':<8}\033[0m {c_sep} \033[1;38;5;242m{'ID':>4}\033[0m {c_sep} \033[1;38;5;242m{'AGE':<10}\033[0m {c_sep} \033[1;38;5;242m{'DATE':<18}\033[0m {c_sep} \033[1;38;5;242mDESCRIPTION\033[0m"
                lines_for_fzf.extend([mode_hdr, hr, table_hdr])
                
                snaps = load_all_snapper_data()
                if snaps:
                    for s in sorted(snaps, key=lambda x: (x['config_name'], int(x.get('number', x.get('id', 0)))), reverse=True):
                        cfg_str = f"\033[38;5;213m{s['config_name']:<8}\033[0m"
                        id_str = f"\033[1;38;5;39m{s.get('id', '0'):>4}\033[0m"
                        age_str = f"\033[38;5;114m{s.get('age', ''):<10}\033[0m"
                        date_str = f"\033[38;5;220m{s.get('date', ''):<18}\033[0m"
                        desc_str = f"\033[38;5;253m{s.get('description', '')}\033[0m"
                        
                        vis = f"{cfg_str} {c_sep} {id_str} {c_sep} {age_str} {c_sep} {date_str} {c_sep} {desc_str}"
                        meta = {
                            "config": s['config_name'], 
                            "id": s.get('id'), 
                            "date": date_str.strip(), 
                            "desc": desc_str.strip(), 
                            "location": s.get('location'),
                            "age": s.get('age', ''),
                            "user": s.get('user', ''),
                            "cleanup": s.get('cleanup', '')
                        }
                        lines_for_fzf.append(f"{vis}\x1f{json.dumps(meta)}")
                else:
                    dummy_vis = f"\033[38;5;246m{'Empty':<8}\033[0m {c_sep} {'':>4} {c_sep} {'':<10} {c_sep} {'No snapshots detected':<18} {c_sep}"
                    lines_for_fzf.append(f"{dummy_vis}\x1f{json.dumps({'empty': True})}")

            case "subvolumes":
                table_hdr = f"\033[1;38;5;242m{'ID':>4}\033[0m {c_sep} \033[1;38;5;242m{'MOUNT TARGET':<15}\033[0m {c_sep} \033[1;38;5;242mPATH\033[0m"
                lines_for_fzf.extend([mode_hdr, hr, table_hdr])
                
                subvols = get_all_subvolumes()
                if subvols:
                    for sv in sorted(subvols, key=lambda x: x['mount_target']):
                        id_str = f"\033[1;38;5;39m{sv['id']:>4}\033[0m"
                        mnt_str = f"\033[38;5;220m{sv['mount_target']:<15}\033[0m"
                        path_str = f"\033[38;5;253m{sv['full_path']}\033[0m"
                        
                        vis = f"{id_str} {c_sep} {mnt_str} {c_sep} {path_str}"
                        lines_for_fzf.append(f"{vis}\x1f{json.dumps(sv)}")
                else:
                    dummy_vis = f"\033[38;5;246m{'N/A':>4}\033[0m {c_sep} {'No subvolumes':<15} {c_sep}"
                    lines_for_fzf.append(f"{dummy_vis}\x1f{json.dumps({'empty': True})}")

        preview_cmd = f"{executable} {script_path} --tui-preview {current_view} {{}}"

        # Latest FZF 0.73.1 bracket notation methodology perfectly encapsulating the FZF actions
        transform_cmd = 'echo "print(click-header:$FZF_CLICK_HEADER_LINE:$FZF_CLICK_HEADER_COLUMN)+accept"'
        click_bind = f"click-header:transform[{transform_cmd}]"

        # Native terminal interruption via code 130 is preserved here.
        fzf_cmd = [
            "fzf", "--ansi", "--reverse", "--delimiter=\\x1f", "--with-nth=1",
            "--header-lines=3", "--border=rounded", "--border-label", " Dusky BTRFS Controller ",
            "--prompt= :: Action ❯ ", f"--color={fzf_colors}", "--pointer=▌", "--marker=▶",
            "--no-hscroll", "--expect=enter,ctrl-d,delete,tab,ctrl-s,ctrl-n,ctrl-b,ctrl-g",
            f"--bind={click_bind}",
            "--info=hidden", "--preview", preview_cmd, "--preview-window", "right,45%,border-left,wrap"
        ]

        try:
            process = subprocess.Popen(fzf_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            stdout, _ = process.communicate(input="\n".join(lines_for_fzf))
            process.wait()
        except Exception as exc:
            fail(f"[!] FZF Execution failed: {exc}")

        # Trap SIGINT cleanly
        if process.returncode in (130, 2):
            print("\n\033[1;38;5;196m[!] Terminated by user.\033[0m", file=sys.stderr)
            sys.exit(130)

        if not stdout.strip(): break

        output_lines = stdout.strip().split("\n")
        key_pressed = output_lines[0]
        
        # Process the newly captured mouse-click stream directly matching the columns layout
        clicked_tab = False
        for out_line in output_lines:
            if out_line.startswith("click-header:"):
                parts = out_line.split(":")
                if len(parts) >= 3:
                    line = int(parts[1]) if parts[1].isdigit() else 0
                    col = int(parts[2]) if parts[2].isdigit() else 0
                    
                    # Flexibility if user slightly clicks near the border
                    if line in (1, 2, 3):
                        # Measured hitboxes perfectly matching the lengths of:
                        # " 󰆑 SYSTEM SNAPSHOTS " (24 columns) vs " 󰋊 BTRFS SUBVOLUMES " 
                        if col <= 24:
                            view_idx = 0      # snapper
                        else:
                            view_idx = 1      # subvolumes
                        clicked_tab = True
                break
        
        if clicked_tab:
            continue
        
        if key_pressed == "tab":
            view_idx = (view_idx + 1) % len(views)
            continue
            
        if len(output_lines) < 2: continue
            
        selected_meta = json.loads(output_lines[1].split('\x1f')[1])
        if selected_meta.get("empty"): continue 

        match current_view:
            case "snapper":
                cfg = selected_meta['config']
                sid = selected_meta['id']
                loc = selected_meta['location']

                match key_pressed:
                    case "enter":
                        print(f"\n\033[1;38;5;81m[*] ACTION: RESTORE SNAPSHOT (Config: {cfg} | ID: {sid})\033[0m")
                        if confirm_prompt("DANGER: Rollback active system state?"):
                            handle_restore(cfg, str(sid), False)
                    case "delete" | "ctrl-d":
                        print(f"\n\033[1;38;5;196m[*] ACTION: DELETE SNAPSHOT (Config: {cfg} | ID: {sid})\033[0m")
                        if confirm_prompt("Permanently delete this snapshot?"):
                            run_cmd(["snapper", "-c", cfg, "delete", str(sid)])
                    case "ctrl-b":
                        print(f"\n\033[1;38;5;213m[*] ACTION: EXTERNAL BACKUP (Send/Receive)\033[0m")
                        print(f"[*] Source: {loc}")
                        try:
                            dest = input("\033[1;38;5;220m[*] Enter Destination Path (e.g., /mnt/ExternalDrive): \033[0m").strip()
                            if dest: backup_snapshot_to_external(loc, dest)
                        except KeyboardInterrupt: pass
                        input("\n\033[1;38;5;114mPress Enter to return...\033[0m")
                    case "ctrl-s":
                        print(f"\n\033[1;38;5;81m[*] ACTION: CREATE SNAPSHOT ({cfg})\033[0m")
                        try:
                            desc = input("\033[1;38;5;220m[*] Description: \033[0m").strip()
                            if desc: run_cmd(["snapper", "-c", cfg, "create", "-d", desc])
                        except KeyboardInterrupt: pass

            case "subvolumes":
                target_path = selected_meta['full_path']

                match key_pressed:
                    case "ctrl-n":
                        print(f"\n\033[1;38;5;213m[*] ACTION: CREATE NEW SUBVOLUME\033[0m")
                        try:
                            parent = input("\033[1;38;5;220m[*] Parent Directory (e.g., /mnt/data): \033[0m").strip()
                            name = input("\033[1;38;5;220m[*] New Subvolume Name: \033[0m").strip()
                            if parent and name:
                                disable_cow = confirm_prompt("Disable Copy-On-Write (NOCOW / chattr +C)?")
                                create_nocow_subvolume(parent, name, disable_cow)
                        except KeyboardInterrupt: pass
                        input("\n\033[1;38;5;114mPress Enter to return...\033[0m")
                    case "ctrl-s":
                        print(f"\n\033[1;38;5;81m[*] ACTION: CREATE NATIVE BTRFS SNAPSHOT\033[0m")
                        print(f"[*] Source: {target_path}")
                        try:
                            dest = input("\033[1;38;5;220m[*] Destination path (incl. new name): \033[0m").strip()
                            if dest:
                                is_ro = confirm_prompt("Make snapshot Read-Only?")
                                cmd = ["btrfs", "subvolume", "snapshot"]
                                if is_ro: cmd.append("-r")
                                cmd.extend([target_path, dest])
                                run_cmd(cmd)
                                print("\033[1;38;5;114m[+] Snapshot created successfully.\033[0m")
                        except KeyboardInterrupt: pass
                        input("\n\033[1;38;5;114mPress Enter to return...\033[0m")
                    case "ctrl-g":
                        print(f"\n\033[1;38;5;213m[*] ACTION: INITIALIZE SNAPPER CONFIG\033[0m")
                        print(f"[*] Target Subvolume: {target_path}")
                        try:
                            cfg_name = input("\033[1;38;5;220m[*] Name for new Snapper config: \033[0m").strip()
                            if cfg_name:
                                run_cmd(["snapper", "-c", cfg_name, "create-config", target_path])
                                print(f"\033[1;38;5;114m[+] Snapper configuration '{cfg_name}' initialized.\033[0m")
                        except KeyboardInterrupt: pass
                        input("\n\033[1;38;5;114mPress Enter to return...\033[0m")
                    case "ctrl-b":
                        print(f"\n\033[1;38;5;213m[*] ACTION: EXTERNAL BACKUP (Send/Receive)\033[0m")
                        print(f"[*] Source: {target_path}")
                        try:
                            dest = input("\033[1;38;5;220m[*] Enter Destination Path (e.g., /mnt/ExternalDrive): \033[0m").strip()
                            if dest: backup_snapshot_to_external(target_path, dest)
                        except KeyboardInterrupt: pass
                        input("\n\033[1;38;5;114mPress Enter to return...\033[0m")
                    case "delete" | "ctrl-d":
                        print(f"\n\033[1;38;5;196m[*] ACTION: DELETE SUBVOLUME\033[0m")
                        print(f"[*] Target: {target_path}")
                        if confirm_prompt("DANGER: Permanently delete this BTRFS subvolume?") :
                            run_cmd(["btrfs", "subvolume", "delete", target_path])

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--tui-preview":
        _view = sys.argv[2]
        _line = " ".join(sys.argv[3:])
        handle_tui_preview(_view, _line)
        sys.exit(0)

    try:
        ensure_root()
        launch_tui()
    except KeyboardInterrupt:
        print("\n\033[1;38;5;196m[!] Terminated by user.\033[0m", file=sys.stderr)
        sys.exit(130)
