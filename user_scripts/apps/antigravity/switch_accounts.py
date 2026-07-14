#!/usr/bin/env python3

import sys
import subprocess
import shutil
import importlib.util
import os
import re
import argparse
from pathlib import Path

# ==========================================
# 1. AUTONOMOUS FAIL-SAFE DEPENDENCY RESOLVER
# ==========================================
def resolve_dependencies() -> None:
    """Iterative dependency resolver with TTY awareness and PIP/AUR fallbacks."""
    requirements = {
        "rich": {"pac": "python-rich", "pip": "rich"},
        "keyring": {"pac": "python-keyring", "pip": "keyring"},
        "questionary": {"pac": "python-questionary", "pip": "questionary"},
        "psutil": {"pac": "python-psutil", "pip": "psutil"}
    }

    missing = [mod for mod in requirements if importlib.util.find_spec(mod) is None]
    if not missing:
        return

    if not sys.stdout.isatty():
        print(f"\n[✖] FATAL: Missing dependencies ({', '.join(missing)}) in non-interactive shell.")
        print("[✖] Cannot invoke pacman/sudo. Please run interactively to bootstrap.")
        sys.exit(1)

    print(f"\n[*] Missing dependencies detected: {', '.join(missing)}")
    print("[*] Engaging autonomous fail-safe resolver...\n")

    subprocess.run(["sudo", "-v"], check=False)
    aur_helper = next((h for h in ["paru", "yay"] if shutil.which(h)), None)

    for mod in missing:
        pkg_pac = requirements[mod]["pac"]
        pkg_pip = requirements[mod]["pip"]
        print(f" -> Resolving '{mod}'...")
        
        success = False

        if aur_helper:
            res = subprocess.run([aur_helper, "-S", "--needed", "--noconfirm", pkg_pac], 
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            success = (res.returncode == 0)

        if not success:
            res = subprocess.run(["sudo", "pacman", "-S", "--needed", "--noconfirm", pkg_pac], 
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            success = (res.returncode == 0)

        if not success:
            print(f"    [!] '{pkg_pac}' absent from repos. Injecting via pip bypass...")
            res = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--user", "--break-system-packages", pkg_pip],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            success = (res.returncode == 0)

        if not success:
            print(f"\n[✖] FATAL: Absolute failure resolving '{mod}'.")
            sys.exit(1)

    print("\n[✔] Matrix dependencies successfully satisfied. Rebooting manager...\n")
    os.execv(sys.executable, [sys.executable] + sys.argv)

resolve_dependencies()

from rich.console import Console
from rich.theme import Theme
from rich.panel import Panel
from rich.table import Table
from rich.align import Align
from rich.text import Text
from rich.rule import Rule
import keyring
import questionary
import psutil

# ==========================================
# 2. UI THEMING & GLOBAL INIT
# ==========================================
custom_theme = Theme({
    "info": "dim cyan",
    "warning": "bold yellow",
    "error": "bold red",
    "success": "bold green",
    "highlight": "bold magenta",
    "muted": "dim white"
})

console = Console(theme=custom_theme)

if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
    console.print("[warning]⚠ DBUS_SESSION_BUS_ADDRESS not found. Keyring auth operations may fail.[/warning]")

# ==========================================
# 3. MODERN TYPE ALIASES (Python 3.12+)
# ==========================================
type ProcList = list[psutil.Process]
type ProfileList = list[str]

# ==========================================
# 4. CORE MANAGER CLASS
# ==========================================
class ProfileManager:
    def __init__(self, force_mode: bool = False) -> None:
        self.force_mode = force_mode
        self.storage_dir = Path.home() / ".config" / "dusky" / "settings" / "apps" / "antigravity"
        self.profiles_dir = self.storage_dir / "profiles"
        self.active_profile_file = self.profiles_dir / "active_profile.txt"
        
        try:
            self.profiles_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            console.print(f"[error]✖ Fatal: Filesystem constraint preventing directory creation in {self.storage_dir}: {e}[/error]")
            sys.exit(1)

    @staticmethod
    def is_valid_name(name: str) -> bool:
        """Strict alphanumeric, dash, and underscore validation."""
        return bool(re.match(r"^[a-zA-Z0-9_-]+$", name))

    def get_active(self) -> str | None:
        if self.active_profile_file.is_file():
            try:
                name = self.active_profile_file.read_text(encoding="utf-8").strip()
                # Security: Prevent path traversal by validating the string
                if name and self.is_valid_name(name) and (self.profiles_dir / name).is_dir():
                    return name
            except IOError as e:
                console.print(f"[warning]⚠ State read error: {e}[/warning]")
        return None

    def get_all(self) -> ProfileList:
        try:
            # Security: Filter out invalid directories (e.g. backup folders)
            return sorted(p.name for p in self.profiles_dir.iterdir() if p.is_dir() and self.is_valid_name(p.name))
        except IOError:
            return []

    def _get_token_path(self, profile_name: str) -> Path:
        """Resolve token path and silently migrate legacy .json extensions to .txt"""
        legacy = self.profiles_dir / profile_name / "keyring_token.json"
        txt = self.profiles_dir / profile_name / "keyring_token.txt"
        if legacy.exists() and not txt.exists():
            try:
                legacy.rename(txt)
            except OSError:
                pass
        return txt

    def check_running_processes(self) -> ProcList:
        """Kernel-level mapping with exact basename precision and lineage exclusions."""
        procs: ProcList = []
        current_pid = os.getpid()
        parent_pid = os.getppid()
        
        try:
            grandparent_pid = psutil.Process(parent_pid).ppid()
        except psutil.Error:
            grandparent_pid = -1
            
        exclude_pids = {current_pid, parent_pid, grandparent_pid}
        target_bins = {"antigravity", "agy", "antigravity-cli", "antigravity-ide"}
        
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['pid'] in exclude_pids:
                    continue
                    
                name = (proc.info['name'] or "").lower()
                cmdline = proc.info['cmdline'] or []
                
                is_match = False
                
                if name in target_bins:
                    is_match = True
                else:
                    for arg in cmdline:
                        base = Path(arg).name.lower()
                        if base in target_bins and "switch_accounts" not in base:
                            is_match = True
                            break
                            
                if is_match:
                    procs.append(proc)
            except psutil.Error:
                pass
        return procs

    def kill_processes(self, processes: ProcList) -> None:
        """Safely terminate blocking processes with broad exception handling."""
        for proc in processes:
            try:
                proc.terminate()
            except psutil.Error:
                continue
        
        gone, alive = psutil.wait_procs(processes, timeout=3.0)
        for proc in alive:
            try:
                proc.kill() 
            except psutil.Error:
                pass
                
        console.print("[success]✔ Conflicting processes resolved.[/success]")

    def stash_keyring(self, profile_name: str) -> None:
        try:
            token = keyring.get_password("gemini", "antigravity")
            token_file = self._get_token_path(profile_name)
            if token:
                token_file.write_text(token, encoding="utf-8")
                # Security Override: Force UNIX permissions regardless of existing file state
                token_file.chmod(0o600)
                console.print(f"[info]ℹ Secured auth token to '{profile_name}'.[/info]")
        except Exception as e:
            console.print(f"[warning]⚠ Credential stash failure: {e}[/warning]")

    def restore_keyring(self, profile_name: str) -> None:
        token_file = self._get_token_path(profile_name)
        if token_file.is_file():
            try:
                token = token_file.read_text(encoding="utf-8").strip()
                if token:
                    keyring.set_password("gemini", "antigravity", token)
                    console.print(f"[info]ℹ Restored auth credentials from '{profile_name}'.[/info]")
            except Exception as e:
                console.print(f"[error]✖ Credential restore failure: {e}[/error]")
        else:
            try:
                keyring.delete_password("gemini", "antigravity")
                console.print("[info]ℹ Purged global auth state (profile initialized fresh).[/info]")
            except Exception:
                pass 

    def switch(self, target_profile: str) -> bool:
        if not self.is_valid_name(target_profile):
            console.print(f"[error]✖ Error: Invalid profile syntax '{target_profile}'.[/error]")
            return False

        current_profile = self.get_active()
        if current_profile == target_profile:
            console.print(f"[info]ℹ State unchanged. Already on '{target_profile}'.[/info]")
            return True

        running_procs = self.check_running_processes()
        if running_procs:
            if self.force_mode:
                console.print("[warning]⚠ Force override active: Bypassing process collision checks.[/warning]")
            elif not sys.stdout.isatty():
                console.print(f"\n[error]✖ Active Antigravity processes detected in non-interactive mode. Aborting switch to prevent background hang. Use -f/--force to override.[/error]")
                return False
            else:
                console.print(f"\n[warning]⚠ {len(running_procs)} Active Antigravity process(es) detected![/warning]")
                action = questionary.select(
                    "Resolve collision:",
                    choices=[
                        questionary.Choice("Abort (Safe)", value="cancel"),
                        questionary.Choice("SIGKILL & Proceed", value="kill"),
                        questionary.Choice("Ignore & Proceed (Risky)", value="ignore")
                    ],
                    style=questionary.Style([('pointer', 'fg:ansiyellow bold')])
                ).ask()
                
                match action:
                    case "cancel" | None:
                        console.print("[error]Operation aborted.[/error]")
                        return False
                    case "kill":
                        self.kill_processes(running_procs)
                    case "ignore":
                        console.print("[warning]Proceeding with collision risk...[/warning]")

        if current_profile:
            self.stash_keyring(current_profile)

        target_path = self.profiles_dir / target_profile
        try:
            target_path.mkdir(parents=True, exist_ok=True)
            self.restore_keyring(target_profile)
            self.active_profile_file.write_text(target_profile, encoding="utf-8")
        except IOError as e:
            console.print(f"[error]✖ IO fault during state switch: {e}[/error]")
            return False
            
        console.print(f"\n[success]✔ Switched to isolated profile: '{target_profile}'.[/success]")
        return True

    def cycle_next(self) -> bool:
        profiles = self.get_all()
        if not profiles:
            console.print("[error]✖ Error: Array is empty. No profiles to cycle.[/error]")
            return False
            
        active = self.get_active()
        next_profile = profiles[0] if active not in profiles else profiles[(profiles.index(active) + 1) % len(profiles)]
            
        console.print(f"\n[info]⟳ Iterating to next sequential profile...[/info]")
        return self.switch(next_profile)

    def create(self, name: str) -> None:
        if not self.is_valid_name(name):
            console.print("[error]✖ Syntax Error: Alphanumeric, dash, and underscores exclusively.[/error]")
            return
            
        profile_path = self.profiles_dir / name
        if profile_path.is_dir():
            console.print(f"[error]✖ Collision: Profile '{name}' already exists.[/error]")
            return
            
        try:
            profile_path.mkdir(parents=True)
            console.print(f"[success]✔ Initialized isolated context: '{name}'.[/success]")
            if questionary.confirm("Execute context switch to new profile now?").ask():
                self.switch(name)
        except OSError as e:
            console.print(f"[error]✖ IO Error during initialization: {e}[/error]")

    def delete(self, name: str) -> None:
        if name == self.get_active():
            console.print("[error]✖ State lock: Cannot wipe the active profile. Cycle first.[/error]")
            return
            
        profile_path = self.profiles_dir / name
        if not profile_path.is_dir():
            console.print(f"[error]✖ Missing Reference: '{name}' does not exist.[/error]")
            return
            
        if questionary.confirm(f"Permanently wipe '{name}' and all isolated data?").ask():
            try:
                shutil.rmtree(profile_path)
                console.print(f"[success]✔ Profile '{name}' successfully eradicated.[/success]")
            except OSError as e:
                console.print(f"[error]✖ IO Fault during deletion: {e}[/error]")

    def render_dashboard(self) -> None:
        active = self.get_active()
        profiles = self.get_all()
        
        table = Table(title="Local Isolation Matrix", title_style="highlight", border_style="magenta", expand=True)
        table.add_column("Index", justify="right", style="cyan", no_wrap=True)
        table.add_column("State", justify="center", no_wrap=True)
        table.add_column("Profile Name", style="success")
        table.add_column("Login Status", justify="center", no_wrap=True)
        
        for idx, p in enumerate(profiles, start=1):
            is_active = p == active
            status_text = Text("● ACTIVE", style="bold green") if is_active else Text("○ STANDBY", style="dim white")
            
            token_file = self._get_token_path(p)
            auth_state = Text("Secured", style="bold cyan") if (token_file.is_file() and token_file.stat().st_size > 0) else Text("Void", style="dim yellow")
            
            table.add_row(str(idx), status_text, p, auth_state)
            
        console.print(Rule(style="dim magenta"))
        if not profiles:
            console.print(Align.center("[muted]No profiles found. Create a profile to begin.[/muted]"))
        else:
            console.print(table)
        console.print(Rule(style="dim magenta"))

# ==========================================
# 5. ROUTER & EVENT LOOP
# ==========================================
def build_profile_choices(profiles: ProfileList, active_profile: str | None = None, lock_active: bool = False) -> list[questionary.Choice]:
    choices = []
    for p in profiles:
        if lock_active and p == active_profile:
            choices.append(questionary.Choice(f"{p} (Active - Locked)", value=p, disabled="Cannot delete active profile"))
        else:
            choices.append(questionary.Choice(p, value=p))
    choices.append(questionary.Choice("↩ Cancel / Go Back", value=None))
    return choices

def interactive_tui(manager: ProfileManager) -> None:
    while True:
        console.clear()
        
        title = Text("🚀 Antigravity Profile Manager", style="bold magenta")
        subtitle = Text("Account Isolation & Credentials Switcher", style="italic cyan")
        console.print(Panel(Align.center(Text.assemble(title, "\n", subtitle)), border_style="magenta"))
        
        manager.render_dashboard()
        
        profiles = manager.get_all()
        main_choices = []
        
        if profiles:
            main_choices.append(questionary.Choice("Switch Profile", value="switch"))
            main_choices.append(questionary.Choice("Cycle to Next Profile", value="cycle"))
        
        main_choices.extend([
            questionary.Choice("Create New Profile", value="create"),
            questionary.Choice("Delete Profile", value="delete", disabled="No profiles created" if not profiles else None),
            questionary.Choice("Backup/Save Credentials", value="stash", disabled="No active profile" if not manager.get_active() else None),
            questionary.Choice("Quit", value="quit")
        ])

        try:
            action = questionary.select(
                "Select Action:",
                choices=main_choices,
                use_indicator=True,
                pointer="❯",
                style=questionary.Style([('pointer', 'fg:ansimagenta bold')])
            ).ask()
        except KeyboardInterrupt:
            console.print("\n[info]Session terminated via interrupt.[/info]")
            break

        if action is None or action == "quit":
            console.print("[info]Session terminated.[/info]")
            break

        console.print("")
        
        try:
            match action:
                case "switch":
                    target = questionary.select(
                        "Select profile to switch to:", 
                        choices=build_profile_choices(profiles),
                        style=questionary.Style([('pointer', 'fg:ansimagenta bold')])
                    ).ask()
                    
                    if target: 
                        manager.switch(target)
                        questionary.press_any_key_to_continue("\nPress any key to return...").ask()
                case "cycle":
                    manager.cycle_next()
                    questionary.press_any_key_to_continue("\nPress any key to return...").ask()
                case "create":
                    name = questionary.text("Enter name for new profile (leave blank to cancel):").ask()
                    
                    if name and name.strip(): 
                        manager.create(name.strip())
                        questionary.press_any_key_to_continue("\nPress any key to return...").ask()
                case "delete":
                    target = questionary.select(
                        "Select profile to delete:", 
                        choices=build_profile_choices(profiles, manager.get_active(), lock_active=True),
                        style=questionary.Style([('pointer', 'fg:ansimagenta bold')])
                    ).ask()
                    
                    if target: 
                        manager.delete(target)
                        questionary.press_any_key_to_continue("\nPress any key to return...").ask()
                case "stash":
                    active_profile = manager.get_active()
                    if active_profile:
                        manager.stash_keyring(active_profile)
                        questionary.press_any_key_to_continue("\nPress any key to return...").ask()
        except KeyboardInterrupt:
            continue

def main() -> None:
    parser = argparse.ArgumentParser(description="Antigravity Profile Manager & Credentials Switcher")
    parser.add_argument("profile", nargs="?", help="Direct profile override")
    parser.add_argument("-l", "--list", action="store_true", help="List all available profiles and exit")
    parser.add_argument("-n", "--next", action="store_true", help="Cycle to the next profile and exit")
    parser.add_argument("-f", "--force", action="store_true", help="Bypass running process check and force switch non-interactively")
    
    args = parser.parse_args()

    manager = ProfileManager(force_mode=args.force)

    if args.list:
        manager.render_dashboard()
    elif args.next:
        if not manager.cycle_next():
            sys.exit(1)
    elif args.profile:
        if not manager.switch(args.profile):
            sys.exit(1)
    else:
        interactive_tui(manager)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[error]Process killed via SIGINT.[/error]")
        sys.exit(130)
