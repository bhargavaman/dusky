#!/usr/bin/env python3
"""
Dusky Core Manager (v13)
Kernel 7.1+ | Python 3.14+ | Arch Linux Optimized
Features: RAPL Power, Non-Invasive Usage, Percentage-Based C-States
"""

import os
import sys
import subprocess
import curses
import time
from pathlib import Path
import argparse

# ==========================================
# 1. Auto-Privilege & Auto-Dependency
# ==========================================
if os.geteuid() != 0:
    print("\033[93m[!] Elevating to root privileges...\033[0m")
    os.execvp("sudo", ["sudo", sys.executable] + sys.argv)

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.align import Align
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
# 2. Hardware Telemetry & ACPI Logic
# ==========================================
def safe_read(path: Path, default: str = "") -> str:
    try:
        if path.is_file():
            return path.read_text().strip()
    except OSError:
        pass
    return default

def hydrate_and_detect_topology() -> tuple[list[int], list[int], set[int]]:
    p_cores: list[int] = []
    e_cores: list[int] = []
    locked_cores: set[int] = set()
    cpu_sysfs = Path("/sys/devices/system/cpu")
    cpu_nodes = sorted([node for node in cpu_sysfs.glob("cpu[0-9]*") if node.is_dir()], key=lambda p: int(p.name[3:]))
    original_states: dict[int, str] = {}

    for node in cpu_nodes:
        cpu_id = int(node.name[3:])
        online_file = node / "online"
        if not online_file.exists():
            locked_cores.add(cpu_id)
            continue
        current_state = safe_read(online_file)
        original_states[cpu_id] = current_state
        if current_state == "0":
            try:
                online_file.write_text("1")
                topology_dir = node / "topology"
                for _ in range(10): 
                    if topology_dir.exists(): break
                    time.sleep(0.005)
            except OSError:
                pass

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

        core_cpus = safe_read(topology_dir / "core_cpus_list")
        if core_cpus and ("," in core_cpus or "-" in core_cpus):
            p_cores.append(cpu_id)
        else:
            e_cores.append(cpu_id)

    for cpu_id, original_state in original_states.items():
        if original_state == "0":
            try: Path(f"/sys/devices/system/cpu/cpu{cpu_id}/online").write_text("0")
            except OSError: pass

    all_found = sorted(p_cores + e_cores)
    if not locked_cores and all_found:
        locked_cores.add(all_found[0])

    return sorted(p_cores), sorted(e_cores), locked_cores

def get_core_status(cpu_id: int) -> bool:
    return safe_read(Path(f"/sys/devices/system/cpu/cpu{cpu_id}/online"), default="1") == "1"

def set_core_status(cpu_id: int, enable: bool) -> tuple[bool, str]:
    online_file = Path(f"/sys/devices/system/cpu/cpu{cpu_id}/online")
    target_state = "1" if enable else "0"
    if not online_file.exists(): return False, "Locked"
    if safe_read(online_file) == target_state: return True, "Already in target state"
    try:
        online_file.write_text(target_state)
        if safe_read(online_file) == target_state: return True, "Success"
        return False, "Ignored"
    except OSError as e:
        return False, f"Locked ({e.strerror})"

def get_core_freq(cpu_id: int) -> str:
    val = safe_read(Path(f"/sys/devices/system/cpu/cpu{cpu_id}/cpufreq/scaling_cur_freq"))
    if val.isdigit():
        return f"{int(val) // 1000} MHz"
    return "---"

def get_package_power(last_energy: int, last_time: float) -> tuple[str, int, float]:
    path = Path("/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj")
    try:
        if path.exists():
            current_energy = int(path.read_text().strip())
            current_time = time.time()
            if last_energy != 0:
                delta_energy = current_energy - last_energy
                delta_time = current_time - last_time
                if delta_time > 0:
                    watts = (delta_energy / 1_000_000) / delta_time
                    return f"{watts:.1f} W", current_energy, current_time
            return "Calibrating...", current_energy, current_time
    except Exception:
        pass
    return "N/A", last_energy, last_time

def read_cpu_usage(prev_stat: dict) -> tuple[dict, dict]:
    current_stat = {}
    usage_dict = {}
    try:
        with open('/proc/stat', 'r') as f:
            lines = f.readlines()
        for line in lines:
            if line.startswith('cpu') and line[3].isdigit():
                parts = line.split()
                cpu_id = int(parts[0][3:])
                stats = list(map(int, parts[1:9]))
                idle = stats[3] + stats[4]
                non_idle = stats[0] + stats[1] + stats[2] + stats[5] + stats[6] + stats[7]
                total = idle + non_idle
                current_stat[cpu_id] = (total, non_idle)
                
                if cpu_id in prev_stat:
                    prev_total, prev_non_idle = prev_stat[cpu_id]
                    total_delta = total - prev_total
                    non_idle_delta = non_idle - prev_non_idle
                    if total_delta > 0:
                        usage_dict[cpu_id] = f"{(non_idle_delta / total_delta) * 100:.1f}%"
                    else:
                        usage_dict[cpu_id] = "0.0%"
                else:
                    usage_dict[cpu_id] = "..."
    except Exception:
        pass
    return usage_dict, current_stat

def take_cstate_snapshot(active_cores: list[int]) -> dict[int, str]:
    """
    Calculates exact percentage residency to prove C-state oscillation.
    """
    snapshot = {}
    t1_data = {}
    
    for core in active_cores:
        core_path = Path(f"/sys/devices/system/cpu/cpu{core}/cpuidle")
        if not core_path.exists(): continue
        t1_data[core] = {}
        for state_dir in core_path.glob("state*"):
            try:
                name = safe_read(state_dir / "name")
                t_val = safe_read(state_dir / "time")
                if t_val.isdigit(): t1_data[core][name] = int(t_val)
            except OSError: pass

    t_start = time.perf_counter()
    time.sleep(0.15) 
    t_end = time.perf_counter()
    
    elapsed_us = (t_end - t_start) * 1_000_000

    for core in active_cores:
        if core not in t1_data:
            snapshot[core] = "C0 (100%)"
            continue
            
        core_path = Path(f"/sys/devices/system/cpu/cpu{core}/cpuidle")
        state_deltas = {}
        total_idle_us = 0
        
        for state_dir in core_path.glob("state*"):
            try:
                name = safe_read(state_dir / "name")
                t_val = safe_read(state_dir / "time")
                if t_val.isdigit():
                    delta = int(t_val) - t1_data[core].get(name, 0)
                    if delta > 0:
                        state_deltas[name] = delta
                        total_idle_us += delta
            except OSError: pass
            
        # Time remaining in the 150ms window is mathematically Active C0 time
        c0_us = max(0, elapsed_us - total_idle_us)
        state_deltas["C0"] = c0_us
        
        if state_deltas:
            active_state = max(state_deltas, key=state_deltas.get)
            total_tracked = total_idle_us + c0_us
            pct = (state_deltas[active_state] / total_tracked) * 100 if total_tracked > 0 else 0
            snapshot[core] = f"{active_state} ({pct:.0f}%)"
        else:
            snapshot[core] = "C0 (100%)"
        
    return snapshot

# ==========================================
# 3. Interactive Minimalist TUI
# ==========================================
def interactive_mode(stdscr, p_cores: list[int], e_cores: list[int], locked_cores: set[int]) -> None:
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    
    curses.init_pair(1, curses.COLOR_CYAN, -1)     
    curses.init_pair(2, curses.COLOR_GREEN, -1)    
    curses.init_pair(3, curses.COLOR_RED, -1)      
    curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_WHITE) 
    curses.init_pair(5, curses.COLOR_YELLOW, -1)   
    curses.init_pair(6, curses.COLOR_MAGENTA, -1)  
    curses.init_pair(7, curses.COLOR_BLUE, -1)     

    stdscr.timeout(1000)

    all_cores = sorted(p_cores + e_cores)
    current_row = 0
    start_row = 0
    feedback_msg = ""
    show_controls = False
    last_key_was_g = False
    
    last_energy = 0
    last_time = time.time()
    prev_stat = {}
    
    stdscr.addstr(0, 0, " Initializing C-States... ", curses.color_pair(5) | curses.A_REVERSE)
    stdscr.refresh()
    active_cores = [c for c in all_cores if get_core_status(c) or c in locked_cores]
    cstate_data = take_cstate_snapshot(active_cores)
    
    ICON_ON = "●"
    ICON_OFF = "○"
    ICON_LOCK = "" 

    while True:
        stdscr.clear()
        max_y, max_x = stdscr.getmaxyx()
        
        if max_y < 10:
            stdscr.addstr(1, 0, "Terminal too small!", curses.color_pair(3) | curses.A_BOLD)
            stdscr.refresh()
            stdscr.getch()
            continue

        pkg_power, last_energy, last_time = get_package_power(last_energy, last_time)
        usage_dict, prev_stat = read_cpu_usage(prev_stat)

        title = " Dusky Core Manager "
        stdscr.addstr(0, max(0, (max_x - len(title)) // 2), title, curses.A_REVERSE | curses.A_BOLD | curses.color_pair(6))
        
        power_str = f" PKG Power: {pkg_power} | [F1] Toggle Controls "
        stdscr.addstr(1, max(0, (max_x - len(power_str)) // 2), power_str, curses.color_pair(7) | curses.A_BOLD)

        if feedback_msg:
            msg_str = f" Status: {feedback_msg} "
            stdscr.addstr(2, max(0, (max_x - len(msg_str)) // 2), msg_str, curses.color_pair(3) | curses.A_BOLD)

        y_offset = 4
        if show_controls:
            stdscr.addstr(y_offset, 2, "Nav:   ", curses.A_BOLD | curses.color_pair(6))
            stdscr.addstr(y_offset, 9, "[j/k] Up/Down  [Ctrl+u/d] Jump  [SPACE] Toggle  [h] Sleep  [l] Wake")
            y_offset += 1
            stdscr.addstr(y_offset, 2, "Batch: ", curses.A_BOLD | curses.color_pair(6))
            stdscr.addstr(y_offset, 9, "[E] E-Cores Only  [P] P-Cores Only  [M] Minimal (Sleep All)  [A] Wake All")
            y_offset += 1
            stdscr.addstr(y_offset, 2, "Util:  ", curses.A_BOLD | curses.color_pair(6))
            stdscr.addstr(y_offset, 9, "[i] Refresh C-States  [Q] Quit")
            y_offset += 2
            
        header_str = f"{'CORE':<10} | {'TYPE':<8} | {'ST':<4} | {'FREQ':<9} | {'USAGE':<7} | {'C-STATE':<12}"
        stdscr.addstr(y_offset, 2, header_str, curses.A_UNDERLINE | curses.A_BOLD | curses.color_pair(6))

        visible_rows = max_y - (y_offset + 2)
        half_page = visible_rows // 2
        
        if current_row < start_row:
            start_row = current_row
        elif current_row >= start_row + visible_rows:
            start_row = current_row - visible_rows + 1
            
        end_row = min(len(all_cores), start_row + visible_rows)

        for idx in range(start_row, end_row):
            core = all_cores[idx]
            is_locked = core in locked_cores
            is_online = get_core_status(core)
            
            arch = "P-Core" if core in p_cores else "E-Core"
            arch_color = curses.color_pair(1) | curses.A_BOLD if core in p_cores else curses.color_pair(2) | curses.A_BOLD
            
            cstate_str = cstate_data.get(core, "---") if is_online or is_locked else "---"
            usage_str = usage_dict.get(core, "---") if is_online or is_locked else "---"
            
            if is_locked:
                icon_str = f"{ICON_LOCK} "
                status_color = curses.color_pair(5) | curses.A_BOLD
                freq_str = get_core_freq(core)
            else:
                icon_str = f"{ICON_ON} " if is_online else f"{ICON_OFF} "
                status_color = curses.color_pair(2) | curses.A_BOLD if is_online else curses.color_pair(3) | curses.A_DIM
                freq_str = get_core_freq(core) if is_online else "---"
            
            row_y = (y_offset + 1) + (idx - start_row)
            
            core_s = f"CPU {core:02d}     | "
            arch_s = f"{arch:<8} | "
            icon_s = f"{icon_str:<4} | "
            freq_s = f"{freq_str:<9} | "
            usage_s = f"{usage_str:<7} | "
            cstate_s = f"{cstate_str:<12}"
            
            if idx == current_row:
                stdscr.addstr(row_y, 2, f"CPU {core:02d}     | {arch:<8} | {icon_str:<4} | {freq_str:<9} | {usage_str:<7} | {cstate_str:<12}", curses.color_pair(4))
            else:
                stdscr.addstr(row_y, 2, core_s, curses.A_NORMAL)
                stdscr.addstr(row_y, 15, arch_s, arch_color)
                stdscr.addstr(row_y, 26, icon_s, status_color)
                stdscr.addstr(row_y, 33, freq_s + usage_s + cstate_s, curses.A_NORMAL)

        stdscr.refresh()
        
        key = stdscr.getch()
        feedback_msg = ""
        
        if key == curses.ERR: continue
            
        if key in (curses.KEY_UP, ord('k')):
            if current_row > 0: current_row -= 1
        elif key in (curses.KEY_DOWN, ord('j')):
            if current_row < len(all_cores) - 1: current_row += 1
        elif key == 4: current_row = min(len(all_cores) - 1, current_row + half_page)
        elif key == 21: current_row = max(0, current_row - half_page)
        elif key == ord('G'): current_row = len(all_cores) - 1
        elif key == ord('g'):
            if last_key_was_g:
                current_row = 0
                last_key_was_g = False
            else:
                last_key_was_g = True
                continue 
                
        elif key == ord('i'):
            feedback_msg = "Refreshing C-States..."
            stdscr.addstr(2, max(0, (max_x - len(feedback_msg) - 9) // 2), f" Status: {feedback_msg} ", curses.color_pair(5) | curses.A_BOLD)
            stdscr.refresh()
            active_cores = [c for c in all_cores if get_core_status(c) or c in locked_cores]
            cstate_data = take_cstate_snapshot(active_cores)
            feedback_msg = "C-States Updated."
                
        elif key == curses.KEY_F1:
            show_controls = not show_controls
            
        elif key in (ord(' '), ord('h'), ord('l')):
            core = all_cores[current_row]
            if core in locked_cores:
                feedback_msg = f"CPU {core:02d} is locked (BSP)."
            else:
                if key == ord(' '): target_enable = not get_core_status(core)
                elif key == ord('h'): target_enable = False
                elif key == ord('l'): target_enable = True
                
                success, msg = set_core_status(core, enable=target_enable)
                if not success: feedback_msg = msg
                else: 
                    if not target_enable and core in cstate_data:
                        del cstate_data[core]
                    
        elif key in (ord('e'), ord('E')):
            for c in p_cores:
                if c not in locked_cores: set_core_status(c, False)
            for c in e_cores: 
                if c not in locked_cores: set_core_status(c, True)
            feedback_msg = "E-Cores Isolated"
        elif key in (ord('p'), ord('P')):
            for c in e_cores:
                if c not in locked_cores: set_core_status(c, False)
            for c in p_cores:
                if c not in locked_cores: set_core_status(c, True)
            feedback_msg = "P-Cores Isolated"
        elif key in (ord('m'), ord('M')):
            for c in all_cores:
                if c not in locked_cores: set_core_status(c, False)
            feedback_msg = "Minimal Power Mode (All cores sleeping except BSP)"
        elif key in (ord('a'), ord('A')):
            for c in all_cores:
                if c not in locked_cores: set_core_status(c, True)
            feedback_msg = "All Cores Online"
        elif key in (ord('q'), ord('Q')):
            break
            
        last_key_was_g = False 

# ==========================================
# 4. CLI Fallback Engine
# ==========================================
def display_status_table(p_cores: list[int], e_cores: list[int], locked_cores: set[int]) -> None:
    console.print(Align.center(Panel("[bold magenta]Dusky Core Manager[/bold magenta]", border_style="cyan", expand=False)))
    table = Table(show_header=True, header_style="bold magenta", expand=True)
    table.add_column("CORE", justify="center")
    table.add_column("TYPE", justify="center")
    table.add_column("ST", justify="center")
    table.add_column("FREQUENCY", justify="center")
    
    for core in sorted(p_cores + e_cores):
        arch = "[bold cyan]P-Core[/bold cyan]" if core in p_cores else "[bold green]E-Core[/bold green]"
        if core in locked_cores:
            table.add_row(f"CPU {core:02d}", arch, "[bold yellow] (BSP)[/bold yellow]", get_core_freq(core))
        else:
            status = get_core_status(core)
            st_icon = "[bold green]●[/bold green]" if status else "[dim red]○[/dim red]"
            freq = get_core_freq(core) if status else "---"
            table.add_row(f"CPU {core:02d}", arch, st_icon, freq)
    console.print(table)

def batch_process_cores(cores: list[int], enable: bool, action_name: str, locked_cores: set[int]) -> None:
    console.print(f"[bold yellow]Initiating {action_name} Sequence...[/bold yellow]")
    for core in cores:
        if core in locked_cores:
            continue
        success, msg = set_core_status(core, enable=enable)
        color = "green" if success else "yellow"
        console.print(f"CPU {core:02d}: [{color}]{msg}[/{color}]")

def parse_core_args(args_list: list[str], valid_cores: list[int]) -> list[int]:
    cores = set()
    try:
        for arg in args_list:
            if "-" in arg:
                start, end = sorted(map(int, arg.split("-")))
                cores.update(range(start, end + 1))
            else:
                cores.add(int(arg))
        invalid_cores = [c for c in cores if c not in valid_cores]
        if invalid_cores:
            console.print(f"[bold red]Hardware Error:[/bold red] CPUs {invalid_cores} do not exist.")
            sys.exit(1)
        return sorted(list(cores))
    except ValueError:
        console.print("[bold red]Error:[/bold red] Invalid format.")
        sys.exit(1)

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

    subparsers.add_parser("interactive", help="Launch the Live TUI (Default if no args)")
    subparsers.add_parser("status", help="View topology and core states")
    subparsers.add_parser("ecores-only", help="Disable P-Cores, Enable E-Cores")
    subparsers.add_parser("pcores-only", help="Disable E-Cores, Enable P-Cores")
    subparsers.add_parser("all-cores", help="Enable all cores")

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
            display_status_table(p_cores, e_cores, locked_cores)
        case "pcores-only":
            batch_process_cores(p_cores, enable=True, action_name="P-Core Wakeup", locked_cores=locked_cores)
            batch_process_cores(e_cores, enable=False, action_name="E-Core Shutdown", locked_cores=locked_cores)
            display_status_table(p_cores, e_cores, locked_cores)
        case "all-cores":
            batch_process_cores(all_known_cores, enable=True, action_name="Global Wakeup", locked_cores=locked_cores)
            display_status_table(p_cores, e_cores, locked_cores)
        case "enable":
            target_cores = parse_core_args(args.cores, all_known_cores)
            batch_process_cores(target_cores, enable=True, action_name="Targeted Wakeup", locked_cores=locked_cores)
            display_status_table(p_cores, e_cores, locked_cores)
        case "disable":
            target_cores = parse_core_args(args.cores, all_known_cores)
            batch_process_cores(target_cores, enable=False, action_name="Targeted Shutdown", locked_cores=locked_cores)
            display_status_table(p_cores, e_cores, locked_cores)
        case "toggle":
            target_cores = parse_core_args(args.cores, all_known_cores)
            for core in target_cores:
                if core in locked_cores: continue
                current_state = get_core_status(core)
                set_core_status(core, enable=not current_state)
            display_status_table(p_cores, e_cores, locked_cores)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
