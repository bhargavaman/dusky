#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
import re
from pathlib import Path

# 1. Dependency Auto-Installer Checker
def check_dependencies():
    """Verify python-rich, python-keyring, python-secretstorage, and python-dbus are installed. Auto-installs if missing."""
    needed = []
    try:
        import rich
    except ImportError:
        needed.append("python-rich")
    try:
        import keyring
    except ImportError:
        needed.append("python-keyring")
    try:
        import secretstorage
    except ImportError:
        needed.append("python-secretstorage")
    try:
        import dbus
    except ImportError:
        needed.append("python-dbus")
        
    if needed:
        if not sys.stdout.isatty():
            print(f"[Error] Missing dependencies: {', '.join(needed)}. Run interactively to install.")
            sys.exit(1)
            
        print(f"[Info] Missing required packages: {', '.join(needed)}")
        print("[Info] Attempting to install missing dependencies via pacman...")
        try:
            # Map Python import names to Arch Linux package names
            pkg_map = {
                "python-rich": "python-rich",
                "python-keyring": "python-keyring",
                "python-secretstorage": "python-secretstorage",
                "python-dbus": "python-dbus"
            }
            pkgs_to_install = [pkg_map[n] for n in needed]
            cmd = ["sudo", "pacman", "-S", "--noconfirm"] + pkgs_to_install
            
            print(f"Running command: {' '.join(cmd)}")
            subprocess.run(cmd, check=True)
            print("[Success] Packages installed. Restarting switcher...")
            # Re-execute the script
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            print(f"[Error] Failed to install packages: {e}")
            print(f"Please run: sudo pacman -S {' '.join(needed)}")
            sys.exit(1)

# Run dependency check first
check_dependencies()

# Now import rich and keyring safely
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt
from rich.align import Align
from rich.text import Text
import keyring

console = Console()

TEST_DIR = os.environ.get("ANTIGRAVITY_PROFILE_TEST_DIR")
if TEST_DIR:
    GEMINI_DIR = Path(TEST_DIR)
else:
    GEMINI_DIR = Path.home() / ".gemini"
PROFILES_DIR = GEMINI_DIR / "profiles"
ACTIVE_PROFILE_FILE = PROFILES_DIR / "active_profile.txt"
TARGETS = ["antigravity", "antigravity-cli", "antigravity-ide"]

def validate_profile_name(name: str) -> bool:
    """Validate profile name to ensure it is alphanumeric, underscores, or dashes."""
    return bool(re.match(r"^[a-zA-Z0-9_-]+$", name))

def get_running_processes() -> list:
    """Return PIDs of running Antigravity or agy processes, excluding this script and parent shells."""
    pids = []
    for term in ["antigravity", "agy"]:
        try:
            out = subprocess.run(["pgrep", "-f", term], capture_output=True, text=True)
            if out.returncode == 0:
                pids.extend([pid.strip() for pid in out.stdout.strip().split("\n") if pid.strip()])
        except Exception:
            pass
            
    # Exclude our own process and direct parent/ancestor processes
    exclude = {str(os.getpid()), str(os.getppid())}
    try:
        grandparent = subprocess.run(
            ["ps", "-o", "ppid=", "-p", str(os.getppid())], 
            capture_output=True, text=True
        )
        if grandparent.returncode == 0:
            exclude.add(grandparent.stdout.strip())
    except Exception:
        pass
        
    return [pid for pid in set(pids) if pid not in exclude]

def get_active_profile() -> str:
    """Get the name of the active profile."""
    if ACTIVE_PROFILE_FILE.exists():
        try:
            name = ACTIVE_PROFILE_FILE.read_text().strip()
            if name and (PROFILES_DIR / name).exists():
                return name
        except Exception:
            pass
            
    # Fallback/Inference
    for target in TARGETS:
        target_path = GEMINI_DIR / target
        if target_path.is_symlink():
            try:
                resolved = target_path.readlink()
                if PROFILES_DIR in resolved.parents:
                    return resolved.parent.name
            except Exception:
                pass
    return None

def stash_keyring(profile_name: str):
    """Save the keyring token to the profile folder."""
    try:
        token = keyring.get_password("gemini", "antigravity")
        token_file = PROFILES_DIR / profile_name / "keyring_token.json"
        if token:
            token_file.write_text(token)
            console.print(f"[bold blue][[Info][/bold blue] Stashed keyring credentials for profile '[bold green]{profile_name}[/bold green]'.")
        elif token_file.exists():
            pass
    except Exception as e:
        console.print(f"[bold yellow][[Warning][/bold yellow] Failed to stash keyring credentials: {e}")

def restore_keyring(profile_name: str):
    """Restore the keyring token from the profile folder."""
    token_file = PROFILES_DIR / profile_name / "keyring_token.json"
    if token_file.exists():
        try:
            token = token_file.read_text().strip()
            if token:
                keyring.set_password("gemini", "antigravity", token)
                console.print(f"[bold blue][[Info][/bold blue] Restored keyring credentials for profile '[bold green]{profile_name}[/bold green]'.")
        except Exception as e:
            console.print(f"[bold yellow][[Warning][/bold yellow] Failed to restore keyring credentials: {e}")
    else:
        # Clear current keyring entry so new profile starts logged out
        try:
            keyring.delete_password("gemini", "antigravity")
            console.print(f"[bold blue][[Info][/bold blue] Cleared keyring credentials (profile '[bold green]{profile_name}[/bold green]' starts logged out).")
        except Exception:
            pass

def ensure_profile_structure(profile_name: str):
    """Ensure the profile directories exist."""
    profile_path = PROFILES_DIR / profile_name
    profile_path.mkdir(parents=True, exist_ok=True)
    for target in TARGETS:
        (profile_path / target).mkdir(parents=True, exist_ok=True)

def migrate_existing_to_profile(profile_name: str):
    """Migrate existing non-symlink directories to a profile."""
    ensure_profile_structure(profile_name)
    profile_path = PROFILES_DIR / profile_name
    
    for target in TARGETS:
        target_path = GEMINI_DIR / target
        if target_path.exists() and not target_path.is_symlink():
            console.print(f"[bold blue][[Info][/bold blue] Migrating existing directory {target_path} to profile '[bold green]{profile_name}[/bold green]'...")
            dest_path = profile_path / target
            if dest_path.exists():
                shutil.rmtree(dest_path)
            shutil.move(str(target_path), str(dest_path))

def setup_symlinks(profile_name: str):
    """Link the main config paths to the target profile."""
    profile_path = PROFILES_DIR / profile_name
    
    for target in TARGETS:
        target_path = GEMINI_DIR / target
        if target_path.exists() or target_path.is_symlink():
            if target_path.is_symlink():
                target_path.unlink()
            elif target_path.is_dir():
                backup_path = GEMINI_DIR / f"{target}.bak"
                console.print(f"[bold yellow][[Warning][/bold yellow] Unexpected directory at {target_path}, backing up to {backup_path}")
                if backup_path.exists():
                    shutil.rmtree(backup_path)
                shutil.move(str(target_path), str(backup_path))
            else:
                target_path.unlink()
                
        target_path.symlink_to(profile_path / target)
        console.print(f"[bold dim][[Link] {target_path} -> {profile_path / target}[/bold dim]")

def switch_profile(profile_name: str):
    """Perform the full switch to the target profile."""
    if not validate_profile_name(profile_name):
        console.print(f"[bold red][[Error][/bold red] Invalid profile name: '{profile_name}'. Use only alphanumeric, dashes, and underscores.")
        sys.exit(1)
        
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    
    # Check for running processes
    running = get_running_processes()
    if running:
        console.print(f"[bold yellow][[Warning][/bold yellow] Active Antigravity processes detected (PIDs: {', '.join(running)}).")
        console.print("[bold yellow][[Warning][/bold yellow] It is highly recommended to close all Antigravity CLI/IDE/App instances before switching profiles.")
        try:
            confirm = Prompt.ask("Do you want to proceed with the switch anyway?", choices=["y", "n"], default="n")
            if confirm != 'y':
                console.print("[bold red]Switch cancelled.[/bold red]")
                sys.exit(0)
        except (KeyboardInterrupt, EOFError):
            console.print("\n[bold red]Switch cancelled.[/bold red]")
            sys.exit(0)
            
    current_profile = get_active_profile()
    
    # Check if migration is needed
    needs_migration = any((GEMINI_DIR / t).exists() and not (GEMINI_DIR / t).is_symlink() for t in TARGETS)
    if needs_migration:
        migration_profile = "default"
        console.print(f"[bold blue][[Info][/bold blue] Non-symlink directories detected. Performing initial migration to '[bold green]{migration_profile}[/bold green]' profile...")
        migrate_existing_to_profile(migration_profile)
        current_profile = migration_profile
        ACTIVE_PROFILE_FILE.write_text(migration_profile)
        
    # Stash keyring of current profile before switching away
    if current_profile:
        stash_keyring(current_profile)
        
    # Ensure target profile folders exist
    ensure_profile_structure(profile_name)
    
    # Setup symlinks
    setup_symlinks(profile_name)
    
    # Restore keyring for the new profile
    restore_keyring(profile_name)
    
    # Save active profile name
    ACTIVE_PROFILE_FILE.write_text(profile_name)
    console.print(f"\n[bold green]✔ Success:[/bold green] Switched active profile to '[bold green]{profile_name}[/bold green]'.")

def list_profiles_rich():
    """List all profiles in a beautiful Rich table."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    active = get_active_profile()
    profiles = sorted([p.name for p in PROFILES_DIR.iterdir() if p.is_dir()])
    
    needs_migration = any((GEMINI_DIR / t).exists() and not (GEMINI_DIR / t).is_symlink() for t in TARGETS)
    
    table = Table(title="Available Antigravity Profiles", title_style="bold magenta", border_style="violet", expand=True)
    table.add_column("No.", justify="right", style="cyan", no_wrap=True)
    table.add_column("Status", justify="center", no_wrap=True)
    table.add_column("Profile Name", style="bold green")
    table.add_column("Credentials State", justify="center", no_wrap=True)
    table.add_column("Storage Path", style="dim white")
    
    if not profiles and needs_migration:
        table.add_row("-", "⚠️", "Unmigrated Local Config", "Logged In", str(GEMINI_DIR))
    else:
        for idx, p in enumerate(profiles, start=1):
            is_active = p == active
            status_text = Text("● Active", style="bold green") if is_active else Text("○ Inactive", style="dim white")
            
            token_file = PROFILES_DIR / p / "keyring_token.json"
            session_status = Text("Logged In", style="bold green") if (token_file.exists() and token_file.stat().st_size > 0) else Text("Logged Out", style="yellow")
            
            path_str = f"~/.gemini/profiles/{p}"
            table.add_row(str(idx), status_text, p, session_status, path_str)
            
    if not profiles and not needs_migration:
        console.print("\n[dim]No profiles created yet.[/dim]\n")
    else:
        console.print(table)
    return profiles

def delete_profile(profile_name: str):
    """Delete a profile and its directories."""
    if profile_name == get_active_profile():
        console.print(f"[bold red][[Error][/bold red] Cannot delete the currently active profile '{profile_name}'. Switch to another profile first.")
        return
        
    profile_path = PROFILES_DIR / profile_name
    if not profile_path.exists():
        console.print(f"[bold red][[Error][/bold red] Profile '{profile_name}' does not exist.")
        return
        
    confirm = Prompt.ask(f"Are you sure you want to permanently delete profile '[bold red]{profile_name}[/bold red]'?", choices=["y", "n"], default="n")
    if confirm == "y":
        try:
            shutil.rmtree(profile_path)
            console.print(f"[bold green]✔ Success:[/bold green] Profile '{profile_name}' deleted.")
        except Exception as e:
            console.print(f"[bold red][[Error][/bold red] Failed to delete profile: {e}")

def print_help():
    """Print dynamic help menu listing active and available profiles."""
    active = get_active_profile()
    profiles = sorted([p.name for p in PROFILES_DIR.iterdir() if p.is_dir()])
    
    title = Text("Antigravity Profile Switcher Help", style="bold magenta")
    console.print(Panel(title, border_style="violet"))
    
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  python3 switch_accounts.py               # Run the interactive TUI menu")
    console.print("  python3 switch_accounts.py <profile>     # Switch to profile (creates if missing)")
    console.print("  python3 switch_accounts.py -l, --list    # List all available profiles")
    console.print("  python3 switch_accounts.py -h, --help    # Show this help menu")
    
    console.print("\n[bold cyan]Active Profile:[/bold cyan]")
    if active:
        console.print(f"  ● [bold green]{active}[/bold green] (Currently selected)")
    else:
        console.print("  ⚠️ [bold yellow]Unmigrated Local Config[/bold yellow]")
        
    console.print("\n[bold cyan]Available Profiles:[/bold cyan]")
    if profiles:
        for p in profiles:
            marker = "  ●" if p == active else "  ○"
            style = "bold green" if p == active else "white"
            console.print(f"{marker} [{style}]{p}[/{style}]")
    else:
        console.print("  [dim]No profiles created yet.[/dim]")
    console.print()

def interactive_tui():
    """Run the interactive rich terminal interface."""
    while True:
        console.clear()
        
        # Header Panel
        title = Text("🚀 Antigravity Profile Manager", style="bold magenta")
        subtitle = Text("Seamlessly switch between multiple accounts", style="italic cyan")
        console.print(Panel(Align.center(Text.assemble(title, "\n", subtitle)), border_style="violet"))
        
        # Show Profiles Table
        profiles = list_profiles_rich()
        
        console.print("\n[bold cyan]Menu Actions:[/bold cyan]")
        if profiles:
            console.print(f"  [bold green]\\[1-{len(profiles)}][/bold green] Switch to a profile")
        console.print("  [bold green]\\[c][/bold green] Create new profile")
        if profiles:
            console.print("  [bold green]\\[d][/bold green] Delete a profile")
        console.print("  [bold green]\\[b][/bold green] Backup / Stash current session credentials")
        console.print("  [bold green]\\[q][/bold green] Quit")
        console.print("")
        
        try:
            if not profiles:
                action = Prompt.ask("Select an option", default="c").strip().lower()
            else:
                action = Prompt.ask("Select an option").strip().lower()
        except (KeyboardInterrupt, EOFError):
            console.print("\nExiting.")
            break
            
        if action == 'q':
            console.print("Exiting. Goodbye!")
            break
        elif action == 'c':
            name = Prompt.ask("Enter name for new profile").strip()
            if name:
                if not validate_profile_name(name):
                    console.print("[bold red][[Error][/bold red] Invalid name. Use only alphanumeric, dashes, and underscores.")
                    Prompt.ask("Press Enter to continue")
                elif (PROFILES_DIR / name).exists():
                    console.print(f"[bold red][[Error][/bold red] Profile '{name}' already exists.")
                    Prompt.ask("Press Enter to continue")
                else:
                    switch_profile(name)
                    Prompt.ask("\nPress Enter to continue")
        elif action == 'd':
            if not profiles:
                console.print("[bold yellow]No profiles to delete.[/bold yellow]")
                Prompt.ask("Press Enter to continue")
                continue
            name = Prompt.ask("Enter profile name to delete").strip()
            if name:
                delete_profile(name)
                Prompt.ask("\nPress Enter to continue")
        elif action == 'b':
            active = get_active_profile()
            if active:
                stash_keyring(active)
            else:
                console.print("[bold red][[Error][/bold red] No active profile set. Please switch to a profile first.")
            Prompt.ask("\nPress Enter to continue")
        elif action.isdigit():
            if not profiles:
                console.print("[bold red][[Error][/bold red] No profiles exist yet. Type '[bold green]c[/bold green]' to create a new profile.")
                Prompt.ask("Press Enter to continue")
            else:
                idx = int(action) - 1
                if 0 <= idx < len(profiles):
                    switch_profile(profiles[idx])
                    Prompt.ask("\nPress Enter to continue")
                else:
                    console.print(f"[bold red][[Error][/bold red] Index out of range (must be between 1 and {len(profiles)}).")
                    Prompt.ask("Press Enter to continue")
        elif action == '':
            continue
        else:
            console.print("[bold red][[Error][/bold red] Invalid option.")
            Prompt.ask("Press Enter to continue")

def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ["-l", "--list"]:
            list_profiles_rich()
        elif arg in ["-h", "--help"]:
            print_help()
        else:
            switch_profile(arg)
    else:
        interactive_tui()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[bold red]Operation cancelled by user.[/bold red]")
