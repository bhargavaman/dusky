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
-- HOW THIS FILE IS STRUCTURED
-- ──────────────────────────────────────────────────────────────────────────
--  SECTION 1 │ GLOBAL FALLBACK RULE       (required — keep this enabled)
--  SECTION 2 │ LAPTOP BUILT-IN DISPLAY    (eDP-1 example)
--  SECTION 3 │ EXTERNAL / DESKTOP MONITORS (DP / HDMI examples)
--  SECTION 4 │ MIRROR / CLONE SETUP
--  SECTION 5 │ DISABLING A MONITOR
--  SECTION 6 │ WORKSPACE → MONITOR BINDINGS
--  SECTION 7 │ GLOBAL RENDER & POWER SETTINGS (VRR, VFR, color pipeline)
--
-- QUICK REFERENCE — hl.monitor() FIELDS
-- ──────────────────────────────────────────────────────────────────────────
--  output         STRING   Port name ("eDP-1", "DP-1", "HDMI-A-1") or ""
--                          for the global fallback.  Use `hyprctl monitors all`
--                          to list every connected and disconnected output.
--                          You may also match by description (see SECTION 3).
--
--  mode           STRING   "WIDTHxHEIGHT[@REFRESH]"  e.g. "1920x1080@144"
--                          Special values: "preferred"  (native res/rate)
--                                          "highres"    (highest resolution)
--                                          "highrr"     (highest refresh rate)
--
--  position       STRING   "XxY" pixel offset from the virtual layout origin.
--                          Hyprland uses an INVERSE-Y system:
--                            negative Y = higher on screen
--                            positive Y = lower on screen
--                          Special values: "auto"        (place to the right)
--                                          "auto-left"   "auto-right"
--                                          "auto-up"     "auto-down"
--
--  scale          NUMBER   Fractional scale factor, e.g. 1, 1.5, 2.
--                 STRING   "auto" lets Hyprland pick based on PPI.
--                          Tip: integer scales (1, 2) avoid sub-pixel blur.
--                          Valid scale = resolution / scale must be integer.
--
--  transform      NUMBER   Screen rotation / flip:
--                            0  normal              4  flipped
--                            1  90°                 5  flipped + 90°
--                            2  180°                6  flipped + 180°
--                            3  270°                7  flipped + 270°
--
--  mirror         STRING   Output name to clone this monitor from.
--                          e.g.  mirror = "eDP-1"  makes this display a copy.
--
--  disabled       BOOLEAN  true = tell Hyprland this output does not exist.
--                          Useful for phantom outputs (e.g. "Unknown-1").
--
--  bitdepth       NUMBER   8 (default) or 10 for 10-bit colour output.
--                          NOTE: Hyprland border colours do NOT support 10-bit.
--                          Some screen-capture tools also break with 10-bit.
--
--  cm             STRING   Colour management preset:
--                            "auto"     automatic (default)
--                            "sdronly"  force SDR pipeline
--                            "hdr"      HDR output (requires HDR-capable panel)
--                            "edid"     use display's EDID colour profile
--
--  sdrbrightness  NUMBER   SDR content brightness multiplier when HDR is on.
--                          Range 0.5–2.0.  Default ~1.0.
--
--  sdrsaturation  NUMBER   SDR content saturation multiplier when HDR is on.
--                          Range 0.5–1.5.  Default ~1.0.
--
--  sdr_eotf       STRING   Transfer function assumed for SDR/sRGB content:
--                            "default"  follows render.cm_sdr_eotf (global)
--                            "srgb"     piecewise sRGB
--                            "gamma22"  Gamma 2.2
--
--  icc            STRING   ABSOLUTE path to an .icm / .icc profile.
--                          Forces sdr_eotf = "srgb" automatically.
--                          Overrides the cm preset.
--                          ⚠  Incompatible with HDR gaming; artefacts may occur.
--
--  vrr            NUMBER   Variable Refresh Rate override for this monitor:
--                            0  off
--                            1  always on
--                            2  fullscreen apps only (recommended for desktops)
--                          Overrides the global misc.vrr setting.
--
--  reserved_area  NUMBER   Pixels reserved on all four edges (single value), or
--                 TABLE    a table { top=N, bottom=N, left=N, right=N }.
--                          Stacks on top of bars / layer-shells.
--                          Only ONE reserved_area rule per monitor is allowed.
-- ──────────────────────────────────────────────────────────────────────────


-- #############################################################################
-- SECTION 1 — GLOBAL FALLBACK RULE
-- #############################################################################
-- This catches any monitor that has no explicit rule below.
-- Critical for plug-and-play (projectors, docks, etc.) — do NOT remove this.
-- Change scale to 2 here if you commonly hotplug HiDPI external displays.

hl.monitor({
    output   = "",          -- "" = match any output not covered by a specific rule
    mode     = "preferred", -- use the display's advertised native resolution & rate
    position = "auto",      -- auto-place to the right of other monitors
    scale    = "auto",      -- let Hyprland decide based on PPI
})


-- #############################################################################
-- SECTION 2 — LAPTOP BUILT-IN DISPLAY (eDP-1)
-- #############################################################################
-- Uncomment and adjust the block that matches your use-case.
-- Run `hyprctl monitors all` to verify your internal display is named "eDP-1".

-- ── 2a. Standard laptop panel ─────────────────────────────────────────────
-- hl.monitor({
--     output    = "eDP-1",
--     mode      = "preferred",   -- or e.g. "2560x1600@165"
--     position  = "0x0",
--     scale     = 1,             -- use 2 for HiDPI / Retina panels
--     transform = 0,             -- 0 = normal (no rotation)
-- })

-- ── 2b. Laptop panel — 10-bit HDR (requires HDR-capable display) ───────────
-- hl.monitor({
--     output        = "eDP-1",
--     mode          = "2880x1800@90",
--     position      = "0x0",
--     scale         = 2,
--     bitdepth      = 10,        -- 10-bit colour depth
--     cm            = "hdr",     -- enable HDR colour pipeline
--     sdrbrightness = 1.0,       -- SDR content brightness in HDR mode (0.5–2.0)
--     sdrsaturation = 1.0,       -- SDR content saturation in HDR mode (0.5–1.5)
-- })

-- ── 2c. Laptop panel with ICC colour profile ───────────────────────────────
-- Absolute path required. Automatically forces sdr_eotf = "srgb".
-- hl.monitor({
--     output = "eDP-1",
--     mode   = "preferred",
--     position = "0x0",
--     scale  = 2,
--     icc    = "/home/USERNAME/.config/hypr/icc/your_panel.icm",
-- })

-- ── 2d. Laptop panel — custom SDR transfer function ───────────────────────
-- Use when you want explicit control over how sRGB content is tone-mapped.
-- hl.monitor({
--     output   = "eDP-1",
--     mode     = "preferred",
--     position = "0x0",
--     scale    = 2,
--     sdr_eotf = "srgb",         -- "default" | "srgb" | "gamma22"
-- })


-- #############################################################################
-- SECTION 3 — EXTERNAL / DESKTOP MONITORS
-- #############################################################################
-- You can match monitors by port name OR by description string.
-- Description matching is more robust (survives port changes on docks):
--   desc:MANUFACTURER MODEL SERIAL   e.g. desc:LG Electronics LG HDR 4K 0x00007B3E
-- Get the description string from:  hyprctl monitors all

-- ── 3a. Single external monitor (simple) ──────────────────────────────────
-- hl.monitor({
--     output   = "DP-1",         -- or HDMI-A-1, DP-2, etc.
--     mode     = "1920x1080@144",
--     position = "0x0",
--     scale    = 1,
-- })

-- ── 3b. Dual-monitor horizontal layout (laptop left, external right) ───────
-- Place the laptop screen at the left edge (x = 0).
-- Place the external monitor immediately to the right (x = laptop logical width).
-- If laptop is 2560px wide at scale 2, its logical width = 1280 → use "1280x0".
--
-- hl.monitor({
--     output   = "eDP-1",
--     mode     = "2560x1600@165",
--     position = "0x0",
--     scale    = 2,
-- })
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "1920x1080@144",
--     position = "1280x0",       -- eDP-1 logical width (2560 / 2) = 1280
--     scale    = 1,
-- })

-- ── 3c. Triple-monitor layout (left / centre / right) ─────────────────────
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "1920x1080@144",
--     position = "0x0",
--     scale    = 1,
-- })
-- hl.monitor({
--     output   = "DP-2",
--     mode     = "2560x1440@165",
--     position = "1920x0",
--     scale    = 1,
-- })
-- hl.monitor({
--     output   = "HDMI-A-1",
--     mode     = "1920x1080@60",
--     position = "4480x0",       -- 1920 + 2560
--     scale    = 1,
-- })

-- ── 3d. Vertical stack (primary on top, secondary below) ──────────────────
-- Hyprland's Y axis is inverted: positive Y goes downward on screen.
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "2560x1440@165",
--     position = "0x0",
--     scale    = 1,
-- })
-- hl.monitor({
--     output   = "HDMI-A-1",
--     mode     = "1920x1080@60",
--     position = "0x1440",       -- placed directly below DP-1
--     scale    = 1,
-- })

-- ── 3e. Portrait monitor (rotated 90°) ────────────────────────────────────
-- When rotated, logical dimensions are swapped.
-- A 1080x1920 portrait monitor's logical width = 1080 → next monitor at "1080x0".
-- hl.monitor({
--     output    = "DP-3",
--     mode      = "1920x1080@60",
--     position  = "0x0",
--     scale     = 1,
--     transform = 1,             -- 1 = 90°  |  3 = 270°
-- })

-- ── 3f. 4K external with per-monitor VRR and 10-bit ───────────────────────
-- hl.monitor({
--     output   = "DP-1",
--     mode     = "3840x2160@144",
--     position = "0x0",
--     scale    = 2,
--     bitdepth = 10,
--     vrr      = 2,              -- VRR only for fullscreen apps (0=off 1=on 2=fs-only)
-- })

-- ── 3g. Match by monitor description (dock / hotplug-safe) ────────────────
-- hl.monitor({
--     output   = "desc:Dell Inc. DELL S2722DGM F9GHVJ3",
--     mode     = "2560x1440@165",
--     position = "1920x0",
--     scale    = 1,
-- })


-- #############################################################################
-- SECTION 4 — MIRROR / CLONE SETUP
-- #############################################################################
-- Mirrors duplicate another monitor's output pixel-for-pixel.
-- The `mirror` field takes the output NAME of the source display.

-- ── 4a. Mirror one specific monitor to another ────────────────────────────
-- hl.monitor({
--     output   = "HDMI-A-1",
--     mode     = "1920x1080@60",
--     position = "0x0",
--     scale    = 1,
--     mirror   = "eDP-1",        -- clone eDP-1 onto HDMI-A-1
-- })

-- ── 4b. Mirror all hotplugged monitors to the primary display ─────────────
-- (Combine with the global fallback rule in SECTION 1)
-- hl.monitor({
--     output   = "",
--     mode     = "preferred",
--     position = "auto",
--     scale    = 1,
--     mirror   = "eDP-1",        -- every unspecified output mirrors eDP-1
-- })


-- #############################################################################
-- SECTION 5 — DISABLING A MONITOR
-- #############################################################################
-- Use `disabled = true` to tell Hyprland a port does not exist.
-- This is especially useful for phantom outputs that appear on some GPUs.
-- To blank an active display temporarily, use the DPMS dispatcher instead:
--   hl.dispatch(hl.dsp.dpms({ action = "disable" }))

-- ── 5a. Suppress a phantom / ghost output ─────────────────────────────────
-- hl.monitor({
--     output   = "Unknown-1",
--     disabled = true,
-- })

-- ── 5b. Disable a known port until you need it ────────────────────────────
-- hl.monitor({
--     output   = "HDMI-A-2",
--     disabled = true,
-- })


-- #############################################################################
-- SECTION 6 — WORKSPACE → MONITOR BINDINGS
-- #############################################################################
-- Use hl.workspace_rule() to pin specific workspaces to specific monitors.
-- `monitor` accepts a port name OR a "desc:..." description string.
-- `default = true` makes that workspace the one shown when the monitor connects.

-- ── 6a. Pin individual workspaces to monitors ─────────────────────────────
-- hl.workspace_rule({ workspace = "1",  monitor = "eDP-1",   default = true })
-- hl.workspace_rule({ workspace = "2",  monitor = "eDP-1" })
-- hl.workspace_rule({ workspace = "3",  monitor = "eDP-1" })
-- hl.workspace_rule({ workspace = "4",  monitor = "eDP-1" })
-- hl.workspace_rule({ workspace = "5",  monitor = "eDP-1" })
-- hl.workspace_rule({ workspace = "6",  monitor = "DP-1",    default = true })
-- hl.workspace_rule({ workspace = "7",  monitor = "DP-1" })
-- hl.workspace_rule({ workspace = "8",  monitor = "DP-1" })
-- hl.workspace_rule({ workspace = "9",  monitor = "DP-1" })
-- hl.workspace_rule({ workspace = "10", monitor = "DP-1" })

-- ── 6b. Pin a named workspace to a monitor (by description) ───────────────
-- hl.workspace_rule({
--     workspace = "name:gaming",
--     monitor   = "desc:LG Electronics LG ULTRAGEAR 0x0000B256",
--     default   = true,
-- })

-- ── 6c. Reserved area for a specific monitor ──────────────────────────────
-- Use this when a bar/panel does not automatically reserve space,
-- or when you want extra padding on any edge.
-- hl.monitor({
--     output        = "eDP-1",
--     mode          = "preferred",
--     position      = "0x0",
--     scale         = 2,
--     reserved_area = { top = 0, bottom = 0, left = 0, right = 0 },
-- })
--
-- Or as a single integer for equal padding on all sides:
-- hl.monitor({ output = "eDP-1", reserved_area = 10 })


-- #############################################################################
-- SECTION 7 — GLOBAL RENDER & POWER SETTINGS
-- #############################################################################
-- These hl.config() options affect all monitors globally.
-- Per-monitor VRR overrides can be set with the `vrr` field in hl.monitor().

hl.config({

    misc = {
        -- ── Variable Refresh Rate (global default) ────────────────────────
        -- Overridden per-monitor by the `vrr` field in hl.monitor().
        --   0 = disabled
        --   1 = always enabled  (can cause brightness flicker on some displays)
        --   2 = fullscreen apps only  ← recommended for most users
        vrr = 0,
    },

    debug = {
        -- ── Variable Frame Rate (power saving) ───────────────────────────
        -- When true, Hyprland stops sending frames to the GPU while nothing
        -- is changing on screen.  Saves ~1 W on a laptop; looks identical.
        -- Set to false only if you notice input latency regressions.
        vfr = true,
    },

    render = {
        -- ── Global SDR EOTF (transfer function for SDR/sRGB content) ─────
        -- Applied to every monitor whose per-monitor sdr_eotf is "default".
        --   "auto"    Hyprland decides (recommended)
        --   "srgb"    piecewise sRGB curve  (best colour accuracy on most panels)
        --   "gamma22" traditional Gamma 2.2
        -- cm_sdr_eotf = "auto",

        -- ── Fullscreen HDR passthrough ────────────────────────────────────
        -- When true, fullscreen apps that output HDR signals bypass Hyprland's
        -- colour pipeline entirely for zero-overhead HDR gaming.
        -- Alternative to setting cm = "hdr" per-monitor.
        -- cm_fs_passthrough = false,

        -- ── Automatic HDR ─────────────────────────────────────────────────
        -- Experimental: automatically promote SDR content to HDR where possible.
        -- Requires --target-colorspace-hint-mode=source in mpv ≥ 0.41.
        -- cm_auto_hdr = false,
    },

})
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
-- -------------------------------------------------------------------------------------------------
-- APPEARANCE, DECORATION & RENDERING
-- -------------------------------------------------------------------------------------------------

hl.config({
    -- ==========================================
    -- GENERAL (Borders, Gaps, Colors)
    -- ==========================================
    general = {
        border_size = 1, -- Size of the border around windows
        gaps_in = 4, -- Gaps between windows
        gaps_out = 8, -- Gaps between windows and monitor edges
        float_gaps = 0, -- Gaps for floating windows (-1 means default)
        gaps_workspaces = 0, -- Gaps between workspaces (stacks with gaps_out)

        ["col.inactive_border"] = inverse_on_surface, -- Border color for inactive windows
        ["col.active_border"] = primary, -- Border color for the active window
        ["col.nogroup_border"] = inverse_on_surface, -- Inactive border color for window that cannot be added to a group
        ["col.nogroup_border_active"] = secondary, -- Active border color for window that cannot be added to a group

        resize_on_border = true, -- Enables resizing windows by clicking and dragging on borders and gaps
        extend_border_grab_area = 15, -- Extends click/drag area around the border (needs resize_on_border)
        hover_icon_on_border = true, -- Shows cursor icon when hovering over borders (needs resize_on_border)
        allow_tearing = true, -- Master switch for allowing tearing to occur
        resize_corner = 0 -- Forces floating windows to use specific corner when resized (1-4, 0 to disable)
    },

    -- ==========================================
    -- DECORATION (Rounding, Blur, Shadows)
    -- ==========================================
    decoration = {
        rounding = 10, -- Rounded corners' radius (in layout px)
        rounding_power = 2.5, -- Curve used for rounding (2.0 is circle, 4.0 squircle, 1.0 triangular)
        active_opacity = 0.85, -- Opacity of active windows [0.0 - 1.0]
        inactive_opacity = 0.85, -- Opacity of inactive windows [0.0 - 1.0]
        fullscreen_opacity = 1.0, -- Opacity of fullscreen windows [0.0 - 1.0]
        dim_modal = true, -- Enables dimming of parents of modal windows
        dim_inactive = true, -- Enables dimming of inactive windows
        dim_strength = 0.3, -- How much inactive windows should be dimmed [0.0 - 1.0]
        dim_special = 0.8, -- How much to dim screen when special workspace is open [0.0 - 1.0]
        dim_around = 0.4, -- How much the dim_around window rule should dim by [0.0 - 1.0]
        screen_shader = "", -- Path to custom shader applied at the end of rendering
        border_part_of_window = true, -- Whether the window border should be a part of the window

        blur = {
            enabled = true, -- Enable kawase window background blur
            size = 10, -- Blur size (distance)
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
            enabled = true, -- Enable drop shadows on windows
            range = 10, -- Shadow range ("size") in layout px
            render_power = 1, -- Falloff power (more power = faster falloff) [1 - 4]
            sharp = false, -- Make shadows sharp, akin to infinite render power
            color = "rgba(1a1a1aee)", -- Shadow's color. Alpha dictates opacity
            offset = {0, 0}, -- Shadow's rendering offset
            scale = 1.0 -- Shadow's scale [0.0 - 1.0]
        },

        glow = {
            enabled = false, -- Enable inner glow on windows
            range = 10, -- Glow range ("size") in layout px
            render_power = 3, -- Falloff power [1 - 4]
            color = primary_container -- Glow's color. Alpha dictates opacity
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
        ["col.border_active"] = primary, -- Active group border color
        ["col.border_inactive"] = inverse_on_surface, -- Inactive group border color
        ["col.border_locked_active"] = tertiary, -- Active locked group border color
        ["col.border_locked_inactive"] = tertiary_container, -- Inactive locked group border color

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
            text_color = on_surface, -- Title color
            ["col.active"] = primary, -- Active background color
            ["col.inactive"] = inverse_on_surface, -- Inactive background color
            ["col.locked_active"] = tertiary, -- Active locked background color
            ["col.locked_inactive"] = tertiary_container, -- Inactive locked background color
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
        background_color = background, -- Custom background color
        render_unfocused_fps = 5, -- Max FPS limit for unfocused background windows
        enable_anr_dialog = true -- Enable "App Not Responding" dialog
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

-- -------------------------------------------------------------------------------------------------
--  ANIMATIONS
-- -------------------------------------------------------------------------------------------------

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
