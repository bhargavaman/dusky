#!/usr/bin/env python3
from python.frontend.core_types import ConfigItem

ENGINE_TYPE = "hypridle"
TARGET_FILE = "~/.config/hypr/hypridle.conf"
APP_TITLE = "Dusky Hypridle"
DEFAULT_MODE = "auto"
ENABLE_USER_PRESETS = True

TABS = ["Power States", "Warnings"]

# Note: The `scope` maps perfectly to the indexing backend of HypridleEngine.
# So `listener:3` automatically finds the 3rd listener block in the config file.

SCHEMA = {
    0: [
        ConfigItem(
            label="1. Auto Lock (s)",
            key="timeout",
            scope="listener:3",
            type_="int",
            min_val=30, max_val=2000000000, step=30,
            default=300,
            extended_help="Time in seconds before the screen automatically locks.\n\n**Note**: You can press `Enter` and manually type `2000000000` to effectively disable this (Never)."
        ),
        ConfigItem(
            label="2. Screen Off (s)",
            key="timeout",
            scope="listener:4",
            type_="int",
            min_val=30, max_val=2000000000, step=30,
            default=330,
            extended_help="Time in seconds before the monitors are powered off (DPMS). This is critical for saving battery.\n\n**Note**: You can press `Enter` and manually type `2000000000` to effectively disable this (Never)."
        ),
        ConfigItem(
            label="3. Suspend (s)",
            key="timeout",
            scope="listener:5",
            type_="int",
            min_val=60, max_val=2000000000, step=60,
            default=600,
            extended_help="Time in seconds before the system suspends.\n\n**Note**: You can press `Enter` and manually type `2000000000` to effectively disable this (Never)."
        ),
    ],
    1: [
        ConfigItem(
            label="4. Kbd Backlight (s)",
            key="timeout",
            scope="listener:1",
            type_="int",
            min_val=10, max_val=2000000000, step=10,
            default=140,
            extended_help="Time in seconds before keyboard backlight dims.\n\n**Note**: You can press `Enter` and manually type `2000000000` to effectively disable this (Never)."
        ),
        ConfigItem(
            label="5. Screen Dim (s)",
            key="timeout",
            scope="listener:2",
            type_="int",
            min_val=10, max_val=2000000000, step=10,
            default=150,
            extended_help="Time in seconds before the screen dims as a warning before sleep/lock.\n\n**Note**: You can press `Enter` and manually type `2000000000` to effectively disable this (Never)."
        ),
    ]
}
