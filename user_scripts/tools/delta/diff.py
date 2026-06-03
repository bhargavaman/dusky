#!/usr/bin/env python3
"""
NeoDiff - Advanced Side-by-Side Diffing Engine with Frecency & FZF Tab-Completion.
Built for cutting-edge Arch Linux / Python 3.12+ environments.
"""

import sys
import os
import subprocess
import tempfile
import difflib
import importlib.util
import shutil
import shlex
import argparse
from pathlib import Path

# ==========================================
# 0. Internal FZF API (Tab Completion & File Explorer)
# ==========================================
# These functions intercept execution to act as instantaneous FZF backend workers.
if len(sys.argv) > 1 and sys.argv[1].startswith("--_fzf_"):

    def load_frecency_fast() -> dict[str, int]:
        state_file = Path.home() / ".config" / "dusky" / "settings" / "neodiff" / "state.tsv"
        weights = {}
        if state_file.exists():
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        parts = line.strip().split('\t')
                        if len(parts) == 2 and parts[0].isdigit():
                            weights[parts[1]] = int(parts[0])
            except Exception:
                pass
        return weights

    def get_fzf_action(actions: list[tuple[str, str]]) -> str:
        # Dynamically picks a safe delimiter for FZF actions to prevent shell injection breaks
        combined = "".join(arg for _, arg in actions if arg)
        for delim in "!@#$%^&*|~;:/":
            if delim not in combined:
                break
        else:
            delim = "\x1f" # Extreme fallback (Unit Separator)
        
        parts = []
        for action, arg in actions:
            if arg:
                parts.append(f"{action}{delim}{arg}{delim}")
            else:
                parts.append(action)
        return "+".join(parts)

    python_exec = shlex.quote(sys.executable)
    script_path = shlex.quote(sys.argv[0])

    if sys.argv[1] == "--_fzf_explore":
        query_str = sys.argv[2] if len(sys.argv) > 2 else ""
        if not query_str:
            query_str = "./"

        expanded_str = query_str
        if expanded_str.startswith("~/"):
            expanded_str = str(Path.home()) + expanded_str[1:]
        elif expanded_str == "~":
            expanded_str = str(Path.home())

        p = Path(expanded_str).expanduser()

        # Determine target directory to scan based on standard Unix shell logic
        if p.is_dir() and (query_str.endswith('/') or query_str in (".", "..", "~", "./", "../")):
            scan_dir = p
            prefix = query_str
            if not prefix.endswith('/') and prefix != "":
                prefix += '/'
        else:
            scan_dir = p.parent
            if "/" in query_str:
                prefix = query_str[:query_str.rindex("/") + 1]
            else:
                prefix = ""

        if not scan_dir.exists() or not scan_dir.is_dir():
            sys.exit(0)

        weights = load_frecency_fast()
        items = []
        
        try:
            # Inject ability to cleanly traverse UP a directory natively
            if scan_dir != Path("/"):
                parent_prefix = prefix + "../" if prefix else "../"
                items.append((9999999, parent_prefix, f"  \033[1;34m{parent_prefix}\033[0m"))
                
            for child in scan_dir.iterdir():
                if child.name in (".git", ".svn", "node_modules", "__pycache__"):
                    continue
                    
                abs_path = str(child.resolve())
                w = weights.get(abs_path, 0)
                score = w * 10
                
                display_path = prefix + child.name
                
                if child.is_dir():
                    display_path += "/"
                    display = f"  \033[1;34m{display_path}\033[0m"
                    items.append((score + 10000, display_path, display))
                else:
                    badge = f" \t\033[3;38;2;249;226;175m {w}\033[0m" if w > 0 else ""
                    display = f"  \033[1;36m{display_path}\033[0m{badge}"
                    items.append((score, display_path, display))
        except (PermissionError, FileNotFoundError, NotADirectoryError):
            pass 
            
        items.sort(key=lambda x: (-x[0], x[1]))
        
        # FZF Parsing Structure: Score \t RawPath \t DisplayString
        for score, raw_path, display in items:
            print(f"{score}\t{raw_path}\t{display}")
        sys.exit(0)

    elif sys.argv[1] == "--_fzf_tab":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        selected = sys.argv[3] if len(sys.argv) > 3 else ""
        
        # 1. User highlighted a valid file/dir. Auto-complete to it seamlessly.
        if selected:
            if selected.endswith('/'):
                q_dir = shlex.quote(selected)
                print(get_fzf_action([("change-query", selected), ("reload", f"{python_exec} {script_path} --_fzf_explore {q_dir}")]))
            else:
                print(get_fzf_action([("change-query", selected)]))
        # 2. No active highlight. Let FZF native fuzzy engine load and filter the current working directory.
        else:
            q_dir = shlex.quote(query)
            print(get_fzf_action([("reload", f"{python_exec} {script_path} --_fzf_explore {q_dir}")]))
        sys.exit(0)

    elif sys.argv[1] == "--_fzf_enter":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        selected = sys.argv[3] if len(sys.argv) > 3 else ""
        
        target = selected if selected else query
        if not target:
            print("accept")
            sys.exit(0)
            
        # Elegantly dive into directories without abruptly exiting the FZF loop
        expanded = str(Path(target).expanduser().resolve())
        if Path(expanded).is_dir():
            if not target.endswith('/'):
                target += '/'
            q_dir = shlex.quote(target)
            print(get_fzf_action([("change-query", target), ("reload", f"{python_exec} {script_path} --_fzf_explore {q_dir}")]))
        else:
            print("accept")
        sys.exit(0)

# ==========================================
# 1. Dependency Management (Arch Native)
# ==========================================
def ensure_system_dependencies():
    missing_sys = []
    if not shutil.which("fzf"): missing_sys.append("fzf")
    if not shutil.which("delta"): missing_sys.append("git-delta")
    
    missing_py = []
    if importlib.util.find_spec("rich") is None: missing_py.append("python-rich")
    
    missing = missing_sys + missing_py
    if missing:
        print(f"[\033[93m*\033[0m] Missing Arch dependencies: {', '.join(missing)}")
        print(f"[\033[94m*\033[0m] Elevating to sudo to provision via pacman...")
        try:
            subprocess.run(["sudo", "pacman", "-S", "--noconfirm"] + missing, check=True)
            print(f"[\033[92m✔\033[0m] Dependencies installed successfully. Restarting engine...\n")
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except subprocess.CalledProcessError:
            print(f"[\033[91m!\033[0m] Pacman failed. Please run: sudo pacman -S {' '.join(missing)}")
            sys.exit(1)

ensure_system_dependencies()
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

console = Console()

# ==========================================
# 2. Frecency & State Management
# ==========================================
STATE_DIR = Path.home() / ".config" / "dusky" / "settings" / "neodiff"
STATE_FILE = STATE_DIR / "state.tsv"

def load_frecency() -> dict[str, int]:
    weights = {}
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) == 2 and parts[0].isdigit():
                    weights[parts[1]] = int(parts[0])
    return weights

def update_frecency(filepath: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    weights = load_frecency()
    
    abs_path = str(Path(filepath).resolve())
    weights[abs_path] = weights.get(abs_path, 0) + 1
    
    tmp_file = STATE_FILE.with_suffix(f".tmp.{os.getpid()}")
    with open(tmp_file, 'w', encoding='utf-8') as f:
        for path, weight in weights.items():
            if Path(path).exists() and Path(path).is_file(): 
                f.write(f"{weight}\t{path}\n")
    tmp_file.replace(STATE_FILE)

# ==========================================
# 3. FZF Interface (God Mode UI)
# ==========================================
def fuzzy_find_file(prompt: str, border_label: str = " dusky fzf ") -> str | None:
    python_exec = shlex.quote(sys.executable)
    script_path = shlex.quote(sys.argv[0])
    
    fzf_cmd = [
        "fzf", "--ansi", "--exact", "--layout=reverse", "--tiebreak=index",
        "--print-query", "--expect=ctrl-y,alt-c",
        f"--prompt={prompt}", "--pointer=▶", "--marker=✓",
        "--border=rounded", f"--border-label= {border_label} ", "--border-label-pos=center",
        "--header= 💡 TAB: Auto-Complete │ ENTER: Select/Dive │ ALT-C: Force Exact ",
        "--header-border=line",
        "--info=inline-right", "--tabstop=4",
        "--delimiter=\t", "--with-nth=3..",
        # Vibrant Catppuccin Schema matching the pkg reference exactly
        "--color=bg+:#1e1e2e,bg:#11111b,spinner:#f5e0dc,hl:#f38ba8,hl+:#f38ba8",
        "--color=fg:#cdd6f4,fg+:#cdd6f4,header:#89b4fa,info:#cba6f7",
        "--color=pointer:#a6e3a1,marker:#f5e0dc,prompt:#cba6f7,query:#cdd6f4",
        "--color=border:#585b70,label:#a6e3a1",
        "--height=80%"
    ]

    env = os.environ.copy()
    env["FZF_DEFAULT_COMMAND"] = f"{python_exec} {script_path} --_fzf_explore ."
    
    # Python-driven event routing ensures flawless execution despite FZF quoting quirks
    tab_transform = f"transform({python_exec} {script_path} --_fzf_tab {{q}} {{2}})"
    enter_transform = f"transform({python_exec} {script_path} --_fzf_enter {{q}} {{2}})"
    
    fzf_cmd.extend(["--bind", f"tab:{tab_transform}", "--bind", f"enter:{enter_transform}"])
    
    try:
        result = subprocess.run(fzf_cmd, env=env, text=True, capture_output=True)
    except KeyboardInterrupt:
        return None

    if result.returncode in (130, 2):
        return None

    lines = result.stdout.splitlines()
    if not lines: return None

    # Parsing the output generated by --print-query and accept actions safely
    query_str = lines[0].strip() if len(lines) > 0 else ""
    key_pressed = lines[1] if len(lines) > 1 else ""
    list_selection = lines[2] if len(lines) > 2 else ""

    actual_path = ""
    if list_selection:
        parts = list_selection.split('\t')
        if len(parts) >= 2:
            actual_path = parts[1].strip()

    if key_pressed in ("ctrl-y", "alt-c"):
        final_path = query_str
    else:
        # Trust target highlight unless deliberately forced
        final_path = actual_path if actual_path else query_str

    if not final_path: return None

    p = Path(final_path).expanduser().resolve()
    if p.exists() and p.is_file():
        update_frecency(str(p))
        return str(p)
    else:
        console.print(f"[bold red]Error:[/] File not found or is a directory: {final_path}")
        Prompt.ask("Press Enter to continue", default="")
        return None

# ==========================================
# 4. Neovim Headless Engine & File Readers
# ==========================================
def extract_nvim_previous_state(filepath: str) -> list[str]:
    target_file = Path(filepath).resolve()

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.lua') as lua_script, \
         tempfile.NamedTemporaryFile(mode='r', delete=False) as dump_file:
        
        lua_script_path, dump_file_path = lua_script.name, dump_file.name

        # Target file is securely passed via Neovim args, isolating Lua from shell injection
        lua_code = f"""
        vim.opt.shortmess:append("A") 
        local dump = "{dump_file_path}"
        
        local initial_state = table.concat(vim.api.nvim_buf_get_lines(0, 0, -1, false), "\\n")
        vim.cmd("silent! earlier 1f")
        local previous_state = table.concat(vim.api.nvim_buf_get_lines(0, 0, -1, false), "\\n")
        
        if initial_state == previous_state then
            vim.cmd("silent! undo")
        end
        
        -- Safely write to temp dump using native Lua IO
        local f = io.open(dump, "w")
        local lines = vim.api.nvim_buf_get_lines(0, 0, -1, false)
        for _, line in ipairs(lines) do
            f:write(line .. "\\n")
        end
        f:close()
        
        vim.cmd("qa!")
        """
        lua_script.write(lua_code)
    
    try:
        subprocess.run(
            ["nvim", "--headless", "-c", f"source {lua_script_path}", str(target_file)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
        )
        with open(dump_file_path, 'r', encoding='utf-8') as f:
            return [line.rstrip('\n') for line in f.readlines()]
    except subprocess.CalledProcessError:
        console.print("[bold red]Failed to execute Neovim API.[/]")
        Prompt.ask("Press Enter to continue", default="")
        return []
    finally:
        os.remove(lua_script_path)
        os.remove(dump_file_path)

def read_file_lines(filepath: str) -> list[str]:
    p = Path(filepath)
    if not p.exists() or not p.is_file():
        return []
    
    # Graceful fallback logic for erratic encodings without fatal crashing
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return [line.rstrip('\n') for line in f.readlines()]
    except UnicodeDecodeError:
        try:
            with open(p, 'r', encoding='latin-1') as f:
                return [line.rstrip('\n') for line in f.readlines()]
        except Exception:
            console.print(f"[bold red]Error:[/] File could not be decoded as text: {filepath}")
            return []

# ==========================================
# 5. Delta Side-by-Side Rendering
# ==========================================
def render_with_delta(old_lines: list[str], new_lines: list[str], title_old: str, title_new: str, filename: str) -> None:
    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=title_old,
        tofile=title_new,
        lineterm=""
    ))

    if not diff:
        console.print(Panel("[bold green]No differences found![/] Both states are identical.", border_style="green"))
        Prompt.ask("Press Enter to continue", default="")
        return

    # Formats unified diff precisely to delta's ingestion standards
    diff_text = "\n".join(diff) + "\n"
    ext = Path(filename).suffix.lstrip('.')
    
    delta_cmd = [
        "delta", 
        "--side-by-side", 
        "--line-numbers",
        "--paging=always",
        "--dark",
        "--keep-plus-minus-markers",
        "--tabs=4",
        "--wrap-max-lines=unlimited",
        "--navigate"
    ]
    
    if ext:
        delta_cmd.append(f"--default-language={ext}")
    
    try:
        subprocess.run(delta_cmd, input=diff_text, text=True)
    except KeyboardInterrupt:
        pass

# ==========================================
# 6. Interactive CLI Menu & Execution Loop
# ==========================================
def run_interactive():
    menu_options = [
        "1. 󰋚  Neovim Undo History Diff (Time Travel)",
        "2. 󰑭  Standard Two-File Diff",
        "3. 󰗼  Exit"
    ]
    
    fzf_cmd = [
        "fzf", "--layout=reverse", "--prompt= 󰘚 NeoDiff Mode > ",
        "--border=rounded", "--border-label= 󰘚 NeoDiff Menu ", "--border-label-pos=center",
        "--pointer=▶", "--height=20%",
        # Vibrant Catppuccin Schema
        "--color=bg+:#1e1e2e,bg:#11111b,spinner:#f5e0dc,hl:#f38ba8,hl+:#f38ba8",
        "--color=fg:#cdd6f4,fg+:#cdd6f4,header:#89b4fa,info:#cba6f7",
        "--color=pointer:#a6e3a1,marker:#f5e0dc,prompt:#cba6f7",
        "--color=border:#585b70,label:#a6e3a1"
    ]
    
    while True:
        try:
            result = subprocess.run(fzf_cmd, input="\n".join(menu_options), text=True, capture_output=True)
            choice = result.stdout.strip()
        except KeyboardInterrupt:
            sys.exit(0)

        if result.returncode != 0 or not choice or choice.startswith("3"):
            sys.exit(0)
            
        if choice.startswith("1"):
            target_file = fuzzy_find_file(" 󰋚 Target File > ", " 󰋚 Undo Diff ")
            if not target_file: continue
                
            with console.status(f"[bold yellow]Extracting temporal state of {Path(target_file).name} via Neovim RPC...[/]"):
                old_lines = extract_nvim_previous_state(target_file)
                if not old_lines: continue
                new_lines = read_file_lines(target_file)
                
            render_with_delta(old_lines, new_lines, f"Neovim Undo History ({target_file})", f"Current State ({target_file})", target_file)
            
        elif choice.startswith("2"):
            file1 = fuzzy_find_file(" 󰑭 FIRST file (Old) > ", " 󰑭 Diff: Old Source ")
            if not file1: continue
            file2 = fuzzy_find_file(f" 󰑭 SECOND file (New) > ", f" 󰑭 Diff: New Target for '{Path(file1).name}' ")
            if not file2: continue
                
            old_lines = read_file_lines(file1)
            new_lines = read_file_lines(file2)
            render_with_delta(old_lines, new_lines, file1, file2, file2)

def main():
    parser = argparse.ArgumentParser(description="NeoDiff - Advanced side-by-side diffing engine.")
    parser.add_argument("files", nargs="*", help="Files to compare (0, 1, or 2 files).")
    parser.add_argument("-n", "--nvim", action="store_true", help="Compare a file against its previous Neovim undo state.")
    parser.add_argument("-m", "--multiple", action="store_true", help="Alias flag (handled automatically via positional args).")
    
    args = parser.parse_args()
    files = args.files
    
    if len(files) == 0:
        run_interactive()
        sys.exit(0)
        
    if args.nvim:
        target = str(Path(files[0]).expanduser().resolve())
        with console.status("[bold yellow]Extracting temporal state via Neovim RPC...[/]"):
            old_lines = extract_nvim_previous_state(target)
            new_lines = read_file_lines(target)
        render_with_delta(old_lines, new_lines, f"Neovim Undo History ({target})", f"Current State ({target})", target)
        sys.exit(0)
        
    # Case A: Two files provided exactly as requested (e.g., diff.py ~/path/file1.md file2.md)
    # The Path().resolve() naturally resolves partial filenames directly in the Current Working Directory.
    if len(files) >= 2:
        file1 = str(Path(files[0]).expanduser().resolve())
        file2 = str(Path(files[1]).expanduser().resolve())
        
        if not Path(file1).exists():
            console.print(f"[bold red]Error:[/] File 1 not found: {file1}")
            sys.exit(1)
        if not Path(file2).exists():
            console.print(f"[bold red]Error:[/] File 2 not found: {file2}")
            sys.exit(1)

        old_lines = read_file_lines(file1)
        new_lines = read_file_lines(file2)
        render_with_delta(old_lines, new_lines, file1, file2, file2)

    # Case B: Exactly ONE file provided. Ask user what they want to do!
    elif len(files) == 1:
        file1 = str(Path(files[0]).expanduser().resolve())
        if not Path(file1).exists():
            console.print(f"[bold red]Error:[/] File not found: {file1}")
            sys.exit(1)
            
        console.print(f"[\033[96m*\033[0m] [bold cyan]Primary File Loaded:[/] {file1}")
        
        menu_options = [
            f"1. 󰋚  Compare '{Path(file1).name}' with its Neovim Undo History",
            f"2. 󰑭  Compare '{Path(file1).name}' with a different file"
        ]
        
        fzf_cmd = [
            "fzf", "--layout=reverse", f"--prompt= 󰢱 Action: {Path(file1).name} > ",
            "--border=rounded", "--border-label= NeoDiff Action ", "--border-label-pos=center",
            "--pointer=▶", "--height=20%",
            # Vibrant Catppuccin Schema
            "--color=bg+:#1e1e2e,bg:#11111b,spinner:#f5e0dc,hl:#f38ba8,hl+:#f38ba8",
            "--color=fg:#cdd6f4,fg+:#cdd6f4,header:#89b4fa,info:#cba6f7",
            "--color=pointer:#a6e3a1,marker:#f5e0dc,prompt:#cba6f7",
            "--color=border:#585b70,label:#a6e3a1"
        ]
        
        try:
            result = subprocess.run(fzf_cmd, input="\n".join(menu_options), text=True, capture_output=True)
            choice = result.stdout.strip()
        except KeyboardInterrupt:
            sys.exit(0)

        if result.returncode != 0 or not choice:
            sys.exit(0)
            
        if choice.startswith("1"):
            with console.status(f"[bold yellow]Extracting temporal state via Neovim RPC...[/]"):
                old_lines = extract_nvim_previous_state(file1)
                new_lines = read_file_lines(file1)
            render_with_delta(old_lines, new_lines, f"Neovim Undo History ({file1})", f"Current State ({file1})", file1)
            sys.exit(0)
            
        elif choice.startswith("2"):
            file2 = fuzzy_find_file(f" 󰑭 Select target to compare with {Path(file1).name} > ", f" 󰑭 Diff Target ")
            if not file2:
                sys.exit(0)
            if not Path(file2).exists():
                console.print(f"[bold red]Error:[/] Target File not found: {file2}")
                sys.exit(1)

            old_lines = read_file_lines(file1)
            new_lines = read_file_lines(file2)
            render_with_delta(old_lines, new_lines, file1, file2, file2)
            sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
