import sys
from pathlib import Path
tui_root = Path(__file__).resolve().parents[2] / "dusky_tui"
if str(tui_root) not in sys.path:
    sys.path.insert(0, str(tui_root))

from python.frontend.core_types import ConfigItem

ENGINE_TYPE = "pkg_throttle"
TARGET_FILE = "/sys/class/powercap"
APP_TITLE = "Dusky Power Limit Manager"
DEFAULT_MODE = "auto"
THEME_FILE = "~/.config/matugen/generated/dusky_tui.json"
REQUIRE_ROOT = True

TABS = [
    "Power Limits",
    "Time Windows"
]

SCHEMA = {
    0: [
        ConfigItem(
            label="PL1 (Long-Term Limit)",
            key="pl1",
            type_="int",
            default=90,
            min_val=0,
            max_val=1000,
            step=1,
            extended_help="Sustained long-term CPU package power limit envelope (in Watts). Applies under continuous high workloads."
        ),
        ConfigItem(
            label="PL2 (Short-Term Limit)",
            key="pl2",
            type_="int",
            default=115,
            min_val=0,
            max_val=1000,
            step=1,
            extended_help="Maximum transient boost power envelope (in Watts). Only sustained for the duration of the PL2 time window."
        ),
        ConfigItem(
            label="PL4 (Peak Limit)",
            key="pl4",
            type_="int",
            default=215,
            min_val=0,
            max_val=1000,
            step=5,
            extended_help="Absolute physical hardware power spike clamp (in Watts). Prevents PSU protection triggers on rapid power transitions."
        )
    ],
    1: [
        ConfigItem(
            label="PL1 Time Window",
            key="pl1_time",
            type_="float",
            default=28.00,
            min_val=0.01,
            max_val=150.0,
            step=0.5,
            extended_help="Rolling averaging window (in seconds) for long-term PL1 enforcement."
        ),
        ConfigItem(
            label="PL2 Time Window",
            key="pl2_time",
            type_="float",
            default=0.0020,
            min_val=0.0001,
            max_val=2.0,
            step=0.0005,
            extended_help="Maximum duration envelope (in seconds) that the CPU package is permitted to boost up to PL2 power limits before scaling down."
        )
    ]
}

if __name__ == "__main__":
    import sys
    import subprocess
    from pathlib import Path

    main_py = Path(__file__).resolve().parents[2] / "dusky_tui" / "python" / "main" / "main.py"

    cmd = [sys.executable, str(main_py), str(Path(__file__).resolve()), *sys.argv[1:]]
    try:
        res = subprocess.run(cmd)
        sys.exit(res.returncode)
    except Exception as e:
        print(f"[-] Error delegating to dusky_tui: {e}")
        sys.exit(1)
