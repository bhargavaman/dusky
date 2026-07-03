#!/usr/bin/env python3
"""
Dusky Core Affinity Wrapper - Final Golden Release
Python 3.14+ | Optimized for Arch Linux Kernel 7.1.2+
"""

import os
import sys
import subprocess
import argparse
import shutil
from pathlib import Path
from typing import Any

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
except ImportError:
    print("\033[91m[X] The 'rich' library is missing. Install via: sudo pacman -S python-rich\033[0m")
    sys.exit(1)

console = Console()

# ==========================================
# Low-Level Core Utilities
# ==========================================
def safe_read(path: Path, default: str = "") -> str:
    """Safely reads sysfs hardware files."""
    try:
        if path.is_file():
            return path.read_text().strip()
    except OSError:
        pass
    return default

def parse_cpu_list(cpu_list_str: str) -> list[int]:
    """Robustly parses sysfs cpu lists like '0-3,8-11' into discrete integers."""
    cores: set[int] = set()
    for part in cpu_list_str.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            try:
                start_str, end_str = part.split('-')
                start, end = int(start_str), int(end_str)
                cores.update(range(start, end + 1))
            except ValueError:
                pass
        elif part.isdigit():
            cores.add(int(part))
    return sorted(list(cores))

def get_core_status(cpu_id: int) -> bool:
    """Checks if a core is actively online in the OS."""
    path = Path(f"/sys/devices/system/cpu/cpu{cpu_id}/online")
    if not path.exists():
        return True  # BSP (Core 0) is permanently online and locked
    return safe_read(path, "1") == "1"

def batch_wake_cores(cpu_ids: list[int]) -> bool:
    """Wakes multiple sleeping cores using a single privilege execution."""
    cmds: list[str] = []
    for cpu_id in cpu_ids:
        path = f"/sys/devices/system/cpu/cpu{cpu_id}/online"
        cmds.append(f"echo 1 > {path}")
    
    if not cmds:
        return True
        
    full_cmd = " ; ".join(cmds)
    
    try:
        if os.geteuid() == 0:
            subprocess.run(['sh', '-c', full_cmd], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(['sudo', 'sh', '-c', full_cmd], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Verify all targets successfully woke up
        return all(get_core_status(c) for c in cpu_ids)
    except subprocess.CalledProcessError:
        return False

# ==========================================
# Topology Detection Engine
# ==========================================
def detect_topology() -> dict[int, dict[str, Any]]:
    """
    Intelligently maps physical hardware to determine 
    Performance vs Efficiency cores using CPPC, Core Type, and SMT structures.
    """
    topology: dict[int, dict[str, Any]] = {}
    cpu_sysfs = Path("/sys/devices/system/cpu")
    cpu_nodes = sorted([node for node in cpu_sysfs.glob("cpu[0-9]*") if node.is_dir()], key=lambda p: int(p.name[3:]))

    # Pre-read CPPC (ACPI) highest performance metrics if available
    cppc_perf: dict[int, int] = {}
    for node in cpu_nodes:
        cpu_id = int(node.name[3:])
        perf_str = safe_read(node / "acpi_cppc" / "highest_perf")
        if perf_str.isdigit():
            cppc_perf[cpu_id] = int(perf_str)

    # Calculate CPPC midpoint to identify P vs E
    cppc_midpoint = 0.0
    if cppc_perf:
        unique_perfs = sorted(list(set(cppc_perf.values())))
        if len(unique_perfs) > 1:
            cppc_midpoint = (unique_perfs[0] + unique_perfs[-1]) / 2.0

    # Determine SMT sibling groups
    smt_siblings: dict[int, list[int]] = {}
    for node in cpu_nodes:
        cpu_id = int(node.name[3:])
        core_cpus = safe_read(node / "topology" / "core_cpus_list")
        siblings = parse_cpu_list(core_cpus) if core_cpus else [cpu_id]
        smt_siblings[cpu_id] = siblings

    # Classify each node
    for node in cpu_nodes:
        cpu_id = int(node.name[3:])
        core_type_val = safe_read(node / "topology" / "core_type")
        c_type = "P"

        # Check 1: CPPC Disparity (Best for AMD / Newer Intel)
        if cppc_perf and cppc_midpoint > 0:
            c_type = "P" if cppc_perf.get(cpu_id, 0) > cppc_midpoint else "E"
        # Check 2: Intel explicit core_type flag
        elif core_type_val in ("1", "0x10", "intel_atom"):
            c_type = "E"
        elif core_type_val in ("2", "0x20", "intel_core"):
            c_type = "P"
        # Check 3: SMT Fallback heuristic
        else:
            siblings = smt_siblings.get(cpu_id, [cpu_id])
            if len(siblings) > 1:
                c_type = "P"
            else:
                is_sibling_of_smt = any(
                    other_id != cpu_id and cpu_id in sib_list and len(sib_list) > 1 
                    for other_id, sib_list in smt_siblings.items()
                )
                c_type = "E" if not is_sibling_of_smt else "P"

        topology[cpu_id] = {
            "type": c_type,
            "online": get_core_status(cpu_id),
            "smt_group": smt_siblings.get(cpu_id, [cpu_id])
        }

    # Failsafe: Symmetric Processors (Treat all as P-Cores if no mixed types exist)
    has_p = any(data["type"] == "P" for data in topology.values())
    has_e = any(data["type"] == "E" for data in topology.values())
    if not (has_p and has_e):
        for data in topology.values():
            data["type"] = "P"

    return topology

# ==========================================
# UI and Execution Control
# ==========================================
def display_status(topology: dict[int, dict[str, Any]]) -> None:
    """Renders the topology status cleanly to the terminal."""
    console.print(Panel("[bold cyan]System Hardware Topology & Current Status[/bold cyan]", expand=False))
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Core ID", justify="center")
    table.add_column("Architecture", justify="center")
    table.add_column("Current State", justify="center")

    for cpu_id, data in topology.items():
        arch_str = "[bold cyan]P-Core[/bold cyan]" if data["type"] == "P" else "[bold green]E-Core[/bold green]"
        state_str = "[bold green]● Online[/bold green]" if data["online"] else "[dim red]○ Offline[/dim red]"
        table.add_row(f"CPU {cpu_id}", arch_str, state_str)

    console.print(table)

def main() -> None:
    if not shutil.which("taskset"):
        console.print("[bold red]Critical Error:[/bold red] 'taskset' utility not found. Please install the 'util-linux' package.")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Advanced Smart Core Affinity Wrapper")
    parser.add_argument("-s", "--status", action="store_true", help="Print detailed topology and exit")
    parser.add_argument("-t", "--type", choices=["pcores", "ecores", "all"], default="pcores", help="Target architecture tier (default: pcores)")
    parser.add_argument("-c", "--custom", type=str, help="Custom comma/dash separated core list (e.g., 0,2-4,6)")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Application executable and arguments")
    
    args = parser.parse_args()
    topology = detect_topology()

    if args.status:
        display_status(topology)
        sys.exit(0)

    # Standardize command execution list
    if not args.command:
        console.print("[bold red]Execution Error:[/bold red] No target command provided.")
        sys.exit(1)

    if args.command[0] == "--":
        args.command = args.command[1:]
        if not args.command:
            console.print("[bold red]Execution Error:[/bold red] No target command provided after '--'.")
            sys.exit(1)

    # Resolve target cores
    target_cores: list[int] = []
    
    if args.custom:
        target_cores = parse_cpu_list(args.custom)
        invalid_cores = [c for c in target_cores if c not in topology]
        if invalid_cores:
            console.print(f"[bold red]Hardware Error:[/bold red] Cores {invalid_cores} do not exist on this CPU.")
            sys.exit(1)
    else:
        match args.type:
            case "all":
                target_cores = list(topology.keys())
            case "pcores":
                target_cores = [c for c, d in topology.items() if d["type"] == "P"]
            case "ecores":
                target_cores = [c for c, d in topology.items() if d["type"] == "E"]
                if not target_cores:
                    console.print("[bold yellow]Notice:[/bold yellow] No E-Cores exist on this system. Falling back to P-Cores.")
                    target_cores = [c for c, d in topology.items() if d["type"] == "P"]

    if not target_cores:
        console.print("[bold red]Fatal Error:[/bold red] Unable to map target cores.")
        sys.exit(1)

    # Manage Hotplug State / Wake Cores Safely
    offline_targets = [c for c in target_cores if not topology[c]["online"]]
    if offline_targets:
        console.print(Panel(
            f"[bold yellow]Wake Sequence Initiated[/bold yellow]\n"
            f"Target cores {offline_targets} are currently in a deep offline sleep state.\n"
            "Requesting temporary escalation to bridge hardware power state...",
            border_style="yellow", expand=False
        ))
        
        if batch_wake_cores(offline_targets):
            console.print(f"[bold green]✔ Link established. Hardware woken successfully.[/bold green]")
        else:
            console.print("[bold red]✖ ACPI Error: Failed to alter hardware state. Execution aborted.[/bold red]")
            sys.exit(1)

    # Hand off to application execution
    target_cores_str = ",".join(map(str, target_cores))
    console.print(f"[bold green]🚀 Bounding execution to cores:[/bold green] [white]{target_cores_str}[/white]")
    
    taskset_cmd = ["taskset", "-c", target_cores_str] + args.command
    
    # Process replacement
    os.execvp("taskset", taskset_cmd)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
