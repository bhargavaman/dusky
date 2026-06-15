#!/usr/bin/env python3
import subprocess
import sys
import os
import re

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Confirm, Prompt
except ImportError:
    print("\n[CRITICAL ERROR] The 'rich' library is not installed.")
    print("Please install it before running this script.")
    print("Run: sudo pacman -S python-rich")
    sys.exit(1)

console = Console()

def check_root_and_locks():
    """Ensure proper privileges and check for pacman database locks."""
    if os.geteuid() == 0:
        console.print("[bold red]Do not run this script as root. Run it as your normal user, and sudo will be invoked securely when needed.[/bold red]")
        sys.exit(1)
        
    if os.path.exists("/var/lib/pacman/db.lck"):
        console.print("[bold red]Pacman database is locked (/var/lib/pacman/db.lck).[/bold red]")
        console.print("Another package manager is running, or a previous installation crashed.")
        console.print("Please resolve this by running: sudo rm /var/lib/pacman/db.lck")
        sys.exit(1)

def is_multilib_enabled() -> bool:
    """Parses pacman.conf to check if [multilib] is active."""
    try:
        with open('/etc/pacman.conf', 'r') as f:
            content = f.read()
            if re.search(r'^\s*\[multilib\]', content, re.MULTILINE):
                return True
    except FileNotFoundError:
        console.print("[bold red]Critical system file /etc/pacman.conf not found![/bold red]")
        sys.exit(1)
    return False

def run_command(command: str, description: str, critical: bool = True):
    """Executes a shell command with an interactive Rich status spinner."""
    console.print(f"\n[bold cyan]Target:[/bold cyan] {description}")
    console.print(f"[bold black on white] {command} [/bold black on white]")
    
    if not Confirm.ask("[bold yellow]Execute this step?[/bold yellow]", default=True):
        console.print("[dim]Skipped by user.[/dim]")
        return True

    with console.status(f"[bold green]Executing: {command}...[/bold green]", spinner="dots"):
        try:
            # We pipe stdout to hide the raw output behind the spinner.
            # CRITICAL: Any command run here MUST have a 'yes' or '--noconfirm' flag!
            process = subprocess.run(
                command, 
                shell=True, 
                check=True, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                text=True
            )
            console.print("[bold green]✔ Success![/bold green]")
            return True
        except subprocess.CalledProcessError as e:
            console.print(f"[bold red]✘ Failed with exit code {e.returncode}[/bold red]")
            error_output = e.stderr.strip() if e.stderr else e.stdout.strip()
            console.print(Panel(error_output, title="Terminal Error Output", border_style="red"))
            
            if critical:
                console.print("[bold red]A critical step failed. Aborting the script to maintain system stability.[/bold red]")
                sys.exit(1)
            return False

def main():
    console.clear()
    console.print(Panel.fit(
        "[bold magenta]Arch Linux Golden Gaming Setup[/bold magenta]\n"
        "[white]Comprehensive automated installer for Drivers, Steam, Bottles, & Flatpaks.[/white]",
        border_style="magenta"
    ))

    # Pre-flight checks
    check_root_and_locks()

    # Cache sudo credentials upfront so it doesn't hang waiting for a password later
    subprocess.run("sudo -v", shell=True, check=True)

    # Step 1: System Sync
    run_command(
        "sudo pacman -Syu --noconfirm",
        "Synchronize package databases and apply core system updates."
    )

    # Step 2: Intelligent Multilib Configuration
    multilib_active = is_multilib_enabled()
    
    if multilib_active:
        console.print(Panel(
            "The \[multilib] repository is [bold green]ALREADY ENABLED[/bold green].\n"
            "Your system is already configured for 32-bit gaming libraries.",
            style="green"
        ))
    else:
        console.print(Panel(
            "The \[multilib] repository is [bold red]NOT ENABLED[/bold red].\n"
            "This is MANDATORY for Steam and Wine to process 32-bit Windows instructions.",
            style="yellow"
        ))
        run_command(
            "sudo sed -i '/^#\\[multilib\\]/{s/^#//;n;s/^#//}' /etc/pacman.conf && sudo pacman -Syu --noconfirm",
            "Enable 32-bit multilib repository in pacman.conf and sync databases."
        )

    # Step 3: GPU Drivers (Vulkan Translation)
    console.print("\n[bold cyan]Select your GPU Vendor for strictly required Vulkan Drivers:[/bold cyan]")
    console.print("1. AMD (Radeon)")
    console.print("2. NVIDIA")
    console.print("3. Skip (I manage my own graphics drivers)")
    gpu_choice = Prompt.ask("Enter choice", choices=["1", "2", "3"], default="3")
    
    if gpu_choice == "1":
        run_command(
            "sudo pacman -S --needed --noconfirm vulkan-radeon lib32-vulkan-radeon mesa lib32-mesa",
            "Install strictly required AMD native and 32-bit Vulkan/Mesa drivers."
        )
    elif gpu_choice == "2":
        run_command(
            "sudo pacman -S --needed --noconfirm nvidia-utils lib32-nvidia-utils",
            "Install strictly required NVIDIA proprietary utilities and 32-bit Vulkan drivers."
        )

    # Step 4: Core Native Gaming Tools
    run_command(
        "sudo pacman -S --needed --noconfirm steam flatpak gamemode lib32-gamemode mangohud lib32-mangohud",
        "Install Steam, Flatpak daemon, Feral GameMode (CPU optimization), and MangoHud."
    )

    # Step 5: Flatpak Repository Initialization
    run_command(
        "flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo",
        "Initialize Flathub remote server for application downloads."
    )

    # Step 6: Flatpak Gaming Ecosystem
    flatpak_apps = {
        "Bottles": "com.usebottles.bottles",
        "Flatseal": "com.github.tchx84.Flatseal",
        "ProtonPlus": "com.vysp3r.ProtonPlus"
    }

    for app_name, app_id in flatpak_apps.items():
        run_command(
            f"flatpak install flathub {app_id} -y",
            f"Install {app_name} securely via Flatpak sandbox.",
            critical=False 
        )

    # Final Summary
    console.print(Panel.fit(
        "[bold green]✔ Architecture Established![/bold green]\n"
        "Your Arch Linux system is fully armed for modern Windows repack compilation.\n\n"
        "[bold]Immediate Next Steps for Forza Horizon 6:[/bold]\n"
        "1. Open [cyan]Flatseal[/cyan] and grant [cyan]Bottles[/cyan] absolute filesystem permissions to your secondary drive.\n"
        "2. Open [cyan]Bottles[/cyan], create a 'Gaming' environment, and execute the FitGirl setup.exe.\n"
        "3. [bold red]CRITICAL:[/bold red] Check the 'Limit installer to 2GB' box to prevent decompression engine crashes.",
        border_style="green"
    ))

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n\n[bold red]Script terminated abruptly by user. Exiting safely.[/bold red]")
        sys.exit(0)
