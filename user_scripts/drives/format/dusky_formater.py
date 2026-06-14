#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Dusky Formatter v5.3 (Architect Edition - Hardened)
A cutting-edge, interactive TUI for securely formatting and encrypting drives.
Engineered for modern Arch Linux environments (Kernel 7.0+, Python 3.14.5).
"""

import os
import sys
import subprocess
import json
import shlex
import uuid
import time
from typing import Any, Optional, TypedDict

# ==============================================================================
# 1. ARCHITECTURAL TYPE DEFINITIONS
# ==============================================================================

class FormatPlan(TypedDict):
    device: str
    encrypt: bool
    fs_type: str
    csum: Optional[str]
    label: str
    passphrase: Optional[str]

class ExecutionStep(TypedDict):
    action: str
    desc: str
    cmd: list[str]
    interactive: bool
    input_data: Optional[str]

# ==============================================================================
# 2. AUTO-ELEVATION & DEPENDENCY RESOLUTION
# ==============================================================================

if os.geteuid() != 0:
    print("\033[1;33m[!] Dusky Formatter requires root privileges. Elevating via sudo...\033[0m")
    try:
        os.execvp("sudo", ["sudo", sys.executable] + sys.argv)
    except Exception as e:
        print(f"\033[1;31m[x] Critical error during privilege escalation: {e}\033[0m")
        sys.exit(1)

try:
    from rich.console import Console
    from rich.table import Table
    from rich.prompt import Prompt, Confirm
    from rich.panel import Panel
    from rich.syntax import Syntax
except ImportError:
    print("\033[1;36m[*] Missing 'rich' TUI library. Automatically resolving via pacman...\033[0m")
    try:
        subprocess.run(["pacman", "-S", "--needed", "--noconfirm", "python-rich"], check=True)
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except subprocess.CalledProcessError:
        print("\033[1;31m[x] Failed to auto-install dependencies. Please check your pacman configuration.\033[0m")
        sys.exit(1)

console = Console()

# ==============================================================================
# 3. DEVICE PROBING & SYSTEM INTELLIGENCE
# ==============================================================================

def get_val(d: dict[str, Any], key: str, default: Any = "") -> Any:
    if not isinstance(d, dict): return default
    val = d.get(key.lower())
    if val is None:
        val = d.get(key.upper())
    return val if val is not None else default

def get_mount_options() -> dict[str, dict[str, str]]:
    cmd = ["findmnt", "-A", "-l", "--json", "-o", "TARGET,FSTYPE,OPTIONS"]
    mounts: dict[str, dict[str, str]] = {}
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            for fs in data.get("filesystems", []):
                target = get_val(fs, "target")
                if target:
                    mounts[target] = {
                        "fstype": get_val(fs, "fstype", "unknown"),
                        "flags": get_val(fs, "options", "unknown")
                    }
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        console.print("[bold yellow]Warning:[/] Could not parse findmnt output.")
    return mounts

def get_block_devices() -> list[dict[str, Any]]:
    cmd = ["lsblk", "--json", "--tree", "-o", "NAME,PATH,MODEL,TYPE,SIZE,FSTYPE,LABEL,MOUNTPOINTS"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        return data.get("blockdevices", [])
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        console.print("[bold red]Critical Error:[/] Failed to parse lsblk output. Is util-linux functioning?")
        sys.exit(1)

def get_all_paths(devices: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for dev in devices:
        path = get_val(dev, "path")
        if path:
            paths.append(path)
        if "children" in dev:
            paths.extend(get_all_paths(get_val(dev, "children", [])))
    return paths

def get_all_mountpoints(device_node: Optional[dict[str, Any]]) -> list[str]:
    if not device_node:
        return []
    mounts: list[str] = []
    raw_mounts = get_val(device_node, "mountpoints", [])
    if isinstance(raw_mounts, list):
        mounts.extend([m for m in raw_mounts if m])
    for child in get_val(device_node, "children", []):
        mounts.extend(get_all_mountpoints(child))
    return mounts

def is_mounted_recursively(device_node: Optional[dict[str, Any]]) -> bool:
    if not device_node: 
        return False
        
    mounts = get_val(device_node, "mountpoints", [])
    if isinstance(mounts, list) and any(m for m in mounts if m):
        return True
        
    for child in get_val(device_node, "children", []):
        if is_mounted_recursively(child):
            return True
            
    return False

def find_device_node(devices: list[dict[str, Any]], target_path: str) -> Optional[dict[str, Any]]:
    for dev in devices:
        if get_val(dev, "path") == target_path:
            return dev
        if "children" in dev:
            found = find_device_node(get_val(dev, "children", []), target_path)
            if found:
                return found
    return None

def display_device_tree(devices: list[dict[str, Any]], table: Table, mount_data: dict[str, dict[str, str]], level: int = 0) -> None:
    for dev in devices:
        if get_val(dev, "type") in ["loop", "rom"] and level == 0:
            continue
            
        path = get_val(dev, "path", "N/A")
        indent = "  " * level + ("[blue]└─[/] " if level > 0 else "")
        
        model = get_val(dev, "model", "").strip()
        dev_type = get_val(dev, "type", "").strip()
        label = get_val(dev, "label", "").strip()
        
        if label:
            identity_str = f"[green]{label}[/]\n[dim]({dev_type})[/]"
        elif model:
            identity_str = f"[yellow]{model}[/]\n[dim]({dev_type})[/]"
        else:
            identity_str = f"[dim]({dev_type})[/]"
        
        size = get_val(dev, "size", "N/A")
        fstype = get_val(dev, "fstype") or "[dim]Raw[/]"
        
        raw_mounts = get_val(dev, "mountpoints", [])
        mounts = [m for m in raw_mounts if m] if isinstance(raw_mounts, list) else []
        
        if mounts:
            mount_details = []
            for m in mounts:
                data = mount_data.get(m, {})
                m_fmt = data.get("fstype", "unknown")
                raw_flags = data.get("flags", "unknown")
                display_flags = raw_flags.replace(",", ", ")
                mount_details.append(f"[bold white]{m}[/] [dim cyan]({m_fmt})[/]\n[dim magenta]↳ {display_flags}[/]")
            mount_str = "\n".join(mount_details)
        elif is_mounted_recursively(dev):
            mount_str = "[dim yellow]↳ Active Child Mount[/]"
        else:
            mount_str = "[dim]Unmounted[/]"

        table.add_row(f"{indent}{path}", identity_str, size, fstype, mount_str)

        if "children" in dev:
            display_device_tree(get_val(dev, "children", []), table, mount_data, level + 1)

def resolve_busy_processes(mountpoint: str) -> bool:
    try:
        res = subprocess.run(["lsof", "+f", "--", mountpoint], capture_output=True, text=True)
    except FileNotFoundError:
        console.print("[dim yellow]Note: 'lsof' is not installed. Cannot scan for busy processes.[/]")
        return False

    if res.returncode != 0 or not res.stdout.strip():
        return False

    lines = res.stdout.strip().split("\n")
    if len(lines) <= 1:
        return False

    processes = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 3:
            pid = parts[1]
            if not any(p["pid"] == pid for p in processes):
                processes.append({
                    "cmd": parts[0],
                    "pid": pid,
                    "user": parts[2]
                })

    if not processes:
        return False

    console.print(Panel(
        f"[bold red]⚠️  WARNING: FILESYSTEM IS BUSY ⚠️[/]\n\n"
        f"The following processes are currently locking [bold white]{mountpoint}[/]\n"
        "Force-closing them will result in unsaved data loss.",
        title="Filesystem Locked", border_style="red"
    ))

    table = Table(show_header=True, header_style="bold yellow", border_style="yellow")
    table.add_column("COMMAND", style="cyan")
    table.add_column("PID", justify="right", style="yellow")
    table.add_column("USER")

    for p in processes:
        table.add_row(p["cmd"], p["pid"], p["user"])

    console.print(table)
    console.print()

    ans = Confirm.ask("Forcefully terminate all listed processes (SIGKILL) to free the drive?", default=False)
    if ans:
        for p in processes:
            console.print(f"Killing {p['cmd']} (PID: {p['pid']})...")
            subprocess.run(["kill", "-9", p['pid']], capture_output=True)
        time.sleep(1)
        return True
    return False

# ==============================================================================
# 4. INTERACTIVE TUI & CONFIGURATION
# ==============================================================================

def generate_secure_mapper_name() -> str:
    return f"dusky_luks_{uuid.uuid4().hex[:8]}"

def interactive_setup() -> FormatPlan:
    console.print(Panel.fit("[bold magenta]Dusky Formatter v5.3[/] - [cyan]Arch Linux Storage & Analysis Utility[/]", border_style="magenta"))
    
    initial_devices = get_block_devices()
    mount_data = get_mount_options()
    
    table = Table(
        title="Live Storage Topology & Active Mount Flags", 
        header_style="bold cyan", 
        border_style="blue", 
        show_lines=True,
        expand=True 
    )
    
    table.add_column("Path", style="bold green", ratio=2, vertical="middle")
    table.add_column("Identity (Label/Model)", vertical="middle", ratio=3)
    table.add_column("Size", justify="right", style="white", no_wrap=True, vertical="middle")
    table.add_column("FS", style="blue", no_wrap=True, vertical="middle")
    table.add_column("Active Mounts & Flags", style="red", ratio=8) 
    
    display_device_tree(initial_devices, table, mount_data)
    console.print(table)
    
    target_device: Optional[str] = None
    
    while True:
        current_devices = get_block_devices()
        valid_paths = get_all_paths(current_devices)
        
        if not target_device:
            target_device = Prompt.ask("\nEnter the [bold green]Path[/] of the device to format (e.g., /dev/nvme0n1p1)")
            
        if not target_device or target_device not in valid_paths or not target_device.startswith("/dev/"):
            console.print("[bold red]Invalid device path selected. Ensure it matches a physical path in the table.[/]")
            target_device = None
            continue
        
        device_node = find_device_node(current_devices, target_device)
        if is_mounted_recursively(device_node):
            active_mounts = get_all_mountpoints(device_node)
            console.print(f"\n[bold red blink]CRITICAL SAFETY LOCK:[/]\n[yellow]{target_device}[/] (or a child volume) is actively mounted at:")
            for m in active_mounts:
                console.print(f"  - [cyan]{m}[/]")
            
            console.print("\n[yellow]Formatting an active mount is strictly prohibited and will corrupt the live filesystem.[/]")
            
            if Confirm.ask("Would you like Dusky Formatter to attempt a [bold red]force unmount[/] now?", default=False):
                unmount_failed = False
                for m in sorted(active_mounts, key=len, reverse=True):
                    console.print(f"[bold yellow]➜[/] Attempting to unmount {m}...")
                    res = subprocess.run(["umount", m], capture_output=True, text=True)
                    
                    if res.returncode == 0:
                        console.print(f"  [bold green]✔ Successfully unmounted {m}[/]")
                    else:
                        console.print(f"  [bold red]✗ Standard unmount failed for {m}. Target is busy.[/]")
                        if resolve_busy_processes(m):
                            res2 = subprocess.run(["umount", m], capture_output=True, text=True)
                            if res2.returncode == 0:
                                console.print(f"  [bold green]✔ Successfully unmounted {m} after force kill.[/]")
                            else:
                                console.print(f"  [bold red]✗ Still unable to unmount {m} (Kernel Lock / Busy).[/]")
                                unmount_failed = True
                        else:
                            unmount_failed = True
                            
                if unmount_failed:
                    console.print("[red]Could not free all mounts. Please resolve manually or reboot if kernel locked.[/]")
                    target_device = None 
                    continue
                else:
                    console.print("[green]All mount points cleared. Verifying state...[/]")
                    continue 
            else:
                console.print("[dim]Aborting selection. Please handle unmounting manually.[/]")
                target_device = None 
                continue

        break

    console.print("\n[bold cyan]--- Security & Encryption ---[/]")
    encrypt = Confirm.ask(f"Encrypt [bold yellow]{target_device}[/] using [bold]LUKS2[/]?", default=False)
    
    passphrase = None
    if encrypt:
        console.print("[dim]Note: Providing the passphrase here enables a fully unattended formatting pipeline.[/]")
        while True:
            p1 = Prompt.ask("Enter a strong LUKS2 passphrase", password=True)
            p2 = Prompt.ask("Verify passphrase", password=True)
            if p1 == p2 and len(p1) > 0:
                passphrase = p1
                break
            else:
                console.print("[bold red]Passphrases do not match or are empty. Try again.[/]")

    console.print("\n[bold cyan]--- Filesystem Configuration ---[/]")
    fs_options = ["btrfs", "ext4", "xfs", "fat32"]
    fs_type = Prompt.ask("Select target filesystem", choices=fs_options, default="btrfs")
    
    csum = None
    if fs_type == "btrfs":
        csum = Prompt.ask("Select BTRFS checksum algorithm", choices=["crc32c", "xxhash", "sha256", "blake2"], default="blake2")

    label = Prompt.ask("Enter a volume label (leave blank for none)", default="")
    if fs_type == "fat32" and len(label) > 11:
        console.print("[bold yellow]Warning:[/] FAT32 limits labels to 11 characters. Truncating.")
        label = label[:11].upper()

    plan: FormatPlan = {
        "device": target_device,
        "encrypt": encrypt,
        "fs_type": fs_type,
        "csum": csum,
        "label": label,
        "passphrase": passphrase
    }

    return plan

# ==============================================================================
# 5. EXECUTION PLAN GENERATION
# ==============================================================================

def build_execution_plan(plan: FormatPlan) -> tuple[list[ExecutionStep], str, Optional[str]]:
    device = plan["device"]
    fs_type = plan["fs_type"]
    label = plan["label"]
    encrypt = plan["encrypt"]
    passphrase = plan.get("passphrase")
    
    commands: list[ExecutionStep] = []
    bash_script = "#!/bin/bash\n# Dusky Formatter Native Execution Pipeline\n# Copy-pasteable syntax directly mirroring system execution:\n\n"
    
    target_block = device
    mapper_name = None

    wipe_cmd = ["wipefs", "--all", device]
    commands.append({
        "action": "wipe_fs",
        "desc": f"Sterilizing target device to remove stale signatures",
        "cmd": wipe_cmd,
        "interactive": False,
        "input_data": None
    })
    bash_script += f"# Clear stale partition tables and filesystems\n{shlex.join(wipe_cmd)}\n\n"

    if encrypt and passphrase:
        mapper_name = generate_secure_mapper_name()
        target_block = f"/dev/mapper/{mapper_name}"
        
        # `-q` runs batch mode (suppressing the manual YES confirmation) 
        # `-` reads the keyfile directly from Standard Input
        luks_fmt = ["cryptsetup", "-q", "luksFormat", "--type", "luks2", device, "-"]
        commands.append({
            "action": "luks_format",
            "desc": "Initializing LUKS2 Encryption Container",
            "cmd": luks_fmt,
            "interactive": False, 
            "input_data": passphrase
        })
        bash_script += f"# Initialize modern LUKS2 Container (Passphrase securely piped)\n"
        bash_script += f"echo -n 'YOUR_PASSPHRASE' | {shlex.join(luks_fmt[:-1])} -\n"
        
        luks_open = ["cryptsetup", "open", "--type", "luks", "--key-file", "-", device, mapper_name]
        commands.append({
            "action": "luks_open",
            "desc": f"Opening encrypted volume as '{mapper_name}'",
            "cmd": luks_open,
            "interactive": False,
            "input_data": passphrase
        })
        bash_script += f"# Map the LUKS volume\n"
        bash_script += f"echo -n 'YOUR_PASSPHRASE' | cryptsetup open --type luks --key-file - {device} {mapper_name}\n\n"

    mkfs_cmd: list[str] = []
    match fs_type:
        case "btrfs":
            csum = plan.get("csum") or "blake2"
            mkfs_cmd = ["mkfs.btrfs", "-f", "--csum", csum] 
            if label: mkfs_cmd.extend(["-L", label])
            mkfs_cmd.append(target_block)
            
        case "ext4":
            mkfs_cmd = ["mkfs.ext4", "-F"] 
            if label: mkfs_cmd.extend(["-L", label])
            mkfs_cmd.append(target_block)
            
        case "xfs":
            mkfs_cmd = ["mkfs.xfs", "-f"]
            if label: mkfs_cmd.extend(["-L", label])
            mkfs_cmd.append(target_block)
            
        case "fat32":
            mkfs_cmd = ["mkfs.fat", "-F", "32", "-I"]
            if label: mkfs_cmd.extend(["-n", label])
            mkfs_cmd.append(target_block)

    commands.append({
        "action": "mkfs",
        "desc": f"Building {fs_type.upper()} filesystem on {target_block}",
        "cmd": mkfs_cmd,
        "interactive": False,
        "input_data": None
    })
    bash_script += f"# Format the block device\n{shlex.join(mkfs_cmd)}\n\n"

    if encrypt:
        close_cmd = ["cryptsetup", "close", mapper_name]
        commands.append({
            "action": "luks_close",
            "desc": f"Locking and securing volume '{mapper_name}'",
            "cmd": close_cmd,
            "interactive": False,
            "input_data": None
        })
        bash_script += f"# Securely lock the container\n{shlex.join(close_cmd)}\n"

    return commands, bash_script, mapper_name

# ==============================================================================
# 6. PIPELINE EXECUTION
# ==============================================================================

def execute_plan(commands: list[ExecutionStep], mapper_name: Optional[str] = None) -> None:
    console.print("\n[bold cyan]Executing Dusky Formatting Plan...[/]")
    luks_is_open = False
    
    try:
        for step in commands:
            # Wrapped in a rich status spinner to prevent the UI from freezing
            # during long background executions like LUKS key benchmarking.
            with console.status(f"[bold yellow]Executing:[/] {step['desc']}...", spinner="dots"):
                try:
                    if step["interactive"]:
                        subprocess.run(step["cmd"], check=True)
                    else:
                        # Dynamically construct kwargs to safely pipe input to the process
                        kwargs: dict[str, Any] = {
                            "capture_output": True,
                            "text": True,  # Allows str I/O, subprocess handles encoding autonomously
                            "check": True
                        }
                        if step.get("input_data") is not None:
                            kwargs["input"] = step["input_data"]
                            
                        subprocess.run(step["cmd"], **kwargs)
                    
                    if step["action"] == "luks_open":
                        luks_is_open = True
                    elif step["action"] == "luks_close":
                        luks_is_open = False
                        
                except subprocess.CalledProcessError as e:
                    console.print(f"[bold red]Fatal Error executing:[/] {shlex.join(step['cmd'])}")
                    if not step["interactive"] and e.stderr is not None:
                        console.print(f"[red]Kernel/API Output:\n{e.stderr.strip()}[/]")
                    raise Exception("Execution pipeline aborted.")
            
            # Print a permanent success message once the spinner disappears
            console.print(f"[bold green]✔[/] {step['desc']} [dim](Completed)[/]")
                
        console.print("\n[bold green]✔ All formatting operations successfully completed![/]")

    except Exception as e:
        console.print(f"\n[bold red]Operation Failed: {str(e)}[/]")
        sys.exit(1)
        
    finally:
        if luks_is_open and mapper_name:
            console.print(f"\n[bold yellow]➜[/] Emergency fallback: Locking dangling LUKS volume '{mapper_name}'...")
            try:
                subprocess.run(["cryptsetup", "close", mapper_name], capture_output=True, check=True)
                console.print("[bold green]✔ Volume locked cleanly.[/]")
            except subprocess.CalledProcessError:
                console.print(f"[bold red]Warning: Failed to auto-lock mapper '{mapper_name}'. Please unmount manually.[/]")

# ==============================================================================
# ENTRY POINT
# ==============================================================================

def main() -> None:
    plan = interactive_setup()
    commands, bash_equivalent, mapper_name = build_execution_plan(plan)
    
    console.print("\n[bold green]Command Execution Pipeline (Educational Transparency):[/]")
    syntax = Syntax(bash_equivalent, "bash", theme="monokai", line_numbers=True)
    console.print(Panel(syntax, title="Raw Subprocess Translation", border_style="green"))
    
    console.print(f"\n[bold red blink]WARNING:[/] ALL DATA ON [bold yellow]{plan['device']}[/] WILL BE PERMANENTLY ERASED.")
    if Confirm.ask("Are you absolutely confident you wish to proceed?", default=False):
        execute_plan(commands, mapper_name)
    else:
        console.print("[yellow]Operation aborted. Your data remains untouched.[/]")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Process interrupted via keyboard. Exiting cleanly.[/]")
        sys.exit(1)
