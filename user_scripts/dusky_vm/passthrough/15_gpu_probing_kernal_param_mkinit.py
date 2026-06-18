#!/usr/bin/env python3
"""
Phase 3: VFIO Kernel Isolation & Bootloader Configuration
Target: Arch Linux (Kernel 7.1.0+), Python 3.14+, systemd-boot
Scope: Dynamic hardware probing, systemd-boot injection, mkinitcpio hook enforcement.
Philosophy: Zero-Clutter Idempotency, Hardware Agnosticism, Bulletproof Parsing.
"""

import os
import sys
import re
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Never

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
# HARDWARE DISCOVERY & IOMMU TOPOLOGY
# ==============================================================================
def bail(msg: str) -> Never:
    """Exit gracefully with a clear error panel."""
    console.print(Panel(f"[bold red]FATAL ERROR:[/bold red] {msg}", border_style="red"))
    sys.exit(1)

def get_cpu_iommu_flag() -> str:
    """Detects CPU architecture to set the correct IOMMU kernel parameter."""
    try:
        lscpu_out = subprocess.check_output(["lscpu"], text=True)
        if "GenuineIntel" in lscpu_out:
            return "intel_iommu"
        elif "AuthenticAMD" in lscpu_out:
            return "amd_iommu"
    except Exception:
        pass
    console.print("[yellow]⚠ Could not strictly determine CPU vendor. Defaulting to Intel VT-d flags.[/yellow]")
    return "intel_iommu"

def probe_gpus() -> Dict[str, Dict[str, Any]]:
    """Dynamically probes PCI tree for discrete GPUs and companion audio controllers."""
    console.print("\n[bold blue]==>[/bold blue] [bold]Probing system PCI topography...[/bold]")
    
    try:
        lspci_out = subprocess.check_output(["lspci", "-nn"], text=True)
    except subprocess.CalledProcessError:
        bail("Failed to execute lspci. Is pciutils installed?")

    gpus = {}
    
    # Pass 1: Identify all VGA/3D Controllers
    for line in lspci_out.splitlines():
        if "[0300]" in line or "[0302]" in line:
            bus_match = re.match(r'^([0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.\d)', line)
            id_match = re.search(r'\[([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\]', line)
            
            if bus_match and id_match:
                bus = bus_match.group(1)
                gpus[bus] = {
                    "video_id": id_match.group(1),
                    "video_desc": line[len(bus):].strip(),
                    "audio_id": None,
                    "audio_desc": "No companion audio detected"
                }

    # Pass 2: Identify companion Audio controllers on the same bus (usually .1)
    for line in lspci_out.splitlines():
        if "Audio device" in line or "[0403]" in line:
            bus_match = re.match(r'^([0-9a-fA-F]{2}:[0-9a-fA-F]{2})\.(\d)', line)
            if bus_match:
                base_bus = bus_match.group(1)
                gpu_bus = f"{base_bus}.0" 
                
                if gpu_bus in gpus:
                    id_match = re.search(r'\[([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\]', line)
                    if id_match:
                        gpus[gpu_bus]["audio_id"] = id_match.group(1)
                        gpus[gpu_bus]["audio_desc"] = line[len(bus_match.group(0)):].strip()

    return gpus

def select_target_gpu(gpus: Dict[str, Dict[str, Any]]) -> List[str]:
    """Provides an interactive UI for the administrator to isolate a specific GPU."""
    if not gpus:
        bail("No VGA/3D controllers detected on this system.")

    table = Table(title="Available Graphics Processing Units", show_header=True, header_style="bold magenta")
    table.add_column("Opt", justify="center", style="cyan")
    table.add_column("PCI Bus", style="dim")
    table.add_column("Video Controller & ID", style="green")
    table.add_column("Companion Audio & ID", style="yellow")

    options = list(gpus.items())
    
    for idx, (bus, data) in enumerate(options):
        v_str = f"{data['video_desc']} [bold]({data['video_id']})[/bold]"
        a_str = f"{data['audio_desc']} [bold]({data['audio_id']})[/bold]" if data['audio_id'] else "None"
        table.add_row(str(idx + 1), bus, v_str, a_str)

    console.print(table)
    
    choice = IntPrompt.ask("\n[bold cyan]Select the discrete GPU to isolate for VFIO[/bold cyan]", choices=[str(i+1) for i in range(len(options))])
    
    selected = options[choice - 1][1]
    ids = [selected["video_id"]]
    if selected["audio_id"]:
        ids.append(selected["audio_id"])
        
    console.print(f"[bold green]  ✓ Selected isolation IDs: {','.join(ids)}[/bold green]")
    return ids

# ==============================================================================
# BOOTLOADER INJECTION (SYSTEMD-BOOT)
# ==============================================================================
def get_systemd_boot_entry() -> Path:
    """Intelligently locates the primary Arch Linux bootloader entry."""
    entries_dir = Path("/boot/loader/entries")
    if not entries_dir.exists():
        bail("Strict constraint failure: systemd-boot entries directory not found. Are you using GRUB?")

    # Prioritize standard Arch conventions directly
    preferred_names = ["arch-linux.conf", "arch.conf"]
    for name in preferred_names:
        candidate = entries_dir / name
        if candidate.exists() and "options " in candidate.read_text(encoding="utf-8"):
            return candidate

    # Fallback: Find the first standard .conf that has an 'options' line
    for conf in entries_dir.glob("*.conf"):
        name_lower = conf.name.lower()
        if "fallback" not in name_lower and "memtest" not in name_lower:
            if "options " in conf.read_text(encoding="utf-8"):
                return conf

    bail("Could not dynamically resolve a valid systemd-boot entry (e.g., arch-linux.conf).")

def inject_bootloader_parameters(vfio_ids: List[str]) -> None:
    """Safely and idempotently updates kernel command line parameters."""
    conf_path = get_systemd_boot_entry()
    console.print(f"\n[bold blue]==>[/bold blue] [bold]Parsing systemd-boot configuration:[/bold] {conf_path.name}")
    
    cpu_flag = get_cpu_iommu_flag()
    id_str = ",".join(vfio_ids)
    
    content = conf_path.read_text(encoding="utf-8")
    
    opt_match = re.search(r'^options\s+(.*)', content, re.MULTILINE)
    if not opt_match:
        bail(f"Could not locate the 'options' line in {conf_path.name}.")
        
    current_opts = opt_match.group(1).split()
    new_opts = []
    
    # Required parameters mapping
    targets = {
        cpu_flag: "on",
        "iommu": "pt",
        "vfio-pci.ids": id_str
    }
    
    blacklist_set = {"nouveau", "nvidia", "nvidia_drm", "nvidia_modeset", "nvidia_uvm"}
    existing_bl = set()

    # Pass 1: Filter existing opts. Remove any old IOMMU/VFIO tags to prevent duplicates.
    # Also extract any existing module_blacklists so we can merge them properly.
    for opt in current_opts:
        if "=" in opt:
            k, v = opt.split("=", 1)
            # If it's one of our target flags (even for the other CPU vendor), drop it. We'll append the correct one.
            if k in ["intel_iommu", "amd_iommu", "iommu", "vfio-pci.ids"]:
                continue
            elif k == "module_blacklist":
                existing_bl.update(v.split(","))
            else:
                new_opts.append(opt)
        else:
            new_opts.append(opt)
            
    # Pass 2: Inject required targets
    for k, v in targets.items():
        new_opts.append(f"{k}={v}")
        
    # Pass 3: Re-inject a unified, sorted module_blacklist
    merged_bl = existing_bl.union(blacklist_set)
    merged_bl.discard("") # Remove empty strings if they exist
    new_opts.append(f"module_blacklist={','.join(sorted(merged_bl))}")
        
    # Reconstruct the line
    updated_opts_line = "options " + " ".join(new_opts)
    
    # Slice the file string securely replacing only the options line
    new_content = content[:opt_match.start()] + updated_opts_line + content[opt_match.end():]
    
    if new_content == content:
        console.print("[bold green]  ✓ Kernel parameters already perfectly optimized. No changes made.[/bold green]")
    else:
        conf_path.write_text(new_content, encoding="utf-8")
        console.print(f"[bold green]  ✓ Injected IOMMU and VFIO parameters into {conf_path.name}.[/bold green]")

# ==============================================================================
# INITRAMFS MANIPULATION
# ==============================================================================
def configure_mkinitcpio() -> None:
    """Enforces VFIO modules and hook ordering securely using AST-like parsing."""
    mk_path = Path("/etc/mkinitcpio.conf")
    console.print("\n[bold blue]==>[/bold blue] [bold]Hardening initramfs via mkinitcpio.conf...[/bold]")
    
    content = mk_path.read_text(encoding="utf-8")
    new_content = content
    
    # 1. Inject MODULES safely
    mod_match = re.search(r'^MODULES=\((.*?)\)', new_content, re.MULTILINE)
    if mod_match:
        mods = mod_match.group(1).split()
        for required in ['vfio_pci', 'vfio', 'vfio_iommu_type1']:
            if required not in mods:
                mods.append(required)
        new_mods_str = " ".join(mods)
        new_content = new_content[:mod_match.start(1)] + new_mods_str + new_content[mod_match.end(1):]

    # 2. Enforce HOOKS order (modconf must strictly precede kms)
    hook_match = re.search(r'^HOOKS=\((.*?)\)', new_content, re.MULTILINE)
    if hook_match:
        hooks = hook_match.group(1).split()
        
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
                    # KMS loaded before modconf: Fix isolation violation
                    hooks.pop(modconf_idx)
                    hooks.insert(kms_idx, 'modconf')
        
        new_hooks_str = " ".join(hooks)
        new_content = new_content[:hook_match.start(1)] + new_hooks_str + new_content[hook_match.end(1):]

    if content == new_content:
        console.print("[bold green]  ✓ mkinitcpio.conf already enforces VFIO isolation constraints.[/bold green]")
    else:
        mk_path.write_text(new_content, encoding="utf-8")
        console.print("[bold green]  ✓ Enforced VFIO modules and structural hook priorities.[/bold green]")

# ==============================================================================
# MODPROBE KERNEL RULES
# ==============================================================================
def write_modprobe_rules(vfio_ids: List[str]) -> None:
    """Generates the absolute Ring 0 isolation rules for the VFIO framework."""
    vfio_conf = Path("/etc/modprobe.d/vfio.conf")
    console.print("\n[bold blue]==>[/bold blue] [bold]Generating static kernel driver rules...[/bold]")
    
    id_str = ",".join(vfio_ids)
    content = vfio_conf.read_text(encoding="utf-8") if vfio_conf.exists() else ""
    original_content = content
    
    # Enforce ID assignment safely handling existing lines
    if re.search(r'^options vfio-pci ids=.*', content, re.MULTILINE):
        content = re.sub(r'^options vfio-pci ids=.*', f'options vfio-pci ids={id_str}', content, flags=re.MULTILINE)
    else:
        content += f"\noptions vfio-pci ids={id_str}\n"

    # Enforce Soft Dependencies and Blacklists
    targets = ["nvidia", "nvidia_drm", "nvidia_modeset", "nvidia_uvm", "nouveau"]
    
    for sd in targets:
        sd_line = f"softdep {sd} pre: vfio-pci"
        if not re.search(rf'^softdep\s+{sd}\s+pre:\s+vfio-pci', content, re.MULTILINE):
            content += f"{sd_line}\n"

        bl_line = f"blacklist {sd}"
        if not re.search(rf'^blacklist\s+{sd}', content, re.MULTILINE):
            content += f"{bl_line}\n"

    # Normalize formatting
    content = re.sub(r'\n{3,}', '\n\n', content).strip() + "\n"
    
    if content == original_content:
        console.print("[bold green]  ✓ VFIO modprobe isolation rules are already perfect.[/bold green]")
    else:
        vfio_conf.write_text(content, encoding="utf-8")
        console.print("[bold green]  ✓ Modprobe isolation dependencies bound successfully.[/bold green]")

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================
def main() -> None:
    console.clear()
    console.print(Panel("[bold green]KVM GPU Passthrough: Phase 3[/bold green]\nTarget: VFIO Isolation & Host Kernel Configuration", expand=False))
    
    try:
        gpus = probe_gpus()
        target_ids = select_target_gpu(gpus)
        
        inject_bootloader_parameters(target_ids)
        
        configure_mkinitcpio()
        write_modprobe_rules(target_ids)
        
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
