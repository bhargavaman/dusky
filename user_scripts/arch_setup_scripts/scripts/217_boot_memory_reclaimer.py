#!/usr/bin/env python3
# =============================================================================
# Elite Arch Linux Boot-Time Memory Reclaimer
# Target: Arch Linux Cutting-Edge (Kernel 5.19+, Python 3.14+, systemd 260+)
# Scope: Platinum Grade. Forcefully pushes cold boot-initialization RAM to ZRAM.
# =============================================================================

from __future__ import annotations

import argparse
import os
import sys
import subprocess
import tempfile
from pathlib import Path

# --- Presentation (Zero-Dependency ANSI) ---
class C:
    BOLD = "\033[1m"
    RED = "\033[1;31m"
    GRN = "\033[1;32m"
    BLU = "\033[1;34m"
    RST = "\033[0m"

    @classmethod
    def strip(cls) -> None:
        for name in ("BOLD", "RED", "GRN", "BLU", "RST"):
            setattr(cls, name, "")

def info(msg: str) -> None: print(f"{C.BLU}[INFO]{C.RST} {msg}")
def ok(msg: str) -> None: print(f"{C.GRN}[ OK ]{C.RST} {msg}")
def err(msg: str) -> None: print(f"{C.RED}[FAIL]{C.RST} {msg}", file=sys.stderr)
def die(msg: str, code: int = 1) -> "typing.NoReturn": # noqa: F821
    err(msg)
    sys.exit(code)

# --- Argument Parsing (Executed BEFORE Privilege Escalation) ---
parser = argparse.ArgumentParser(description="Elite Arch Linux Boot-Time Memory Reclaimer")
parser.add_argument("--run", action="store_true", help="Directly trigger the memory reclaim task")
parser.add_argument("--no-color", action="store_true", help="Disable ANSI color output")

args = parser.parse_args()

if args.no_color or not sys.stdout.isatty() or "NO_COLOR" in os.environ:
    C.strip()

# --- Privilege Escalation ---
def escalate_privileges() -> None:
    if os.geteuid() != 0:
        info("Root privileges required. Escalating...")
        if subprocess.call(["command", "-v", "sudo"], stdout=subprocess.DEVNULL, shell=True) != 0:
            die("sudo is required to run this script as root.")
        os.execvp("sudo", ["sudo", sys.executable, os.path.abspath(__file__)] + sys.argv[1:])

escalate_privileges()

def write_file_atomic(path: Path, content: str, mode: int = 0o644) -> None:
    if path.exists() and path.read_text() == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise

# --- Reclaim Logic ---
def perform_reclaim() -> None:
    info("Initiating targeted boot-time cold memory sweep...")
    
    slices = ["user.slice", "system.slice"]
    reclaimed_total_bytes = 0
    
    for slice_name in slices:
        cgroup_dir = Path("/sys/fs/cgroup") / slice_name
        current_file = cgroup_dir / "memory.current"
        reclaim_file = cgroup_dir / "memory.reclaim"
        
        if not current_file.exists() or not reclaim_file.exists():
            info(f"Cgroup slice {slice_name} does not support memory reclaim. Skipping.")
            continue
            
        try:
            current_bytes = int(current_file.read_text().strip())
            # Reclaim 50% of current memory usage (targeting only cold anon & shmem pages)
            reclaim_bytes = int(current_bytes * 0.50)
            
            if reclaim_bytes > 0:
                # Forcefully reclaim cold memory using swappiness=200
                reclaim_command = f"{reclaim_bytes} swappiness=200"
                reclaim_file.write_text(reclaim_command)
                reclaimed_total_bytes += reclaim_bytes
                ok(f"Reclaimed {reclaim_bytes / (1024*1024):.1f} MB of cold memory from {slice_name}")
        except Exception as e:
            info(f"Failed to reclaim memory from {slice_name}: {e}")
            
    ok(f"Targeted cold memory sweep completed. Swapped ~{reclaimed_total_bytes / (1024*1024):.1f} MB of cold pages to ZRAM.")



# --- Installer Logic ---
def deploy_systemd_units() -> None:
    info("Deploying boot-time memory reclaim systemd units...")
    
    service_path = Path("/etc/systemd/system/boot-memory-reclaim.service")
    service_content = f"""[Unit]
Description=Boot-time Cold Memory Reclaimer
After=local-fs.target

[Service]
Type=oneshot
ExecStart={sys.executable} {os.path.abspath(__file__)} --run
"""
    write_file_atomic(service_path, service_content)
    ok(f"Service unit written to {service_path}")
    
    timer_path = Path("/etc/systemd/system/boot-memory-reclaim.timer")
    timer_content = """[Unit]
Description=Trigger Boot-time Cold Memory Reclaimer 1 minute after boot

[Timer]
OnActiveSec=1min

[Install]
WantedBy=timers.target
"""
    write_file_atomic(timer_path, timer_content)
    ok(f"Timer unit written to {timer_path}")
    
    info("Reloading systemd daemon...")
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    
    info("Enabling and starting boot-memory-reclaim.timer...")
    subprocess.run(["systemctl", "enable", "--now", "boot-memory-reclaim.timer"], check=True)
    
    ok("Boot-time reclaimer timer is active. Cold memory will be purged 1 minute after boot.")

def main() -> None:
    if sys.version_info < (3, 14):
        die(f"Python 3.14+ required, running {sys.version.split()[0]}")
        
    if args.run:
        perform_reclaim()
    else:
        deploy_systemd_units()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{C.BOLD}{C.RED}aborted — operation cancelled by user.{C.RST}")
        sys.exit(130)
