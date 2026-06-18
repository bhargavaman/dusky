#!/usr/bin/env python3
"""
Phase 3: VFIO Kernel Isolation & Bootloader Configuration
Target: Arch Linux (Kernel 7.1.0+), Python 3.14.5+, systemd 260
Scope: Dynamic hardware probing, bootctl JSON parsing, mkinitcpio hook enforcement.
Philosophy: Zero-Clutter Idempotency, Atomic Writes, Sysfs Topography.
"""

import os
import sys
import re
import json
import shlex
import shutil
import tempfile
import subprocess
import dataclasses
from pathlib import Path
from typing import Dict, Any, List, Set, Optional, Never

# ==============================================================================
# BOOTSTRAP: Strict Privilege & UI Enforcement
# ==============================================================================
def require_root() -> None:
    if os.geteuid() != 0:
        print("\n[FATAL] Phase 3 must be executed as root.")
        print("        Run with: sudo ./kvm_stage_three.py\n")
        sys.exit(1)

require_root()

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.prompt import IntPrompt
except ImportError:
    print("\n[FATAL] 'python-rich' is missing. Please ensure Phase 1 completed successfully.")
    sys.exit(1)

console = Console()

# ==============================================================================
# DATA STRUCTURES
# ==============================================================================
@dataclasses.dataclass
class VFIODevice:
    pci_bus: str
    video_id: str
    video_desc: str
    audio_id: Optional[str] = None
    audio_desc: str = "No companion audio detected"
    iommu_group: str = "Unknown"

# ==============================================================================
# CORE UTILITIES (Borrowed from Elite DevOps pattern)
# ==============================================================================
def bail(msg: str) -> Never:
    """Exit gracefully with a clear error panel."""
    console.print(Panel(f"[bold red]FATAL ERROR:[/bold red] {msg}", border_style="red"))
    sys.exit(1)

def check_deps() -> None:
    """Ensures pciutils is installed before executing system hardware scans."""
    if shutil.which("lspci"):
        return
    console.print("[yellow]⚠ Missing dependency detected: pciutils[/yellow]")
    console.print("[cyan]  Attempting to install via pacman...[/cyan]")
    try:
        subprocess.run(['pacman', '-S', '--needed', '--noconfirm', 'pciutils'], check=True, stdout=subprocess.DEVNULL)
        console.print("[green]  ✓ Dependencies installed.[/green]")
    except subprocess.CalledProcessError:
        bail("Failed to install required dependencies. Aborting.")

def atomic_write(target_path: Path, new_content: str) -> bool:
    """
    Safely writes data using a temporary file and atomic swap.
    Returns True if changes were made, False if the file is already optimal.
    """
    if target_path.exists() and target_path.read_text(encoding="utf-8") == new_content:
        return False
        
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(dir=target_path.parent, prefix=f".{target_path.name}.tmp.")
    tmp_path = Path(tmp_path_str)
    
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(new_content)
        os.chmod(tmp_path, 0o644)
        shutil.move(tmp_path, target_path)
        return True
    except Exception as e:
        if tmp_path.exists():
            tmp_path.unlink()
        bail(f"Atomic write failed on {target_path}: {e}")

# ==============================================================================
# HARDWARE DISCOVERY & IOMMU TOPOLOGY
# ==============================================================================
def get_cpu_iommu_flag() -> str:
    """Detects CPU architecture via /proc/cpuinfo to set the correct IOMMU flag."""
    cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8")
    if "GenuineIntel" in cpuinfo:
        return "intel_iommu"
    elif "AuthenticAMD" in cpuinfo:
        return "amd_iommu"
    
    console.print("[yellow]⚠ Could not strictly determine CPU vendor. Defaulting to Intel VT-d flags.[/yellow]")
    return "intel_iommu"

def probe_gpus() -> List[VFIODevice]:
    """Dynamically probes PCI tree for GPUs, companion audio, and IOMMU groups."""
    console.print("\n[bold blue]==>[/bold blue] [bold]Probing system PCI & IOMMU topography...[/bold]")
    check_deps()
    
    try:
        # Use -D to get the full domain address (0000:xx:xx.x) needed for sysfs
        res = subprocess.run(["lspci", "-Dnn"], capture_output=True, text=True, check=True)
        lspci_out = res.stdout
    except subprocess.CalledProcessError:
        bail("Failed to execute lspci.")

    gpu_map: Dict[str, VFIODevice] = {}
    
    # Pass 1: Identify all VGA/3D Controllers
    for line in lspci_out.splitlines():
        if "[0300]" in line or "[0302]" in line:
            bus_match = re.match(r'^([0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.\d)', line)
            id_match = re.search(r'\[([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\]', line)
            
            if bus_match and id_match:
                bus = bus_match.group(1)
                
                # Directly interrogate the Kernel via Sysfs for IOMMU grouping
                iommu_group = "Unknown"
                iommu_path = Path(f"/sys/bus/pci/devices/{bus}/iommu_group")
                if iommu_path.is_symlink():
                    iommu_group = iommu_path.resolve().name
                
                gpu_map[bus] = VFIODevice(
                    pci_bus=bus,
                    video_id=id_match.group(1),
                    video_desc=line[len(bus):].strip(),
                    iommu_group=iommu_group
                )

    # Pass 2: Identify companion Audio controllers on the same base bus (usually .1)
    for line in lspci_out.splitlines():
        if "Audio device" in line or "[0403]" in line:
            bus_match = re.match(r'^([0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2})\.(\d)', line)
            if bus_match:
                base_bus = bus_match.group(1)
                gpu_bus = f"{base_bus}.0" 
                
                if gpu_bus in gpu_map:
                    id_match = re.search(r'\[([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\]', line)
                    if id_match:
                        gpu_map[gpu_bus].audio_id = id_match.group(1)
                        gpu_map[gpu_bus].audio_desc = line[len(bus_match.group(0)):].strip()

    # Sort deterministically by PCI bus address
    return sorted(list(gpu_map.values()), key=lambda x: x.pci_bus)

def select_target_gpu(devices: List[VFIODevice]) -> List[str]:
    """Provides an interactive UI for the administrator to isolate a specific GPU."""
    if not devices:
        bail("No VGA/3D controllers detected on this system.")

    table = Table(title="Available Graphics Processing Units", show_header=True, header_style="bold magenta")
    table.add_column("Opt", justify="center", style="cyan")
    table.add_column("PCI Bus", style="dim")
    table.add_column("IOMMU", justify="center", style="bold red")
    table.add_column("Video Controller & ID", style="green")
    table.add_column("Companion Audio & ID", style="yellow")

    for idx, dev in enumerate(devices):
        v_str = f"{dev.video_desc} [bold]({dev.video_id})[/bold]"
        a_str = f"{dev.audio_desc} [bold]({dev.audio_id})[/bold]" if dev.audio_id else "None"
        table.add_row(str(idx + 1), dev.pci_bus, dev.iommu_group, v_str, a_str)

    console.print(table)
    
    choice = IntPrompt.ask("\n[bold cyan]Select the discrete GPU to isolate for VFIO[/bold cyan]", choices=[str(i+1) for i in range(len(devices))])
    
    selected = devices[choice - 1]
    ids = [selected.video_id]
    if selected.audio_id:
        ids.append(selected.audio_id)
        
    console.print(f"[bold green]  ✓ Selected isolation IDs: {','.join(ids)} (IOMMU Group {selected.iommu_group})[/bold green]")
    return ids

# ==============================================================================
# BOOTLOADER INJECTION: SYSTEMD-BOOT (JSON NATIVE)
# ==============================================================================
def get_systemd_boot_entry() -> Path:
    """Uses systemd 260 native JSON output to flawlessly locate the active boot entry."""
    console.print("  [cyan]Querying systemd-boot EFI payload data...[/cyan]")
    
    try:
        res = subprocess.run(["bootctl", "list", "--json=short"], capture_output=True, text=True, check=True)
        entries = json.loads(res.stdout)
        
        for entry in entries:
            # When default=@saved, 'is_selected' or 'is_default' dictates the target.
            if entry.get("is_default") or entry.get("is_selected"):
                source_path = entry.get("source")
                if source_path and Path(source_path).exists():
                    return Path(source_path)
                    
    except Exception as e:
        console.print(f"[yellow]  ⚠ bootctl JSON query failed: {e}. Falling back to standard paths.[/yellow]")

    # Fallback to absolute paths if bootctl is unreachable via chroot/vars
    entries_dir = Path("/boot/loader/entries")
    for name in ["arch-linux.conf", "arch.conf"]:
        candidate = entries_dir / name
        if candidate.exists():
            return candidate

    bail("Could not dynamically resolve the target systemd-boot entry via bootctl or fallback paths.")

def inject_bootloader_parameters(vfio_ids: List[str]) -> None:
    """Safely and idempotently parses and updates kernel command line parameters."""
    conf_path = get_systemd_boot_entry()
    console.print(f"\n[bold blue]==>[/bold blue] [bold]Targeting systemd-boot payload:[/bold] {conf_path.name}")
    
    cpu_flag = get_cpu_iommu_flag()
    id_str = ",".join(vfio_ids)
    
    content = conf_path.read_text(encoding="utf-8")
    opt_match = re.search(r'^options\s+(.*)', content, re.MULTILINE)
    if not opt_match:
        bail(f"Could not locate the 'options' line in {conf_path.name}.")
        
    current_opts = opt_match.group(1).split()
    new_opts: List[str] = []
    
    targets = {
        cpu_flag: "on",
        "iommu": "pt",
        "vfio-pci.ids": id_str
    }
    
    blacklist_set: Set[str] = {"nouveau", "nvidia", "nvidia_drm", "nvidia_modeset", "nvidia_uvm"}
    existing_bl: Set[str] = set()

    # Extract clean list and deduplicate existing blacklists
    for opt in current_opts:
        if "=" in opt:
            k, v = opt.split("=", 1)
            if k in ["intel_iommu", "amd_iommu", "iommu", "vfio-pci.ids"]:
                continue
            elif k == "module_blacklist":
                existing_bl.update(v.split(","))
            else:
                new_opts.append(opt)
        else:
            new_opts.append(opt)
            
    # Inject parameters
    for k, v in targets.items():
        new_opts.append(f"{k}={v}")
        
    merged_bl = existing_bl.union(blacklist_set)
    merged_bl.discard("")
    new_opts.append(f"module_blacklist={','.join(sorted(merged_bl))}")
        
    updated_opts_line = "options " + " ".join(new_opts)
    new_content = content[:opt_match.start()] + updated_opts_line + content[opt_match.end():]
    
    if atomic_write(conf_path, new_content):
        console.print(f"[bold green]  ✓ Injected IOMMU and VFIO parameters securely into {conf_path.name}.[/bold green]")
    else:
        console.print("[bold green]  ✓ Kernel parameters already perfectly optimized. No changes made.[/bold green]")

# ==============================================================================
# INITRAMFS MANIPULATION
# ==============================================================================
def configure_mkinitcpio() -> None:
    """Enforces VFIO modules and hook ordering securely using AST-like parsing."""
    mk_path = Path("/etc/mkinitcpio.conf")
    console.print("\n[bold blue]==>[/bold blue] [bold]Hardening initramfs via mkinitcpio.conf...[/bold]")
    
    new_content = mk_path.read_text(encoding="utf-8")
    
    # 1. Inject MODULES safely
    mod_match = re.search(r'^MODULES=\((.*?)\)', new_content, re.MULTILINE)
    if mod_match:
        raw_mods = mod_match.group(1).replace('"', '').replace("'", "")
        mods = raw_mods.split()
        for required in ['vfio_pci', 'vfio', 'vfio_iommu_type1']:
            if required not in mods:
                mods.append(required)
        new_mods_str = " ".join(mods)
        new_content = new_content[:mod_match.start(1)] + new_mods_str + new_content[mod_match.end(1):]

    # 2. Enforce HOOKS order (modconf must strictly precede kms)
    hook_match = re.search(r'^HOOKS=\((.*?)\)', new_content, re.MULTILINE)
    if hook_match:
        raw_hooks = hook_match.group(1).replace('"', '').replace("'", "")
        hooks = raw_hooks.split()
        
        if 'modconf' not in hooks:
            if 'kms' in hooks:
                hooks.insert(hooks.index('kms'), 'modconf')
            else:
                hooks.append('modconf')
        else:
            modconf_idx = hooks.index('modconf')
            if 'kms' in hooks:
                kms_idx = hooks.index('kms')
                if modconf_idx > kms_idx:
                    hooks.pop(modconf_idx)
                    hooks.insert(kms_idx, 'modconf')
        
        new_hooks_str = " ".join(hooks)
        new_content = new_content[:hook_match.start(1)] + new_hooks_str + new_content[hook_match.end(1):]

    if atomic_write(mk_path, new_content):
        console.print("[bold green]  ✓ Enforced VFIO modules and structural hook priorities.[/bold green]")
    else:
        console.print("[bold green]  ✓ mkinitcpio.conf already enforces VFIO isolation constraints.[/bold green]")

# ==============================================================================
# MODPROBE KERNEL RULES
# ==============================================================================
def write_modprobe_rules(vfio_ids: List[str]) -> None:
    """Generates the absolute Ring 0 isolation rules for the VFIO framework."""
    vfio_conf = Path("/etc/modprobe.d/vfio.conf")
    console.print("\n[bold blue]==>[/bold blue] [bold]Generating static kernel driver rules...[/bold]")
    
    id_str = ",".join(vfio_ids)
    content = vfio_conf.read_text(encoding="utf-8") if vfio_conf.exists() else ""
    
    if re.search(r'^options vfio-pci ids=.*', content, re.MULTILINE):
        content = re.sub(r'^options vfio-pci ids=.*', f'options vfio-pci ids={id_str}', content, flags=re.MULTILINE)
    else:
        content += f"\noptions vfio-pci ids={id_str}\n"

    targets = ["nvidia", "nvidia_drm", "nvidia_modeset", "nvidia_uvm", "nouveau"]
    for sd in targets:
        sd_line = f"softdep {sd} pre: vfio-pci"
        if not re.search(rf'^softdep\s+{sd}\s+pre:\s+vfio-pci', content, re.MULTILINE):
            content += f"{sd_line}\n"

        bl_line = f"blacklist {sd}"
        if not re.search(rf'^blacklist\s+{sd}', content, re.MULTILINE):
            content += f"{bl_line}\n"

    content = re.sub(r'\n{3,}', '\n\n', content).strip() + "\n"
    
    if atomic_write(vfio_conf, content):
        console.print("[bold green]  ✓ Modprobe isolation dependencies bound securely.[/bold green]")
    else:
        console.print("[bold green]  ✓ VFIO modprobe isolation rules are already perfect.[/bold green]")

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================
def main() -> None:
    console.clear()
    console.print(Panel("[bold green]KVM GPU Passthrough: Phase 3[/bold green]\nTarget: VFIO Isolation & Host Kernel Configuration", expand=False))
    
    try:
        # 1. Hardware Intelligence (Sysfs + pciutils)
        devices = probe_gpus()
        target_ids = select_target_gpu(devices)
        
        # 2. Bootloader Strategy (systemd 260 JSON NATIVE + Atomic Write)
        inject_bootloader_parameters(target_ids)
        
        # 3. Kernel Strategy (Atomic Writes)
        configure_mkinitcpio()
        write_modprobe_rules(target_ids)
        
        # 4. Compilation
        console.print("\n[bold blue]==>[/bold blue] [bold]Compiling Initramfs Environment (mkinitcpio -P)...[/bold]")
        subprocess.run(["mkinitcpio", "-P"], check=True)
        
        console.print("\n[bold green]=== PHASE 3 COMPLETE ===[/bold green]")
        console.print("The host kernel is now structurally programmed to drop the GPU at boot.")
        console.print(Panel("ACTION REQUIRED: Reboot your system now. The isolation takes effect at Ring 0 during startup.", border_style="yellow"))

    except KeyboardInterrupt:
        console.print("\n\n[bold red]⚠ Process interrupted by operator. Exiting cleanly.[/bold red]\n")
        sys.exit(130)

if __name__ == "__main__":
    main()
