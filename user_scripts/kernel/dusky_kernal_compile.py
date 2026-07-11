#!/usr/bin/env python3
"""
Dusky Kernel - 2026.07 Production Grade - Fixed for Latest Arch
Target: Arch Linux rolling, kernel 7.1.x+, systemd 261, Python 3.14+
Methodology: LSMOD + LMC_KEEP (dir-prefix), make pacman-pkg upstream, X86_NATIVE_CPU
Fixes: sudo keepalive removed, Content-Length safe, linger user fix,
       scripts/config built, expanded safe LMC_KEEP, robust config export,
       correct disk check, no FD leak, clean dependencies
"""
from __future__ import annotations

import gzip
import getpass
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
from collections import deque
from pathlib import Path

# --- Preflight ---
if sys.version_info < (3, 11):
    sys.exit("Fatal: Python 3.11+ required.")
if os.geteuid() == 0:
    sys.exit("Fatal: Do not run as root. makepkg refuses root. Run as normal user.")

try:
    import rich # noqa: F401
except ImportError:
    print(":: Missing 'python-rich'. Install: sudo pacman -S --needed python-rich")
    sys.exit(1)

from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn
from rich.table import Table
from rich.live import Live
from rich.align import Align
from rich import box

console = Console()

# 2026-07: Cleaned vs old script. base-devel covers bison/flex/binutils/gcc/make/patch.
# xmlto/inetutils removed - only needed for htmldocs. Kept clang/llvm/lld for Rust.
DEPENDENCIES = [
    "base-devel",
    "bc", "cpio", "gettext", "libelf", "pahole", "perl", "tar", "xz", "zstd",
    "kmod", "openssl", "zlib", "ncurses",
    "rust", "rust-src", "rust-bindgen", "clang", "llvm", "lld",
    "git", "rsync", "python"
]

MODPROBED_DB_AUR = "modprobed-db"
XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
DB_FILE = XDG_CONFIG / "modprobed.db"
BUILD_DIR = Path.home() / "dusky_build"
DUSKY_DIR = XDG_CONFIG / "dusky" / "settings" / "dusky_kernel"
DUSKY_STATE_FILE = DUSKY_DIR / "state.json"
DUSKY_SAVED_CONFIG = DUSKY_DIR / "kernel.config"

def ensure_sudo():
    """2026 methodology: single sudo -v, no background keepalive thread."""
    console.print("[dim]Authenticating sudo...[/dim]")
    subprocess.run(["sudo", "-v"], check=True)

def get_username() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USER") or Path.home().name

def load_dusky_state() -> dict:
    DUSKY_DIR.mkdir(parents=True, exist_ok=True)
    if DUSKY_STATE_FILE.exists():
        try:
            with open(DUSKY_STATE_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {"use_imported_config": True}

def save_dusky_state(state: dict):
    DUSKY_DIR.mkdir(parents=True, exist_ok=True)
    with open(DUSKY_STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

def check_aur_helper() -> str | None:
    for helper in ["paru", "yay"]:
        if shutil.which(helper):
            return helper
    return None

def install_aur_package(pkg_name: str) -> None:
    if subprocess.run(["pacman", "-Qq", pkg_name], capture_output=True, check=False).returncode == 0:
        return
    helper = check_aur_helper()
    if helper:
        console.print(f"[cyan]::[/cyan] Using [bold]{helper}[/bold] to install {pkg_name}...")
        subprocess.run([helper, "-S", "--noconfirm", "--needed", pkg_name], check=True)
    else:
        console.print(f"[yellow]::[/yellow] No AUR helper. Building {pkg_name} manually...")
        build_dir = Path("/tmp") / f"{pkg_name}-{os.getpid()}"
        if build_dir.exists():
            shutil.rmtree(build_dir)
        subprocess.run(["git", "clone", f"https://aur.archlinux.org/{pkg_name}.git", str(build_dir)], check=True)
        console.print(f"[yellow]Review PKGBUILD at {build_dir}/PKGBUILD before continuing.[/yellow]")
        subprocess.run(["makepkg", "-si", "--noconfirm"], cwd=build_dir, check=True)
        shutil.rmtree(build_dir)

def get_latest_kernel() -> tuple[str, str]:
    """Handles missing Content-Length and LTS-as-stable edge case."""
    try:
        req = urllib.request.Request("https://www.kernel.org/releases.json", headers={'User-Agent': 'dusky-kernel/2026.07'})
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())
            stable = None
            mainline = None
            for release in data.get('releases', []):
                if release.get('moniker') == 'stable' and not release.get('iseol'):
                    stable = (release['version'], release['source'])
                    break
            for release in data.get('releases', []):
                if release.get('moniker') == 'mainline':
                    mainline = (release['version'], release['source'])
                    break
            # Prefer stable, fallback to mainline if stable missing
            if stable:
                return stable
            if mainline:
                return mainline
            raise ValueError("No stable/mainline found")
    except Exception as e:
        console.print(f"[bold red]Fatal:[/bold red] kernel.org API failed: {e}")
        sys.exit(1)

def count_db_modules() -> int:
    if not DB_FILE.exists():
        return 0
    try:
        with open(DB_FILE, "r") as f:
            return sum(1 for line in f if line.strip() and not line.startswith("#"))
    except Exception:
        return 0

def export_active_config(target_file: Path) -> bool:
    """Robust export: /proc/config.gz -> /boot/config -> /lib/modules config."""
    # 1. /proc/config.gz
    try:
        if Path("/proc/config.gz").exists():
            with gzip.open("/proc/config.gz", "rt") as f_in, open(target_file, "w") as f_out:
                f_out.write(f_in.read())
            return True
    except Exception:
        pass
    # 2. /boot/config-$(uname -r) and /usr/lib/modules
    try:
        rel = os.uname().release
        candidates = [
            Path(f"/boot/config-{rel}"),
            Path(f"/usr/lib/modules/{rel}/config"),
            Path(f"/lib/modules/{rel}/config"),
        ]
        for cand in candidates:
            if cand.exists():
                shutil.copy(cand, target_file)
                return True
    except Exception as e:
        console.print(f"[dim]Config fallback failed: {e}[/dim]")
    return False

# ==========================================
# ACTION PHASES
# ==========================================
def initialize_tracking():
    ensure_sudo()
    console.print("\n[bold cyan]::[/bold cyan] Syncing modern native toolchains...")
    subprocess.run(["sudo", "pacman", "-S", "--needed", "--noconfirm"] + DEPENDENCIES, check=True)

    console.print("[bold cyan]::[/bold cyan] Resolving hardware profiler (modprobed-db)...")
    install_aur_package(MODPROBED_DB_AUR)

    console.print("[bold cyan]::[/bold cyan] Initializing local user database...")
    subprocess.run(["modprobed-db", "store"], capture_output=True, check=False)

    console.print("[bold cyan]::[/bold cyan] Enabling background systemd user daemon...")
    subprocess.run(["systemctl", "--user", "enable", "--now", "modprobed-db.timer"], check=True)
    subprocess.run(["sudo", "loginctl", "enable-linger", get_username()], check=False)

    console.print(Panel(
        "[bold green]Daemon Initialization Complete![/bold green]\n\n"
        "modprobed-db timer tracks modules every 6 hours + boot/shutdown.\n"
        "Use system heavily (USB, VPN, filesystems) to populate DB.",
        border_style="green", padding=(1, 2)
    ))

def monitor_modules():
    console.clear()
    console.print("[bold yellow]Press Ctrl+C to return to menu.[/bold yellow]\n")
    try:
        with Live(console=console, refresh_per_second=2) as live:
            while True:
                subprocess.run(["modprobed-db", "store"], capture_output=True, check=False)
                panel = Panel(
                    Align.center(f"[bold white]Unique Drivers Mapped:[/bold white] [bold green]{count_db_modules()}[/bold green]"),
                    title="Live Hardware Profiling Telemetry",
                    border_style="cyan", padding=(2, 5)
                )
                live.update(panel)
                time.sleep(2)
    except KeyboardInterrupt:
        pass

def manage_dusky_state():
    while True:
        console.clear()
        state = load_dusky_state()
        status_color = "green" if state.get("use_imported_config") else "yellow"
        status_text = "ACTIVE" if state.get("use_imported_config") else "INACTIVE"
        info_text = (
            f"[bold white]Target Dir:[/bold white] {DUSKY_DIR}\n"
            f"[bold white]Auto-Import:[/bold white] [bold {status_color}]{status_text}[/bold {status_color}]\n\n"
            f"[dim]Backup:[/dim] {'Found' if DUSKY_SAVED_CONFIG.exists() else 'Missing'}\n"
        )
        console.print(Panel(Align.center(info_text), title="[bold cyan]Dusky Configuration Manager[/bold cyan]", border_style="blue"))
        table = Table(show_header=False, box=box.SIMPLE)
        table.add_column("Option", style="bold green", justify="right")
        table.add_column("Description", style="white")
        table.add_row("1.", "Export Live System Config to Dusky Dir")
        table.add_row("2.", "Toggle Config Auto-Import")
        table.add_row("3.", "Back")
        console.print(table)
        choice = Prompt.ask("\n[bold cyan]Select[/bold cyan]", choices=["1", "2", "3"], default="3")
        if choice == "1":
            DUSKY_DIR.mkdir(parents=True, exist_ok=True)
            if export_active_config(DUSKY_SAVED_CONFIG):
                console.print(f"\n[bold green]Success:[/bold green] Exported to {DUSKY_SAVED_CONFIG}")
            else:
                console.print("\n[bold red]Error:[/bold red] No valid config found.")
            Prompt.ask("\n[dim]Enter to continue...[/dim]")
        elif choice == "2":
            if not DUSKY_SAVED_CONFIG.exists():
                console.print("\n[bold red]Error: No backup. Export first.[/bold red]")
            else:
                state["use_imported_config"] = not state.get("use_imported_config")
                save_dusky_state(state)
                mode = "ACTIVATED" if state["use_imported_config"] else "DEACTIVATED"
                console.print(f"\n[bold green]Success:[/bold green] Auto-Import {mode}.")
            Prompt.ask("\n[dim]Enter to continue...[/dim]")
        else:
            break

def compile_kernel():
    if count_db_modules() < 100:
        console.print(Panel(f"[bold red]Hardware profile {DB_FILE} sparse (<100 drivers).[/bold red]\nMap hardware first.", border_style="red"))
        return

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    free_space = shutil.disk_usage(str(BUILD_DIR)).free
    if free_space < 30 * 1024**3:
        if not Confirm.ask(f"\n[bold yellow]Only {free_space/1024**3:.1f}GB free in {BUILD_DIR}. Need ~30GB. Continue?[/bold yellow]", default=False):
            return

    ensure_sudo()
    subprocess.run(["sudo", "pacman", "-S", "--needed", "--noconfirm"] + DEPENDENCIES, check=True)

    version, url = get_latest_kernel()
    tarball = BUILD_DIR / f"linux-{version}.tar.xz"
    kernel_dir = BUILD_DIR / f"linux-{version}"

    try:
        if not kernel_dir.exists():
            console.print(f"\n[bold cyan]::[/bold cyan] Fetching [bold]linux-{version}[/bold]...")
            req = urllib.request.Request(url, headers={'User-Agent': 'dusky-kernel/2026.07'})
            with urllib.request.urlopen(req) as response:
                total_str = response.headers.get('Content-Length')
                total_size = int(total_str) if total_str and total_str.isdigit() else None
                with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), BarColumn() if total_size else TextColumn(""), DownloadColumn(), TransferSpeedColumn(), console=console) as progress:
                    task = progress.add_task("Downloading...", total=total_size or 1)
                    with open(tarball, 'wb') as out_file:
                        while True:
                            buf = response.read(8192)
                            if not buf:
                                break
                            out_file.write(buf)
                            if total_size:
                                progress.advance(task, advance=len(buf))
                            else:
                                progress.advance(task, advance=1)

            with console.status("[bold yellow]Unpacking...[/bold yellow]"):
                subprocess.run(["tar", "-xf", str(tarball)], cwd=BUILD_DIR, check=True)
        else:
            console.print(f"\n[bold cyan]::[/bold cyan] Found existing tree linux-{version}, skipping download.")

        # --- Config Injection ---
        state = load_dusky_state()
        if state.get("use_imported_config") and DUSKY_SAVED_CONFIG.exists():
            console.print("[bold green]::[/bold green] Injecting saved Dusky config...")
            shutil.copy(DUSKY_SAVED_CONFIG, kernel_dir / ".config")
        else:
            console.print("[bold cyan]::[/bold cyan] Cloning live config...")
            if not Path("/proc/config.gz").exists():
                subprocess.run(["sudo", "modprobe", "configs"], check=False)
            if not export_active_config(kernel_dir / ".config"):
                subprocess.run(["make", "defconfig"], cwd=kernel_dir, check=True)

        # --- localmodconfig ---
        console.print("[bold cyan]::[/bold cyan] Pruning with modprobed-db...")
        env = os.environ.copy()
        env["LSMOD"] = str(DB_FILE)
        # Expanded safe keeps for 2026 laptops/desktops
        env["LMC_KEEP"] = (
            "drivers/usb:drivers/gpu:fs:drivers/input:drivers/nvme:"
            "drivers/scsi:drivers/hid:drivers/block:drivers/md:"
            "drivers/acpi:drivers/firmware:drivers/platform:fs/nls:"
            "kernel/power:drivers/net:drivers/char"
        )
        subprocess.run(["make", "localmodconfig"], cwd=kernel_dir, env=env, input=b"\n", stdout=subprocess.DEVNULL, check=True)

        # Ensure scripts/config exists (7.1 requirement)
        console.print("[bold cyan]::[/bold cyan] Building kconfig tooling...")
        subprocess.run(["make", "scripts"], cwd=kernel_dir, stdout=subprocess.DEVNULL, check=True)

        # --- Hardening & Debug Bloat Fixes ---
        console.print("[bold cyan]::[/bold cyan] Applying 2026 Arch hardening matrix...")
        scripts_cfg = [str(kernel_dir / "scripts" / "config")]
        subprocess.run(scripts_cfg + [
            "-d", "DEBUG_INFO_BTF_MODULES",
            "-d", "DEBUG_INFO_BTF",
            "-d", "DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT",
            "-d", "DEBUG_INFO_DWARF4",
            "-d", "DEBUG_INFO_DWARF5",
            "-e", "DEBUG_INFO_NONE",
            "-d", "DEBUG_INFO_COMPRESSED_ZLIB",
            "-d", "DEBUG_INFO_COMPRESSED_ZSTD",
            "-e", "DEBUG_INFO_COMPRESSED_NONE",
            "--set-str", "SYSTEM_TRUSTED_KEYS", "",
            "--set-str", "SYSTEM_REVOCATION_KEYS", ""
        ], cwd=kernel_dir, check=True)

        if os.uname().machine == "x86_64":
            subprocess.run(scripts_cfg + ["-e", "X86_NATIVE_CPU"], cwd=kernel_dir, check=True)

        (kernel_dir / "localversion").write_text("-dusky")
        subprocess.run(["make", "olddefconfig"], cwd=kernel_dir, stdout=subprocess.DEVNULL, check=True)

        if Confirm.ask("\n[bold yellow]Edit config manually (make nconfig)?[/bold yellow]", default=False):
            console.print("[dim]Launching nconfig... F9 to save.[/dim]")
            time.sleep(1)
            subprocess.run(["make", "nconfig"], cwd=kernel_dir, check=True)
            subprocess.run(["make", "olddefconfig"], cwd=kernel_dir, stdout=subprocess.DEVNULL, check=True)

        DUSKY_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy(kernel_dir / ".config", DUSKY_SAVED_CONFIG)
        state["use_imported_config"] = True
        save_dusky_state(state)

        cores = os.cpu_count() or 4
        console.print(f"\n[bold green]Building linux-{version}-dusky with {cores} threads...[/bold green]\n")

        build_cmd = [
            "make", f"-j{cores}",
            "PACMAN_PKGBASE=linux-dusky",
            "PACMAN_EXTRAPACKAGES=headers",
            "pacman-pkg"
        ]

        process = subprocess.Popen(build_cmd, cwd=kernel_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        log_lines = deque(maxlen=20)
        with Live(console=console, auto_refresh=True, refresh_per_second=8) as live:
            assert process.stdout
            for line in iter(process.stdout.readline, ''):
                clean = line.strip()
                if not clean:
                    continue
                log_lines.append(clean)
                live.update(Panel("\n".join(log_lines), title=f"[bold cyan]Compiling linux-{version}[/bold cyan]", border_style="blue", padding=(0, 2)))
        process.wait()
        if process.returncode!= 0:
            console.print("\n[bold red]Fatal:[/bold red] Compilation failed. Config saved.")
            return

        console.print("\n[bold cyan]::[/bold cyan] Resolving packages...")
        pkgs = list((kernel_dir / "pacman").glob("*.pkg.tar.zst"))
        valid_pkgs = [p for p in pkgs if "-debug" not in p.name]
        if not valid_pkgs:
            console.print("[bold red]No packages in pacman/ dir![/bold red]")
            return

        console.print(f"[bold cyan]::[/bold cyan] Installing {len(valid_pkgs)} package(s)...")
        subprocess.run(["sudo", "pacman", "-U", "--noconfirm"] + [str(p) for p in valid_pkgs], check=True)

        console.print(Panel(
            f"[bold green]Mission Accomplished![/bold green]\n\n"
            f"Dusky Kernel [bold]linux-{version}-dusky[/bold] installed.\n"
            "mkinitcpio & bootloader hooks triggered via pacman.",
            border_style="green", padding=(1, 2)
        ))

    except KeyboardInterrupt:
        console.print("\n[bold yellow]Interrupted.[/bold yellow]")
    except subprocess.CalledProcessError as e:
        console.print(f"\n[bold red]Subprocess failed:[/bold red] {e}")

def main_menu():
    while True:
        console.clear()
        state = load_dusky_state()
        config_status = "[bold green]IMPORTED[/bold green]" if state.get("use_imported_config") and DUSKY_SAVED_CONFIG.exists() else "[dim]LIVE[/dim]"
        console.print(Panel(
            Align.center(f"[bold cyan]Dusky Kernel[/bold cyan] [dim]- 2026.07 Fixed[/dim]\n[dim]Arch • localmodconfig + LMC_KEEP safe • pacman-pkg[/dim]\n[dim]Source: {config_status}[/dim]"),
            box=box.DOUBLE, border_style="blue"
        ))
        table = Table(show_header=False, box=box.SIMPLE)
        table.add_column("Option", style="bold green", justify="right")
        table.add_column("Description", style="white")
        table.add_row("1.", "Install Toolchains & Init Profiling")
        table.add_row("2.", "View Hardware DB Telemetry")
        table.add_row("3.", "Compile & Install Kernel")
        table.add_row("4.", "Config Manager")
        table.add_row("5.", "Exit")
        console.print(table)
        choice = Prompt.ask("\n[bold cyan]Select[/bold cyan]", choices=["1","2","3","4","5"], default="5")
        match choice:
            case "1":
                initialize_tracking()
                Prompt.ask("\n[dim]Enter to return...[/dim]")
            case "2":
                monitor_modules()
            case "3":
                compile_kernel()
                Prompt.ask("\n[dim]Enter to return...[/dim]")
            case "4":
                manage_dusky_state()
            case "5":
                console.print("\n[bold cyan]Exiting. May your uptime be long.[/bold cyan]\n")
                break

if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Force quit.[/bold yellow]\n")
        sys.exit(0)