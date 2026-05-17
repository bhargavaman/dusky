#!/usr/bin/env python3
"""
===============================================================================
DUSKY TUI: INPUT CONFIGURATION SCHEMA
===============================================================================
Target: ~/.config/hypr/edit_here/source/input.lua
Engine: LUA AST Mapper
===============================================================================
"""

from python.frontend.core_types import ConfigItem

# =============================================================================
# 1. CORE APPLICATION ROUTING
# =============================================================================
ENGINE_TYPE = "lua"
TARGET_FILE = "~/.config/hypr/edit_here/source/input.lua"
APP_TITLE = "Dusky Input Configuration"

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
    "Keyboard",
    "Pointer",
    "Touch",
    "Profiles"
]

# =============================================================================
# 4. SCHEMA DEFINITION
# =============================================================================
SCHEMA = {
    # -------------------------------------------------------------------------
    # TAB 0: KEYBOARD
    # -------------------------------------------------------------------------
    0: [
        ConfigItem(
            label="Keyboard Layout",
            key="kb_layout",
            scope="input",
            type_="string",
            default="us",
            group="Layout",
            extended_help="**Keyboard Layout**\n\nSets the appropriate XKB keymap layout parameter (e.g., 'us', 'gb', 'de'). Controls the primary language layout for your keyboard."
        ),
        ConfigItem(
            label="Keyboard Variant",
            key="kb_variant",
            scope="input",
            type_="string",
            default="",
            group="Layout",
            extended_help="**Keyboard Variant**\n\nSets the XKB keymap variant. Leave blank for standard layouts, or specify variants like 'intl' for international configurations."
        ),
        ConfigItem(
            label="Repeat Rate",
            key="repeat_rate",
            scope="input",
            type_="int",
            default=35,
            min_val=10,
            max_val=100,
            step=5,
            group="Typing",
            extended_help="**Repeat Rate**\n\nThe rate at which held-down keys repeat, measured in repeats per second. Higher values make the cursor or character repeat faster when holding a key."
        ),
        ConfigItem(
            label="Repeat Delay",
            key="repeat_delay",
            scope="input",
            type_="int",
            default=250,
            min_val=100,
            max_val=1000,
            step=50,
            group="Typing",
            extended_help="**Repeat Delay**\n\nThe delay before a held-down key starts repeating, in milliseconds. Lower values make repeat behavior kick in faster."
        ),
        ConfigItem(
            label="Enable Numlock by Default",
            key="numlock_by_default",
            scope="input",
            type_="bool",
            default=False,
            group="Typing",
            extended_help="**Numlock Default**\n\nIf enabled, the numpad will automatically be active (Numlock engaged) when the compositor starts up."
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 1: POINTER (Mouse & Cursor)
    # -------------------------------------------------------------------------
    1: [
        ConfigItem(
            label="Mouse Sensitivity",
            key="sensitivity",
            scope="input",
            type_="float",
            default=0.0,
            min_val=-1.0,
            max_val=1.0,
            step=0.1,
            group="Mouse",
            extended_help="**Sensitivity**\n\nSets the mouse input sensitivity. Value is clamped to the range -1.0 to 1.0. 0.0 is neutral/default."
        ),
        ConfigItem(
            label="Acceleration Profile",
            key="accel_profile",
            scope="input",
            type_="cycle",
            default="adaptive",
            options=["adaptive", "flat", "custom"],
            group="Mouse",
            extended_help="**Acceleration Profile**\n\nSets the cursor acceleration profile.\n- **Adaptive**: Accelerates naturally based on speed.\n- **Flat**: Constant sensitivity regardless of speed (good for gaming).\n- **Custom**: Based on scroll points."
        ),
        ConfigItem(
            label="Left Handed Mode",
            key="left_handed",
            scope="input",
            type_="bool",
            default=True,
            group="Mouse",
            extended_help="**Left Handed**\n\nSwitches the Right Mouse Button (RMB) and Left Mouse Button (LMB) across devices."
        ),
        ConfigItem(
            label="Natural Scrolling",
            key="natural_scroll",
            scope="input",
            type_="bool",
            default=False,
            group="Scrolling",
            extended_help="**Natural Scrolling**\n\nInverts scrolling direction for standard mice. Scrolling down moves content up, similar to touchscreen behavior."
        ),
        ConfigItem(
            label="Scroll Method",
            key="scroll_method",
            scope="input",
            type_="cycle",
            default="2fg",
            options=["2fg", "edge", "on_button_down", "no_scroll"],
            group="Scrolling",
            extended_help="**Scroll Method**\n\nDetermines the input method required to trigger scroll events (e.g., Two-Finger '2fg' or edge scrolling)."
        ),
        ConfigItem(
            label="Window Focus Behavior",
            key="follow_mouse",
            scope="input",
            type_="int",
            default=1,
            options=[0, 1, 2, 3],
            group="Focus",
            extended_help="**Follow Mouse**\n\nSpecify if and how cursor movement affects window focus.\n- 0: Cursor won't focus windows.\n- 1: Cursor focuses windows on hover.\n- 2/3: Advanced click-to-focus hybrid behaviors."
        ),
        ConfigItem(
            label="Mouse Refocus",
            key="mouse_refocus",
            scope="input",
            type_="bool",
            default=True,
            group="Focus",
            extended_help="**Mouse Refocus**\n\nIf disabled, mouse focus won't automatically switch unless crossing a window boundary when follow_mouse is set to 1."
        ),
        ConfigItem(
            label="Hide Cursor on Key Press",
            key="hide_on_key_press",
            scope="cursor",
            type_="bool",
            default=False,
            group="Cursor",
            extended_help="**Hide on Typing**\n\nAutomatically hides the mouse cursor when you press any keyboard key, preventing it from obscuring text. It reappears instantly upon moving the mouse."
        ),
        ConfigItem(
            label="Cursor Inactivity Timeout",
            key="inactive_timeout",
            scope="cursor",
            type_="float",
            default=0.0,
            min_val=0.0,
            max_val=60.0,
            step=1.0,
            group="Cursor",
            extended_help="**Inactivity Timeout**\n\nIn seconds, defines how long to wait during cursor inactivity before completely hiding it. Set to 0.0 to disable hiding."
        ),
        ConfigItem(
            label="Enable Hyprcursor Integration",
            key="enable_hyprcursor",
            scope="cursor",
            type_="bool",
            default=True,
            group="Cursor",
            extended_help="**Hyprcursor Support**\n\nToggles native rendering capabilities for advanced cursor themes using the Hyprcursor standard."
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 2: TOUCH (Touchpad & Gestures)
    # -------------------------------------------------------------------------
    2: [
        ConfigItem(
            label="Disable Touchpad While Typing",
            key="disable_while_typing",
            scope="input/touchpad",
            type_="bool",
            default=True,
            group="Touchpad",
            extended_help="**Typing Protection**\n\nAutomatically disables touchpad input while the keyboard is actively in use to prevent accidental palm clicks."
        ),
        ConfigItem(
            label="Touchpad Natural Scroll",
            key="natural_scroll",
            scope="input/touchpad",
            type_="bool",
            default=True,
            group="Touchpad",
            extended_help="**Touchpad Natural Scrolling**\n\nInverts vertical touchpad scrolling direction so that scrolling moves the page content directly."
        ),
        ConfigItem(
            label="Tap to Click",
            key="tap_to_click",
            scope="input/touchpad",
            type_="bool",
            default=True,
            group="Touchpad",
            extended_help="**Tap to Click**\n\nAllows tapping on the touchpad surface to register as a mouse click (1 finger = Left, 2 fingers = Right, 3 fingers = Middle)."
        ),
        ConfigItem(
            label="Clickfinger Behavior",
            key="clickfinger_behavior",
            scope="input/touchpad",
            type_="bool",
            default=False,
            group="Touchpad",
            extended_help="**Clickfinger Behavior**\n\nChanges physical button presses based on the number of fingers touching the pad (e.g., 2 fingers down + click = Right Click) instead of relying on click-pad zones."
        ),
        ConfigItem(
            label="Workspace Swipe Distance",
            key="workspace_swipe_distance",
            scope="gestures",
            type_="int",
            default=300,
            min_val=100,
            max_val=1000,
            step=50,
            group="Gestures",
            extended_help="**Swipe Distance**\n\nThe physical distance in pixels that a touchpad gesture must travel to successfully switch to the adjacent workspace."
        ),
        ConfigItem(
            label="Invert Workspace Swipe",
            key="workspace_swipe_invert",
            scope="gestures",
            type_="bool",
            default=True,
            group="Gestures",
            extended_help="**Invert Swiping**\n\nReverses the direction of horizontal touchpad swipes for changing workspaces."
        ),
        ConfigItem(
            label="Swipe Creates New Workspace",
            key="workspace_swipe_create_new",
            scope="gestures",
            type_="bool",
            default=True,
            group="Gestures",
            extended_help="**Swipe to Create**\n\nIf enabled, swiping right while on the last active workspace will dynamically create a new empty workspace."
        ),
    ],

    # -------------------------------------------------------------------------
    # TAB 3: PROFILES (Presets)
    # -------------------------------------------------------------------------
    3: [
        ConfigItem(
            label="Apply Mac-Like Touch Profile",
            key="preset_mac_defaults",
            scope="DEFAULT",
            type_="preset",
            default=None,
            group="System",
            preset_payload={
                "input/touchpad.natural_scroll": True,
                "input/touchpad.tap_to_click": True,
                "gestures.workspace_swipe_invert": True,
                "input.left_handed": False,
                "input.accel_profile": "adaptive"
            },
            extended_help="**Mac-Like Touch Defaults**\n\nApplies intuitive touchpad scrolling, inverted gesture swiping, and adaptive acceleration commonly found on macOS devices."
        ),
        ConfigItem(
            label="Apply Raw Gaming Input Profile",
            key="preset_raw_gaming",
            scope="DEFAULT",
            type_="preset",
            default=None,
            group="System",
            preset_payload={
                "input.accel_profile": "flat",
                "input.sensitivity": 0.0,
                "cursor.no_hardware_cursors": 0,
                "input.left_handed": False
            },
            extended_help="**Raw Gaming Input**\n\nOptimizes mouse settings for FPS gaming by flattening the acceleration curve to ensure 1:1 raw mouse movement input without artificial acceleration."
        ),
    ]
}
