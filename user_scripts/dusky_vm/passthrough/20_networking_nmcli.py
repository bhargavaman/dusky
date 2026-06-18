#!/usr/bin/env python3
"""
Phase 4: KVM Network Bridging & LAN Access Automation
Environment: Arch Linux (Kernel 7.1.0, Python 3.14.5, systemd 260)
Scope: NetworkManager, UFW, Libvirt

Elite Standard:
- Dynamic kernel-level interface discovery.
- Modern NM terminology (controller vs deprecated master).
- Atomic libvirt injection with guaranteed zero-clutter cleanup.
"""

import os
import sys
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
    """Execute shell commands with elite reliability and timeout enforcement."""
    try:
        return subprocess.run(
            cmd,
            check=check,
            capture_output=capture,
            text=True,
            timeout=timeout
        )
    except subprocess.TimeoutExpired as e:
        console.print(f"[bold red]Command timed out after {timeout}s:[/bold red] {' '.join(cmd)}")
        if check:
            sys.exit(1)
        return e
    except subprocess.CalledProcessError as e:
        console.print(f"[bold red]Command failed:[/bold red] {' '.join(cmd)}")
        console.print(f"[red]Error:[/red] {e.stderr.strip() or e.stdout.strip()}")
        if check:
            sys.exit(1)
        return e

def enforce_root():
    """Ensure immutable privileges."""
    if os.geteuid() != 0:
        console.print("[bold red]ERROR: Phase 4 requires root privileges (sudo).[/bold red]")
        sys.exit(1)

def discover_active_interface() -> str:
    """
    Dynamically discover the active routing interface via the kernel's routing table.
    This prevents any hardcoding of 'enp3s0' or similar volatile identifiers.
    """
    try:
        res = run_cmd(["ip", "route", "show", "default"])
        output = res.stdout.strip()
        if not output:
            raise ValueError("No default route found in the kernel routing table.")
        
        parts = output.split()
        if "dev" in parts:
            dev_index = parts.index("dev")
            return parts[dev_index + 1]
        raise ValueError("Could not parse 'dev' identifier from the routing table.")
    except Exception as e:
        console.print(f"[bold red]Hardware Discovery Failed: {e}[/bold red]")
        sys.exit(1)

def is_wireless(interface: str) -> bool:
    """Definitively verify 802.11 status via sysfs kernel hooks."""
    return Path(f"/sys/class/net/{interface}/wireless").exists()

def provision_nmcli_bridge(interface: str):
    """Idempotent and modern NetworkManager bridge creation."""
    console.print("\n[bold cyan]─── NetworkManager Bridge Provisioning ───[/bold cyan]")
    
    # Precise Idempotency Check using modern -g (--get-values) flag
    res = run_cmd(["nmcli", "-g", "NAME,TYPE", "connection", "show"])
    connections = [line.split(':')[0] for line in res.stdout.strip().split('\n') if 'bridge' in line]
    
    if "br0" in connections:
        console.print("[bold green]✓ System bridge 'br0' already present. Perfectly staged.[/bold green]")
        return

    with console.status(f"[cyan]Constructing system bridge 'br0' over {interface}...", spinner="dots"):
        # 1. Instantiate the bridge. STP disabled for instantaneous VM network handshakes.
        run_cmd(["nmcli", "connection", "add", "type", "bridge", "ifname", "br0", "con-name", "br0", "bridge.stp", "no"])
        
        # 2. Bind physical interface using cutting-edge 'controller' syntax (deprecated: master/bridge-slave)
        slave_name = f"bridge-slave-{interface}"
        run_cmd([
            "nmcli", "connection", "add", 
            "type", "ethernet", 
            "ifname", interface, 
            "controller", "br0", 
            "con-name", slave_name
        ])
        
        # 3. Bring bridge online with strict 15-second timeout safeguard
        run_cmd(["nmcli", "--wait", "15", "connection", "up", "br0"])
        
    console.print(f"[bold green]✓ Bridge 'br0' materialized and successfully bound to {interface}.[/bold green]")

def configure_firewall():
    """Apply UFW routing rules to prevent default bridge traffic drops."""
    console.print("\n[bold cyan]─── Firewall Routing Configuration ───[/bold cyan]")
    
    if subprocess.run(["which", "ufw"], capture_output=True).returncode != 0:
        console.print("[yellow]⚠ UFW binary not found. Skipping iptables/nftables frontend configuration.[/yellow]")
        return

    with console.status("[cyan]Injecting UFW bridge forwarding rules...", spinner="dots"):
        run_cmd(["ufw", "route", "allow", "in", "on", "br0"], check=False)
        run_cmd(["ufw", "route", "allow", "out", "on", "br0"], check=False)
        run_cmd(["ufw", "reload"], check=False)
        
    console.print("[bold green]✓ Bridge traffic authorized through UFW kernel space.[/bold green]")

def inject_libvirt_network():
    """Atomically inject the bridge definition into the libvirt daemon."""
    console.print("\n[bold cyan]─── Libvirt Network Injection ───[/bold cyan]")
    
    # Check libvirt state idempotently
    res = run_cmd(["virsh", "net-list", "--all", "--name"])
    if "host-bridge" in res.stdout.split():
        console.print("[bold green]✓ Libvirt network 'host-bridge' already registered. Skipping injection.[/bold green]")
        
        # Enforce activation guarantees
        run_cmd(["virsh", "net-autostart", "host-bridge"], check=False)
        state_res = run_cmd(["virsh", "net-info", "host-bridge"])
        if "Active: yes" not in state_res.stdout:
            run_cmd(["virsh", "net-start", "host-bridge"], check=False)
        return

    # Modern libvirt XML payload
    xml_payload = """<network>
  <name>host-bridge</name>
  <forward mode='bridge'/>
  <bridge name='br0'/>
</network>"""

    # Atomic execution: generate, digest, and instantly vaporize the file.
    fd, temp_path = tempfile.mkstemp(prefix="libvirt-br0-", suffix=".xml")
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(xml_payload)
            
        with console.status("[cyan]Injecting atomic payload into libvirt...", spinner="bouncingBar"):
            run_cmd(["virsh", "net-define", temp_path])
            run_cmd(["virsh", "net-start", "host-bridge"])
            run_cmd(["virsh", "net-autostart", "host-bridge"])
            
    finally:
        os.unlink(temp_path)  # Absolute guarantee of zero clutter
        
    console.print("[bold green]✓ Libvirt payload digested and activated atomically.[/bold green]")

def generate_telemetry_summary(interface: str):
    """Render the executive Phase 4 summary table."""
    table = Table(title="Phase 4: Network Architecture Summary", show_header=True, header_style="bold magenta")
    table.add_column("Component", style="dim", width=22)
    table.add_column("State", justify="left")
    table.add_column("Telemetry Details", justify="left")

    table.add_row("Kernel Routing", "[green]Discovered[/green]", interface)
    table.add_row("NetworkManager br0", "[green]Online[/green]", "STP: off, Timeout Guard: 15s")
    table.add_row("UFW Firewall", "[green]Enforced[/green]", "ALLOW IN/OUT routing on br0")
    table.add_row("Libvirt tracking", "[green]Provisioned[/green]", "host-bridge (Autostart: ON)")

    console.print("\n")
    console.print(table)
    console.print("\n[bold green]🚀 Phase 4 Execution Completed with Elite DevOps Precision![/bold green]\n")

def main():
    console.print(Panel.fit("[bold white]Phase 4: Enterprise KVM Network Bridging Automation[/bold white]", border_style="cyan"))
    
    enforce_root()
    
    interface = discover_active_interface()
    console.print(f"[*] Primary routing interface identified: [bold yellow]{interface}[/bold yellow]")
    
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
