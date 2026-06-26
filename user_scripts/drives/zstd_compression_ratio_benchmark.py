#!/usr/bin/env python3
# =============================================================================
# Elite ZSTD Compression Ratio & Throughput Benchmark Utility
# Target: Arch Linux Cutting-Edge (Kernel 7.0+, Python 3.14+, systemd 260+)
# Scope: Platinum Grade. High-fidelity ZSTD performance analytics.
# =============================================================================

from __future__ import annotations

import os
import sys
import time
import shutil
import subprocess
from pathlib import Path
from typing import Any

# Verify minimum Python version
if sys.version_info < (3, 14):
    print(f"Warning: This script is optimized for Python 3.14+, running {sys.version.split()[0]}", file=sys.stderr)

try:
    from rich.console import Console
    from rich.table import Table
    from rich.prompt import Prompt, IntPrompt, Confirm
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
except ImportError:
    print("Error: The 'rich' library is required but not installed.", file=sys.stderr)
    print("Please install it using: pacman -S python-rich", file=sys.stderr)
    sys.exit(1)

console = Console()

# --- Time Formatter ---
def format_duration(seconds: float) -> str:
    """Formats a float duration into human-readable duration strings."""
    if seconds < 1.0:
        return f"{seconds * 1000:.0f}ms"
    elif seconds < 60.0:
        return f"{seconds:.2f}s"
    else:
        minutes = int(seconds // 60)
        rem_seconds = seconds % 60
        return f"{minutes}m {rem_seconds:.1f}s"

# --- Realistic Data Generator ---
def generate_realistic_data(size_bytes: int) -> bytes:
    """Generates patterned, realistic data to achieve life-like compression ratios."""
    console.print("[cyan][INFO][/cyan] Generating realistic test data structure...")
    
    # We mix readable text patterns, structured formatting, repeating sequences, and some entropy
    base_text = (
        b"Arch Linux is a independently developed, x86-64 general-purpose GNU/Linux distribution "
        b"that strives to provide the latest stable versions of most software by following a rolling-release model. "
        b"The default installation is a minimal base system, configured by the user to only add what is purposely required. "
        b"Zstd, short for Zstandard, is a fast lossless compression algorithm, targeting real-time compression scenarios "
        b"at zlib-level and better compression ratios. It is backed by a very fast entropy compression engine. "
        b"Memory compression is a critical facet of modern system architectures. By reclaiming cold pages and "
        b"compressing them in RAM, we prevent disk thrashing and extend hardware lifespan. "
        b"Level 1 provides maximum throughput, while Level 3 or higher is suited for deep background compaction. "
    )
    
    # Generate some structure (JSON-like text patterns)
    base_json = (
        b'{"system": {"kernel": "7.0.0-arch1-1", "arch": "x86_64", "zram": {"active": true, "priority": 100, "algorithm": "zstd"}},'
        b'"metrics": {"cpu_usage": 14.5, "mem_total": 8182748, "mem_free": 1024840, "swap_total": 12288000, "swap_used": 331840}}'
    )
    
    # Mix patterns to form a ~256KB block
    pattern_block = (base_text * 120) + (base_json * 100) + os.urandom(32768)
    
    # Tile up to the requested size
    repeats = (size_bytes // len(pattern_block)) + 1
    return (pattern_block * repeats)[:size_bytes]

# --- In-Memory Benchmark Engine ---
def benchmark_in_memory(data: bytes, level: int) -> dict[str, Any]:
    """Runs compression and decompression entirely in memory using zstd stdin/stdout."""
    # Compression
    t_start = time.perf_counter()
    p_comp = subprocess.Popen(
        ["zstd", f"-{level}", "-c"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    stdout_comp, stderr_comp = p_comp.communicate(input=data)
    comp_time = time.perf_counter() - t_start
    
    if p_comp.returncode != 0:
        raise RuntimeError(f"zstd compression failed: {stderr_comp.decode().strip()}")
        
    compressed_data = stdout_comp
    compressed_size = len(compressed_data)
    
    # Decompression
    t_start = time.perf_counter()
    p_decomp = subprocess.Popen(
        ["zstd", "-d", "-c"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    stdout_decomp, stderr_decomp = p_decomp.communicate(input=compressed_data)
    decomp_time = time.perf_counter() - t_start
    
    if p_decomp.returncode != 0:
        raise RuntimeError(f"zstd decompression failed: {stderr_decomp.decode().strip()}")
        
    return {
        "compressed_size": compressed_size,
        "comp_time": comp_time,
        "decomp_time": decomp_time
    }

# --- File-Based Benchmark Engine ---
def benchmark_file_based(data: bytes, level: int, target_dir: Path) -> dict[str, Any]:
    """Runs compression and decompression using files on the target directory."""
    input_file = target_dir / "zstd_bench_input.bin"
    output_file = target_dir / "zstd_bench_output.zst"
    decomp_file = target_dir / "zstd_bench_decomp.bin"
    
    try:
        # Write input data
        input_file.write_bytes(data)
        
        # Compression
        t_start = time.perf_counter()
        p_comp = subprocess.run(
            ["zstd", f"-{level}", "-f", "-o", str(output_file), str(input_file)],
            capture_output=True,
            text=True
        )
        comp_time = time.perf_counter() - t_start
        
        if p_comp.returncode != 0:
            raise RuntimeError(f"zstd compression failed: {p_comp.stderr.strip()}")
            
        compressed_size = output_file.stat().st_size
        
        # Decompression
        t_start = time.perf_counter()
        p_decomp = subprocess.run(
            ["zstd", "-d", "-f", "-o", str(decomp_file), str(output_file)],
            capture_output=True,
            text=True
        )
        decomp_time = time.perf_counter() - t_start
        
        if p_decomp.returncode != 0:
            raise RuntimeError(f"zstd decompression failed: {p_decomp.stderr.strip()}")
            
        return {
            "compressed_size": compressed_size,
            "comp_time": comp_time,
            "decomp_time": decomp_time
        }
    finally:
        # Ensure cleanup of temp files
        for f in (input_file, output_file, decomp_file):
            try:
                if f.exists():
                    f.unlink()
            except Exception:
                pass

# --- CLI Presentation ---
def main() -> None:
    console.print(
        "\n[bold magenta]======================================================================[/bold magenta]\n"
        "[bold cyan] ⚡ ZSTD Multi-Level Compression & Throughput Forensic Analyzer ⚡[/bold cyan]\n"
        "[bold magenta]======================================================================[/bold magenta]"
    )
    
    # 1. Ask Max Compression Level to test (Validate 1-22 without printing massive choices)
    while True:
        max_level = IntPrompt.ask(
            "\nEnter maximum ZSTD compression level to test (Standard: 1-19, Ultra: 20-22) (1-22)",
            default=10
        )
        if 1 <= max_level <= 22:
            break
        console.print("[bold red]Please enter a level between 1 and 22.[/bold red]")
    
    # 2. Ask Data size to test
    size_mb = IntPrompt.ask(
        "Enter test data payload size (in Megabytes)",
        default=100
    )
    if size_mb <= 0:
        console.print("[bold red]FATAL: Size must be a positive integer.[/bold red]")
        sys.exit(1)
        
    size_bytes = size_mb * 1024 * 1024
    
    # 3. Ask storage/benchmark execution mode
    console.print("\n[bold]Choose benchmark storage profile:[/bold]")
    console.print("  [cyan]1)[/cyan] [bold]Pure In-Memory[/bold] (Uses stdin/stdout pipes, zero SSD writes/wear)")
    console.print("  [cyan]2)[/cyan] [bold]File-based RAM-disk/ZRAM[/bold] (Writes to a directory like /tmp or /mnt/zram1)")
    
    mode_choice = Prompt.ask("Select profile", choices=["1", "2"], default="1")
    
    target_dir: Path | None = None
    if mode_choice == "2":
        # Provide suggestions
        suggestions = ["/tmp", "/mnt/zram1"]
        active_suggestions = [s for s in suggestions if Path(s).is_dir() and os.access(s, os.W_OK)]
        
        console.print(f"\nWritable paths detected: [green]{', '.join(active_suggestions)}[/green]")
        target_path_str = Prompt.ask("Enter directory path for tests", default=active_suggestions[0] if active_suggestions else "/tmp")
        target_dir = Path(target_path_str)
        
        if not target_dir.is_dir():
            console.print(f"[bold red]FATAL: Directory {target_dir} does not exist.[/bold red]")
            sys.exit(1)
        if not os.access(target_dir, os.W_OK):
            console.print(f"[bold red]FATAL: Directory {target_dir} is not writable.[/bold red]")
            sys.exit(1)
            
    # Generate test data in RAM
    data = generate_realistic_data(size_bytes)
    
    results = []
    
    console.print(f"\n[bold green]Starting benchmark on {size_mb} MB payload...[/bold green]\n")
    
    # Benchmarking progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Benchmarking ZSTD...[/cyan]", total=max_level)
        
        for level in range(1, max_level + 1):
            progress.update(task, description=f"[cyan]Testing Level {level}...[/cyan]")
            try:
                if mode_choice == "1":
                    res = benchmark_in_memory(data, level)
                else:
                    assert target_dir is not None
                    res = benchmark_file_based(data, level, target_dir)
                    
                ratio = size_bytes / res["compressed_size"]
                comp_speed = size_mb / res["comp_time"]
                decomp_speed = size_mb / res["decomp_time"]
                saved_mb = (size_bytes - res["compressed_size"]) / (1024 * 1024)
                
                results.append({
                    "level": level,
                    "orig_size": size_mb,
                    "compr_size": res["compressed_size"] / (1024 * 1024),
                    "ratio": ratio,
                    "comp_time": res["comp_time"],
                    "decomp_time": res["decomp_time"],
                    "comp_speed": comp_speed,
                    "decomp_speed": decomp_speed,
                    "saved_mb": saved_mb
                })
            except Exception as e:
                console.print(f"[bold red]Error at level {level}: {e}[/bold red]")
            progress.advance(task)
            
    # Draw beautiful Rich grid table
    table = Table(
        title=f"\n📊 ZSTD Compression Level Benchmark Results ({size_mb}MB Payload)",
        title_style="bold magenta",
        header_style="bold cyan",
        border_style="dim blue"
    )
    
    table.add_column("Level", justify="center", style="bold yellow")
    table.add_column("Compressed Size", justify="right")
    table.add_column("Ratio", justify="right", style="bold green")
    table.add_column("Space Saved", justify="right")
    table.add_column("Compression (Time / Speed)", justify="right")
    table.add_column("Decompression (Time / Speed)", justify="right")
    
    for r in results:
        comp_time_formatted = format_duration(r["comp_time"])
        decomp_time_formatted = format_duration(r["decomp_time"])
        table.add_row(
            str(r["level"]),
            f"{r['compr_size']:.2f} MB",
            f"{r['ratio']:.2f}x",
            f"{r['saved_mb']:.2f} MB",
            f"{comp_time_formatted} ({r['comp_speed']:.1f} MB/s)",
            f"{decomp_time_formatted} ({r['decomp_speed']:.1f} MB/s)"
        )
        
    console.print(table)
    
    # 4. Ask to save report (default to False / 'n')
    if Confirm.ask("\nWould you like to save this report to a file?", default=False):
        report_path_str = Prompt.ask(
            "Enter path to save report",
            default=str(Path.home() / "zstd_benchmark_report.md")
        )
        report_path = Path(report_path_str).expanduser()
        
        try:
            # Generate markdown report content
            md_content = f"# ZSTD Compression Benchmark Report\n\n"
            md_content += f"- **Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            md_content += f"- **Payload Size**: {size_mb} MB\n"
            md_content += f"- **Execution Mode**: {'In-Memory' if mode_choice == '1' else f'File-based ({target_dir})'}\n\n"
            
            md_content += "| Level | Compressed Size | Ratio | Space Saved | Compression (Time / Speed) | Decompression (Time / Speed) |\n"
            md_content += "| :---: | :---: | :---: | :---: | :---: | :---: |\n"
            
            for r in results:
                comp_time_formatted = format_duration(r["comp_time"])
                decomp_time_formatted = format_duration(r["decomp_time"])
                md_content += (
                    f"| {r['level']} | {r['compr_size']:.2f} MB | {r['ratio']:.2f}x | "
                    f"{r['saved_mb']:.2f} MB | {comp_time_formatted} ({r['comp_speed']:.1f} MB/s) | "
                    f"{decomp_time_formatted} ({r['decomp_speed']:.1f} MB/s) |\n"
                )
                
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(md_content)
            console.print(f"[bold green]Report successfully saved to {report_path}[/bold green]")
        except Exception as e:
            console.print(f"[bold red]Failed to save report: {e}[/bold red]")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[bold yellow]aborted — operation cancelled by user.[/bold yellow]")
        sys.exit(130)
