#!/usr/bin/env bash
# Initializes or validates the 'edit_here' user configuration overlay for Hyprland.
#              Ensures all template files exist.
#              Designed for Arch Linux / Hyprland 0.55+ / UWSM environments.
#              All configuration files use Lua syntax (.lua) as of Hyprland 0.55.
#              hyprlang (.conf) is deprecated and will be dropped in a future release.
#
# Usage:       ./005_hypr_custom_config_setup.sh [--force]
#              --force: Backs up existing 'edit_here' dir and regenerates all templates.
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. Strict Mode & Configuration
# ------------------------------------------------------------------------------
set -euo pipefail

# --- ANSI Color Codes ---
readonly RED=$'\033[0;31m'
readonly GREEN=$'\033[0;32m'
readonly YELLOW=$'\033[0;33m'
readonly BLUE=$'\033[0;34m'
readonly RESET=$'\033[0m'

# --- Paths ---
readonly HYPR_DIR="${HOME}/.config/hypr"
readonly EDIT_DIR="${HYPR_DIR}/edit_here"
readonly EDIT_SOURCE_DIR="${EDIT_DIR}/source"
readonly MAIN_CONF="${HYPR_DIR}/hyprland.lua"
readonly NEW_CONF="${EDIT_DIR}/hyprland.lua"

# Lua require() strings that are inserted into / searched for in hyprland.lua.
# These are the EXACT literal strings written to and grepped from the main config.
#
# Dot-separated Lua module paths map to filesystem paths relative to ~/.config/hypr/:
#   "edit_here.source.default_apps"  ->  ~/.config/hypr/edit_here/source/default_apps.lua
#   "edit_here.hyprland"             ->  ~/.config/hypr/edit_here/hyprland.lua
readonly APPS_DEFAULTS_REQUIRE='require("edit_here.source.default_apps")'
readonly OVERLAY_REQUIRE='require("edit_here.hyprland")'

# ==============================================================================
# CONFIG FILE LIST  <<<  EDIT THIS TO ADD / REMOVE FILES  >>>
# ==============================================================================
# Each entry is a .lua filename created inside:
#   ~/.config/hypr/edit_here/source/
#
# The script will automatically:
#   - Create a template file if it does not already exist
#   - Append a require() line for it to ~/.config/hypr/edit_here/hyprland.lua
#     (the loader that is sourced at the bottom of hyprland.lua)
#
# "default_apps.lua" is SPECIAL:
#   It is require()d at the very TOP of hyprland.lua so that its global
#   variables are available to every other file.  If you rename it you must
#   also update the APPS_DEFAULTS_REQUIRE variable above.
#
# FUTURE EXPANSION EXAMPLE — splitting input.lua into sub-files:
#   Remove "input.lua" and add:
#     "keyboard.lua"
#     "touchpad.lua"
#     "cursor.lua"
#   Each new file is automatically picked up on next run.
# ==============================================================================
readonly -a CONFIG_FILES=(
    # --- Core (required at top of hyprland.lua via APPS_DEFAULTS_REQUIRE) ---
    "default_apps.lua"

    # --- Display & Layout ---
    "monitors.lua"
    "appearance.lua"
    "workspace_rules.lua"

    # --- Behavior ---
    "keybinds.lua"
    "input.lua"
    "window_rules.lua"

    # --- Session ---
    "autostart.lua"
    "environment_variables.lua"
    "plugins.lua"

    # --- Future files: add new entries here ---
    # "keyboard.lua"
    # "touchpad.lua"
    # "cursor.lua"
)

# ------------------------------------------------------------------------------
# 2. Helper Functions
# ------------------------------------------------------------------------------
log_info()    { printf '%s[INFO]%s %s\n'    "${BLUE}"   "${RESET}" "${1:-}"; }
log_success() { printf '%s[OK]%s   %s\n'    "${GREEN}"  "${RESET}" "${1:-}"; }
log_warn()    { printf '%s[WARN]%s %s\n'    "${YELLOW}" "${RESET}" "${1:-}"; }
log_error()   { printf '%s[ERR]%s  %s\n'    "${RED}"    "${RESET}" "${1:-}" >&2; }

# ------------------------------------------------------------------------------
# Generates template content for each configuration file.
# All files use Lua syntax — comments are --, not #.
#
# NOTE: We use <<'EOF' (single-quoted) heredocs to prevent shell variable
# expansion, so Lua strings like "edit_here.source.foo" are written literally.
#
# EDIT THIS FUNCTION to update the default template for any file.
# ------------------------------------------------------------------------------
get_file_content() {
    local -r filename="${1:-}"

    case "${filename}" in

        # ======================================================================
        "default_apps.lua")
            cat <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION: default_apps.lua
-- ==============================================================================
-- Override default applications here.
-- These are Lua GLOBALS (defined WITHOUT the 'local' keyword) so that they
-- are accessible in every file require()d after this one in hyprland.lua.
--
-- This file is require()d at the very TOP of hyprland.lua — before all
-- other config files — so these variables are always in scope.
--
-- See: https://wiki.hypr.land/Configuring/Start/
-- ==============================================================================

-- -------------------------------------------------------------------------------------------------
-- User Configurable Defaults
-- -------------------------------------------------------------------------------------------------

terminal    = "kitty"
fileManager = "nemo"
menu        = "rofi -show drun"
browser     = "firefox"
textEditor  = "nvim"
EOF
            ;;

        # ======================================================================
        "monitors.lua")
            cat <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION: monitors.lua
-- ==============================================================================
-- Add your monitor configuration here.
-- These will override or add to the defaults found in ~/.config/hypr/source/
-- This file can also be managed with dusky monitor from the rofi menu or
-- from dusky control center.
--
-- Syntax:
--   hl.monitor({ output = "DP-1", mode = "2560x1440@144", position = "0x0", scale = 1 })
--   hl.monitor({ output = "",     mode = "preferred",     position = "auto", scale = "auto" })
--
-- See: https://wiki.hypr.land/Configuring/Basics/Monitors/
-- ==============================================================================
--[[
#################################################################################################
  MONITOR CONFIGURATION — Hyprland 0.55 (Lua)
  https://wiki.hypr.land/Configuring/Basics/Monitors/

  Quick-reference commands:
    hyprctl monitors all          → list all active + inactive monitors with full details
    hyprctl monitors              → list only active monitors
    hyprctl monitors | grep desc  → grab the description string for desc:-based rules

  FIELD REFERENCE (all fields beyond `output` are optional):
    output        — connector name ("eDP-1", "DP-1", "HDMI-A-1") or desc:"..." or "" (fallback)
    mode          — "WxH@RR" | "preferred" (native) | "highres" | "highrr"
    position      — "XxY" | "auto" | "auto-right/left/up/down"
                    "auto-center-right/left/up/down" (centers-based placement)
    scale         — float (1, 1.5, 2 …) | "auto" (Hyprland picks based on PPI)
    transform     — 0=normal 1=90° 2=180° 3=270° 4=flip 5=flip+90° 6=flip+180° 7=flip+270°
    mirror        — connector name of the source monitor to mirror
    bitdepth      — 8 (default) | 10 (HDR/wide-gamut panels)
    cm            — colour-management preset (see Section 9)
    sdrbrightness — SDR brightness multiplier when cm="hdr" (default 1.0)
    sdrsaturation — SDR saturation multiplier when cm="hdr" (default 1.0)
    sdr_eotf      — "default" | "srgb" | "gamma22"  (SDR transfer function)
    icc           — absolute path to an ICC/ICM profile for this output
    vrr           — per-display VRR mode: 0=off 1=on 2=fullscreen-only
    disabled      — true/false  (soft-disable the output, e.g. Unknown-1)
    reserved_area — { top, bottom, left, right }  extra reserved pixels (stacks on bar area)
#################################################################################################
--]]


-- =================================================================================================
-- SECTION 1 — GLOBAL FALLBACK  (CRITICAL — keep this first, always)
-- =================================================================================================
-- Catches every monitor not matched by a specific rule below.
-- "preferred" = native resolution & refresh. scale "auto" = Hyprland picks based on PPI.
-- Without this, hotplugged displays (projectors, docks, USB-C adapters) may stay black.

hl.monitor({
    output   = "",
    mode     = "preferred",
    position = "auto",
    scale    = "auto",
})


-- =================================================================================================
-- SECTION 2 — LAPTOP BUILT-IN DISPLAY  (eDP-1)
-- =================================================================================================
-- Uncomment and adjust the block that matches your panel.
-- Run `hyprctl monitors all` to confirm your connector name (eDP-1, eDP-2, …).

-- --- 2.1  Standard 1080p laptop (1x scale) --------------------------------------------------
-- hl.monitor({
--     output   = "eDP-1",
--     mode     = "1920x1080@60",
--     position = "0x0",
--     scale    = 1,
-- })

-- --- 2.2  QHD / 2K laptop (1.5x scale) -------------------------------------------------------
-- hl.monitor({
--     output   = "eDP-1",
--     mode     = "2560x1600@165",
--     position = "0x0",
--     scale    = 1.5,
-- })

-- --- 2.3  4K / UHD laptop (2x scale) ---------------------------------------------------------
-- hl.monitor({
--     output   = "eDP-1",
--     mode     = "3840x2400@60",
--     position = "0x0",
--     scale    = 2,
-- })

-- --- 2.4  High-refresh OLED (preferred mode, auto scale) --------------------------------------
-- hl.monitor({
--     output   = "eDP-1",
--     mode     = "preferred",
--     position = "0x0",
--     scale    = "auto",
-- })


-- =================================================================================================
-- SECTION 3 — DESKTOP / SINGLE EXTERNAL MONITOR
-- =================================================================================================
-- Uncomment the block that best describes your display.

-- --- 3.1  Full-HD @ 60 Hz -------------------------------------------------------------------
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "1920x1080@60",
--     position = "0x0",
--     scale    = 1,
-- })

-- --- 3.2  Full-HD @ 144 Hz ------------------------------------------------------------------
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "1920x1080@144",
--     position = "0x0",
--     scale    = 1,
-- })

-- --- 3.3  QHD @ 144/165 Hz ------------------------------------------------------------------
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "2560x1440@165",
--     position = "0x0",
--     scale    = 1,
-- })

-- --- 3.4  4K @ 60 Hz ------------------------------------------------------------------------
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "3840x2160@60",
--     position = "0x0",
--     scale    = 2,
-- })

-- --- 3.5  4K @ 120/144 Hz (DisplayPort 1.4 / HDMI 2.1) ------------------------------------
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "3840x2160@144",
--     position = "0x0",
--     scale    = 2,
-- })

-- --- 3.6  Ultrawide 21:9 @ 144 Hz -----------------------------------------------------------
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "3440x1440@144",
--     position = "0x0",
--     scale    = 1,
-- })

-- --- 3.7  Let Hyprland pick the best available mode (highres / highrr) ----------------------
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "highres",    -- highest resolution available
--     position = "0x0",
--     scale    = "auto",
-- })
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "highrr",    -- highest refresh rate available
--     position = "0x0",
--     scale    = "auto",
-- })


-- =================================================================================================
-- SECTION 4 — MULTI-MONITOR LAYOUTS
-- =================================================================================================
-- Positions are pixel-offsets from the top-left corner of the virtual canvas.
-- Tip: for fractional-scaled monitors, position must account for the *logical* (scaled) size.
--   Example: a 3840x2160 display at scale=2 occupies 1920x1080 in layout space.

-- --- 4.1  Two monitors side-by-side (1080p primary left, 1080p secondary right) --------------
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "1920x1080@144",
--     position = "0x0",
--     scale    = 1,
-- })
-- hl.monitor({
--     output   = "DP-2",
--     mode     = "1920x1080@60",
--     position = "1920x0",
--     scale    = 1,
-- })

-- --- 4.2  Laptop + external (external on the right, auto-positioned) -------------------------
-- hl.monitor({
--     output   = "eDP-1",
--     mode     = "1920x1080@60",
--     position = "0x0",
--     scale    = 1,
-- })
-- hl.monitor({
--     output   = "HDMI-A-1",
--     mode     = "preferred",
--     position = "auto-right",
--     scale    = "auto",
-- })

-- --- 4.3  Three monitors (left | centre | right) ---------------------------------------------
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "2560x1440@144",
--     position = "0x0",
--     scale    = 1,
-- })
-- hl.monitor({
--     output   = "DP-2",
--     mode     = "2560x1440@144",
--     position = "2560x0",
--     scale    = 1,
-- })
-- hl.monitor({
--     output   = "DP-3",
--     mode     = "2560x1440@144",
--     position = "5120x0",
--     scale    = 1,
-- })

-- --- 4.4  Stacked (primary on top, secondary below) -----------------------------------------
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "1920x1080@144",
--     position = "0x0",
--     scale    = 1,
-- })
-- hl.monitor({
--     output   = "HDMI-A-1",
--     mode     = "1920x1080@60",
--     position = "0x1080",
--     scale    = 1,
-- })

-- --- 4.5  Auto-placement (let Hyprland decide direction) -------------------------------------
-- hl.monitor({ output = "DP-1",    mode = "preferred", position = "auto",       scale = 1 })
-- hl.monitor({ output = "DP-2",    mode = "preferred", position = "auto-right",  scale = 1 })
-- hl.monitor({ output = "HDMI-A-1",mode = "preferred", position = "auto-left",   scale = 1 })


-- =================================================================================================
-- SECTION 5 — IDENTIFY MONITORS BY DESCRIPTION  (desc:)
-- =================================================================================================
-- More robust than connector names — survives cable swaps and GPU reseats.
-- Run `hyprctl monitors` and use the description *without* the trailing port name in parentheses.
-- Example output:  "description: Dell Inc. S2721DGF 7JHVG43   (DP-1)"
--                  → use:  "desc:Dell Inc. S2721DGF 7JHVG43"

-- --- 5.1  Single display identified by description ------------------------------------------
-- hl.monitor({
--     output   = "desc:Dell Inc. S2721DGF 7JHVG43",
--     mode     = "2560x1440@165",
--     position = "0x0",
--     scale    = 1,
-- })

-- --- 5.2  Multi-monitor by description -------------------------------------------------------
-- hl.monitor({
--     output   = "desc:LG Electronics LG ULTRAGEAR 311NTWB123456",
--     mode     = "2560x1440@144",
--     position = "0x0",
--     scale    = 1,
-- })
-- hl.monitor({
--     output   = "desc:Samsung Electric Company C27HG7x HTQH123456",
--     mode     = "2560x1440@144",
--     position = "2560x0",
--     scale    = 1,
-- })

-- --- 5.3  Laptop panel by description --------------------------------------------------------
-- hl.monitor({
--     output   = "desc:Chimei Innolux Corporation 0x150C",
--     mode     = "preferred",
--     position = "0x0",
--     scale    = 1.5,
-- })


-- =================================================================================================
-- SECTION 6 — DISPLAY MIRRORING
-- =================================================================================================
-- NOTE: Mirroring re-uses the source framebuffer — it does NOT re-render.
-- A 1080p source mirrored to a 4K display stays at 1080p on the 4K panel.
-- Aspect-ratio mismatches (16:9 → 16:10) will result in stretching.
-- HDR is fundamentally incompatible with mirroring.

-- --- 6.1  Mirror DP-2 onto DP-3 -------------------------------------------------------------
-- hl.monitor({
--     output   = "DP-3",
--     mode     = "1920x1080@60",
--     position = "0x0",
--     scale    = 1,
--     mirror   = "DP-2",
-- })

-- --- 6.2  Fallback: mirror all unspecified monitors onto DP-1 --------------------------------
-- hl.monitor({
--     output   = "",
--     mode     = "preferred",
--     position = "auto",
--     scale    = 1,
--     mirror   = "DP-1",
-- })


-- =================================================================================================
-- SECTION 7 — TRANSFORM / ROTATION
-- =================================================================================================
-- Values:  0 = normal  |  1 = 90°  |  2 = 180°  |  3 = 270°
--          4 = flipped |  5 = flip+90° | 6 = flip+180° | 7 = flip+270°

-- --- 7.1  Portrait monitor (rotated 90°) -----------------------------------------------------
-- hl.monitor({
--     output    = "DP-2",
--     mode      = "1080x1920@60",
--     position  = "1920x0",
--     scale     = 1,
--     transform = 1,       -- 90° clockwise
-- })

-- --- 7.2  Upside-down / ceiling-mounted display ----------------------------------------------
-- hl.monitor({
--     output    = "HDMI-A-1",
--     mode      = "1920x1080@60",
--     position  = "0x0",
--     scale     = 1,
--     transform = 2,       -- 180°
-- })

-- --- 7.3  Portrait (rotated 270° / counter-clockwise 90°) ------------------------------------
-- hl.monitor({
--     output    = "DP-3",
--     mode      = "1080x1920@60",
--     position  = "0x0",
--     scale     = 1,
--     transform = 3,       -- 270°
-- })


-- =================================================================================================
-- SECTION 8 — COLOUR DEPTH (BIT DEPTH)
-- =================================================================================================
-- 10-bit (bitdepth = 10) is needed for HDR, wide-gamut, and banding-free gradients.
-- Requires a panel and cable (DP 1.4 / HDMI 2.0+) that support 10-bit output.
-- Check support: `hyprctl monitors` → look for "10bpc" in the output.

-- --- 8.1  10-bit on an OLED / HDR panel ------------------------------------------------------
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "3840x2160@120",
--     position = "0x0",
--     scale    = 2,
--     bitdepth = 10,
-- })

-- --- 8.2  Explicit 8-bit (default, usually unnecessary to set) -------------------------------
-- hl.monitor({
--     output   = "HDMI-A-1",
--     mode     = "1920x1080@60",
--     position = "0x0",
--     scale    = 1,
--     bitdepth = 8,
-- })


-- =================================================================================================
-- SECTION 9 — COLOUR MANAGEMENT PRESETS  (cm)
-- =================================================================================================
-- Requires bitdepth = 10 for anything beyond sRGB to be meaningful.
-- Preset options:
--   "auto"   → sRGB for 8bpc; "wide" for 10bpc when supported  [RECOMMENDED default]
--   "srgb"   → sRGB primaries (IEC 61966-2-1)                  [software default]
--   "dcip3"  → DCI P3 primaries (cinema)
--   "dp3"    → Apple Display P3 (D65 white point, P3 primaries)
--   "adobe"  → Adobe RGB (1998)
--   "wide"   → BT.2020 / wide-colour-gamut
--   "edid"   → primaries read from the display's EDID (may be inaccurate)
--   "hdr"    → wide-gamut + HDR signalling  (requires bitdepth = 10)

-- --- 9.1  Auto (recommended — Hyprland decides based on bitdepth) ----------------------------
-- hl.monitor({
--     output   = "eDP-1",
--     mode     = "2880x1800@90",
--     position = "0x0",
--     scale    = 2,
--     bitdepth = 10,
--     cm       = "auto",
-- })

-- --- 9.2  Apple Display P3 (macOS-style wide-gamut) -----------------------------------------
-- hl.monitor({
--     output   = "eDP-1",
--     mode     = "2880x1800@90",
--     position = "0x0",
--     scale    = 2,
--     bitdepth = 10,
--     cm       = "dp3",
-- })

-- --- 9.3  DCI P3 (cinema grading displays) ---------------------------------------------------
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "3840x2160@60",
--     position = "0x0",
--     scale    = 2,
--     bitdepth = 10,
--     cm       = "dcip3",
-- })

-- --- 9.4  Adobe RGB (photo editing) ----------------------------------------------------------
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "3840x2160@60",
--     position = "0x0",
--     scale    = 2,
--     bitdepth = 10,
--     cm       = "adobe",
-- })


-- =================================================================================================
-- SECTION 10 — HDR  (High Dynamic Range)
-- =================================================================================================
-- Requirements: cm = "hdr" + bitdepth = 10 + an actual HDR-capable panel + DP 1.4 / HDMI 2.1.
-- sdrbrightness — multiplier for SDR content brightness in HDR mode (default 1.0, range ~0.5–2.0)
-- sdrsaturation — multiplier for SDR content saturation in HDR mode (default 1.0, range ~0.5–1.5)
-- sdr_eotf      — transfer function for SDR content:
--                   "default"  → follows render:cm_sdr_eotf global setting
--                   "srgb"     → piecewise sRGB (IEC 61966-2-1)
--                   "gamma22"  → simple Gamma 2.2
-- NOTE: HDR is fundamentally incompatible with mirroring and ICC profiles.

-- --- 10.1  HDR OLED with tuned SDR tone-mapping ----------------------------------------------
-- hl.monitor({
--     output        = "DP-1",
--     mode          = "3840x2160@120",
--     position      = "0x0",
--     scale         = 2,
--     bitdepth      = 10,
--     cm            = "hdr",
--     sdrbrightness = 1.0,     -- raise to boost SDR content brightness (e.g. 1.2)
--     sdrsaturation = 1.0,     -- raise to boost SDR saturation in HDR mode (e.g. 1.05)
--     sdr_eotf      = "srgb",  -- force sRGB EOTF for SDR content
-- })

-- --- 10.2  HDR with EDID-derived primaries (experimental) ------------------------------------
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "3840x2160@120",
--     position = "0x0",
--     scale    = 2,
--     bitdepth = 10,
--     cm       = "hdr",
--     -- sdr_eotf = "gamma22",
-- })


-- =================================================================================================
-- SECTION 11 — ICC PROFILES
-- =================================================================================================
-- Load a per-output ICC/ICM file for hardware-accurate colour management.
-- Requirements:
--   • Path MUST be absolute (no ~, $HOME, or relative paths).
--   • Applying an ICC profile automatically forces sdr_eotf = "srgb" on that output.
--   • ICC profiles OVERRIDE the cm preset — do not combine both.
--   • ICC is INCOMPATIBLE with HDR — unexpected results will occur.
-- Typical locations: /usr/share/color/icc/ or ~/.local/share/icc/

-- --- 11.1  Calibrated ICC profile for the built-in display -----------------------------------
-- hl.monitor({
--     output = "eDP-1",
--     icc    = "/usr/share/color/icc/colord/MyLaptopPanel.icm",
-- })

-- --- 11.2  Calibrated external display -------------------------------------------------------
-- hl.monitor({
--     output = "DP-1",
--     icc    = "/home/USER/.local/share/icc/dell-s2721dgf-calibrated.icm",
-- })


-- =================================================================================================
-- SECTION 12 — PER-MONITOR VRR  (Variable Refresh Rate)
-- =================================================================================================
-- Overrides the global misc.vrr setting for a specific display.
-- Modes:  0 = disabled  |  1 = always enabled  |  2 = fullscreen-only
-- Requires a FreeSync / G-Sync Compatible panel and a driver that exposes VRR.
-- The global fallback is set in Section 16 (misc).

-- --- 12.1  VRR always on for a gaming monitor ------------------------------------------------
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "2560x1440@165",
--     position = "0x0",
--     scale    = 1,
--     vrr      = 1,
-- })

-- --- 12.2  VRR only in fullscreen (reduces flicker in mixed workloads) -----------------------
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "2560x1440@144",
--     position = "0x0",
--     scale    = 1,
--     vrr      = 2,
-- })

-- --- 12.3  Explicitly disable VRR on a secondary display -------------------------------------
-- hl.monitor({
--     output   = "HDMI-A-1",
--     mode     = "1920x1080@60",
--     position = "1920x0",
--     scale    = 1,
--     vrr      = 0,
-- })


-- =================================================================================================
-- SECTION 13 — DISABLING MONITORS
-- =================================================================================================
-- Use disabled = true to soft-disable an output without physically disconnecting it.
-- Most commonly needed for the ghost "Unknown-1" monitor that appears when Hyprland
-- starts before all displays are enumerated.

-- --- 13.1  Suppress the ghost Unknown-1 monitor ----------------------------------------------
-- hl.monitor({
--     output   = "Unknown-1",
--     disabled = true,
-- })

-- --- 13.2  Disable a specific port (e.g. unused HDMI) ----------------------------------------
-- hl.monitor({
--     output   = "HDMI-A-2",
--     disabled = true,
-- })


-- =================================================================================================
-- SECTION 14 — RESERVED AREA
-- =================================================================================================
-- Reserve additional pixels on an edge of a specific monitor.
-- Useful for custom status bars that do not use layer-shell protocols.
-- Format: { top, bottom, left, right }  (pixels)
-- This STACKS on top of any area already reserved by layer-shell bars (e.g. Waybar).
-- Only ONE reserved_area rule is permitted per monitor in the config.

-- --- 14.1  Reserve 30px at the top for a custom bar ------------------------------------------
-- hl.monitor({
--     output        = "eDP-1",
--     mode          = "1920x1080@60",
--     position      = "0x0",
--     scale         = 1,
--     reserved_area = { 30, 0, 0, 0 },   -- { top, bottom, left, right }
-- })

-- --- 14.2  Reserve pixels on multiple edges --------------------------------------------------
-- hl.monitor({
--     output        = "DP-1",
--     mode          = "2560x1440@144",
--     position      = "0x0",
--     scale         = 1,
--     reserved_area = { 35, 0, 0, 0 },   -- top bar only
-- })


-- =================================================================================================
-- SECTION 15 — WORKSPACE BINDINGS
-- =================================================================================================
-- Pin specific workspaces to a specific monitor so they never migrate.
-- "monitor" field accepts a connector name or a desc: string.
-- "default = true" makes a workspace the one shown when the monitor first activates.

-- --- 15.1  Pin workspaces 1-5 to the laptop screen -------------------------------------------
-- hl.workspace_rule({ workspace = "1", monitor = "eDP-1", default = true })
-- hl.workspace_rule({ workspace = "2", monitor = "eDP-1" })
-- hl.workspace_rule({ workspace = "3", monitor = "eDP-1" })
-- hl.workspace_rule({ workspace = "4", monitor = "eDP-1" })
-- hl.workspace_rule({ workspace = "5", monitor = "eDP-1" })

-- --- 15.2  Pin workspaces 6-10 to an external monitor ----------------------------------------
-- hl.workspace_rule({ workspace = "6",  monitor = "DP-1", default = true })
-- hl.workspace_rule({ workspace = "7",  monitor = "DP-1" })
-- hl.workspace_rule({ workspace = "8",  monitor = "DP-1" })
-- hl.workspace_rule({ workspace = "9",  monitor = "DP-1" })
-- hl.workspace_rule({ workspace = "10", monitor = "DP-1" })

-- --- 15.3  Pin a named workspace (e.g. "coding") to a display by description -----------------
-- hl.workspace_rule({
--     workspace = "name:coding",
--     monitor   = "desc:Dell Inc. S2721DGF 7JHVG43",
--     default   = true,
-- })

-- --- 15.4  Pin the "gaming" workspace to a specific monitor and open steam on creation -------
-- hl.workspace_rule({
--     workspace        = "name:gaming",
--     monitor          = "DP-1",
--     default          = true,
--     on_created_empty = "[float] steam",
-- })


-- =================================================================================================
-- SECTION 16 — MISC  (Power-saving & Global VRR / VFR)
-- =================================================================================================

hl.config({
    misc = {

        -- -----------------------------------------------------------------------------------------
        -- vfr — Variable Frame Rate (idle power-saving)
        -- When true, Hyprland drops the rendering rate while the compositor is idle.
        -- Saves ~1–3 W on the GPU at the cost of a brief delay when activity resumes.
        -- -----------------------------------------------------------------------------------------

        -- -----------------------------------------------------------------------------------------
        -- vrr — Global Variable Refresh Rate  (per-monitor override is in Section 12)
        --   0 = disabled (default)
        --   1 = always enabled (may cause flicker on some panels with mixed refresh content)
        --   2 = fullscreen-only (recommended if you game; avoids flicker in desktop use)
        -- Uses ~1 extra watt but produces noticeably smoother motion when active.
        -- -----------------------------------------------------------------------------------------
        vrr = 0,

    }
})


-- =================================================================================================
-- SECTION 17 — CLAMSHELL / LID-SWITCH
-- =================================================================================================
-- Automatically disable the built-in display when the laptop lid is closed and an
-- external monitor is connected, then re-enable it when the lid is opened.
-- Requires bindl (lid-switch bind) and the hyprctl dispatch to toggle outputs.

-- --- 17.1  Simple clamshell (disable eDP-1 on lid close, re-enable on open) -----------------
-- hl.bind("", "switch:on:Lid Switch", function()
--     hl.dispatch(hl.dsp.dpms({ output = "eDP-1", action = "off" }))
-- end)
-- hl.bind("", "switch:off:Lid Switch", function()
--     hl.dispatch(hl.dsp.dpms({ output = "eDP-1", action = "on" }))
-- end)

-- --- 17.2  Hard-disable eDP-1 on lid close (stronger — removes it from the layout) ----------
-- hl.bind("", "switch:on:Lid Switch", function()
--     hl.monitor({ output = "eDP-1", disabled = true })
-- end)
-- hl.bind("", "switch:off:Lid Switch", function()
--     hl.monitor({
--         output   = "eDP-1",
--         mode     = "preferred",
--         position = "0x0",
--         scale    = "auto",
--     })
-- end)
EOF
            ;;

        # ======================================================================
        "keybinds.lua")
            cat <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION: keybinds.lua
-- ==============================================================================
-- Add your custom keybinds here.
-- These will override or add to the defaults found in ~/.config/hypr/source/
-- This file can also be managed with dusky keybinds manager from the rofi
-- menu or from dusky control center.
--
-- Syntax:
--   local mainMod = "SUPER"
--   hl.bind(mainMod .. " + Q", hl.dsp.exec_cmd(terminal))
--   hl.bind(mainMod .. " + Q", hl.dsp.exec_cmd("kitty"), { description = "Launch terminal" })
--
-- NOTE: 'terminal', 'browser', etc. are globals defined in default_apps.lua.
--
-- See: https://wiki.hypr.land/Configuring/Basics/Binds/
-- ==============================================================================

-- local mainMod = "SUPER"

hl.bind(
    "SUPER + Q",
    hl.dsp.exec_cmd(terminal),
    { description = "Launch Terminal" }
)

hl.bind(
    "SUPER + W",
    hl.dsp.exec_cmd(browser),
    { description = "Launch Browser" }
)

hl.bind(
    "SUPER + E",
    hl.dsp.exec_cmd(terminal .. " -e " .. fileManager),
    { description = "File Manager" }
)

hl.bind(
    "SUPER + R",
    hl.dsp.exec_cmd(terminal .. " --class nvim -e " .. textEditor),
    { description = "Open Text Editor" }
)
EOF
            ;;

        # ======================================================================
        "appearance.lua")
            cat <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION: appearance.lua
-- ==============================================================================
-- Add your custom appearance settings here.
-- These will override or add to the defaults found in ~/.config/hypr/source/
-- This file can also be managed with dusky appearance from the rofi menu or
-- from dusky control center.
--
-- -------------------------------------------------------------------------------------------------
-- 1. THEME SOURCE & ANIMATIONS
-- -------------------------------------------------------------------------------------------------

-- Sourcing colors generated by Matugen (Ensure this outputs valid Lua syntax)
dofile(HOME .. "/.config/matugen/generated/hyprland-colors.lua")


-- -------------------------------------------------------------------------------------------------
-- 2. APPEARANCE, DECORATION & RENDERING
-- -------------------------------------------------------------------------------------------------

hl.config({
    -- ==========================================
    -- GENERAL (Borders, Gaps, Colors)
    -- ==========================================
    general = {
        border_size = 2, -- Size of the border around windows
        gaps_in = 6, -- Gaps between windows
        gaps_out = 12, -- Gaps between windows and monitor edges
        float_gaps = 0, -- Gaps for floating windows (-1 means default)
        gaps_workspaces = 0, -- Gaps between workspaces (stacks with gaps_out)

        ["col.inactive_border"] = inverse_on_surface, -- Border color for inactive windows
        ["col.active_border"] = primary, -- Border color for the active window
        ["col.nogroup_border"] = "0xffffaaff", -- Inactive border color for window that cannot be added to a group
        ["col.nogroup_border_active"] = "0xffff00ff", -- Active border color for window that cannot be added to a group

        layout = "dwindle", -- Which layout to use [dwindle/master/scrolling/monocle]
        resize_on_border = false, -- Enables resizing windows by clicking and dragging on borders and gaps
        extend_border_grab_area = 15, -- Extends click/drag area around the border (needs resize_on_border)
        hover_icon_on_border = true, -- Shows cursor icon when hovering over borders (needs resize_on_border)
        allow_tearing = true, -- Master switch for allowing tearing to occur
        resize_corner = 0 -- Forces floating windows to use specific corner when resized (1-4, 0 to disable)
    },

    -- ==========================================
    -- DECORATION (Rounding, Blur, Shadows)
    -- ==========================================
    decoration = {
        rounding = 6, -- Rounded corners' radius (in layout px)
        rounding_power = 6.0, -- Curve used for rounding (2.0 is circle, 4.0 squircle, 1.0 triangular)
        active_opacity = 1.0, -- Opacity of active windows [0.0 - 1.0]
        inactive_opacity = 1.0, -- Opacity of inactive windows [0.0 - 1.0]
        fullscreen_opacity = 1.0, -- Opacity of fullscreen windows [0.0 - 1.0]
        dim_modal = true, -- Enables dimming of parents of modal windows
        dim_inactive = true, -- Enables dimming of inactive windows
        dim_strength = 0.2, -- How much inactive windows should be dimmed [0.0 - 1.0]
        dim_special = 0.8, -- How much to dim screen when special workspace is open [0.0 - 1.0]
        dim_around = 0.4, -- How much the dim_around window rule should dim by [0.0 - 1.0]
        screen_shader = "", -- Path to custom shader applied at the end of rendering
        border_part_of_window = true, -- Whether the window border should be a part of the window

        blur = {
            enabled = false, -- Enable kawase window background blur
            size = 4, -- Blur size (distance)
            passes = 2, -- Amount of passes to perform
            ignore_opacity = true, -- Make the blur layer ignore the opacity of the window
            new_optimizations = true, -- Enable further optimizations (massively improves performance)
            xray = false, -- Floating windows ignore tiled windows in blur (reduces overhead)
            noise = 0.0117, -- How much noise to apply [0.0 - 1.0]
            contrast = 0.8916, -- Contrast modulation for blur [0.0 - 2.0]
            brightness = 0.8172, -- Brightness modulation for blur [0.0 - 2.0]
            vibrancy = 0.1696, -- Increase saturation of blurred colors [0.0 - 1.0]
            vibrancy_darkness = 0.0, -- How strong vibrancy effect is on dark areas [0.0 - 1.0]
            special = false, -- Whether to blur behind special workspace (expensive)
            popups = false, -- Whether to blur popups (e.g. right-click menus)
            popups_ignorealpha = 0.2, -- If pixel opacity is below this, will not blur popups [0.0 - 1.0]
            input_methods = false, -- Whether to blur input methods (e.g. fcitx5)
            input_methods_ignorealpha = 0.2 -- If pixel opacity is below this, will not blur input methods [0.0 - 1.0]
        },

        shadow = {
            enabled = false, -- Enable drop shadows on windows
            range = 35, -- Shadow range ("size") in layout px
            render_power = 2, -- Falloff power (more power = faster falloff) [1 - 4]
            sharp = false, -- Make shadows sharp, akin to infinite render power
            color = "rgba(1a1a1aee)", -- Shadow's color. Alpha dictates opacity
            offset = {0, 0}, -- Shadow's rendering offset
            scale = 1.0 -- Shadow's scale [0.0 - 1.0]
        },

        glow = {
            enabled = false, -- Enable inner glow on windows
            range = 10, -- Glow range ("size") in layout px
            render_power = 3, -- Falloff power [1 - 4]
            color = "0xee1a1a1a" -- Glow's color. Alpha dictates opacity
        }
    },

    -- ==========================================
    -- ANIMATIONS
    -- ==========================================
    animations = {
        workspace_wraparound = false -- Directional workspace animations animate as if first/last are adjacent
    },

    -- ==========================================
    -- GROUP UI (Colors & Groupbars)
    -- ==========================================
    group = {
        ["col.border_active"] = "0x66ffff00", -- Active group border color
        ["col.border_inactive"] = "0x66777700", -- Inactive group border color
        ["col.border_locked_active"] = "0x66ff5500", -- Active locked group border color
        ["col.border_locked_inactive"] = "0x66775500", -- Inactive locked group border color

        groupbar = {
            enabled = true, -- Enables groupbars
            font_family = "", -- Font for groupbar titles (falls back to misc.font_family)
            font_size = 8, -- Font size of title
            font_weight_active = "normal", -- Font weight of active title
            font_weight_inactive = "normal", -- Font weight of inactive title
            gradients = false, -- Enables gradients
            height = 14, -- Height of groupbar
            indicator_gap = 0, -- Gap between indicator and title
            indicator_height = 3, -- Height of indicator
            stacked = false, -- Render as vertical stack
            priority = 3, -- Decoration priority
            render_titles = true, -- Render titles in decoration
            text_offset = 0, -- Vertical position adjust for titles
            text_padding = 0, -- Horizontal padding for titles
            rounding = 1, -- Round indicator
            rounding_power = 2.0, -- Curve used for rounding indicator
            gradient_rounding = 2, -- Round gradients
            gradient_rounding_power = 2.0, -- Curve used for rounding gradients
            round_only_edges = true, -- Round only indicator edges
            gradient_round_only_edges = true, -- Round only gradient edges
            text_color = "0xffffffff", -- Title color
            ["col.active"] = "0x66ffff00", -- Active background color
            ["col.inactive"] = "0x66777700", -- Inactive background color
            ["col.locked_active"] = "0x66ff5500", -- Active locked background color
            ["col.locked_inactive"] = "0x66775500", -- Inactive locked background color
            gaps_in = 2, -- Gap between gradients
            gaps_out = 2, -- Gap between gradients and window
            keep_upper_gap = true, -- Add/remove upper gap
            blur = false -- Apply blur to indicators and gradients
        }
    },

    -- ==========================================
    -- MISC VISUALS & UI
    -- ==========================================
    misc = {
        disable_hyprland_logo = true, -- Disables random anime girl background
        disable_splash_rendering = true, -- Disables splash rendering
        font_family = "Sans", -- Default font for debug/error text
        splash_font_family = "", -- Font for splash text
        force_default_wallpaper = 1, -- Enforce default wallpapers (-1 random, 0/1 disables anime)
        animate_manual_resizes = false, -- Animate manual window resizes/moves
        animate_mouse_windowdragging = false, -- Animate windows being dragged by mouse
        background_color = "0x111111", -- Custom background color
        render_unfocused_fps = 15, -- Max FPS limit for unfocused background windows
        enable_anr_dialog = true -- Enable "App Not Responding" dialog
    },

    -- ==========================================
    -- LAYOUT TWEAKS (For Appearance)
    -- ==========================================
    layout = {
        single_window_aspect_ratio = {0, 0}, -- Add padding to force single window to aspect ratio
        single_window_aspect_ratio_tolerance = 0.1 -- Tolerance for padding application [0.0 - 1.0]
    },

    dwindle = {
        preserve_split = true
    },

    master = {
        new_status = "master"
    },

    -- ==========================================
    -- RENDER PIPELINE & XWAYLAND SCALING
    -- ==========================================
    xwayland = {
        use_nearest_neighbor = true, -- Nearest neighbor filtering (pixelated vs blurry)
        force_zero_scaling = false -- Force scale of 1 on xwayland windows on scaled displays
    },

    opengl = {
        nvidia_anti_flicker = true -- Reduces flickering on nvidia (ignored on others)
    },

    render = {
        direct_scanout = 0, -- Attempt to reduce lag for single fullscreen app [0=off, 1=on, 2=auto]
        expand_undersized_textures = true, -- Expand undersized textures vs stretching entire texture
        xp_mode = false, -- Disables back buffer and bottom layer rendering
        ctm_animation = 2, -- Fade animation for CTM changes (2=auto disables on Nvidia)
        cm_enabled = true, -- Color management pipeline enabled
        cm_auto_hdr = 1, -- Auto-switch to HDR in fullscreen [0=off, 1=cm/hdr, 2=cm/hdr/edid]
        use_shader_blur_blend = false -- Blurred bg blending
    },

    -- ==========================================
    -- DEBUG VISUALS
    -- ==========================================
    debug = {
        overlay = false, -- Print debug performance overlay
        damage_blink = false, -- Flash areas updated with damage tracking
        colored_stdout_logs = true -- Colors in stdout logs
    }
})


-- Sourcing active animations
require("source.animations.active.active")
EOF
            ;;

        # ======================================================================
        "autostart.lua")
            cat <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION: autostart.lua
-- ==============================================================================
-- Add your custom autostart entries here.
-- These will override or add to the defaults found in ~/.config/hypr/source/
--
-- Syntax:
--   hl.on("hyprland.start", function()
--       hl.exec_cmd("waybar")
--       hl.exec_cmd("nm-applet")
--   end)
--
-- See: https://wiki.hypr.land/Configuring/Basics/Autostart/
-- ==============================================================================

-- --- XWAYLAND CONFIGURATION ---
-- to disable xwayland to save 20-30 mbs of ram, disabling will prevent xwayland apps from working
-- Uncomment the block below to apply:
-- hl.config({
--     xwayland = {
--         enabled = false
--     }
-- })

-- -------------------------------------------------------------------------------------------------
-- AUTOSTART COMMANDS
-- -------------------------------------------------------------------------------------------------
hl.on("hyprland.start", function()

    -- --- SYSTEM ESSENTIALS ---

    -- Gnome Keyring: Stores passwords for apps (VSCode, Chrome, etc.). (recommanded to enable systemd service instead of auto starting with exec-once)
    -- hl.exec_cmd("uwsm-app -- /usr/bin/gnome-keyring-daemon --start --components=secrets")
    -- OR
    -- replace the exec-once line with:
    -- hl.exec_cmd("uwsm-app -- systemctl --user start gnome-keyring-daemon.service")

    -- XHost: Grants root access to the display (needed for GParted/Synaptic to run).
    -- make sure to install xorg-xhost beofre uncommenting the following line, sudo pacman -S xorg-xhost
    -- hl.exec_cmd("uwsm-app -- xhost +si:localuser:root")

    -- --- BACKGROUND SERVICES ---
    hl.exec_cmd("uwsm-app -- awww-daemon")           -- Wallpaper engine

    -- hypridle has systemd service
    -- hl.exec_cmd("uwsm-app -- hypridle")              -- Idle manager
    -- hl.exec_cmd("uwsm-app -- $HOME/user_scripts/hypr/layout_notify.sh") -- Keyboard Layout Notify

    -- --- CLIPBOARD MANAGER ---
    hl.exec_cmd("uwsm-app -- wl-paste --type text --watch cliphist store")
    hl.exec_cmd("uwsm-app -- wl-paste --type image --watch cliphist store")
    hl.exec_cmd("uwsm-app -- wl-clip-persist --clipboard regular")

    -- --- OPTIONAL / USER INTERFACE ---
    hl.exec_cmd("uwsm-app -- $HOME/user_scripts/waybar/waybar_autostart.sh")
    -- hl.exec_cmd("uwsm-app -- $HOME/user_scripts/waybar/toggle_timer_waybar.sh")
    -- hl.exec_cmd("uwsm-app -- nm-applet")

    -- --- Slow app launch fix -- set systemd vars
    -- The subshell evaluating $(env | cut -d'=' -f 1) is passed directly as a string 
    -- to be evaluated by the shell instance spawned by hl.exec_cmd
    hl.exec_cmd("systemctl --user import-environment $(env | cut -d'=' -f 1)")
    hl.exec_cmd("dbus-update-activation-environment --systemd --all")

    -- --- dusky glance ---
    -- EG: dusky glance (uncomment only one at a time)
    -- hl.exec_cmd("~/user_scripts/rofi/dusky_glance.sh --cpu")
    -- hl.exec_cmd("~/user_scripts/rofi/dusky_glance.sh --ram")
    -- hl.exec_cmd("~/user_scripts/rofi/dusky_glance.sh --temp")
    -- hl.exec_cmd("~/user_scripts/rofi/dusky_glance.sh --battery")
    -- hl.exec_cmd("~/user_scripts/rofi/dusky_glance.sh --network")
    -- hl.exec_cmd("~/user_scripts/rofi/dusky_glance.sh --uptime")
    -- hl.exec_cmd("~/user_scripts/rofi/dusky_glance.sh --workspace")
    -- hl.exec_cmd("~/user_scripts/rofi/dusky_glance.sh --clock")

end)

EOF
            ;;

        # ======================================================================
        "plugins.lua")
            cat <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION: plugins.lua
-- ==============================================================================
-- Add your plugin configuration here.
-- These will override or add to the defaults found in ~/.config/hypr/source/
--
-- See: https://wiki.hypr.land/Plugins/Using-Plugins/
-- ==============================================================================

EOF
            ;;

        # ======================================================================
        "window_rules.lua")
            cat <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION: window_rules.lua
-- ==============================================================================
-- Add your custom window rules here.
-- These will override or add to the defaults found in ~/.config/hypr/source/
--
-- Syntax:
--   hl.window_rule({
--       name  = "my-rule-name",            -- unique identifier (required)
--       match = { class = "^kitty$" },     -- match table
--       float = true,
--   })
--
--   hl.layer_rule({
--       name  = "my-layer-rule",
--       match = { namespace = "^waybar$" },
--       blur  = true,
--   })
--
-- See: https://wiki.hypr.land/Configuring/Basics/Window-Rules/
-- ==============================================================================

EOF
            ;;

        # ======================================================================
        "workspace_rules.lua")
            cat <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION: workspace_rules.lua
-- ==============================================================================
-- Add your custom workspace rules here.
-- These will override or add to the defaults found in:
--   ~/.config/hypr/source/workspace_rules.lua
--
-- This file can also be managed with dusky workspace manager TUI,
-- which can be found in dusky control center.
--
-- Syntax:
--   hl.workspace_rule({ workspace = "1",       layout = "dwindle" })
--   hl.workspace_rule({ workspace = "r[11-99]", layout = "dwindle" })
--
-- NOTE: layoutopt keys (orientation, direction) are passed inside layout_opts:
--   hl.workspace_rule({
--       workspace   = "2",
--       layout      = "master",
--       layout_opts = { orientation = "top" },
--   })
--
-- See: https://wiki.hypr.land/Configuring/Basics/Workspace-Rules/
-- ==============================================================================

-- NOTE: Standard workspace rules (1-10) and the global fallback (11-99) are 
-- strictly managed by the Dusky TUI Variable-Proxy Engine.
--
-- HYPRLAND 0.55+ ARCHITECTURE: 
-- ------------------------------------------------------------------------------

-- ==============================================================================
-- 1. TUI DATA INJECTION POINT
-- The TUI should generate and insert its rule tables here.
-- ==============================================================================
local tui_workspace_data = {
    -- Examples of what the TUI might generate based on user selection:
    
    -- [Monitor Binding & Persistence]
    -- { workspace = "1", monitor = "DP-1", default = true, persistent = true },
    -- { workspace = "2", monitor = "DP-1", persistent = true },
    -- { workspace = "3", monitor = "eDP-1", persistent = true },

    -- [Temporary / Project-Specific Workspaces]
    -- { workspace = "name:coding", monitor = "DP-1", gaps_in = 0, gaps_out = 0, no_border = true, no_rounding = true, decorate = false },
    
    -- [Special Workspaces / Scratchpads]
    -- { workspace = "special:scratchpad", on_created_empty = "kitty" },
    -- { workspace = "special:browser", on_created_empty = "firefox", layout = "scrolling" },

    -- [Aesthetic Overrides]
    -- { workspace = "8", border_size = 8, animation = "slidevert", default_name = "visuals" }
}

-- Engine Loop: Applies all generated TUI rules to Hyprland
for _, rule in ipairs(tui_workspace_data) do
    hl.workspace_rule(rule)
end


-- ==============================================================================
-- 2. DYNAMIC WORKSPACE GENERATOR (1-10)
-- Instead of hardcoding 10 lines, the TUI can toggle a loop.
-- Example: Make workspaces 1 through 10 persistent globally.
-- ==============================================================================
local enforce_persistent_1_to_10 = false

if enforce_persistent_1_to_10 then
    for i = 1, 10 do
        hl.workspace_rule({
            workspace = tostring(i),
            persistent = true
        })
    end
end


-- ==============================================================================
-- 3. SMART GAPS MODULE (No Gaps When Only)
-- This replicates the popular "smart gaps" feature. It removes gaps and borders 
-- when there is only one tiled window on a screen, or when the window is fullscreen.
-- 
-- Selectors utilized:
-- w[tv1] : Workspace has exactly 1 visible tiled window
-- f[1]   : Fullscreen state of the workspace is maximized
-- s[false] : Ignores special workspaces
-- ==============================================================================
local enable_smart_gaps = false

if enable_smart_gaps then
    -- Workspace Rules: Remove gaps
    hl.workspace_rule({ workspace = "w[tv1]s[false]", gaps_out = 0, gaps_in = 0 })
    hl.workspace_rule({ workspace = "f[1]s[false]", gaps_out = 0, gaps_in = 0 })

    -- Window Rules: Remove borders and rounding for those specific states
    hl.window_rule({ match = { float = false, workspace = "w[tv1]s[false]" }, border_size = 0, rounding = 0 })
    hl.window_rule({ match = { float = false, workspace = "f[1]s[false]" }, border_size = 0, rounding = 0 })
end


-- ==============================================================================
-- 4. RANGE RULES (Global Fallbacks)
-- The TUI can apply broad rules across ranges of workspaces.
-- ==============================================================================
local enforce_global_fallbacks = false

if enforce_global_fallbacks then
    -- Example: Workspaces 11 through 99 use the "scrolling" layout by default
    hl.workspace_rule({
        workspace = "r[11-99]",
        layout = "scrolling"
    })
end
EOF
            ;;

        # ======================================================================
        "environment_variables.lua")
            cat <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION: environment_variables.lua
-- ==============================================================================
-- Add your custom environment variables here.
-- These will override or add to the defaults found in:
--   ~/.config/hypr/source/environment_variables.lua
--
-- NOTE: It is strongly recommended to place environment variables in the
-- UWSM files at ~/.config/uwsm/{env,env-hyprland} instead, as those are
-- sourced before Hyprland starts and apply to the full session.
--
-- Syntax:
--   hl.env("XCURSOR_SIZE",    "24")
--   hl.env("HYPRCURSOR_SIZE", "24")
--
-- See: https://wiki.hypr.land/Configuring/Advanced-and-Cool/Environment-variables/
-- ==============================================================================

EOF
            ;;

        # ======================================================================
        "input.lua")
            cat <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION: input.lua
-- ==============================================================================
-- Add your custom input settings here.
-- These will override or add to the defaults found in ~/.config/hypr/source/
-- This file can also be managed with dusky input from the rofi menu or
-- from dusky control center.

-- See: https://wiki.hypr.land/Configuring/Basics/Variables/
-- See: https://wiki.hypr.land/Configuring/Advanced-and-Cool/Devices/
-- -------------------------------------------------------------------------------------------------
-- 1. INPUT (KEYBOARD, MOUSE, TOUCHPAD, TABLET, VIRTUAL KEYBOARD)
-- -------------------------------------------------------------------------------------------------
hl.config({
    input = {
        -- --- Keyboard ---
        kb_model = "",                   -- Appropriate XKB keymap parameter.
        kb_layout = "us",                -- Appropriate XKB keymap parameter.
        kb_variant = "",                 -- Appropriate XKB keymap parameter.
        kb_options = "",                 -- Appropriate XKB keymap parameter.
        kb_rules = "",                   -- Appropriate XKB keymap parameter.
        kb_file = "",                    -- If you prefer, you can use a path to your custom .xkb file.
        numlock_by_default = false,      -- Engage numlock by default.
        resolve_binds_by_sym = false,    -- Determines how keybinds act when multiple layouts are used.
        repeat_rate = 35,                -- The repeat rate for held-down keys, in repeats per second.
        repeat_delay = 250,              -- Delay before a held-down key is repeated, in milliseconds.

        -- --- Mouse & Pointer ---
        sensitivity = 0.0,               -- Sets the mouse input sensitivity. Value is clamped to the range -1.0 to 1.0.
        accel_profile = "adaptive",      -- Sets the cursor acceleration profile. Can be one of adaptive, flat, or custom.
        force_no_accel = false,          -- Force no cursor acceleration. Bypasses most pointer settings to get a raw signal.
        rotation = 0,                    -- Sets the rotation of a device in degrees clockwise off the logical neutral position.
        left_handed = false,             -- Switches RMB and LMB.

        -- --- Scrolling ---
        scroll_points = "",              -- Sets the scroll acceleration profile, when accel_profile is set to custom.
        scroll_method = "2fg",           -- Sets the scroll method. Can be one of 2fg, edge, on_button_down, no_scroll.
        scroll_button = 0,               -- Sets the scroll button. 0 means default.
        scroll_button_lock = false,      -- Toggles the button lock logically holding it down to convert motion to scroll events.
        scroll_factor = 1.0,             -- Multiplier added to scroll movement for external mice.
        natural_scroll = false,          -- Inverts scrolling direction. Scrolling moves content directly.
        emulate_discrete_scroll = 1,     -- Emulates discrete scrolling from high resolution scrolling events (0: off, 1: non-standard, 2: all).

        -- --- Focus & Interaction Behavior ---
        follow_mouse = 1,                -- Specify if and how cursor movement should affect window focus.
        follow_mouse_shrink = 0,         -- Shrinks the inactive window hitboxes used for focus detection by pixels.
        follow_mouse_threshold = 0.0,    -- Smallest distance in logical pixels the mouse needs to travel to focus a window.
        focus_on_close = 0,              -- Controls window focus behavior when a window is closed (0: next, 1: under cursor, 2: recent).
        mouse_refocus = true,            -- If disabled, mouse focus won't switch unless crossing a window boundary when follow_mouse=1.
        float_switch_override_focus = 1, -- Focus changes to window under cursor when changing tiled-to-floating and vice versa.
        special_fallthrough = false,     -- Having only floating windows in special workspace will not block focusing in regular workspace.
        off_window_axis_events = 1,      -- Handles axis events around a focused window (0: ignores, 1: out-of-bounds, 2: fakes, 3: warps).

        -- --- Touchpad (Subcategory of Input) ---
        touchpad = {
            disable_while_typing = true,     -- Disable the touchpad while typing.
            natural_scroll = true,           -- Inverts scrolling direction. Scrolling moves content directly.
            scroll_factor = 1.0,             -- Multiplier applied to the amount of scroll movement.
            middle_button_emulation = false, -- Sending LMB and RMB simultaneously will be interpreted as a middle click.
            tap_button_map = "",             -- Sets the tap button mapping for touchpad button emulation (lrm or lmr).
            clickfinger_behavior = false,    -- Button presses with 1, 2, or 3 fingers will be mapped to LMB, RMB, and MMB respectively.
            tap_to_click = true,             -- Tapping on the touchpad with 1, 2, or 3 fingers will send LMB, RMB, and MMB respectively.
            drag_lock = 0,                   -- Lifting the finger off while dragging will not drop item (0: disabled, 1: timeout, 2: sticky).
            tap_and_drag = true,             -- Sets the tap and drag mode for the touchpad.
            flip_x = false,                  -- Inverts the horizontal movement of the touchpad.
            flip_y = false,                  -- Inverts the vertical movement of the touchpad.
            drag_3fg = 0                     -- Enables three finger drag (0: disabled, 1: 3 fingers, 2: 4 fingers).
        },

        -- --- Touchdevice (Subcategory of Input) ---
        touchdevice = {
            transform = -1,                  -- Transform the input from touchdevices. -1 means it’s unset.
            output = "[[Auto]]",             -- The monitor to bind touch devices. The default is auto-detection.
            enabled = true                   -- Whether input is enabled for touch devices.
        },

        -- --- Tablet (Subcategory of Input) ---
        tablet = {
            transform = -1,                  -- Transform the input from tablets. -1 means it’s unset.
            output = "",                     -- The monitor to bind tablets. Leave empty to map across all monitors.
            region_position = { 0, 0 },      -- Position of the mapped region in monitor layout relative to top left.
            absolute_region_position = false,-- Whether to treat the region_position as an absolute position in monitor layout.
            region_size = { 0, 0 },          -- Size of the mapped region.
            relative_input = false,          -- Whether the input should be relative.
            left_handed = false,             -- If enabled, the tablet will be rotated 180 degrees.
            active_area_size = { 0, 0 },     -- Size of tablet’s active area in mm.
            active_area_position = { 0, 0 }  -- Position of the active area in mm.
        },

        -- --- Virtual Keyboard (Subcategory of Input) ---
        virtualkeyboard = {
            share_states = 2,                -- Unify key down states and modifier states with other keyboards.
            release_pressed_on_close = false -- Release all pressed keys by virtual keyboard on close.
        }
    },

    -- ---------------------------------------------------------------------------------------------
    -- 2. CURSOR BEHAVIOR & RENDERING
    -- ---------------------------------------------------------------------------------------------
    cursor = {
        invisible = false,                   -- Don’t render cursors.
        sync_gsettings_theme = true,         -- Sync xcursor theme with gsettings.
        no_hardware_cursors = 2,             -- Disables hardware cursors. 0: use hw, 1: don't use hw, 2: auto.
        no_break_fs_vrr = 2,                 -- Disables scheduling new frames on cursor movement for fullscreen apps with VRR enabled.
        min_refresh_rate = 24,               -- Minimum refresh rate for cursor movement when no_break_fs_vrr is active.
        hotspot_padding = 1,                 -- The padding, in logical px, between screen edges and the cursor.
        inactive_timeout = 0.0,              -- In seconds, after how many seconds of cursor’s inactivity to hide it.
        no_warps = false,                    -- If true, will not warp the cursor in many cases (focusing, keybinds, etc).
        persistent_warps = false,            -- Cursor returns to its last position relative to that window, rather than to the centre.
        warp_on_change_workspace = 0,        -- Move the cursor to the last focused window after changing the workspace.
        warp_on_toggle_special = 0,          -- Move the cursor to the last focused window when toggling a special workspace.
        default_monitor = "[[EMPTY]]",       -- The name of a default monitor for the cursor to be set to on startup.
        zoom_factor = 1.0,                   -- The factor to zoom by around the cursor. Minimum 1.0.
        zoom_rigid = false,                  -- Whether the zoom should follow the cursor rigidly or loosely.
        zoom_detached_camera = true,         -- Detach the camera from the mouse when zoomed in, only ever moving to keep mouse in view.
        enable_hyprcursor = true,            -- Whether to enable hyprcursor support.
        hide_on_key_press = false,           -- Hides the cursor when you press any key until the mouse is moved.
        hide_on_touch = true,                -- Hides the cursor when the last input was a touch input until a mouse input is done.
        hide_on_tablet = true,               -- Hides the cursor when the last input was a tablet input until a mouse input is done.
        use_cpu_buffer = 2,                  -- Makes HW cursors use a CPU buffer. Required on Nvidia to have HW cursors.
        warp_back_after_non_mouse_input = false, -- Warp the cursor back to where it was after using a non-mouse input.
        zoom_disable_aa = false              -- Disable antialiasing when zooming, which means things will be pixelated.
    },

    -- ---------------------------------------------------------------------------------------------
    -- 3. GESTURE PHYSICS (Tuning)
    -- ---------------------------------------------------------------------------------------------
    gestures = {
        workspace_swipe_distance = 300,              -- In px, the distance of the touchpad gesture.
        workspace_swipe_touch = false,               -- Enable workspace swiping from the edge of a touchscreen.
        workspace_swipe_invert = true,               -- Invert the direction (touchpad only).
        workspace_swipe_touch_invert = false,        -- Invert the direction (touchscreen only).
        workspace_swipe_min_speed_to_force = 30,     -- Minimum speed in px per timepoint to force the change ignoring cancel_ratio.
        workspace_swipe_cancel_ratio = 0.5,          -- How much the swipe has to proceed in order to commence it.
        workspace_swipe_create_new = true,           -- Whether a swipe right on the last workspace should create a new one.
        workspace_swipe_direction_lock = true,       -- If enabled, switching direction will be locked when you swipe past the threshold.
        workspace_swipe_direction_lock_threshold = 10, -- In px, the distance to swipe before direction lock activates (touchpad only).
        workspace_swipe_forever = false,             -- If enabled, swiping will not clamp at the neighboring workspaces but continue.
        workspace_swipe_use_r = false,               -- If enabled, swiping will use the r prefix instead of the m prefix for finding workspaces.
        close_max_timeout = 1000                     -- The timeout for a window to close when using a 1:1 gesture, in ms.
    },

    -- ---------------------------------------------------------------------------------------------
    -- 4. NEW GESTURE BINDINGS (0.55+ Overhaul)
    -- ---------------------------------------------------------------------------------------------
    gesture = {
        -- --- 3-Finger Gestures (Navigation) ---
        
        -- Replicates native 1:1 smooth swiping between workspaces (Highly Intuitive)
        "3, horizontal, workspace",
        
        -- Swipe up for Overview / Mission Control (hyprexpo)
        "3, up, hyprexpo:expo, toggle",
        
        -- Swipe down to drop into a Special Workspace (Scratchpad/Terminal)
        "3, down, togglespecialworkspace",

        -- --- 4-Finger Gestures (Media & Brightness) ---
        
        -- Horizontal for Brightness
        "4, left, exec, brightnessctl -e4 -n2 set 10%-",
        "4, right, exec, brightnessctl -e4 -n2 set 10%+",

        -- Vertical for Volume
        "4, up, exec, wpctl set-volume -l 1.5 @DEFAULT_AUDIO_SINK@ 10%+",
        "4, down, exec, wpctl set-volume @DEFAULT_AUDIO_SINK@ 10%-"
    }
})
EOF
            ;;

        # ======================================================================
        *)
            # Fallback for any future files added to CONFIG_FILES
            printf '-- ==============================================================================\n'
            printf '-- USER CONFIGURATION: %s\n' "${filename}"
            printf '-- ==============================================================================\n'
            printf '-- Add your custom settings here.\n'
            printf '-- ==============================================================================\n\n'
            ;;
    esac
}

# ------------------------------------------------------------------------------
# 3. Privilege & Pre-flight Checks
# ------------------------------------------------------------------------------
if [[ "${EUID}" -eq 0 ]]; then
    log_error "This script must NOT be run as root."
    log_error "It modifies user configuration files in ${HOME}."
    exit 1
fi

# Ensure base directory structure exists FIRST
if [[ ! -d "${HYPR_DIR}" ]]; then
    log_info "Creating Hyprland config directory: ${HYPR_DIR}"
    mkdir -p -- "${HYPR_DIR}"
fi

if [[ ! -f "${MAIN_CONF}" ]]; then
    log_warn "Main Hyprland config not found at ${MAIN_CONF}."
    log_warn "Creating empty file. You will need to populate it with your base config."
    touch -- "${MAIN_CONF}"
fi

# ------------------------------------------------------------------------------
# 4. Handle Arguments
# ------------------------------------------------------------------------------
force_mode=false

while [[ $# -gt 0 ]]; do
    case "${1}" in
        --force)
            force_mode=true
            shift
            ;;
        *)
            log_error "Unknown argument: ${1}"
            log_error "Usage: ${0##*/} [--force]"
            exit 1
            ;;
    esac
done

if [[ "${force_mode}" == true && -d "${EDIT_DIR}" ]]; then
    # Bash 5.0+ builtin timestamp (no external 'date' command needed)
    printf -v backup_timestamp '%(%Y%m%d_%H%M%S)T' -1
    backup_name="edit_here.bak_${backup_timestamp}"

    log_warn "Force mode: Backing up '${EDIT_DIR}' to '${HYPR_DIR}/${backup_name}'..."
    mv -- "${EDIT_DIR}" "${HYPR_DIR}/${backup_name}"
    log_success "Backup complete. Proceeding with clean regeneration."
fi

# ------------------------------------------------------------------------------
# 5. Main Logic: Create or Verify Overlay
# ------------------------------------------------------------------------------
log_info "Initializing/Verifying Hyprland user configuration overlay..."

# Ensure directory structure exists
if [[ ! -d "${EDIT_SOURCE_DIR}" ]]; then
    log_info "Creating directory: ${EDIT_SOURCE_DIR}"
    mkdir -p -- "${EDIT_SOURCE_DIR}"
else
    log_info "Directory exists: ${EDIT_SOURCE_DIR} (verifying contents...)"
fi

# Iterate and create missing files using the content function
for file in "${CONFIG_FILES[@]}"; do
    target_file="${EDIT_SOURCE_DIR}/${file}"

    if [[ -f "${target_file}" ]]; then
        log_info "  - Exists: ${file}"
    else
        log_warn "  - Missing: ${file} -> Creating with default template..."
        get_file_content "${file}" > "${target_file}"
        log_success "    Created: ${file}"
    fi
done

# Generate the user overlay loader: edit_here/hyprland.lua
# Dynamically built from CONFIG_FILES to prevent list drift.
if [[ -f "${NEW_CONF}" ]]; then
    log_info "Loader file exists: ${NEW_CONF}"
else
    log_warn "Loader file missing: ${NEW_CONF} -> Creating..."

    # Write header
    cat > "${NEW_CONF}" <<'EOF'
-- ==============================================================================
-- USER CONFIGURATION OVERLAY LOADER
-- ==============================================================================
-- This file is require()d at the bottom of hyprland.lua.
-- It loads all your custom configuration files from 'source/'.
-- Edit the specific files in 'source/' to apply your changes.
--
-- NOTE: 'default_apps.lua' is intentionally excluded here — it is require()d
-- directly at the top of hyprland.lua so its globals are available first.
-- ==============================================================================

EOF

    # Dynamically append require() lines (skip default_apps — handled separately)
    for file in "${CONFIG_FILES[@]}"; do
        if [[ "${file}" == "default_apps.lua" ]]; then
            continue
        fi
        # Strip .lua extension to form the Lua module path
        module_name="${file%.lua}"
        printf 'require("edit_here.source.%s")\n' "${module_name}" >> "${NEW_CONF}"
    done

    log_success "Created loader: ${NEW_CONF}"
fi

# ------------------------------------------------------------------------------
# 6. Modify Main Configuration (hyprland.lua)
# ------------------------------------------------------------------------------
log_info "Verifying main configuration at '${MAIN_CONF}'..."

# A. Insert default_apps require() at the TOP of the file (priority — globals first)
#    Uses grep -Fq (fixed-string, quiet) to match the exact require() string.
if grep -Fq "${APPS_DEFAULTS_REQUIRE}" "${MAIN_CONF}"; then
    log_success "Main config already contains default_apps require()."
else
    # Robust prepend via temp file — handles empty files safely
    temp_file=$(mktemp)
    {
        printf '%s\n' "${APPS_DEFAULTS_REQUIRE}"
        cat "${MAIN_CONF}"
    } > "${temp_file}" && mv -- "${temp_file}" "${MAIN_CONF}"

    log_success "Prepended '${APPS_DEFAULTS_REQUIRE}' to the top of '${MAIN_CONF}'."
fi

# B. Insert overlay loader require() at the BOTTOM of the file (last override wins)
if grep -Fq "${OVERLAY_REQUIRE}" "${MAIN_CONF}"; then
    log_success "Main config already contains the overlay loader require()."
else
    printf '\n-- Source User Custom Config Overlay\n%s\n' "${OVERLAY_REQUIRE}" >> "${MAIN_CONF}"
    log_success "Appended '${OVERLAY_REQUIRE}' to '${MAIN_CONF}'."
fi

# ------------------------------------------------------------------------------
# 7. Completion
# ------------------------------------------------------------------------------
printf '\n'
log_success "Setup/Verification complete!"
log_info  "Your custom configs are located in: ${EDIT_DIR}"
log_info  "To apply changes, save any .lua file (auto-reload) or run 'hyprctl reload'."
