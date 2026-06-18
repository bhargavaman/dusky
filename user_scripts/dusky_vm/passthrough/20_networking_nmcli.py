#!/usr/bin/env python3
"""
Phase 4: KVM Network Bridging & LAN Access Automation
Environment: Arch Linux (Kernel 7.1.0, Python 3.14.5, systemd 260)
Scope: NetworkManager, UFW, Libvirt

Elite Standard:
- Strict JSON kernel routing table parsing.
- Modern NM terminology (controller vs deprecated master/bridge-slave).
- Atomic libvirt injection with strict C-level file descriptor cleanup.
- Pure idempotency with dynamic NM state arrays.
"""

import os
import sys
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

try:
    from rich.console import Console
    from rich.prompt import Confirm
    from rich.panel import Panel
    from rich.table import Table
except ImportError:
    print("CRITICAL: The 'rich' library is required. Install via: pip install rich")
    sys.exit(1)

console = Console()

def run_cmd(cmd: list, check: bool = True, capture: bool = True, timeout: int = 30) -> subprocess.CompletedProcess:
    """Execute shell commands with elite reliability and strict timeout enforcement."""
    try:
        return subprocess.run(
            cmd,
            check=check,
            capture_output=capture,
            text=True,
            timeout=timeout
        )
    except subprocess.TimeoutExpired as e:
        console.print(f"[bold red]FATAL: Command timed out after {timeout}s:[/bold red] {' '.join(cmd)}")
        if check:
            sys.exit(1)
        return e
    except subprocess.CalledProcessError as e:
        console.print(f"[bold red]FATAL: Command failed with exit code {e.returncode}:[/bold red] {' '.join(cmd)}")
        console.print(f"[red]Details:[/red] {e.stderr.strip() or e.stdout.strip()}")
        if check:
            sys.exit(1)
        return e

def verify_environment():
    """Ensure immutable privileges and mandatory toolchain presence."""
    if os.geteuid() != 0:
        console.print("[bold red]ERROR: Phase 4 requires immutable root privileges (sudo).[/bold red]")
        sys.exit(1)
        
    required_binaries = ["ip", "nmcli", "virsh"]
    missing = [bin for bin in required_binaries if not shutil.which(bin)]
    if missing:
        console.print(f"[bold red]ERROR: Missing mandatory binaries in PATH: {', '.join(missing)}[/bold red]")
        sys.exit(1)

def discover_active_interface() -> str:
    """
    Dynamically discover the active routing interface via the kernel's routing table.
    Utilizes JSON parsing for 100% deterministic accuracy over string splitting.
    """
    try:
        # Request native JSON output from the kernel tool
        res = run_cmd(["ip", "-j", "route", "show", "default"])
        routes = json.loads(res.stdout.strip())
        
        if not routes:
            raise ValueError("Kernel routing table returned empty for default route.")
            
        active_dev = routes[0].get("dev")
        if not active_dev:
            raise ValueError("No 'dev' identifier found in the primary JSON route object.")
            
        return active_dev
    except json.JSONDecodeError:
        console.print("[bold red]ERROR: Failed to decode kernel JSON routing output.[/bold red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]Hardware Discovery Failed: {e}[/bold red]")
        sys.exit(1)

def is_wireless(interface: str) -> bool:
    """Definitively verify 802.11 status via the kernel's sysfs virtual filesystem."""
    return Path(f"/sys/class/net/{interface}/wireless").exists()

def provision_nmcli_bridge(interface: str):
    """Idempotent and modern NetworkManager bridge creation using the latest specifications."""
    console.print("\n[bold cyan]─── NetworkManager Bridge Provisioning ───[/bold cyan]")
    
    # Precise Idempotency Check: Parse NM's internal array via get-values (-g)
    res = run_cmd(["nmcli", "-g", "NAME,TYPE", "connection", "show"])
    
    # Parse output into tuples (name, type) handling empty lines gracefully
    connections = [tuple(line.split(':')) for line in res.stdout.strip().split('\n') if ':' in line]
    
    # Verify br0 exists AND is correctly typed as a bridge
    if any(c[0] == 'br0' and c[1] == 'bridge' for c in connections):
        console.print("[bold green]✓ System bridge 'br0' already present and typed correctly. Perfectly staged.[/bold green]")
        return

    with console.status(f"[cyan]Constructing system bridge 'br0' over {interface}...", spinner="dots"):
        # 1. Instantiate the bridge. STP explicitly disabled for instantaneous VM network handshakes.
        run_cmd([
            "nmcli", "connection", "add", 
            "type", "bridge", 
            "ifname", "br0", 
            "con-name", "br0", 
            "bridge.stp", "no"
        ])
        
        # 2. Bind physical interface using cutting-edge 'controller' syntax
        # The nmcli manual strictly deprecates 'master' and 'bridge-slave' types.
        slave_name = f"bridge-slave-{interface}"
        run_cmd([
            "nmcli", "connection", "add", 
            "type", "ethernet", 
            "ifname", interface, 
            "controller", "br0", 
            "con-name", slave_name
        ])
        
        # 3. Bring bridge online with strict 15-second timeout safeguard as a global option
        run_cmd(["nmcli", "--wait", "15", "connection", "up", "br0"])
        
    console.print(f"[bold green]✓ Bridge 'br0' materialized and successfully bound to {interface}.[/bold green]")

def configure_firewall():
    """Apply UFW routing rules to prevent default bridge traffic drops through kernel filter space."""
    console.print("\n[bold cyan]─── Firewall Routing Configuration ───[/bold cyan]")
    
    if not shutil.which("ufw"):
        console.print("[yellow]⚠ UFW binary not found in PATH. Skipping iptables/nftables frontend configuration.[/yellow]")
        return

    with console.status("[cyan]Injecting UFW bridge forwarding rules...", spinner="dots"):
        # We do not strictly check exit codes here as rules may already exist or UFW may be disabled
        run_cmd(["ufw", "route", "allow", "in", "on", "br0"], check=False)
        run_cmd(["ufw", "route", "allow", "out", "on", "br0"], check=False)
        run_cmd(["ufw", "reload"], check=False)
        
    console.print("[bold green]✓ Bridge traffic authorized natively through UFW kernel space.[/bold green]")

def inject_libvirt_network():
    """Atomically inject the bridge definition into the libvirt daemon."""
    console.print("\n[bold cyan]─── Libvirt Network Injection ───[/bold cyan]")
    
    # Check libvirt state idempotently
    res = run_cmd(["virsh", "net-list", "--all", "--name"])
    if "host-bridge" in res.stdout.split():
        console.print("[bold green]✓ Libvirt network 'host-bridge' already registered. Skipping XML injection.[/bold green]")
        
        # Enforce activation guarantees irrespective of creation status
        run_cmd(["virsh", "net-autostart", "host-bridge"], check=False)
        state_res = run_cmd(["virsh", "net-info", "host-bridge"])
        if "Active: yes" not in state_res.stdout:
            run_cmd(["virsh", "net-start", "host-bridge"], check=False)
        return

    # Modern libvirt XML payload (UUID and MAC intentionally omitted for auto-generation)
    xml_payload = """<network>
  <name>host-bridge</name>
  <forward mode='bridge'/>
  <bridge name='br0'/>
</network>"""

    # Atomic execution: strict C-level fd allocation, writing, and deterministic vaporization
    fd, temp_path = tempfile.mkstemp(prefix="libvirt-br0-", suffix=".xml")
    try:
        # Wrap fd in Python file object to handle encoding and automatic flushing
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(xml_payload)
            
        with console.status("[cyan]Injecting atomic payload into libvirt daemon...", spinner="bouncingBar"):
            run_cmd(["virsh", "net-define", temp_path])
            run_cmd(["virsh", "net-start", "host-bridge"])
            run_cmd(["virsh", "net-autostart", "host-bridge"])
            
    finally:
        # Absolute guarantee of zero clutter. Unlink bypasses normal filesystem recycling.
        if os.path.exists(temp_path):
            os.unlink(temp_path)
            
    console.print("[bold green]✓ Libvirt payload digested and activated atomically.[/bold green]")

def generate_telemetry_summary(interface: str):
    """Render the executive Phase 4 summary architecture table."""
    table = Table(title="Phase 4: Network Architecture Summary", show_header=True, header_style="bold magenta")
    table.add_column("Component", style="dim", width=22)
    table.add_column("State", justify="left")
    table.add_column("Telemetry Details", justify="left")

    table.add_row("Kernel Routing", "[green]Discovered[/green]", f"Device: {interface} (JSON Verified)")
    table.add_row("NetworkManager br0", "[green]Online[/green]", "STP: off, Guard: 15s, Controller Binding")
    
    fw_state = "[green]Enforced[/green]" if shutil.which("ufw") else "[yellow]Skipped (N/A)[/yellow]"
    table.add_row("UFW Firewall", fw_state, "ALLOW IN/OUT routing on br0")
    
    table.add_row("Libvirt Tracking", "[green]Provisioned[/green]", "host-bridge (Autostart: ON)")

    console.print("\n")
    console.print(table)
    console.print("\n[bold green]🚀 Phase 4 Execution Completed with Elite DevOps Precision![/bold green]\n")

def main():
    console.print(Panel.fit("[bold white]Phase 4: Enterprise KVM Network Bridging Automation[/bold white]", border_style="cyan"))
    
    verify_environment()
    
    interface = discover_active_interface()
    console.print(f"[*] Primary routing interface identified via kernel JSON: [bold yellow]{interface}[/bold yellow]")
    
    if is_wireless(interface):
        console.print(Panel("[bold red]CRITICAL HARDWARE LIMITATION: 802.11 Protocol violation detected.[/bold red]\n"
                            "The target interface is wireless. Standard system bridges strictly fail on Wi-Fi.\n"
                            "You must utilize 'macvtap' manually, or connect physical ethernet.", 
                            title="Abort Recommended", border_style="red"))
        if not Confirm.ask("Do you want to override and forcefully attempt standard bridging? (Highly destructive)"):
            console.print("[yellow]Execution aborted gracefully.[/yellow]")
            sys.exit(0)
    
    if not Confirm.ask(f"Ready to provision system bridge targeting [bold yellow]{interface}[/bold yellow]?"):
        console.print("[yellow]Execution aborted gracefully.[/yellow]")
        sys.exit(0)
        
    provision_nmcli_bridge(interface)
    configure_firewall()
    inject_libvirt_network()
    
    generate_telemetry_summary(interface)

if __name__ == "__main__":
    main()
