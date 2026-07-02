#!/usr/bin/env python3
"""
Advanced Intel P-Core/E-Core Hotplug Manager (Ultimate Edition)
Kernel 7.1+ | Python 3.14+ | Arch Linux Optimized
BSP-Aware | Race-Condition Immune | Vim-Interactive
"""

import os
import sys
import subprocess
import curses
import time
from pathlib import Path
import argparse

# ==========================================
# 1. Auto-Privilege & Auto-Dependency System
# ==========================================
if os.geteuid() != 0:
    print("\033[93m[!] Elevating to root privileges for CPU management...\033[0m")
    os.execvp("sudo", ["sudo", sys.executable] + sys.argv)

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
except ImportError:
    print("\033[93m[!] Missing 'rich' library. Auto-installing via pacman...\033[0m")
    try:
        subprocess.run(["pacman", "-S", "--needed", "--noconfirm", "python-rich"], check=True)
    except subprocess.CalledProcessError:
        print("\033[91m[X] Failed to install dependencies. Please run: sudo pacman -S python-rich\033[0m")
        sys.exit(1)
    os.execvp(sys.executable, [sys.executable] + sys.argv)

console = Console()

# ==========================================
# 2. Core I/O & Topology Logic
# ==========================================
def safe_read(path: Path, default: str = "") -> str:
    """Safely reads volatile sysfs files to prevent I/O crashes."""
    try:
        if path.is_file():
            return path.read_text().strip()
    except OSError:
        pass
    return default

def hydrate_and_detect_topology() -> tuple[list[int], list[int], set[int]]:
    """
    Safely hydrates offline cores and polls for sysfs topology propagation
    to avoid kernel-level ACPI race conditions. Identifies immutable BSPs.
    """
    p_cores: list[int] = []
    e_cores: list[int] = []
    locked_cores: set[int] = set()
    
    cpu_sysfs = Path("/sys/devices/system/cpu")
    cpu_nodes = sorted(
        [node for node in cpu_sysfs.glob("cpu[0-9]*") if node.is_dir()],
        key=lambda p: int(p.name[3:])
    )
    
    original_states: dict[int, str] = {}

    # HYDRATION PHASE
    for node in cpu_nodes:
        cpu_id = int(node.name[3:])
        online_file = node / "online"
        
        # Kernel 6.5+ Reality: Missing 'online' means immutable Bootstrap Processor (BSP)
        if not online_file.exists():
            locked_cores.add(cpu_id)
            continue
            
        current_state = safe_read(online_file)
        original_states[cpu_id] = current_state
        
        if current_state == "0":
            try:
                online_file.write_text("1")
                # ANTI-RACE CONDITION: Wait for kernel kobject workers to build topology
                topology_dir = node / "topology"
                for _ in range(10): # Max wait 50ms per core
                    if topology_dir.exists():
                        break
                    time.sleep(0.005)
            except OSError:
                pass

    # DETECTION PHASE
    for node in cpu_nodes:
        cpu_id = int(node.name[3:])
        topology_dir = node / "topology"
        
        core_type_val = safe_read(topology_dir / "core_type")
        if core_type_val in ("1", "0x10", "intel_atom"):
            e_cores.append(cpu_id)
            continue
        elif core_type_val in ("2", "0x20", "intel_core", "0"):
            p_cores.append(cpu_id)
            continue

        # SMT hardware fallback
        core_cpus = safe_read(topology_dir / "core_cpus_list")
        if core_cpus and ("," in core_cpus or "-" in core_cpus):
            p_cores.append(cpu_id)
        else:
            e_cores.append(cpu_id)

    # DEHYDRATION PHASE
    for cpu_id, original_state in original_states.items():
        if original_state == "0":
            try:
                Path(f"/sys/devices/system/cpu/cpu{cpu_id}/online").write_text("0")
            except OSError:
                pass

    return sorted(p_cores), sorted(e_cores), locked_cores

def get_core_status(cpu_id: int) -> bool:
    return safe_read(Path(f"/sys/devices/system/cpu/cpu{cpu_id}/online"), default="1") == "1"

def set_core_status(cpu_id: int, enable: bool) -> tuple[bool, str]:
    online_file = Path(f"/sys/devices/system/cpu/cpu{cpu_id}/online")
    target_state = "1" if enable else "0"
    
    if not online_file.exists():
         return False, "Hardware Blocked (BSP/Immutable)"
    if safe_read(online_file) == target_state:
         return True, "Already in target state"
         
    try:
        online_file.write_text(target_state)
        if safe_read(online_file) == target_state:
             return True, "Success"
        return False, "Kernel overridden change"
    except OSError as e:
        return False, f"Locked ({e.strerror})"

# ==========================================
# 3. Interactive UI (Curses with Vim Keys)
# ==========================================
def interactive_mode(stdscr, p_cores: list[int], e_cores: list[int], locked_cores: set[int]) -> None:
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    
    curses.init_pair(1, curses.COLOR_BLUE, -1)   
    curses.init_pair(2, curses.COLOR_GREEN, -1)  
    curses.init_pair(3, curses.COLOR_RED, -1)    
    curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_WHITE) 
    curses.init_pair(5, curses.COLOR_YELLOW, -1) 

    all_cores = sorted(p_cores + e_cores)
    current_row = 0
    feedback_msg = ""
    last_key_was_g = False

    while True:
        stdscr.clear()
        max_y, max_x = stdscr.getmaxyx()
        
        stdscr.addstr(0, 0, " Live CPU Core Manager (Vim Mode) ", curses.A_REVERSE | curses.color_pair(2))
        
        if max_y < 10:
            stdscr.addstr(1, 0, "Terminal too small!", curses.color_pair(3))
            stdscr.refresh()
            stdscr.getch()
            continue
            
        stdscr.addstr(1, 0, "Controls: ", curses.A_BOLD)
        stdscr.addstr(1, 10, "[j/k] Nav  [Ctrl+u/d] Jump  [gg/G] Top/Bottom  [SPACE] Toggle  [E/P/A] Batch  [Q] Quit")
        
        if feedback_msg:
            stdscr.addstr(2, 0, f" Status: {feedback_msg} ", curses.color_pair(3) | curses.A_BOLD)
        else:
            stdscr.addstr(2, 0, " " * (max_x - 1))

        stdscr.addstr(4, 2, f"{'CORE':<6} | {'ARCHITECTURE':<20} | {'STATE':<14}", curses.A_UNDERLINE)

        visible_rows = max_y - 6 
        half_page = visible_rows // 2
        
        start_row = max(0, current_row - visible_rows // 2)
        end_row = min(len(all_cores), start_row + visible_rows)
        
        if end_row - start_row < visible_rows and len(all_cores) > visible_rows:
            start_row = max(0, len(all_cores) - visible_rows)
            end_row = len(all_cores)

        for idx in range(start_row, end_row):
            core = all_cores[idx]
            is_locked = core in locked_cores
            is_online = get_core_status(core)
            
            arch = "P-Core (Performance)" if core in p_cores else "E-Core (Efficiency)"
            arch_color = curses.color_pair(1) if core in p_cores else curses.color_pair(2)
            
            if is_locked:
                status_str = "BSP [Locked]"
                status_color = curses.color_pair(5)
            else:
                status_str = "Online" if is_online else "Sleeping"
                status_color = curses.color_pair(2) if is_online else curses.color_pair(3)
            
            y_pos = 5 + (idx - start_row)
            
            if idx == current_row:
                stdscr.addstr(y_pos, 2, f"CPU {core:02d} | {arch:<20} | {status_str:<14}", curses.color_pair(4))
            else:
                stdscr.addstr(y_pos, 2, f"CPU {core:02d} | ", curses.A_NORMAL)
                stdscr.addstr(y_pos, 11, f"{arch:<20}", arch_color)
                stdscr.addstr(y_pos, 34, f"| {status_str:<14}", status_color)

        stdscr.refresh()
        
        key = stdscr.getch()
        feedback_msg = ""
        
        if key in (curses.KEY_UP, ord('k')):
            if current_row > 0: current_row -= 1
        elif key in (curses.KEY_DOWN, ord('j')):
            if current_row < len(all_cores) - 1: current_row += 1
        elif key == 4: 
            current_row = min(len(all_cores) - 1, current_row + half_page)
        elif key == 21: 
            current_row = max(0, current_row - half_page)
        elif key == ord('G'):
            current_row = len(all_cores) - 1
        elif key == ord('g'):
            if last_key_was_g:
                current_row = 0
                last_key_was_g = False
            else:
                last_key_was_g = True
                continue 
                
        elif key == ord(' '):
            core = all_cores[current_row]
            if core in locked_cores:
                feedback_msg = f"CPU {core:02d} is the Bootstrap Processor (Immutable)."
            else:
                current_state = get_core_status(core)
                success, msg = set_core_status(core, enable=not current_state)
                if not success:
                    feedback_msg = f"CPU {core:02d}: {msg}"
                    
        elif key in (ord('e'), ord('E')):
            for c in p_cores:
                if c not in locked_cores: set_core_status(c, False)
            for c in e_cores: 
                if c not in locked_cores: set_core_status(c, True)
            feedback_msg = "Power Saving Mode Activated"
            
        elif key in (ord('p'), ord('P')):
            for c in e_cores:
                if c not in locked_cores: set_core_status(c, False)
            for c in p_cores:
                if c not in locked_cores: set_core_status(c, True)
            feedback_msg = "Performance Mode Activated"
            
        elif key in (ord('a'), ord('A')):
            for c in all_cores:
                if c not in locked_cores: set_core_status(c, True)
            feedback_msg = "All Cores Online"
            
        elif key in (ord('q'), ord('Q')):
            break
            
        last_key_was_g = False 

# ==========================================
# 4. CLI Fallback & Formatting
# ==========================================
def parse_core_args(args_list: list[str]) -> list[int]:
    """Parses lists of cores and ranges (e.g., '1', '12-15')."""
    cores = set()
    try:
        for arg in args_list:
            if "-" in arg:
                start, end = map(int, arg.split("-"))
                cores.update(range(start, end + 1))
            else:
                cores.add(int(arg))
        return sorted(list(cores))
    except ValueError:
        console.print("[bold red]Error:[/bold red] Invalid format. Use numbers or ranges (e.g., 1 2 12-15)")
        sys.exit(1)

def display_status_table(p_cores: list[int], e_cores: list[int], locked_cores: set[int]) -> None:
    table = Table(title="Live CPU Core Topology & ACPI Status", show_header=True, header_style="bold cyan")
    table.add_column("Logical Core ID", justify="center")
    table.add_column("Microarchitecture", justify="center")
    table.add_column("Kernel Hotplug State", justify="center")
    
    for core in sorted(p_cores + e_cores):
        arch = "[bold blue]P-Core (Performance)[/bold blue]" if core in p_cores else "[bold green]E-Core (Efficiency)[/bold green]"
        
        if core in locked_cores:
            status_str = "[bold yellow]BSP [Locked][/bold yellow]"
        else:
            status = get_core_status(core)
            status_str = "[bold green]Online (Active)[/bold green]" if status else "[bold red]Offline (Sleeping)[/bold red]"
            
        table.add_row(f"CPU {core:02d}", arch, status_str)
        
    console.print(table)

def batch_process_cores(cores: list[int], enable: bool, action_name: str, locked_cores: set[int]) -> None:
    console.print(f"[bold yellow]Initiating {action_name} Sequence...[/bold yellow]")
    for core in cores:
        if core in locked_cores:
            continue # Silently skip the immutable Bootstrap Processor
        success, msg = set_core_status(core, enable=enable)
        color = "green" if success else "yellow"
        console.print(f"CPU {core:02d}: [{color}]{msg}[/{color}]")

def main() -> None:
    p_cores, e_cores, locked_cores = hydrate_and_detect_topology()
    all_known_cores = p_cores + e_cores

    if not e_cores:
        console.print(Panel("[bold red]Symmetric Topology Detected![/bold red] No E-cores found.", border_style="red"))
        sys.exit(1)

    if len(sys.argv) == 1:
        curses.wrapper(interactive_mode, p_cores, e_cores, locked_cores)
        sys.exit(0)

    parser = argparse.ArgumentParser(description="Advanced Hybrid Core Hotplug Manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # General Subcommands
    subparsers.add_parser("interactive", help="Launch the Live TUI (Default if no args)")
    subparsers.add_parser("status", help="View topology and core states")
    subparsers.add_parser("ecores-only", help="Disable P-Cores, Enable E-Cores")
    subparsers.add_parser("pcores-only", help="Disable E-Cores, Enable P-Cores")
    subparsers.add_parser("all-cores", help="Enable all cores")

    # Specific Core Control Subcommands
    toggle_p = subparsers.add_parser("toggle", help="Toggle state of specific cores")
    toggle_p.add_argument("cores", nargs="+", help="Core IDs (e.g., 1 2 or 12-15)")
    
    enable_p = subparsers.add_parser("enable", help="Enable specific cores")
    enable_p.add_argument("cores", nargs="+", help="Core IDs (e.g., 12-15)")
    
    disable_p = subparsers.add_parser("disable", help="Disable specific cores")
    disable_p.add_argument("cores", nargs="+", help="Core IDs (e.g., 1 2 3)")

    args = parser.parse_args()

    match args.command:
        case "interactive":
            curses.wrapper(interactive_mode, p_cores, e_cores, locked_cores)
        case "status":
            display_status_table(p_cores, e_cores, locked_cores)
        case "ecores-only":
            batch_process_cores(e_cores, enable=True, action_name="E-Core Wakeup", locked_cores=locked_cores)
            batch_process_cores(p_cores, enable=False, action_name="P-Core Shutdown", locked_cores=locked_cores)
            console.print(Panel("[bold green]Power Saving Mode Activated (E-Cores Only).[/bold green]", border_style="green"))
            display_status_table(p_cores, e_cores, locked_cores)
        case "pcores-only":
            batch_process_cores(p_cores, enable=True, action_name="P-Core Wakeup", locked_cores=locked_cores)
            batch_process_cores(e_cores, enable=False, action_name="E-Core Shutdown", locked_cores=locked_cores)
            console.print(Panel("[bold green]High Performance Mode Activated (P-Cores Only).[/bold green]", border_style="green"))
            display_status_table(p_cores, e_cores, locked_cores)
        case "all-cores":
            batch_process_cores(all_known_cores, enable=True, action_name="Global Wakeup", locked_cores=locked_cores)
            console.print(Panel("[bold green]Maximum Throughput Activated (All Cores Online).[/bold green]", border_style="green"))
            display_status_table(p_cores, e_cores, locked_cores)
        case "enable":
            target_cores = parse_core_args(args.cores)
            batch_process_cores(target_cores, enable=True, action_name="Targeted Wakeup", locked_cores=locked_cores)
            display_status_table(p_cores, e_cores, locked_cores)
        case "disable":
            target_cores = parse_core_args(args.cores)
            batch_process_cores(target_cores, enable=False, action_name="Targeted Shutdown", locked_cores=locked_cores)
            display_status_table(p_cores, e_cores, locked_cores)
        case "toggle":
            target_cores = parse_core_args(args.cores)
            console.print("[bold yellow]Initiating Targeted Toggle Sequence...[/bold yellow]")
            for core in target_cores:
                if core in locked_cores:
                    console.print(f"CPU {core:02d}: [yellow]Skipped (BSP/Immutable)[/yellow]")
                    continue
                current_state = get_core_status(core)
                success, msg = set_core_status(core, enable=not current_state)
                color = "green" if success else "yellow"
                action = "Enabled" if not current_state else "Disabled"
                console.print(f"CPU {core:02d} -> {action}: [{color}]{msg}[/{color}]")
            display_status_table(p_cores, e_cores, locked_cores)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
