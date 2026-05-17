#!/usr/bin/env python3

from python.frontend.core_types import ConfigItem

# =============================================================================
# 1. CORE APPLICATION ROUTING
# =============================================================================
ENGINE_TYPE = "lua"
TARGET_FILE = "~/.config/hypr/edit_here/source/autostart.lua"
APP_TITLE = "Autostart & Services"

# =============================================================================
# 2. UI & ENVIRONMENT BEHAVIOR
# =============================================================================
DEFAULT_MODE = "auto"
THEME_FILE = "~/.config/matugen/generated/dusky_tui.json"
ENABLE_USER_PRESETS = True
USER_PRESETS_TAB = "Profiles"

# =============================================================================
# 3. TABS DEFINITION
# =============================================================================
TABS = [
    "System",
    "Utilities",
    "Profiles"
]

# =============================================================================
# 4. SCHEMA DEFINITION
# =============================================================================
SCHEMA = {
    # -------------------------------------------------------------------------
    # TAB 0: System Configuration (AST mapped)
    # -------------------------------------------------------------------------
    0: [
        ConfigItem(
            label="Enable XWayland Subsystem",
            key="enabled",
            scope="xwayland",       # Maps to hl.config({ xwayland = { enabled = ... } })
            type_="bool",
            default=True,
            group="Compatibility",
            extended_help="**XWayland Support**\n\nToggles the XWayland translation layer globally. \n\n- **ON**: Better compatibility for older X11 applications.\n- **OFF**: Disables the layer to save 20-30 MB of RAM, but strictly prevents non-Wayland applications from functioning."
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 1: Utility Actions (Dusky Dashboards & Autostart Triggers)
    # -------------------------------------------------------------------------
    1: [
        # --- HYBRID FOLDER: Dusky Glance Dashboards ---
        ConfigItem(
            label="Dusky Glance Dashboards",
            key="menu_dusky_glance",
            scope="DEFAULT",
            type_="menu",
            default=None,
            is_parent=True,
            expanded=False,
            group="Monitors",
            extended_help="**Dusky Glance Modules**\n\nLaunch various system monitoring overlays directly via Rofi. These commands provide quick, floating overviews of your system's real-time metrics."
        ),
        ConfigItem(
            label="Glance: CPU Usage",
            key="action_glance_cpu",
            scope="DEFAULT",
            type_="action",
            default="~/user_scripts/rofi/dusky_glance.sh --cpu",
            parent_ref="menu_dusky_glance",
            group="Monitors",
            extended_help="**CPU Glance**\n\nExecutes the Rofi overlay to display current CPU utilization and core statistics."
        ),
        ConfigItem(
            label="Glance: Memory (RAM)",
            key="action_glance_ram",
            scope="DEFAULT",
            type_="action",
            default="~/user_scripts/rofi/dusky_glance.sh --ram",
            parent_ref="menu_dusky_glance",
            group="Monitors",
            extended_help="**RAM Glance**\n\nExecutes the Rofi overlay to display current Memory usage, caching, and swap allocation."
        ),
        ConfigItem(
            label="Glance: Temperatures",
            key="action_glance_temp",
            scope="DEFAULT",
            type_="action",
            default="~/user_scripts/rofi/dusky_glance.sh --temp",
            parent_ref="menu_dusky_glance",
            group="Monitors",
            extended_help="**Temperature Glance**\n\nExecutes the Rofi overlay to display thermal metrics for your CPU and GPU."
        ),
        ConfigItem(
            label="Glance: Battery Status",
            key="action_glance_battery",
            scope="DEFAULT",
            type_="action",
            default="~/user_scripts/rofi/dusky_glance.sh --battery",
            parent_ref="menu_dusky_glance",
            group="Monitors",
            extended_help="**Battery Glance**\n\nExecutes the Rofi overlay to display the charging state, overall health, and exact capacity of the internal battery."
        ),
        ConfigItem(
            label="Glance: Network",
            key="action_glance_network",
            scope="DEFAULT",
            type_="action",
            default="~/user_scripts/rofi/dusky_glance.sh --network",
            parent_ref="menu_dusky_glance",
            group="Monitors",
            extended_help="**Network Glance**\n\nExecutes the Rofi overlay to display active network connections, local IP addresses, and bandwidth data."
        ),
        ConfigItem(
            label="Glance: System Uptime",
            key="action_glance_uptime",
            scope="DEFAULT",
            type_="action",
            default="~/user_scripts/rofi/dusky_glance.sh --uptime",
            parent_ref="menu_dusky_glance",
            group="Monitors",
            extended_help="**Uptime Glance**\n\nExecutes the Rofi overlay to display how long the operating system has been running since the last boot."
        ),

        # --- INDIVIDUAL ACTIONS: Interface Control ---
        ConfigItem(
            label="Launch / Reload Waybar",
            key="action_launch_waybar",
            scope="DEFAULT",
            type_="action",
            default="uwsm-app -- $HOME/user_scripts/waybar/waybar_autostart.sh",
            group="Interface",
            extended_help="**Waybar Controller**\n\nManually triggers the Waybar launch script. This is highly useful if the status bar crashes or if you want to apply Waybar configuration changes without rebooting."
        ),
        ConfigItem(
            label="Toggle Waybar Timer",
            key="action_toggle_timer",
            scope="DEFAULT",
            type_="action",
            default="uwsm-app -- $HOME/user_scripts/waybar/toggle_timer_waybar.sh",
            group="Interface",
            extended_help="**Waybar Timer**\n\nToggles the built-in productivity pomodoro timer module on the Waybar interface."
        ),
        ConfigItem(
            label="Start Wallpaper Engine",
            key="action_launch_awww",
            scope="DEFAULT",
            type_="action",
            default="uwsm-app -- awww-daemon",
            group="Interface",
            extended_help="**Wallpaper Engine**\n\nManually starts the `awww-daemon` background service responsible for rendering the desktop wallpaper."
        ),

        # --- INDIVIDUAL ACTIONS: Background Services ---
        ConfigItem(
            label="Start Gnome Keyring Daemon",
            key="action_gnome_keyring",
            scope="DEFAULT",
            type_="action",
            default="uwsm-app -- /usr/bin/gnome-keyring-daemon --start --components=secrets",
            group="Services",
            extended_help="**Gnome Keyring**\n\nManually launches the Gnome Keyring daemon. This securely stores credentials and passwords for applications like VSCode, Chrome, and Nextcloud."
        ),
        ConfigItem(
            label="Grant Root XHost Access",
            key="action_xhost_root",
            scope="DEFAULT",
            type_="action",
            default="uwsm-app -- xhost +si:localuser:root",
            group="Services",
            extended_help="**XHost Root Access**\n\nGrants local root access to the display server. Required to run graphical administrative applications like GParted or Synaptic Package Manager."
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 2: Profiles (System Presets)
    # -------------------------------------------------------------------------
    2: [
        ConfigItem(
            label="Deploy Lightweight Mode",
            key="preset_lightweight_mode",
            scope="DEFAULT",
            type_="preset",
            default=None,
            group="Optimization",
            preset_payload={
                "xwayland.enabled": False
            },
            extended_help="**Lightweight Preset**\n\nOptimizes RAM usage by aggressively disabling the XWayland compatibility layer. \n\n⚠️ Ensure you are only running native Wayland applications before applying this profile."
        ),
        ConfigItem(
            label="Restore Standard Defaults",
            key="preset_restore_defaults",
            scope="DEFAULT",
            type_="preset",
            default=None,
            group="Optimization",
            preset_payload={
                "xwayland.enabled": True
            },
            extended_help="**Standard Defaults**\n\nRe-enables the XWayland compatibility layer, reverting the system back to maximum application compatibility."
        ),
    ]
}
