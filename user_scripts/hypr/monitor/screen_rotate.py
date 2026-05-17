#!/usr/bin/env python3
"""
screen_rotate.py — Hyprland 0.55+ IPC-only Screen Rotation Utility

Rotates the focused monitor 90° clockwise (+90) or counter-clockwise (-90).

Usage:
    screen_rotate.py +90
    screen_rotate.py -90

Design principles:
  • Zero config-file access — reads/writes nothing on disk.
  • Temporary by design — changes reset on `hyprctl reload` (as intended).
  • Mode-string fidelity — resolves the active mode via availableModes so
    custom refresh rates, VRR modelines, and fractional Hz are preserved.
  • Flip-transform aware — rotates within the current flip state (0-3 / 4-7).
  • stdlib-only — requires only Python 3.8+ and hyprctl.

Hyprland IPC reference:
  hyprctl monitors -j  →  JSON list of active monitors
  hyprctl eval 'hl.monitor({...})'  →  apply monitor rule via Lua (0.55+)

Transform values (WL_OUTPUT_TRANSFORM_*):
    0 = normal        1 = 90°         2 = 180°        3 = 270°
    4 = flipped       5 = flipped+90° 6 = flipped+180° 7 = flipped+270°
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any


# ── ANSI colour helpers ────────────────────────────────────────────────────────

_COLOURS = sys.stderr.isatty() or sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOURS else text

def _red(t: str)    -> str: return _c("31", t)
def _green(t: str)  -> str: return _c("32", t)
def _yellow(t: str) -> str: return _c("33", t)
def _blue(t: str)   -> str: return _c("34", t)
def _bold(t: str)   -> str: return _c("1",  t)


# ── Logging ────────────────────────────────────────────────────────────────────

def log_info(msg: str)    -> None: print(f"{_blue('[INFO]')}    {msg}")
def log_ok(msg: str)      -> None: print(f"{_green('[OK]')}      {msg}")
def log_warn(msg: str)    -> None: print(f"{_yellow('[WARN]')}   {msg}", file=sys.stderr)
def log_payload(msg: str) -> None: print(f"{_yellow('[PAYLOAD]')} {msg}")

def die(msg: str, code: int = 1) -> None:
    print(f"{_red('[ERROR]')}   {msg}", file=sys.stderr)
    sys.exit(code)


# ── Dependency / environment checks ───────────────────────────────────────────

def check_environment() -> None:
    """Abort early for obvious mis-configurations."""
    if os.geteuid() == 0:
        die("Do not run as root — hyprctl requires user-space socket access.")

    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        die(
            "HYPRLAND_INSTANCE_SIGNATURE is not set.\n"
            "         Is Hyprland running, and are you in the correct session?"
        )

    result = subprocess.run(
        ["hyprctl", "--version"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and "not found" in (result.stderr or "").lower():
        die("'hyprctl' not found. Install Hyprland.")


# ── Argument parsing ───────────────────────────────────────────────────────────

def parse_direction() -> int:
    """
    Parse +90 / -90 from argv.
    Returns +1 (clockwise) or -1 (counter-clockwise).
    """
    prog = os.path.basename(sys.argv[0])
    if len(sys.argv) != 2 or sys.argv[1] not in ("+90", "-90"):
        print(
            f"{_yellow('[INFO]')}    Usage: {prog} [+90|-90]",
            file=sys.stderr,
        )
        sys.exit(1)
    return 1 if sys.argv[1] == "+90" else -1


# ── hyprctl IPC wrappers ───────────────────────────────────────────────────────

def hyprctl_json(args: list[str]) -> Any:
    """
    Run `hyprctl -j <args>` and return parsed JSON.

    Hyprland ≤ 0.28 could prepend stray debug lines before the JSON array;
    we strip any non-JSON prefix to be safe.
    """
    try:
        proc = subprocess.run(
            ["hyprctl", "-j"] + args,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        die("'hyprctl' not found.")
    except subprocess.TimeoutExpired:
        die("hyprctl timed out — is Hyprland responsive?")

    if proc.returncode != 0:
        die(f"hyprctl exited {proc.returncode}: {proc.stderr.strip() or '(no stderr)'}")

    raw = proc.stdout.strip()

    # Strip any stray non-JSON prefix lines (defensive; not needed in 0.55)
    if raw and not raw[0] in ("[", "{"):
        for i, line in enumerate(raw.splitlines()):
            line = line.strip()
            if line.startswith(("[", "{")):
                raw = "\n".join(raw.splitlines()[i:])
                break

    if not raw:
        die("hyprctl returned empty output.")

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        die(f"Failed to parse hyprctl JSON: {exc}\n         Raw output: {raw[:300]!r}")


def hyprctl_eval(lua_str: str) -> bool:
    """
    Run `hyprctl eval '<lua_str>'` — the Hyprland 0.55 runtime Lua API.

    In 0.55, `hyprctl keyword monitor NAME,...` uses the deprecated hyprlang
    comma-syntax; transforms are silently ignored.  `hyprctl eval` executes
    Lua directly in the running compositor state and is the correct mechanism.

    We don't rely on stdout for success — `hl.monitor()` returns nil, so eval
    prints nothing useful.  Instead we check the exit code and let the caller
    do IPC polling to confirm the change was applied.
    """
    try:
        proc = subprocess.run(
            ["hyprctl", "eval", lua_str],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        die("hyprctl eval timed out — compositor may be unresponsive.")

    return proc.returncode == 0


# ── Mode resolution ────────────────────────────────────────────────────────────

def _parse_hz(mode_str: str) -> float | None:
    """
    Extract the numeric Hz value from a mode string.
    Accepts: "1920x1080@144.00Hz", "1920x1080@144.00", "1920x1080@144"
    Returns None on parse failure.
    """
    try:
        _, hz_part = mode_str.split("@", 1)
        return float(hz_part.rstrip("HhZz"))
    except (ValueError, IndexError):
        return None


def resolve_active_mode(monitor: dict[str, Any]) -> str:
    """
    Return the best-matching mode string for `hyprctl keyword monitor`
    (WITHOUT the Hz suffix, e.g. "1920x1080@144.00").

    Strategy:
      1. IPC `width` × `height` are post-transform pixels.
         For 90°/270° rotations (odd transform), swap to recover native W×H.
      2. Filter availableModes to those matching native W×H.
      3. Pick the candidate whose Hz is closest to IPC refreshRate.
      4. Fallback: reconstruct from raw IPC float (accurate to ±0.01 Hz).

    This guarantees zero-drift on custom refresh rates, VRR, and fractional Hz.
    """
    transform: int   = int(monitor.get("transform", 0))
    ipc_w: int       = int(monitor["width"])
    ipc_h: int       = int(monitor["height"])
    refresh: float   = float(monitor["refreshRate"])
    available: list  = monitor.get("availableModes", [])

    # Un-rotate: odd transforms (1, 3, 5, 7) swap W↔H
    if transform % 2 == 1:
        native_w, native_h = ipc_h, ipc_w
    else:
        native_w, native_h = ipc_w, ipc_h

    target_prefix = f"{native_w}x{native_h}@"

    # Build candidates: (hz_float, mode_without_hz_suffix)
    candidates: list[tuple[float, str]] = []
    for mode in available:
        if not mode.lower().startswith(target_prefix.lower()):
            continue
        hz = _parse_hz(mode)
        if hz is None:
            continue
        # Strip trailing "Hz" / "hz" to produce the payload-safe string
        clean = mode.rstrip("HhZz")
        candidates.append((hz, clean))

    if not candidates:
        log_warn(
            f"No availableModes entry for {native_w}x{native_h} "
            f"(IPC refreshRate={refresh:.5f}). "
            "Reconstructing mode string from IPC data — "
            "result may differ slightly from the physical modeline."
        )
        return f"{native_w}x{native_h}@{refresh:.2f}"

    # Closest Hz match (handles tiny IPC floating-point drift, e.g. 59.973 vs 60.00)
    best_hz, best_clean = min(candidates, key=lambda c: abs(c[0] - refresh))
    return best_clean


# ── Transform arithmetic ───────────────────────────────────────────────────────

def compute_new_transform(current: int, direction: int) -> int:
    """
    Rotate the monitor within its current flip-state.

    Transforms 0-3 are non-flipped; 4-7 add a horizontal flip.
    We cycle the rotation bits (0-3) independently, preserving the flip bit.

    direction: +1 = clockwise (+90°), -1 = counter-clockwise (-90°)
    """
    flip_bit      = current & 4       # 0 or 4
    rotation_bits = current & 3       # 0..3
    new_rotation  = (rotation_bits + direction + 4) % 4
    return flip_bit | new_rotation


# ── Scale formatting ───────────────────────────────────────────────────────────

def format_scale(scale: float) -> str:
    """
    Format scale for the hyprctl payload.
    Avoids unnecessary trailing zeros: 1.0→"1", 1.5→"1.5", 1.333→"1.333333"
    Hyprland accepts up to 6 significant decimal digits fine.
    """
    # Round to 6 decimal places to avoid float noise, then strip trailing zeros
    rounded = f"{scale:.6f}".rstrip("0").rstrip(".")
    return rounded


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    check_environment()
    direction = parse_direction()

    # ── 1. Query live monitor state ──────────────────────────────────────────
    monitors: list[dict] = hyprctl_json(["monitors"])

    if not isinstance(monitors, list) or not monitors:
        die("hyprctl returned no monitor data.")

    # Select the focused monitor; fall back to the first one
    focused: dict | None = next(
        (m for m in monitors if m.get("focused") is True), None
    )
    if focused is None:
        log_warn("No focused monitor found; using first monitor.")
        focused = monitors[0]

    name: str           = str(focused.get("name", ""))
    current_transform   = int(focused.get("transform", 0))
    x: int              = int(focused.get("x", 0))
    y: int              = int(focused.get("y", 0))
    scale: float        = float(focused.get("scale", 1.0))
    disabled: bool      = bool(focused.get("disabled", False))

    # ── Validation ───────────────────────────────────────────────────────────
    if not name or name == "null":
        die("Could not read monitor name from IPC.")

    if disabled:
        die(f"Monitor '{name}' is currently disabled; cannot rotate.")

    if current_transform not in range(8):
        die(
            f"Unexpected transform value '{current_transform}' from IPC. "
            "Expected 0-7."
        )

    # ── 2. Compute new transform ─────────────────────────────────────────────
    new_transform = compute_new_transform(current_transform, direction)

    # ── 3. Resolve active mode string ────────────────────────────────────────
    active_mode = resolve_active_mode(focused)

    # ── 4. Build the Lua hl.monitor() call ───────────────────────────────────
    #
    # hyprctl eval executes Lua directly in the running compositor (0.55+).
    # hl.monitor() takes a table matching the Lua config format:
    #   { output, mode, position, scale, transform }
    #
    # IMPORTANT: mode must NOT have the "Hz" suffix.
    # Position format is the string "XxY" e.g. "0x0", "1920x0".
    # Scale is a bare number (Lua doesn't need quotes for numbers).
    #
    pos_str   = f"{x}x{y}"
    scale_str = format_scale(scale)

    # Escape monitor name for Lua string literal (handles names with quotes,
    # though connector names like eDP-1, DP-2 are always safe in practice).
    lua_name = name.replace("\\", "\\\\").replace('"', '\\"')

    lua_call = (
        f'hl.monitor({{ output = "{lua_name}", mode = "{active_mode}", '
        f'position = "{pos_str}", scale = {scale_str}, transform = {new_transform} }})'
    )

    # ── 5. Log intent ────────────────────────────────────────────────────────
    print()
    log_info(f"Monitor   : {_bold(name)}")
    log_info(f"Mode      : {active_mode}")
    log_info(f"Position  : {pos_str}   Scale: {scale_str}")
    log_info(f"Transform : {current_transform} → {new_transform}  "
             f"({direction:+d} × 90°)")
    log_payload(lua_call)
    print()

    # ── 6. Apply via hyprctl eval (Lua API) ──────────────────────────────────
    eval_ok = hyprctl_eval(lua_call)
    if not eval_ok:
        die(
            "hyprctl eval returned a non-zero exit code.\n"
            "  Is Hyprland 0.55+ running and the socket accessible?\n"
            f"  Lua: {lua_call}"
        )

    # ── 7. Poll IPC to confirm transform was actually applied ─────────────────
    #
    # Borrowed from adjust_scale.py: Wayland compositor state updates are async.
    # Poll up to 2.5 s (25 × 100 ms) for the transform to change.
    # This also catches the old "eval accepted but silently ignored" edge case.
    #
    actual_transform = current_transform
    for _ in range(25):
        time.sleep(0.1)
        try:
            polled = hyprctl_json(["monitors"])
            for m in polled:
                if m.get("name") == name:
                    actual_transform = int(m.get("transform", current_transform))
                    break
        except SystemExit:
            break  # die() already called inside hyprctl_json
        if actual_transform != current_transform:
            break

    if actual_transform != new_transform:
        die(
            f"Transform did not change after eval "
            f"(expected {new_transform}, IPC reports {actual_transform}).\n"
            "  This may indicate the compositor overrode the value, or that\n"
            "  'hyprctl eval' is not supported on your build.\n"
            f"  Lua sent: {lua_call}"
        )

    log_ok(f"Rotation applied — transform {current_transform} → {new_transform}")

    # ── 8. Optional desktop notification ────────────────────────────────────
    _notify(name, new_transform, active_mode)


def _notify(monitor: str, transform: int, mode: str) -> None:
    """Send a libnotify desktop notification if notify-send is available."""
    _TRANSFORM_NAMES = {
        0: "0° (normal)",   1: "90°",    2: "180°",   3: "270°",
        4: "0° (flipped)",  5: "90°+flip", 6: "180°+flip", 7: "270°+flip",
    }
    label = _TRANSFORM_NAMES.get(transform, str(transform))
    body  = f"Monitor: {monitor}\nRotation: {label}\nMode: {mode}"

    try:
        subprocess.run(
            [
                "notify-send",
                "--app-name=System",
                "Display Rotated",
                body,
                "--hint=string:x-canonical-private-synchronous:display-rotate",
            ],
            capture_output=True,
            timeout=3,
        )
    except FileNotFoundError:
        pass  # notify-send not installed — silently skip
    except subprocess.TimeoutExpired:
        pass  # notification daemon unresponsive — silently skip


if __name__ == "__main__":
    main()
