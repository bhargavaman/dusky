#!/usr/bin/env python3
"""
Dusky Kernel - 2026.07 Production Grade - Fixed for Latest Arch
Target: Arch Linux rolling, kernel 7.1.x+, systemd 261, Python 3.14+
Methodology: LSMOD + LMC_KEEP (dir-prefix), make pacman-pkg upstream, X86_NATIVE_CPU

Verified fixes (2026-07-11, Arch/CachyOS kernel 7.1.3):
  - zlib removed from DEPENDENCIES (conflicts with zlib-ng-compat which Provides: zlib)
  - PKGDEST set + multi-path package discovery (makepkg writes to startdir, not BUILDDIR)
  - Sudo keepalive restored (clean daemon thread + atexit) for multi-hour builds
  - Tarball filename derived from URL (mainline is .tar.gz, stable is .tar.xz)
  - localmodconfig fed defaults via yes "" (oldconfig can prompt many times)
  - Download: incomplete files deleted; Content-Length-safe progress
  - Dep install: skip already-satisfied packages (installed or provided)
  - scripts/config is a shell script; still build host tools via make scripts
"""
from __future__ import annotations

import atexit
import gzip
import getpass
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

# --- Preflight ---
if sys.version_info < (3, 11):
    sys.exit("Fatal: Python 3.11+ required.")
if os.geteuid() == 0:
    sys.exit("Fatal: Do not run as root. makepkg refuses root. Run as normal user.")

try:
    import rich  # noqa: F401
except ImportError:
    print(":: Missing 'python-rich'. Install: sudo pacman -S --needed python-rich")
    sys.exit(1)

from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    DownloadColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from rich.live import Live
from rich.align import Align
from rich import box

console = Console()

# 2026-07: base-devel covers bison/flex/binutils/gcc/make/patch.
# xmlto/inetutils removed - only needed for htmldocs. Kept clang/llvm/lld for Rust.
# zlib intentionally omitted: on modern Arch/CachyOS, zlib-ng-compat Provides: zlib
# and Conflicts: zlib — pacman -S zlib fails the entire transaction.
DEPENDENCIES = [
    "base-devel",
    "bc",
    "cpio",
    "gettext",
    "libelf",
    "pahole",
    "perl",
    "tar",
    "xz",
    "zstd",
    "kmod",
    "openssl",
    "ncurses",
    "rust",
    "rust-src",
    "rust-bindgen",
    "clang",
    "llvm",
    "lld",
    "git",
    "rsync",
    "python",
]

MODPROBED_DB_AUR = "modprobed-db"
XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
DB_FILE = XDG_CONFIG / "modprobed.db"
BUILD_DIR = Path.home() / "dusky_build"
DUSKY_DIR = XDG_CONFIG / "dusky" / "settings" / "dusky_kernel"
DUSKY_STATE_FILE = DUSKY_DIR / "state.json"
DUSKY_SAVED_CONFIG = DUSKY_DIR / "kernel.config"

# --- Sudo keepalive (required: default sudo timestamp is 15m, kernel builds take hours) ---
_sudo_stop = threading.Event()
_sudo_thread: threading.Thread | None = None


def _sudo_keepalive_loop() -> None:
    while not _sudo_stop.wait(60):
        r = subprocess.run(["sudo", "-n", "-v"], capture_output=True)
        if r.returncode != 0:
            break


def stop_sudo_keepalive() -> None:
    _sudo_stop.set()


def ensure_sudo() -> None:
    """Authenticate once and keep the timestamp alive for long builds."""
    global _sudo_thread
    console.print("[dim]Authenticating sudo...[/dim]")
    subprocess.run(["sudo", "-v"], check=True)
    if _sudo_thread is None or not _sudo_thread.is_alive():
        _sudo_stop.clear()
        _sudo_thread = threading.Thread(
            target=_sudo_keepalive_loop, name="sudo-keepalive", daemon=True
        )
        _sudo_thread.start()
        atexit.register(stop_sudo_keepalive)


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


def save_dusky_state(state: dict) -> None:
    DUSKY_DIR.mkdir(parents=True, exist_ok=True)
    with open(DUSKY_STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)


def check_aur_helper() -> str | None:
    for helper in ("paru", "yay"):
        if shutil.which(helper):
            return helper
    return None


def missing_packages(pkgs: list[str]) -> list[str]:
    """
    Return packages not satisfied by the local DB.

    pacman -T understands Provides (e.g. zlib-ng-compat satisfies zlib)
    and groups (base-devel). Exit 0 + empty stdout => all satisfied.
    """
    r = subprocess.run(
        ["pacman", "-T"] + pkgs, capture_output=True, text=True
    )
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def install_dependencies() -> None:
    """Install only packages that are not already installed/provided."""
    to_install = missing_packages(DEPENDENCIES)
    if not to_install:
        console.print("[green]::[/green] All build dependencies already satisfied.")
        return
    console.print(f"[cyan]::[/cyan] Installing: {', '.join(to_install)}")
    subprocess.run(
        ["sudo", "pacman", "-S", "--needed", "--noconfirm"] + to_install,
        check=True,
    )


def install_aur_package(pkg_name: str) -> None:
    if subprocess.run(["pacman", "-Qq", pkg_name], capture_output=True).returncode == 0:
        return
    helper = check_aur_helper()
    if helper:
        console.print(f"[cyan]::[/cyan] Using [bold]{helper}[/bold] to install {pkg_name}...")
        subprocess.run(
            [helper, "-S", "--noconfirm", "--needed", pkg_name], check=True
        )
    else:
        console.print(f"[yellow]::[/yellow] No AUR helper. Building {pkg_name} manually...")
        build_dir = Path("/tmp") / f"{pkg_name}-{os.getpid()}"
        if build_dir.exists():
            shutil.rmtree(build_dir)
        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    f"https://aur.archlinux.org/{pkg_name}.git",
                    str(build_dir),
                ],
                check=True,
            )
            console.print(
                f"[yellow]Review PKGBUILD at {build_dir}/PKGBUILD before continuing.[/yellow]"
            )
            subprocess.run(
                ["makepkg", "-si", "--noconfirm"], cwd=build_dir, check=True
            )
        finally:
            if build_dir.exists():
                shutil.rmtree(build_dir)


def get_latest_kernel() -> tuple[str, str]:
    """Return (version, source_url). Prefers newest non-EOL stable, else mainline."""
    try:
        req = urllib.request.Request(
            "https://www.kernel.org/releases.json",
            headers={"User-Agent": "dusky-kernel/2026.07"},
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())
            stable = None
            mainline = None
            for release in data.get("releases", []):
                if release.get("moniker") == "stable" and not release.get("iseol"):
                    # kernel.org lists newest first; take first non-EOL stable
                    stable = (release["version"], release["source"])
                    break
            for release in data.get("releases", []):
                if release.get("moniker") == "mainline":
                    mainline = (release["version"], release["source"])
                    break
            if stable:
                return stable
            if mainline:
                return mainline
            raise ValueError("No stable/mainline found")
    except Exception as e:
        console.print(f"[bold red]Fatal:[/bold red] kernel.org API failed: {e}")
        sys.exit(1)


def tarball_name_from_url(version: str, url: str) -> str:
    """Derive archive filename from URL (stable=.tar.xz, mainline=.tar.gz)."""
    path = urlparse(url).path
    base = Path(path).name
    if base:
        return base
    return f"linux-{version}.tar.xz"


def is_valid_kernel_tree(kernel_dir: Path) -> bool:
    """True if dir looks like a usable kernel source tree."""
    makefile = kernel_dir / "Makefile"
    if not makefile.is_file():
        return False
    try:
        head = makefile.read_text(errors="replace")[:2000]
    except OSError:
        return False
    return "VERSION" in head and (kernel_dir / "scripts").is_dir()


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
    try:
        if Path("/proc/config.gz").exists():
            with gzip.open("/proc/config.gz", "rt") as f_in, open(
                target_file, "w"
            ) as f_out:
                f_out.write(f_in.read())
            return True
    except Exception:
        pass
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


def find_built_packages(kernel_dir: Path, pkg_dir: Path) -> list[Path]:
    """
    Locate .pkg.tar.zst outputs.

    Upstream pacman-pkg sets BUILDDIR=.../pacman (src/pkg staging only).
    makepkg writes finished packages to PKGDEST, which defaults to startdir
    (kernel_dir) unless we set PKGDEST ourselves.
    """
    seen: set[Path] = set()
    found: list[Path] = []
    search_roots = [pkg_dir, kernel_dir]
    env_dest = os.environ.get("PKGDEST")
    if env_dest:
        search_roots.append(Path(env_dest))
    for root in search_roots:
        if not root.is_dir():
            continue
        for p in root.glob("*.pkg.tar.zst"):
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                found.append(p)
        # Also common nested layout
        for p in root.glob("**/*.pkg.tar.zst"):
            # Skip makepkg intermediate if any; only real packages at shallow depth
            if p.parent == root or p.parent.name in ("pacman",):
                rp = p.resolve()
                if rp not in seen:
                    seen.add(rp)
                    found.append(p)
    return found


def download_file(url: str, dest: Path) -> None:
    """Download with progress; delete partial file on failure."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "dusky-kernel/2026.07"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            total_str = response.headers.get("Content-Length")
            total_size = (
                int(total_str) if total_str and total_str.isdigit() else None
            )
            columns = [
                SpinnerColumn(),
                TextColumn("[cyan]{task.description}"),
            ]
            if total_size:
                columns.extend(
                    [BarColumn(), DownloadColumn(), TransferSpeedColumn()]
                )
            else:
                columns.extend(
                    [TextColumn("[cyan]{task.completed} bytes"), TransferSpeedColumn()]
                )
            with Progress(*columns, console=console) as progress:
                task = progress.add_task("Downloading...", total=total_size)
                with open(dest, "wb") as out_file:
                    while True:
                        buf = response.read(1024 * 256)
                        if not buf:
                            break
                        out_file.write(buf)
                        progress.advance(task, advance=len(buf))
    except Exception:
        if dest.exists():
            dest.unlink(missing_ok=True)
        raise


# ==========================================
# ACTION PHASES
# ==========================================
def initialize_tracking() -> None:
    ensure_sudo()
    console.print("\n[bold cyan]::[/bold cyan] Syncing modern native toolchains...")
    install_dependencies()

    console.print(
        "[bold cyan]::[/bold cyan] Resolving hardware profiler (modprobed-db)..."
    )
    install_aur_package(MODPROBED_DB_AUR)

    console.print("[bold cyan]::[/bold cyan] Initializing local user database...")
    subprocess.run(["modprobed-db", "store"], capture_output=True, check=False)

    console.print(
        "[bold cyan]::[/bold cyan] Enabling background systemd user daemon..."
    )
    # modprobed-db >=2.50: Install section is on the *service* (WantedBy=default.target).
    # The timer has no [Install] and is pulled in via Wants= from the service.
    # Official: systemctl --user enable --now modprobed-db
    r = subprocess.run(
        ["systemctl", "--user", "enable", "--now", "modprobed-db.service"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        # Fallback for older packaging that only installed the timer unit
        r2 = subprocess.run(
            ["systemctl", "--user", "enable", "--now", "modprobed-db.timer"],
            capture_output=True,
            text=True,
        )
        if r2.returncode != 0:
            console.print(
                f"[yellow]Warning:[/yellow] could not enable modprobed-db service/timer.\n"
                f"[dim]{r.stderr or r.stdout}\n{r2.stderr or r2.stdout}[/dim]\n"
                "You can still run: modprobed-db store"
            )
    subprocess.run(
        ["sudo", "loginctl", "enable-linger", get_username()], check=False
    )

    console.print(
        Panel(
            "[bold green]Daemon Initialization Complete![/bold green]\n\n"
            "modprobed-db timer tracks modules every 6 hours + boot/shutdown.\n"
            "Use system heavily (USB, VPN, filesystems) to populate DB.",
            border_style="green",
            padding=(1, 2),
        )
    )


def monitor_modules() -> None:
    console.clear()
    console.print("[bold yellow]Press Ctrl+C to return to menu.[/bold yellow]\n")
    try:
        with Live(console=console, refresh_per_second=2) as live:
            while True:
                subprocess.run(
                    ["modprobed-db", "store"], capture_output=True, check=False
                )
                panel = Panel(
                    Align.center(
                        f"[bold white]Unique Drivers Mapped:[/bold white] "
                        f"[bold green]{count_db_modules()}[/bold green]"
                    ),
                    title="Live Hardware Profiling Telemetry",
                    border_style="cyan",
                    padding=(2, 5),
                )
                live.update(panel)
                time.sleep(2)
    except KeyboardInterrupt:
        pass


def manage_dusky_state() -> None:
    while True:
        console.clear()
        state = load_dusky_state()
        status_color = "green" if state.get("use_imported_config") else "yellow"
        status_text = "ACTIVE" if state.get("use_imported_config") else "INACTIVE"
        info_text = (
            f"[bold white]Target Dir:[/bold white] {DUSKY_DIR}\n"
            f"[bold white]Auto-Import:[/bold white] "
            f"[bold {status_color}]{status_text}[/bold {status_color}]\n\n"
            f"[dim]Backup:[/dim] "
            f"{'Found' if DUSKY_SAVED_CONFIG.exists() else 'Missing'}\n"
        )
        console.print(
            Panel(
                Align.center(info_text),
                title="[bold cyan]Dusky Configuration Manager[/bold cyan]",
                border_style="blue",
            )
        )
        table = Table(show_header=False, box=box.SIMPLE)
        table.add_column("Option", style="bold green", justify="right")
        table.add_column("Description", style="white")
        table.add_row("1.", "Export Live System Config to Dusky Dir")
        table.add_row("2.", "Toggle Config Auto-Import")
        table.add_row("3.", "Back")
        console.print(table)
        choice = Prompt.ask(
            "\n[bold cyan]Select[/bold cyan]", choices=["1", "2", "3"], default="3"
        )
        if choice == "1":
            DUSKY_DIR.mkdir(parents=True, exist_ok=True)
            if export_active_config(DUSKY_SAVED_CONFIG):
                console.print(
                    f"\n[bold green]Success:[/bold green] Exported to {DUSKY_SAVED_CONFIG}"
                )
            else:
                console.print(
                    "\n[bold red]Error:[/bold red] No valid config found."
                )
            Prompt.ask("\n[dim]Enter to continue...[/dim]")
        elif choice == "2":
            if not DUSKY_SAVED_CONFIG.exists():
                console.print(
                    "\n[bold red]Error: No backup. Export first.[/bold red]"
                )
            else:
                state["use_imported_config"] = not state.get("use_imported_config")
                save_dusky_state(state)
                mode = (
                    "ACTIVATED"
                    if state["use_imported_config"]
                    else "DEACTIVATED"
                )
                console.print(
                    f"\n[bold green]Success:[/bold green] Auto-Import {mode}."
                )
            Prompt.ask("\n[dim]Enter to continue...[/dim]")
        else:
            break


def compile_kernel() -> None:
    if count_db_modules() < 100:
        console.print(
            Panel(
                f"[bold red]Hardware profile {DB_FILE} sparse "
                f"(<100 drivers).[/bold red]\nMap hardware first.",
                border_style="red",
            )
        )
        return

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    free_space = shutil.disk_usage(str(BUILD_DIR)).free
    if free_space < 30 * 1024**3:
        if not Confirm.ask(
            f"\n[bold yellow]Only {free_space / 1024**3:.1f}GB free in "
            f"{BUILD_DIR}. Need ~30GB. Continue?[/bold yellow]",
            default=False,
        ):
            return

    ensure_sudo()
    install_dependencies()

    version, url = get_latest_kernel()
    tarball = BUILD_DIR / tarball_name_from_url(version, url)
    kernel_dir = BUILD_DIR / f"linux-{version}"
    # Predictable package output directory (PKGDEST). Upstream Makefile still
    # sets BUILDDIR=kernel_dir/pacman for makepkg src/pkg staging only.
    pkg_dir = kernel_dir / "pacman"

    try:
        if kernel_dir.exists() and not is_valid_kernel_tree(kernel_dir):
            console.print(
                f"[yellow]::[/yellow] Incomplete tree at {kernel_dir}, removing..."
            )
            shutil.rmtree(kernel_dir)

        if not is_valid_kernel_tree(kernel_dir):
            console.print(
                f"\n[bold cyan]::[/bold cyan] Fetching [bold]linux-{version}[/bold]..."
            )
            if not tarball.exists() or tarball.stat().st_size == 0:
                download_file(url, tarball)
            # Remove any partial extract before unpacking
            if kernel_dir.exists():
                shutil.rmtree(kernel_dir)
            with console.status("[bold yellow]Unpacking...[/bold yellow]"):
                subprocess.run(
                    ["tar", "-xf", str(tarball)], cwd=BUILD_DIR, check=True
                )
            if not is_valid_kernel_tree(kernel_dir):
                console.print(
                    f"[bold red]Fatal:[/bold red] Expected valid tree "
                    f"{kernel_dir} missing after extract."
                )
                return
        else:
            console.print(
                f"\n[bold cyan]::[/bold cyan] Found existing tree "
                f"linux-{version}, skipping download."
            )

        pkg_dir.mkdir(parents=True, exist_ok=True)

        # --- Config Injection ---
        state = load_dusky_state()
        if state.get("use_imported_config") and DUSKY_SAVED_CONFIG.exists():
            console.print(
                "[bold green]::[/bold green] Injecting saved Dusky config..."
            )
            shutil.copy(DUSKY_SAVED_CONFIG, kernel_dir / ".config")
        else:
            console.print("[bold cyan]::[/bold cyan] Cloning live config...")
            if not Path("/proc/config.gz").exists():
                subprocess.run(["sudo", "modprobe", "configs"], check=False)
            if not export_active_config(kernel_dir / ".config"):
                subprocess.run(
                    ["make", "defconfig"], cwd=kernel_dir, check=True
                )

        # --- localmodconfig ---
        console.print("[bold cyan]::[/bold cyan] Pruning with modprobed-db...")
        env = os.environ.copy()
        env["LSMOD"] = str(DB_FILE)
        # Expanded safe keeps for 2026 laptops/desktops (dir-prefix match)
        env["LMC_KEEP"] = (
            "drivers/usb:drivers/gpu:fs:drivers/input:drivers/nvme:"
            "drivers/scsi:drivers/hid:drivers/block:drivers/md:"
            "drivers/acpi:drivers/firmware:drivers/platform:fs/nls:"
            "kernel/power:drivers/net:drivers/char"
        )
        # localmodconfig runs conf --oldconfig which can prompt many times.
        # Feed empty answers (accept defaults) non-interactively.
        yes_proc = subprocess.Popen(
            ["yes", ""],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            subprocess.run(
                ["make", "localmodconfig"],
                cwd=kernel_dir,
                env=env,
                stdin=yes_proc.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=True,
            )
        finally:
            yes_proc.terminate()
            try:
                yes_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                yes_proc.kill()

        # Host tooling (fixdep, etc.). scripts/config itself is a bash script.
        console.print("[bold cyan]::[/bold cyan] Building kconfig tooling...")
        subprocess.run(
            ["make", "scripts"],
            cwd=kernel_dir,
            stdout=subprocess.DEVNULL,
            check=True,
        )

        # --- Hardening & Debug Bloat Fixes ---
        console.print(
            "[bold cyan]::[/bold cyan] Applying 2026 Arch hardening matrix..."
        )
        scripts_cfg = [str(kernel_dir / "scripts" / "config")]
        subprocess.run(
            scripts_cfg
            + [
                "-d",
                "DEBUG_INFO_BTF_MODULES",
                "-d",
                "DEBUG_INFO_BTF",
                "-d",
                "DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT",
                "-d",
                "DEBUG_INFO_DWARF4",
                "-d",
                "DEBUG_INFO_DWARF5",
                "-e",
                "DEBUG_INFO_NONE",
                "-d",
                "DEBUG_INFO_COMPRESSED_ZLIB",
                "-d",
                "DEBUG_INFO_COMPRESSED_ZSTD",
                "-e",
                "DEBUG_INFO_COMPRESSED_NONE",
                "--set-str",
                "SYSTEM_TRUSTED_KEYS",
                "",
                "--set-str",
                "SYSTEM_REVOCATION_KEYS",
                "",
            ],
            cwd=kernel_dir,
            check=True,
        )

        if os.uname().machine == "x86_64":
            subprocess.run(
                scripts_cfg + ["-e", "X86_NATIVE_CPU"], cwd=kernel_dir, check=True
            )

        (kernel_dir / "localversion").write_text("-dusky")
        subprocess.run(
            ["make", "olddefconfig"],
            cwd=kernel_dir,
            stdout=subprocess.DEVNULL,
            check=True,
        )

        if Confirm.ask(
            "\n[bold yellow]Edit config manually (make nconfig)?[/bold yellow]",
            default=False,
        ):
            console.print("[dim]Launching nconfig... F9 to save.[/dim]")
            time.sleep(1)
            subprocess.run(["make", "nconfig"], cwd=kernel_dir, check=True)
            subprocess.run(
                ["make", "olddefconfig"],
                cwd=kernel_dir,
                stdout=subprocess.DEVNULL,
                check=True,
            )

        DUSKY_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy(kernel_dir / ".config", DUSKY_SAVED_CONFIG)
        state["use_imported_config"] = True
        save_dusky_state(state)

        cores = os.cpu_count() or 4
        console.print(
            f"\n[bold green]Building linux-{version}-dusky with {cores} threads..."
            f"[/bold green]\n"
        )

        build_cmd = [
            "make",
            f"-j{cores}",
            "PACMAN_PKGBASE=linux-dusky",
            "PACMAN_EXTRAPACKAGES=headers",
            "pacman-pkg",
        ]
        build_env = os.environ.copy()
        # Force finished packages into pkg_dir (not only BUILDDIR staging).
        build_env["PKGDEST"] = str(pkg_dir)

        process = subprocess.Popen(
            build_cmd,
            cwd=kernel_dir,
            env=build_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        log_lines: deque[str] = deque(maxlen=20)
        with Live(console=console, auto_refresh=True, refresh_per_second=8) as live:
            assert process.stdout
            for line in iter(process.stdout.readline, ""):
                clean = line.strip()
                if not clean:
                    continue
                log_lines.append(clean)
                live.update(
                    Panel(
                        "\n".join(log_lines),
                        title=f"[bold cyan]Compiling linux-{version}[/bold cyan]",
                        border_style="blue",
                        padding=(0, 2),
                    )
                )
            process.stdout.close()
        process.wait()
        if process.returncode != 0:
            console.print(
                "\n[bold red]Fatal:[/bold red] Compilation failed. Config saved."
            )
            return

        console.print("\n[bold cyan]::[/bold cyan] Resolving packages...")
        pkgs = find_built_packages(kernel_dir, pkg_dir)
        valid_pkgs = [p for p in pkgs if "-debug" not in p.name]
        if not valid_pkgs:
            console.print(
                "[bold red]No packages found![/bold red] "
                f"Searched {pkg_dir} and {kernel_dir}"
            )
            return

        # Re-auth in case keepalive failed for any reason
        ensure_sudo()
        console.print(
            f"[bold cyan]::[/bold cyan] Installing {len(valid_pkgs)} package(s)..."
        )
        for p in valid_pkgs:
            console.print(f"  [dim]{p.name}[/dim]")
        subprocess.run(
            ["sudo", "pacman", "-U", "--noconfirm"] + [str(p) for p in valid_pkgs],
            check=True,
        )

        console.print(
            Panel(
                f"[bold green]Mission Accomplished![/bold green]\n\n"
                f"Dusky Kernel [bold]linux-{version}-dusky[/bold] installed.\n"
                "mkinitcpio & bootloader hooks triggered via pacman.",
                border_style="green",
                padding=(1, 2),
            )
        )

    except KeyboardInterrupt:
        console.print("\n[bold yellow]Interrupted.[/bold yellow]")
    except subprocess.CalledProcessError as e:
        console.print(f"\n[bold red]Subprocess failed:[/bold red] {e}")
        if e.stderr:
            err = e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr
            console.print(f"[dim]{err[-2000:]}[/dim]")
    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")


def main_menu() -> None:
    while True:
        console.clear()
        state = load_dusky_state()
        config_status = (
            "[bold green]IMPORTED[/bold green]"
            if state.get("use_imported_config") and DUSKY_SAVED_CONFIG.exists()
            else "[dim]LIVE[/dim]"
        )
        console.print(
            Panel(
                Align.center(
                    f"[bold cyan]Dusky Kernel[/bold cyan] "
                    f"[dim]- 2026.07 Fixed[/dim]\n"
                    f"[dim]Arch • localmodconfig + LMC_KEEP safe • pacman-pkg[/dim]\n"
                    f"[dim]Source: {config_status}[/dim]"
                ),
                box=box.DOUBLE,
                border_style="blue",
            )
        )
        table = Table(show_header=False, box=box.SIMPLE)
        table.add_column("Option", style="bold green", justify="right")
        table.add_column("Description", style="white")
        table.add_row("1.", "Install Toolchains & Init Profiling")
        table.add_row("2.", "View Hardware DB Telemetry")
        table.add_row("3.", "Compile & Install Kernel")
        table.add_row("4.", "Config Manager")
        table.add_row("5.", "Exit")
        console.print(table)
        choice = Prompt.ask(
            "\n[bold cyan]Select[/bold cyan]",
            choices=["1", "2", "3", "4", "5"],
            default="5",
        )
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
                console.print(
                    "\n[bold cyan]Exiting. May your uptime be long.[/bold cyan]\n"
                )
                break


if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Force quit.[/bold yellow]\n")
        sys.exit(0)
