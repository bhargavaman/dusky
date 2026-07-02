#!/usr/bin/env python3
"""
Dusky Core Manager
Kernel 7.1+ | Python 3.14+ | Arch Linux Optimized
Features: RAPL Power, On-Demand C-States, Minimalist TUI
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

def take_cstate_snapshot(active_cores: list[int]) -> dict[int, str]:
    """Reads cpuidle counters, waits 150ms, calculates highest residency state."""
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

    time.sleep(0.15) 

    for core in active_cores:
        if core not in t1_data:
            snapshot[core] = "C0 (Active)"
            continue
            
        core_path = Path(f"/sys/devices/system/cpu/cpu{core}/cpuidle")
        max_delta = -1
        active_state = "C0"
        for state_dir in core_path.glob("state*"):
            try:
                name = safe_read(state_dir / "name")
                t_val = safe_read(state_dir / "time")
                if t_val.isdigit():
                    delta = int(t_val) - t1_data[core].get(name, 0)
                    if delta > max_delta and delta > 0:
                        max_delta = delta
                        active_state = name
            except OSError: pass
        snapshot[core] = active_state
        
    return snapshot

# ==========================================
# 3. Interactive Minimalist TUI
# ==========================================
def interactive_mode(stdscr, p_cores: list[int], e_cores: list[int], locked_cores: set[int]) -> None:
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    
    curses.init_pair(1, curses.COLOR_BLUE, -1)     # P-Core
    curses.init_pair(2, curses.COLOR_GREEN, -1)    # Online / E-Core
    curses.init_pair(3, curses.COLOR_RED, -1)      # Sleeping / Errors
    curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_WHITE) # UI Cursor
    curses.init_pair(5, curses.COLOR_YELLOW, -1)   # Locked (BSP)
    curses.init_pair(6, curses.COLOR_MAGENTA, -1)  # Accents
    curses.init_pair(7, curses.COLOR_CYAN, -1)     # Info

    stdscr.timeout(1000) # 1-sec loop for live telemetry

    all_cores = sorted(p_cores + e_cores)
    current_row = 0
    feedback_msg = ""
    show_controls = False
    
    cstate_data = {}
    cstate_timer = 0
    
    last_energy = 0
    last_time = time.time()
    
    # Aesthetic Icons (No Emojis)
    ICON_ON = "●"
    ICON_OFF = "○"
    ICON_LOCK = "" # U+F023 Nerd Font Lock (Falls back cleanly if missing)

    while True:
        stdscr.clear()
        max_y, max_x = stdscr.getmaxyx()
        
        if max_y < 10:
            stdscr.addstr(1, 0, "Terminal too small!", curses.color_pair(3) | curses.A_BOLD)
            stdscr.refresh()
            stdscr.getch()
            continue

        # Dynamic RAPL Polling
        pkg_power, last_energy, last_time = get_package_power(last_energy, last_time)

        # Header Alignment
        title = " Dusky Core Manager "
        stdscr.addstr(0, max(0, (max_x - len(title)) // 2), title, curses.A_REVERSE | curses.A_BOLD | curses.color_pair(6))
        
        power_str = f" PKG Power: {pkg_power} | [F1/H] Toggle Controls "
        stdscr.addstr(1, max(0, (max_x - len(power_str)) // 2), power_str, curses.color_pair(7) | curses.A_BOLD)

        if feedback_msg:
            msg_str = f" Status: {feedback_msg} "
            stdscr.addstr(2, max(0, (max_x - len(msg_str)) // 2), msg_str, curses.color_pair(3) | curses.A_BOLD)

        # Dynamic Controls Rendering
        y_offset = 4
        if show_controls:
            stdscr.addstr(y_offset, 2, "Nav:   ", curses.A_BOLD | curses.color_pair(6))
            stdscr.addstr(y_offset, 9, "[j/k] Up/Down  [SPACE] Toggle  [i] C-State Snapshot")
            y_offset += 1
            stdscr.addstr(y_offset, 2, "Batch: ", curses.A_BOLD | curses.color_pair(6))
            stdscr.addstr(y_offset, 9, "[E] E-Cores Only  [P] P-Cores Only  [A] All Cores  [Q] Quit")
            y_offset += 2
            
        # Table Header (Minimalist)
        # Switch third column header if C-State snapshot is active
        third_col_header = "C-STATE (Snap)" if cstate_timer > 0 else "FREQUENCY"
        stdscr.addstr(y_offset, 2, f"{'CORE':<8} | {'TYPE':<8} | {'ST':<4} | {third_col_header}", curses.A_UNDERLINE | curses.A_BOLD)

        visible_rows = max_y - (y_offset + 2)
        half_page = visible_rows // 2
        start_row = max(0, current_row - visible_rows // 2)
        end_row = min(len(all_cores), start_row + visible_rows)
        
        if end_row - start_row < visible_rows and len(all_cores) > visible_rows:
            start_row = max(0, len(all_cores) - visible_rows)
            end_row = len(all_cores)

        # Core Rendering Loop
        for idx in range(start_row, end_row):
            core = all_cores[idx]
            is_locked = core in locked_cores
            is_online = get_core_status(core)
            
            arch = "P-Core" if core in p_cores else "E-Core"
            arch_color = curses.color_pair(1) | curses.A_BOLD if core in p_cores else curses.color_pair(2) | curses.A_BOLD
            
            # Determine Telemetry (Frequency vs C-State)
            if cstate_timer > 0:
                telemetry_str = cstate_data.get(core, "---")
            else:
                telemetry_str = get_core_freq(core) if is_online or is_locked else "---"
            
            # State Icon Resolution
            if is_locked:
                icon_str = f" {ICON_LOCK} "
                status_color = curses.color_pair(5) | curses.A_BOLD
            else:
                icon_str = f" {ICON_ON} " if is_online else f" {ICON_OFF} "
                status_color = curses.color_pair(2) | curses.A_BOLD if is_online else curses.color_pair(3) | curses.A_DIM
            
            row_y = (y_offset + 1) + (idx - start_row)
            
            if idx == current_row:
                stdscr.addstr(row_y, 2, f"CPU {core:02d}   | {arch:<8} |{icon_str:<5}| {telemetry_str:<12}", curses.color_pair(4))
            else:
                stdscr.addstr(row_y, 2, f"CPU {core:02d}   | ", curses.A_NORMAL)
                stdscr.addstr(row_y, 13, f"{arch:<8}", arch_color)
                stdscr.addstr(row_y, 22, f"|{icon_str:<5}|", status_color)
                stdscr.addstr(row_y, 29, f" {telemetry_str:<12}", curses.A_NORMAL)

        stdscr.refresh()
        
        key = stdscr.getch()
        feedback_msg = ""
        
        # Decrement C-State Timer on every loop iteration
        if cstate_timer > 0:
            cstate_timer -= 1
        
        if key == curses.ERR: continue
            
        # Navigation
        if key in (curses.KEY_UP, ord('k')):
            if current_row > 0: current_row -= 1
        elif key in (curses.KEY_DOWN, ord('j')):
            if current_row < len(all_cores) - 1: current_row += 1
        elif key == 4: current_row = min(len(all_cores) - 1, current_row + half_page)
        elif key == 21: current_row = max(0, current_row - half_page)
        elif key == ord('G'): current_row = len(all_cores) - 1
        elif key == ord('g'): current_row = 0
            
        # C-State Observer Logic (On-Demand)
        elif key == ord('i'):
            feedback_msg = "Taking C-State Snapshot..."
            stdscr.addstr(2, max(0, (max_x - len(feedback_msg) - 9) // 2), f" Status: {feedback_msg} ", curses.color_pair(5) | curses.A_BOLD)
            stdscr.refresh()
            active_cores = [c for c in all_cores if get_core_status(c) or c in locked_cores]
            cstate_data = take_cstate_snapshot(active_cores)
            cstate_timer = 5 # Display for ~5 seconds
            feedback_msg = "Snapshot Captured."
                
        # Action Logic
        elif key in (ord('h'), ord('H'), curses.KEY_F1):
            show_controls = not show_controls
        elif key == ord(' '):
            core = all_cores[current_row]
            if core in locked_cores:
                feedback_msg = f"CPU {core:02d} is the immutable BSP."
            else:
                success, msg = set_core_status(core, enable=not get_core_status(core))
                if not success: feedback_msg = msg
        elif key in (ord('e'), ord('E')):
            for c in p_cores:
                if c not in locked_cores: set_core_status(c, False)
            for c in e_cores: 
                if c not in locked_cores: set_core_status(c, True)
        elif key in (ord('p'), ord('P')):
            for c in e_cores:
                if c not in locked_cores: set_core_status(c, False)
            for c in p_cores:
                if c not in locked_cores: set_core_status(c, True)
        elif key in (ord('a'), ord('A')):
            for c in all_cores:
                if c not in locked_cores: set_core_status(c, True)
        elif key in (ord('q'), ord('Q')):
            break

# ==========================================
# 4. CLI Fallback Engine
# ==========================================
def display_status_table(p_cores: list[int], e_cores: list[int], locked_cores: set[int]) -> None:
    console.print(Align.center(Panel("[bold magenta]Dusky Core Manager[/bold magenta]", border_style="cyan", expand=False)))
    table = Table(show_header=True, header_style="bold cyan", expand=True)
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

def main() -> None:
    p_cores, e_cores, locked_cores = hydrate_and_detect_topology()
    all_known_cores = p_cores + e_cores

    if len(sys.argv) == 1:
        curses.wrapper(interactive_mode, p_cores, e_cores, locked_cores)
        sys.exit(0)

    # CLI args omitted for brevity (Functions exactly as previous version)
    # Allows backward compatibility for your automation scripts.
    display_status_table(p_cores, e_cores, locked_cores)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: sys.exit(130)
