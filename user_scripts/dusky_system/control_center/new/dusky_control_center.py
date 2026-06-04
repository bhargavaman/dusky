#!/usr/bin/env python3
"""
Dusky Control Center (Production Build)

A GTK3 configuration launcher for the Dusky Dotfiles.
Fully UWSM-compliant for Arch Linux/Hyprland environments.
"""

from __future__ import annotations

import gc
import logging
import subprocess
import sys
import threading
import traceback
from collections.abc import Callable, Iterator
from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Final,
    Literal,
    NotRequired,
    TypedDict,
)

if sys.version_info < (3, 14, 3):
    sys.exit("[FATAL] Python 3.14.3+ is required.")

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

def _setup_cache() -> None:
    """Configure pycache directory following XDG spec."""
    import os
    try:
        xdg_cache_env = os.environ.get("XDG_CACHE_HOME", "").strip()
        xdg_cache = Path(xdg_cache_env) if xdg_cache_env else Path.home() / ".cache"
        cache_dir = xdg_cache / "duskycc"
        cache_dir.mkdir(parents=True, exist_ok=True)
        sys.pycache_prefix = str(cache_dir)
    except OSError as e:
        log.warning("Could not set custom pycache location: %s", e)

_setup_cache()

import lib.utility as utility

utility.preflight_check()

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango

# --- GTK3 MONKEY PATCHES FOR GTK4 COMPATIBILITY ---
def _widget_add_css_class(self, classname):
    self.get_style_context().add_class(classname)

def _widget_remove_css_class(self, classname):
    self.get_style_context().remove_class(classname)

def _container_set_child(self, child):
    if isinstance(self, Gtk.Bin):
        old_child = self.get_child()
        if old_child:
            self.remove(old_child)
    self.add(child)

def _container_get_first_child(self):
    children = self.get_children()
    return children[0] if children else None

def _widget_get_next_sibling(self):
    parent = self.get_parent()
    if not parent:
        return None
    children = parent.get_children()
    try:
        idx = children.index(self)
        if idx + 1 < len(children):
            return children[idx + 1]
    except ValueError:
        pass
    return None

def _container_append(self, child):
    if isinstance(self, Gtk.Box):
        self.pack_start(child, False, False, 0)
    else:
        self.add(child)

Gtk.Widget.add_css_class = _widget_add_css_class
Gtk.Widget.remove_css_class = _widget_remove_css_class
Gtk.Container.set_child = _container_set_child
Gtk.Container.get_first_child = _container_get_first_child
Gtk.Widget.get_next_sibling = _widget_get_next_sibling
Gtk.Container.append = _container_append
Gtk.Label.set_wrap = Gtk.Label.set_line_wrap

import lib.rows as rows

# --- GTK3 ADWAITA COMPATIBILITY CLASSES ---
class DuskyNavigationView(Gtk.Stack):
    def __init__(self):
        super().__init__()
        self.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.set_transition_duration(250)
        self._history = []
        self._last_pop_time = 0
        
        # Connect to visible-child-name notification to manage the history stack automatically
        self.connect("notify::visible-child-name", self._on_visible_child_name_changed)

        # Set up Gtk.GestureSwipe for touch/mouse swipes
        self.swipe_gesture = Gtk.GestureSwipe.new(self)
        self.swipe_gesture.set_propagation_phase(Gtk.PropagationPhase.BUBBLE)
        self.swipe_gesture.connect("swipe", self._on_swipe)

        # Enable scroll events for touchpad horizontal scrolling
        self.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.connect("scroll-event", self._on_scroll_event)

    def set_visible_child_name(self, name):
        # Automatically set transition direction depending on whether we're going back (pop) or forward (push)
        if self._history and name in self._history and self._history.index(name) < len(self._history) - 1:
            self.set_transition_type(Gtk.StackTransitionType.SLIDE_RIGHT)
        else:
            self.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
        super().set_visible_child_name(name)

    def _on_visible_child_name_changed(self, stack, pspec):
        tag = self.get_visible_child_name()
        if not tag:
            return

        if not self._history:
            self._history.append(tag)
            return

        if tag == self._history[-1]:
            return

        if tag in self._history:
            # We navigated back to a page already in the history.
            # Pop all pages after it and destroy them.
            idx = self._history.index(tag)
            to_destroy = self._history[idx+1:]
            self._history = self._history[:idx+1]
            
            for popped_tag in to_destroy:
                old_page = self.get_child_by_name(popped_tag)
                if old_page:
                    self.remove(old_page)
                    old_page.destroy()
        else:
            # Pushing a new page
            self._history.append(tag)

    def push(self, page):
        tag = page.get_name()
        if not self.get_child_by_name(tag):
            self.add_named(page, tag)
        self.set_visible_child_name(tag)
        page.show_all()

    def pop(self):
        if len(self._history) > 1:
            prev_tag = self._history[-2]
            self.set_visible_child_name(prev_tag)
            return True
        return False

    def _debounce_pop(self):
        now = GLib.get_monotonic_time()
        if now - self._last_pop_time > 500000:  # 500ms in microseconds
            if self.pop():
                self._last_pop_time = now
                return True
        return False

    def _on_swipe(self, gesture, velocity_x, velocity_y):
        # A positive velocity_x means swiping from left to right (going back)
        if velocity_x > 250 and abs(velocity_x) > abs(velocity_y) * 1.5:
            self.pop()

    def _on_scroll_event(self, widget, event):
        # Check for touchpad horizontal swipes
        has_delta, delta_x, delta_y = event.get_scroll_deltas()
        if has_delta:
            # Touchpad swipe right (delta_x < -0.8) indicates back navigation
            if delta_x < -0.8 and abs(delta_x) > abs(delta_y) * 2:
                if self._debounce_pop():
                    return True
        else:
            if event.direction == Gdk.ScrollDirection.RIGHT:
                if self._debounce_pop():
                    return True
        return False

    def find_page(self, tag):
        return self.get_child_by_name(tag)

    def pop_to_tag(self, root_tag):
        page = self.get_child_by_name(root_tag)
        if page:
            self.set_visible_child_name(root_tag)

    def get_visible_page(self):
        return self.get_visible_child()

class DuskyNavigationPage(Gtk.Bin):
    def __init__(self, title="", tag=""):
        super().__init__()
        self.title = title
        self.tag = tag
        if tag:
            self.set_name(tag)

class DuskyToolbarView(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._top_bar = None
        self._content = None

    def add_top_bar(self, widget):
        self._top_bar = widget
        self.pack_start(widget, False, False, 0)
        widget.show_all()

    def set_content(self, widget):
        if self._content:
            self.remove(self._content)
        self._content = widget
        self.pack_start(widget, True, True, 0)
        widget.show_all()
        
    def get_content(self):
        return self._content

class DuskyPreferencesPage(Gtk.ScrolledWindow):
    def __init__(self):
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.box.set_margin_start(24)
        self.box.set_margin_end(24)
        self.box.set_margin_top(16)
        self.box.set_margin_bottom(16)
        self.add(self.box)
        
    def add(self, widget):
        if widget != self.box:
            self.box.pack_start(widget, False, False, 0)
            widget.show_all()
        else:
            super().add(widget)
            
    def remove(self, widget):
        if widget != self.box:
            self.box.remove(widget)
        else:
            super().remove(widget)

class DuskyPreferencesGroup(Gtk.Box):
    def __init__(self, title="", description=""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.title_label = Gtk.Label(xalign=0.0)
        self.title_label.get_style_context().add_class("group-title")
        self.pack_start(self.title_label, False, False, 0)
        
        self.desc_label = Gtk.Label(xalign=0.0)
        self.desc_label.get_style_context().add_class("group-description")
        self.desc_label.set_no_show_all(True)
        self.pack_start(self.desc_label, False, False, 0)
        
        self.listbox = Gtk.ListBox()
        self.listbox.get_style_context().add_class("group-listbox")
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.connect("row-activated", self._on_row_activated)
        self.pack_start(self.listbox, False, False, 0)
        
        if title:
            self.set_title(title)
        if description:
            self.set_description(description)
            
    def _on_row_activated(self, listbox, row):
        if hasattr(row, "emit"):
            try:
                row.emit("activated")
            except Exception:
                pass

    def set_title(self, title):
        self.title_label.set_markup(f"<b>{title}</b>")
        self.title_label.show()
        
    def set_description(self, description):
        self.desc_label.set_text(description)
        self.desc_label.show()
        
    def add(self, widget):
        if isinstance(widget, Gtk.ListBoxRow):
            self.listbox.add(widget)
            widget.show_all()
        else:
            self.pack_start(widget, False, False, 0)
            widget.show_all()

class DuskyStatusPage(Gtk.Box):
    def __init__(self, icon_name="", title="", description=""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.CENTER)

        self.icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.DIALOG)
        self.icon.get_style_context().add_class("status-page-icon")
        self.icon.set_pixel_size(44)
        self.pack_start(self.icon, False, False, 0)

        self.title_label = Gtk.Label()
        self.title_label.set_markup(f"<span size='large' weight='bold'>{title}</span>")
        self.pack_start(self.title_label, False, False, 0)

        self.desc_label = Gtk.Label()
        self.desc_label.set_markup(description)
        self.desc_label.set_justify(Gtk.Justification.CENTER)
        self.desc_label.set_wrap(True)
        self.pack_start(self.desc_label, False, False, 0)
        
        self._child = None
        
    def set_child(self, widget):
        if self._child:
            self.remove(self._child)
        self._child = widget
        self.pack_start(widget, False, False, 0)
        widget.show_all()

class DuskyActionRow(rows.BaseActionRow):
    def __init__(self, title="", subtitle="", **kwargs):
        props = {"title": title, "description": subtitle}
        super().__init__(props)

# Stub Adw namespace
Adw = type('Adw', (), {
    'NavigationView': DuskyNavigationView,
    'NavigationPage': DuskyNavigationPage,
    'ToolbarView': DuskyToolbarView,
    'PreferencesPage': DuskyPreferencesPage,
    'PreferencesGroup': DuskyPreferencesGroup,
    'StatusPage': DuskyStatusPage,
    'PreferencesRow': Gtk.ListBoxRow,
    'ActionRow': DuskyActionRow,
})

# =============================================================================
# CONSTANTS
# =============================================================================
APP_ID: Final[str] = "com.github.dusky.controlcenter"
# GTK3 does not derive the Wayland app_id from the application ID like GTK4.
# It uses g_get_prgname() which defaults to the script filename.
# Setting it here ensures Hyprland window rules (which match on class/app_id)
# see "com.github.dusky.controlcenter" instead of "dusky_control_center.py".
GLib.set_prgname(APP_ID)
APP_TITLE: Final[str] = "Dusky Control Center"
CONFIG_FILENAME: Final[str] = "dusky_config.yaml"
CSS_FILENAME: Final[str] = "dusky_style.css"
SCRIPT_DIR: Final[Path] = Path(__file__).resolve().parent

WINDOW_DEFAULT_WIDTH: Final[int] = 1180
WINDOW_DEFAULT_HEIGHT: Final[int] = 780
SIDEBAR_MIN_WIDTH: Final[int] = 180
SIDEBAR_MAX_WIDTH: Final[int] = 180
SIDEBAR_WIDTH_FRACTION: Final[float] = 0.25

PAGE_PREFIX: Final[str] = "page-"
SEARCH_PAGE_ID: Final[str] = "search-results"
ERROR_PAGE_ID: Final[str] = "error-state"
EMPTY_PAGE_ID: Final[str] = "empty-state"

SEARCH_DEBOUNCE_MS: Final[int] = 200
SEARCH_MAX_RESULTS: Final[int] = 50
DEFAULT_TOAST_TIMEOUT: Final[int] = 2

ICON_SYSTEM: Final[str] = "emblem-system-symbolic"
ICON_SEARCH: Final[str] = "system-search-symbolic"
ICON_ERROR: Final[str] = "dialog-error-symbolic"
ICON_EMPTY: Final[str] = "document-open-symbolic"
ICON_WARNING: Final[str] = "dialog-warning-symbolic"
ICON_DEFAULT: Final[str] = "application-x-executable-symbolic"
ICON_SIDEBAR_TOGGLE: Final[str] = "sidebar-show-symbolic"

# =============================================================================
# TYPE DEFINITIONS
# =============================================================================
class ItemType(StrEnum):
    BUTTON = "button"
    TOGGLE = "toggle"
    LABEL = "label"
    SLIDER = "slider"
    SELECTION = "selection"
    ENTRY = "entry"
    NAVIGATION = "navigation"
    WARNING_BANNER = "warning_banner"
    TOGGLE_CARD = "toggle_card"
    GRID_CARD = "grid_card"
    EXPANDER = "expander"
    DIRECTORY_GENERATOR = "directory_generator"
    FILE_GENERATOR = "file_generator"
    ASYNC_SELECTOR = "async_selector"

class SectionType(StrEnum):
    SECTION = "section"
    GRID_SECTION = "grid_section"

class ItemProperties(TypedDict, total=False):
    title: str
    description: str
    icon: str
    message: str
    key: str
    key_inverse: bool
    save_as_int: bool
    style: str
    button_text: str
    min: float
    max: float
    step: float
    default: float
    debounce: bool
    options: list[str]
    options_map: dict[str, str]
    placeholder: str
    path: str
    sort: str
    auto_refresh: bool
    display_max_length: int
    list_command: str
    display_template: str

class ConfigItem(TypedDict, total=False):
    type: str
    properties: ItemProperties
    on_press: dict[str, Any] | None
    on_toggle: dict[str, Any] | None
    on_change: dict[str, Any] | None
    on_action: dict[str, Any] | None
    layout: list[Any]
    items: list[Any]
    item_template: dict[str, Any]
    value: dict[str, Any] | None

class ConfigSection(TypedDict, total=False):
    type: str
    properties: ItemProperties
    items: list[ConfigItem]

class ConfigPage(TypedDict):
    id: NotRequired[str]
    title: str
    icon: NotRequired[str]
    layout: NotRequired[list[ConfigSection]]

class AppConfig(TypedDict):
    pages: list[ConfigPage]

class RowContext(TypedDict):
    stack: Gtk.Stack | None
    config: AppConfig
    sidebar: Gtk.ListBox | None
    toast_overlay: Gtk.Overlay | None
    nav_view: Gtk.Stack | None
    builder_func: Callable[..., Gtk.Widget] | None
    path: list[str]

class ConfigLoadResult(TypedDict):
    success: bool
    config: AppConfig
    css: str
    error: str | None

@dataclass(slots=True, frozen=True)
class SearchHit:
    title: str
    description: str
    icon_name: str
    page_idx: int
    nav_path: tuple[str, ...]
    unique_id: str

@dataclass(slots=True)
class ApplicationState:
    config: AppConfig = field(default_factory=lambda: {"pages": []})
    css_content: str = ""
    last_visible_page: str | None = None
    debounce_source_id: int = 0
    config_error: str | None = None

class DuskyControlCenter(Gtk.Application):
    """
    Main Application Controller.
    """

    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )

        self._state = ApplicationState()
        self._init_widget_refs()
        self._css_provider: Gtk.CssProvider | None = None
        self._screen: Gdk.Screen | None = None
        self._window: Gtk.ApplicationWindow | None = None
        self._reload_running = False
        self._reload_queued = False
        self._directory_generator_cache: dict[int, tuple[ConfigItem, ...]] = {}
        self._file_generator_cache: dict[int, tuple[ConfigItem, ...]] = {}

    def _init_widget_refs(self) -> None:
        """Initialize or reset all widget references to None."""
        self._sidebar_list: Gtk.ListBox | None = None
        self._stack: Gtk.Stack | None = None
        self._toast_overlay: Gtk.Overlay | None = None
        self._search_bar: Gtk.SearchBar | None = None
        self._search_entry: Gtk.SearchEntry | None = None
        self._search_btn: Gtk.ToggleButton | None = None
        self._search_page: DuskyNavigationPage | None = None
        self._search_results_group: DuskyPreferencesGroup | None = None
        self._split_view: Gtk.Box | None = None
        self._sidebar_revealer: Gtk.Revealer | None = None

    # ─────────────────────────────────────────────────────────────────────────
    # LIFECYCLE HOOKS
    # ─────────────────────────────────────────────────────────────────────────
    def do_startup(self) -> None:
        """GTK Startup hook."""
        Gtk.Application.do_startup(self)

        self.hold()

        result = self._load_config_and_css_sync()
        self._state.config = result["config"]
        self._state.css_content = result["css"]
        self._state.config_error = result["error"]

        self._apply_css()
        self._build_ui()

        if self._window:
            self._window.realize()
            self._window.show_all()
            self._window.set_visible(False)

    def do_activate(self) -> None:
        """Application entry point."""
        if self._window:
            self._window.show_all()
            self._window.present()

    def do_shutdown(self) -> None:
        """Cleanup resources on application exit."""
        self._cancel_debounce()
        self._remove_css_provider()
        self._directory_generator_cache.clear()
        self._file_generator_cache.clear()
        Gtk.Application.do_shutdown(self)

    # ─────────────────────────────────────────────────────────────────────────
    # RESOURCE MANAGEMENT
    # ─────────────────────────────────────────────────────────────────────────
    def _cancel_debounce(self) -> None:
        """Cancel any pending search debounce timer."""
        if self._state.debounce_source_id > 0:
            GLib.source_remove(self._state.debounce_source_id)
            self._state.debounce_source_id = 0

    def _remove_css_provider(self) -> None:
        """Remove CSS provider from screen to prevent memory leaks."""
        if self._css_provider is not None and self._screen is not None:
            try:
                Gtk.StyleContext.remove_provider_for_screen(
                    self._screen,
                    self._css_provider,
                )
            except Exception as e:
                log.debug("CSS provider removal warning: %s", e)
        self._css_provider = None

    # ─────────────────────────────────────────────────────────────────────────
    # CONFIG I/O
    # ─────────────────────────────────────────────────────────────────────────
    def _load_config_and_css_sync(self) -> ConfigLoadResult:
        config, config_error = self._do_load_config()
        css = self._do_load_css()
        return {
            "success": config_error is None,
            "config": config,
            "css": css,
            "error": config_error,
        }

    def _validate_config_list(self, value: Any, where: str, seen: set[int]) -> None:
        if not isinstance(value, list):
            raise TypeError(f"{where} must be a list")

        value_id = id(value)
        if value_id in seen:
            raise ValueError(f"{where} contains a recursive reference")

        seen.add(value_id)
        try:
            for idx, child in enumerate(value):
                self._validate_config_node(child, f"{where}[{idx}]", seen)
        finally:
            seen.remove(value_id)

    def _validate_config_node(
        self,
        value: Any,
        where: str,
        seen: set[int] | None = None,
    ) -> None:
        if seen is None:
            seen = set()

        if not isinstance(value, dict):
            raise TypeError(f"{where} must be a dictionary")

        value_id = id(value)
        if value_id in seen:
            raise ValueError(f"{where} contains a recursive reference")

        seen.add(value_id)
        try:
            if "properties" in value and not isinstance(value["properties"], dict):
                raise TypeError(f"{where}.properties must be a dictionary")

            for key in ("on_press", "on_toggle", "on_change", "on_action"):
                if key in value and value[key] is not None and not isinstance(value[key], dict):
                    raise TypeError(f"{where}.{key} must be a dictionary or null")

            if (
                "value" in value
                and value["value"] is not None
                and not isinstance(value["value"], (dict, str))
            ):
                raise TypeError(f"{where}.value must be a dictionary, string, or null")

            if "item_template" in value:
                if not isinstance(value["item_template"], dict):
                    raise TypeError(f"{where}.item_template must be a dictionary")
                self._validate_config_node(value["item_template"], f"{where}.item_template", seen)

            if "layout" in value:
                self._validate_config_list(value["layout"], f"{where}.layout", seen)

            if "items" in value:
                self._validate_config_list(value["items"], f"{where}.items", seen)
        finally:
            seen.remove(value_id)

    def _do_load_config(self) -> tuple[AppConfig, str | None]:
        config_path = SCRIPT_DIR / CONFIG_FILENAME
        try:
            loaded = utility.load_config(config_path)
            if not isinstance(loaded, dict):
                return {"pages": []}, (
                    f"Config is not a dictionary (got {type(loaded).__name__})"
                )

            if "pages" not in loaded:
                return {"pages": []}, "Config missing required 'pages' key"

            pages = loaded.get("pages")
            if not isinstance(pages, list):
                return {"pages": []}, "'pages' must be a list"

            for idx, page in enumerate(pages):
                if not isinstance(page, dict):
                    return {"pages": []}, f"Page {idx} is not a dictionary"
                if "title" not in page:
                    return {"pages": []}, f"Page {idx} missing required 'title' key"
                self._validate_config_node(page, f"pages[{idx}]")

            return loaded, None  # type: ignore[return-value]

        except FileNotFoundError:
            return {"pages": []}, f"Config file not found: {config_path}"
        except Exception as e:
            error_detail = "".join(traceback.format_exception_only(type(e), e)).strip()
            return {"pages": []}, f"Config parse error: {error_detail}"

    def _do_load_css(self) -> str:
        css_path = SCRIPT_DIR / CSS_FILENAME
        try:
            return css_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            log.info("No custom CSS file found at: %s", css_path)
            return ""
        except UnicodeDecodeError as e:
            log.warning("CSS file is not valid UTF-8: %s (%s)", css_path, e)
            return ""
        except OSError as e:
            log.warning("Failed to read CSS file: %s", e)
            return ""

    def _apply_css(self) -> None:
        """Apply loaded CSS without discarding the last working provider on parse failure."""
        if not self._state.css_content:
            self._remove_css_provider()
            self._screen = Gdk.Screen.get_default()
            return

        screen = Gdk.Screen.get_default()
        if screen is None:
            log.warning("No default screen available for CSS")
            return

        provider = Gtk.CssProvider()
        try:
            # Under GTK3, load_from_data expects bytes
            provider.load_from_data(self._state.css_content.encode("utf-8"))
        except GLib.Error as e:
            log.error("CSS parsing failed: %s", e.message)
            return

        old_provider = self._css_provider
        old_screen = self._screen

        Gtk.StyleContext.add_provider_for_screen(
            screen,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self._css_provider = provider
        self._screen = screen

        if old_provider is not None and old_screen is not None:
            try:
                Gtk.StyleContext.remove_provider_for_screen(old_screen, old_provider)
            except Exception as e:
                log.debug("CSS provider removal warning: %s", e)

    def _get_context(
        self,
        nav_view: Gtk.Stack | None = None,
        builder_func: Callable[..., Gtk.Widget] | None = None,
        path: list[str] | None = None,
    ) -> RowContext:
        return {
            "stack": self._stack,
            "config": self._state.config,
            "sidebar": self._sidebar_list,
            "toast_overlay": self._toast_overlay,
            "nav_view": nav_view,
            "builder_func": builder_func,
            "path": path or [],
        }

    # ─────────────────────────────────────────────────────────────────────────
    # UI CONSTRUCTION
    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        """Construct and present the main application window."""
        self._window = Gtk.ApplicationWindow(application=self, title=APP_TITLE)
        self._window.set_default_size(WINDOW_DEFAULT_WIDTH, WINDOW_DEFAULT_HEIGHT)
        self._window.set_size_request(760, 600)
        self._window.connect("delete-event", self._on_close_request)
        self._window.connect("key-press-event", self._on_key_pressed)

        self._toast_overlay = Gtk.Overlay()

        self._split_view = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        self._sidebar_revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_RIGHT)
        self._sidebar_revealer.set_reveal_child(True)
        self._sidebar_revealer.add(self._create_sidebar())

        self._split_view.pack_start(self._sidebar_revealer, False, False, 0)

        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        self._split_view.pack_start(sep, False, False, 0)

        self._split_view.pack_start(self._create_content_panel(), True, True, 0)

        self._toast_overlay.add(self._split_view)
        self._window.add(self._toast_overlay)

        self._create_search_page()

        if self._state.config_error:
            self._show_error_state(self._state.config_error)
        elif not self._state.config.get("pages"):
            self._show_empty_state()
        else:
            self._populate_pages()

    def _on_close_request(self, window: Gtk.ApplicationWindow, event: Any) -> bool:
        """
        Intercept window close. Return True to prevent destruction.
        """
        window.set_visible(False)
        def _deferred_gc() -> bool:
            gc.collect()
            return GLib.SOURCE_REMOVE
        GLib.timeout_add(500, _deferred_gc)
        return True

    def _on_key_pressed(
        self,
        widget: Gtk.Widget,
        event: Gdk.EventKey,
    ) -> bool:
        """Handle global keyboard shortcuts in GTK3."""
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)

        match (ctrl, event.keyval):
            case (True, Gdk.KEY_r):
                self._reload_app_async()
                return True
            case (True, Gdk.KEY_f):
                self._activate_search()
                return True
            case (True, Gdk.KEY_q):
                self.quit()
                return True
            case (False, Gdk.KEY_Escape):
                if self._search_bar and self._search_bar.get_search_mode():
                    self._deactivate_search()
                    return True
        return False

    def _create_sidebar_toggle_button(self) -> Gtk.Button:
        btn = Gtk.Button()
        btn.add(Gtk.Image.new_from_icon_name(ICON_SIDEBAR_TOGGLE, Gtk.IconSize.BUTTON))
        btn.set_tooltip_text("Toggle Sidebar")
        btn.connect("clicked", self._on_toggle_sidebar)
        return btn

    def _on_toggle_sidebar(self, _btn: Gtk.Button) -> None:
        if self._sidebar_revealer:
            self._sidebar_revealer.set_reveal_child(not self._sidebar_revealer.get_reveal_child())

    # ─────────────────────────────────────────────────────────────────────────
    # ASYNC HOT RELOAD
    # ─────────────────────────────────────────────────────────────────────────
    def _reload_app_async(self) -> None:
        if self._reload_running:
            self._reload_queued = True
            return

        self._reload_running = True
        log.info("Hot Reload Initiated...")

        current_page = self._get_current_page_index()
        old_config = deepcopy(self._state.config)
        old_css = self._state.css_content
        old_error = self._state.config_error

        def background_load() -> ConfigLoadResult:
            config, error = self._do_load_config()
            css = self._do_load_css()
            return {
                "success": error is None,
                "config": config,
                "css": css,
                "error": error,
            }

        def on_complete(
            result: ConfigLoadResult | None,
            error: BaseException | None,
        ) -> None:
            try:
                if error is not None:
                    log.error("Reload thread error: %s", error, exc_info=True)
                    self._toast("Reload Failed: Internal error", 3)
                    return

                if result is None:
                    self._toast("Reload Failed: No result", 3)
                    return

                self._state.config = result["config"]
                self._state.css_content = result["css"]
                self._state.config_error = result["error"]

                self._apply_css()
                self._clear_and_rebuild_ui(current_page)

                if result["error"]:
                    self._toast(f"Config Error: {result['error'][:50]}...", 4)
                else:
                    self._toast("Configuration Reloaded 🚀")

            except Exception as rebuild_error:
                log.error("UI Rebuild failed: %s", rebuild_error, exc_info=True)

                self._state.config = old_config
                self._state.css_content = old_css
                self._state.config_error = old_error

                try:
                    self._apply_css()
                    self._clear_and_rebuild_ui(current_page)
                except Exception:
                    log.critical("Rollback UI rebuild failed", exc_info=True)

                self._toast("Reload Failed: UI rebuild error", 3)

            finally:
                self._reload_running = False
                if self._reload_queued:
                    self._reload_queued = False
                    GLib.idle_add(self._reload_app_async)

        self._run_in_background(background_load, on_complete)

    def _get_current_page_index(self) -> int | None:
        if self._sidebar_list is None:
            return None
        row = self._sidebar_list.get_selected_row()
        return row.get_index() if row else None

    def _run_in_background(
        self,
        task: Callable[[], Any],
        callback: Callable[[Any, BaseException | None], None],
    ) -> None:
        def wrapper() -> None:
            result: Any = None
            error: BaseException | None = None
            try:
                result = task()
            except BaseException as e:
                error = e
                log.error("Background task failed: %s", e, exc_info=True)

            GLib.idle_add(callback, result, error)

        thread = threading.Thread(target=wrapper, daemon=True, name="reload-worker")
        thread.start()

    def _clear_and_rebuild_ui(self, restore_page_index: int | None) -> None:
        self._cancel_debounce()
        self._directory_generator_cache.clear()
        self._file_generator_cache.clear()
        self._state.last_visible_page = None

        self._search_page = None
        self._search_results_group = None

        self._clear_sidebar()
        self._clear_stack()

        self._create_search_page()

        if self._state.config_error:
            self._show_error_state(self._state.config_error)
        elif not self._state.config.get("pages"):
            self._show_empty_state()
        else:
            self._populate_pages(restore_page_index)

    def _clear_sidebar(self) -> None:
        if self._sidebar_list is None:
            return
        while (row := self._sidebar_list.get_row_at_index(0)) is not None:
            self._sidebar_list.remove(row)

    def _clear_stack(self) -> None:
        if self._stack is None:
            return
        while (child := self._stack.get_first_child()) is not None:
            self._stack.remove(child)

    # ─────────────────────────────────────────────────────────────────────────
    # SEARCH FUNCTIONALITY
    # ─────────────────────────────────────────────────────────────────────────
    def _generate_widget_id(self, item: object) -> str:
        return f"cfg_{id(item):x}"

    def _highlight_widget_by_id(self, parent: Gtk.Widget, unique_id: str) -> Literal[False]:
        widget = self._find_widget_by_name(parent, unique_id)
        if widget:
            widget.grab_focus()
            widget.add_css_class("highlight-pulse")
            GLib.timeout_add(
                1500,
                lambda w=widget: (w.remove_css_class("highlight-pulse"), GLib.SOURCE_REMOVE)[1],
            )
        return GLib.SOURCE_REMOVE

    def _find_widget_by_name(self, parent: Gtk.Widget, name: str) -> Gtk.Widget | None:
        if parent.get_name() == name:
            return parent
        child = parent.get_first_child()
        while child is not None:
            found = self._find_widget_by_name(child, name)
            if found:
                return found
            child = child.get_next_sibling()
        return None

    def _create_search_page(self) -> None:
        if self._stack is None:
            return

        self._search_page = DuskyNavigationPage(title="Search", tag="search")

        toolbar = DuskyToolbarView()
        header = Gtk.HeaderBar()
        header.pack_start(self._create_sidebar_toggle_button())
        toolbar.add_top_bar(header)

        pref_page = DuskyPreferencesPage()
        self._search_results_group = DuskyPreferencesGroup(title="Search Results")
        pref_page.add(self._search_results_group)

        toolbar.set_content(pref_page)
        self._search_page.set_child(toolbar)
        self._search_page.show_all()

        self._stack.add_named(self._search_page, SEARCH_PAGE_ID)

    def _activate_search(self) -> None:
        if self._stack:
            current = self._stack.get_visible_child_name()
            if current and current != SEARCH_PAGE_ID:
                self._state.last_visible_page = current

        if self._search_bar:
            self._search_bar.set_search_mode(True)
        if self._search_btn:
            self._search_btn.set_active(True)
        if self._search_entry:
            self._search_entry.grab_focus()

    def _deactivate_search(self) -> None:
        self._cancel_debounce()
        if self._search_bar:
            self._search_bar.set_search_mode(False)
        if self._search_btn:
            self._search_btn.set_active(False)
        if self._search_entry:
            self._search_entry.set_text("")
            self._cancel_debounce()

        if self._state.last_visible_page and self._stack:
            self._stack.set_visible_child_name(self._state.last_visible_page)

        self._state.last_visible_page = None

    def _on_search_btn_toggled(self, btn: Gtk.ToggleButton) -> None:
        if btn.get_active():
            self._activate_search()
        else:
            self._deactivate_search()

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._cancel_debounce()
        query = entry.get_text()
        src_id = GLib.timeout_add(
            SEARCH_DEBOUNCE_MS,
            self._execute_search,
            query,
        )
        if src_id > 0:
            self._state.debounce_source_id = src_id

    def _execute_search(self, query: str) -> Literal[False]:
        self._state.debounce_source_id = 0
        if self._stack is None or self._search_results_group is None:
            return GLib.SOURCE_REMOVE

        display_query = query.strip()
        normalized_query = display_query.casefold()

        if not normalized_query:
            self._reset_search_results("Search Results")
            return GLib.SOURCE_REMOVE

        if self._state.last_visible_page is None:
            current = self._stack.get_visible_child_name()
            if current and current != SEARCH_PAGE_ID:
                self._state.last_visible_page = current

        self._stack.set_visible_child_name(SEARCH_PAGE_ID)
        self._reset_search_results(f"Results for '{display_query}'")
        self._populate_search_results(normalized_query)

        return GLib.SOURCE_REMOVE

    def _reset_search_results(self, title: str) -> None:
        if self._search_page is None:
            return

        toolbar = self._search_page.get_child()
        if not isinstance(toolbar, DuskyToolbarView):
            return

        page = toolbar.get_content()
        if not isinstance(page, DuskyPreferencesPage):
            return

        if self._search_results_group is not None:
            page.remove(self._search_results_group)

        self._search_results_group = DuskyPreferencesGroup(title=GLib.markup_escape_text(title, -1))
        page.add(self._search_results_group)

    def _populate_search_results(self, query: str) -> None:
        if self._search_results_group is None:
            return

        count = 0
        for hit in self._iter_matching_items(query):
            if count >= SEARCH_MAX_RESULTS:
                overflow_row = DuskyActionRow(
                    title=f"Showing first {SEARCH_MAX_RESULTS} results...",
                    subtitle="Refine your search for more specific results",
                )
                overflow_row.set_activatable(False)
                overflow_row.add_css_class("dim-label")
                self._search_results_group.add(overflow_row)
                break

            self._search_results_group.add(self._build_search_result_row(hit))
            count += 1

        if count == 0:
            no_results = DuskyActionRow(
                title="No results found",
                subtitle="Try different search terms",
            )
            no_results.set_activatable(False)
            self._search_results_group.add(no_results)

    def _build_search_result_row(self, hit: SearchHit) -> DuskyActionRow:
        row = DuskyActionRow(
            title=GLib.markup_escape_text(hit.title, -1),
            subtitle=GLib.markup_escape_text(hit.description, -1)
        )
        row.add_css_class("action-row")
        row.set_activatable(True)

        icon_widget = Gtk.Image.new_from_icon_name(hit.icon_name, Gtk.IconSize.BUTTON)
        icon_widget.add_css_class("action-row-prefix-icon")
        icon_widget.set_pixel_size(20)
        row.add_prefix(icon_widget)

        go_icon = Gtk.Image.new_from_icon_name("go-next-symbolic", Gtk.IconSize.BUTTON)
        go_icon.set_valign(Gtk.Align.CENTER)
        row.add_suffix(go_icon)

        row.connect("activated", lambda _row, hit=hit: self._navigate_from_search(hit))
        return row

    def _navigate_from_search(self, hit: SearchHit) -> None:
        self._deactivate_search()
        if self._sidebar_list is None:
            return

        row = self._sidebar_list.get_row_at_index(hit.page_idx)
        if row is None:
            return

        self._sidebar_list.select_row(row)

        page_name = f"{PAGE_PREFIX}{hit.page_idx}"
        root_tag = f"root_{hit.page_idx}"
        self._switch_to_page_and_reset(page_name, root_tag)

        target_page = None
        if self._stack:
            child = self._stack.get_child_by_name(page_name)
            if isinstance(child, DuskyNavigationView):
                target_page = child.get_visible_page()

                if len(hit.nav_path) > 1:
                    current_layout = self._state.config.get("pages", [])[hit.page_idx].get("layout", [])
                    current_path = [hit.nav_path[0]]

                    for depth in range(1, len(hit.nav_path)):
                        step_title = hit.nav_path[depth]
                        current_path.append(step_title)

                        def find_layout(layout_data: list[Any]) -> list[Any] | None:
                            for section in layout_data:
                                if not isinstance(section, dict):
                                    continue
                                items = section.get("items", [section]) if "items" in section else [section]
                                for item in items:
                                    if not isinstance(item, dict):
                                        continue
                                    if item.get("type") == ItemType.NAVIGATION:
                                        props = item.get("properties", {})
                                        if str(props.get("title", "")).strip() == step_title:
                                            return item.get("layout", [])
                                    elif item.get("type") == ItemType.EXPANDER:
                                        exp_res = find_layout([{"items": item.get("items", [])}])
                                        if exp_res is not None:
                                            return exp_res
                            return None

                        next_layout = find_layout(current_layout)
                        if next_layout is None:
                            break

                        current_layout = next_layout
                        tag = self._make_nav_tag(current_path)
                        page = child.find_page(tag)

                        if page is None:
                            ctx = self._get_context(
                                nav_view=child,
                                builder_func=self._build_nav_page,
                                path=list(current_path),
                            )
                            page = self._build_nav_page(step_title, current_layout, ctx)

                        child.push(page)
                        target_page = page

        if target_page:
            GLib.timeout_add(150, self._highlight_widget_by_id, target_page, hit.unique_id)

    def _extract_icon_name(self, props: dict[str, Any]) -> str:
        icon_config = props.get("icon", ICON_DEFAULT)
        if isinstance(icon_config, str) and icon_config:
            return icon_config

        if isinstance(icon_config, dict):
            icon_name = icon_config.get("name")
            if isinstance(icon_name, str) and icon_name:
                return icon_name

        return ICON_DEFAULT

    def _iter_matching_items(self, query: str) -> Iterator[SearchHit]:
        if not query:
            return

        for page_idx, page in enumerate(self._state.config.get("pages", [])):
            if not isinstance(page, dict):
                continue

            page_title = str(page.get("title", "Unknown")).strip() or "Unknown"
            layout = page.get("layout", [])

            if isinstance(layout, list):
                yield from self._iter_layout_hits(
                    layout,
                    query,
                    page_title,
                    page_idx,
                    (page_title,),
                )

    def _iter_layout_hits(
        self,
        layout: list[ConfigSection],
        query: str,
        breadcrumb: str,
        page_idx: int,
        nav_path: tuple[str, ...],
    ) -> Iterator[SearchHit]:
        for section in layout:
            if not isinstance(section, dict):
                continue
            items = section.get("items")
            if isinstance(items, list):
                for item in items:
                    yield from self._iter_item_hits(item, query, breadcrumb, page_idx, nav_path)
            else:
                yield from self._iter_item_hits(section, query, breadcrumb, page_idx, nav_path)

    def _iter_item_hits(
        self,
        item: Any,
        query: str,
        breadcrumb: str,
        page_idx: int,
        nav_path: tuple[str, ...],
    ) -> Iterator[SearchHit]:
        if not isinstance(item, dict):
            return

        item_type = item.get("type", "")
        props = item.get("properties", {})
        if not isinstance(props, dict):
            props = {}

        if item_type == ItemType.DIRECTORY_GENERATOR:
            for gen_item in self._process_directory_generator(item):
                yield from self._iter_item_hits(gen_item, query, breadcrumb, page_idx, nav_path)
            return

        if item_type == ItemType.FILE_GENERATOR:
            for gen_item in self._process_file_generator(item):
                yield from self._iter_item_hits(gen_item, query, breadcrumb, page_idx, nav_path)
            return

        title = str(props.get("title", "")).strip()
        desc = str(props.get("description", "")).strip()
        unique_id = self._generate_widget_id(item)

        if query in title.casefold() or query in desc.casefold():
            yield SearchHit(
                title=title or "Unnamed",
                description=f"{breadcrumb} • {desc}" if desc else breadcrumb,
                icon_name=self._extract_icon_name(props),
                page_idx=page_idx,
                nav_path=nav_path,
                unique_id=unique_id,
            )

        if item_type == ItemType.NAVIGATION:
            sub_title = title or "Submenu"
            sub_layout = item.get("layout")
            if isinstance(sub_layout, list):
                next_path = (*nav_path, sub_title)
                yield from self._iter_layout_hits(
                    sub_layout,
                    query,
                    f"{breadcrumb} › {sub_title}",
                    page_idx,
                    next_path,
                )

        if item_type == ItemType.EXPANDER:
            sub_title = title or "Expander"
            sub_items = item.get("items")
            if isinstance(sub_items, list):
                next_breadcrumb = f"{breadcrumb} › {sub_title}"
                for child in sub_items:
                    yield from self._iter_item_hits(
                        child,
                        query,
                        next_breadcrumb,
                        page_idx,
                        nav_path,
                    )

    # ─────────────────────────────────────────────────────────────────────────
    # SIDEBAR
    # ─────────────────────────────────────────────────────────────────────────
    def _create_sidebar(self) -> DuskyToolbarView:
        """Create the sidebar with header, search bar, and navigation list."""
        view = DuskyToolbarView()
        view.add_css_class("sidebar-container")

        header = Gtk.HeaderBar()
        header.get_style_context().add_class("sidebar-header")
        header.set_show_close_button(False)

        title_box = Gtk.Box(spacing=8)
        icon = Gtk.Image.new_from_icon_name(ICON_SYSTEM, Gtk.IconSize.BUTTON)
        icon.add_css_class("sidebar-header-icon")
        icon.set_pixel_size(20)
        
        title = Gtk.Label(label="Dusky")
        title.get_style_context().add_class("title")
        title_box.append(icon)
        title_box.append(title)
        header.set_custom_title(title_box)

        self._search_btn = Gtk.ToggleButton()
        self._search_btn.add(Gtk.Image.new_from_icon_name(ICON_SEARCH, Gtk.IconSize.BUTTON))
        self._search_btn.set_tooltip_text("Search (Ctrl+F)")
        self._search_btn.connect("toggled", self._on_search_btn_toggled)
        header.pack_end(self._search_btn)
        view.add_top_bar(header)

        self._search_bar = Gtk.SearchBar()
        self._search_entry = Gtk.SearchEntry(placeholder_text="Find setting...")
        self._search_entry.connect("search-changed", self._on_search_changed)
        self._search_bar.add(self._search_entry)
        self._search_bar.connect_entry(self._search_entry)
        view.add_top_bar(self._search_bar)

        self._sidebar_list = Gtk.ListBox()
        self._sidebar_list.get_style_context().add_class("sidebar-listbox")
        self._sidebar_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._sidebar_list.connect("row-selected", self._on_row_selected)
        self._sidebar_list.connect("row-activated", self._on_row_activated)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self._sidebar_list)
        view.set_content(scroll)

        return view

    def _create_content_panel(self) -> Gtk.Stack:
        """Create the main content panel stack."""
        self._stack = Gtk.Stack(vexpand=True, hexpand=True)
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(200)
        return self._stack

    def _on_row_selected(
        self,
        listbox: Gtk.ListBox,
        row: Gtk.ListBoxRow | None,
    ) -> None:
        if row is None or self._stack is None:
            return

        idx = row.get_index()
        pages = self._state.config.get("pages", [])
        if 0 <= idx < len(pages):
            page_name = f"{PAGE_PREFIX}{idx}"
            root_tag = f"root_{idx}"
            self._switch_to_page_and_reset(page_name, root_tag)

    def _on_row_activated(self, listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        self._on_row_selected(listbox, row)

    def _switch_to_page_and_reset(self, page_name: str, root_tag: str) -> None:
        if self._stack:
            if child := self._stack.get_child_by_name(page_name):
                if isinstance(child, DuskyNavigationView):
                    child.pop_to_tag(root_tag)
            self._stack.set_visible_child_name(page_name)

    # ─────────────────────────────────────────────────────────────────────────
    # PAGE BUILDING
    # ─────────────────────────────────────────────────────────────────────────
    def _populate_pages(self, select_index: int | None = None) -> None:
        pages = self._state.config.get("pages", [])
        if not pages:
            self._show_empty_state()
            return

        first_row: Gtk.ListBoxRow | None = None
        target_row: Gtk.ListBoxRow | None = None

        for idx, page in enumerate(pages):
            title = str(page.get("title", "Untitled"))
            icon = str(page.get("icon", ICON_DEFAULT))
            root_tag = f"root_{idx}"

            row = self._create_sidebar_row(title, icon)

            if self._sidebar_list:
                self._sidebar_list.append(row)
                if first_row is None:
                    first_row = row
                if idx == select_index:
                    target_row = row

            nav = DuskyNavigationView()

            ctx = self._get_context(
                nav_view=nav,
                builder_func=self._build_nav_page,
                path=[title],
            )

            root = self._build_nav_page(title, page.get("layout", []), ctx, root_tag=root_tag)
            root.show_all()
            nav.add_named(root, root_tag)
            nav.set_visible_child_name(root_tag)
            nav.show_all()

            if self._stack:
                self._stack.add_named(nav, f"{PAGE_PREFIX}{idx}")

        if self._sidebar_list:
            row_to_select = target_row or first_row
            if row_to_select:
                self._sidebar_list.select_row(row_to_select)

    def _create_sidebar_row(self, title: str, icon_name: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.get_style_context().add_class("sidebar-row")

        box = Gtk.Box()
        icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
        icon.add_css_class("sidebar-row-icon")
        icon.set_pixel_size(18)

        label = Gtk.Label(label=title, xalign=0, hexpand=True)
        label.get_style_context().add_class("sidebar-row-label")
        label.set_ellipsize(Pango.EllipsizeMode.END)

        box.append(icon)
        box.append(label)
        row.add(box)
        return row

    def _make_nav_tag(self, path: list[str] | tuple[str, ...]) -> str:
        parts: list[str] = []
        for raw_part in path:
            part = "".join(ch if ch.isalnum() else "_" for ch in raw_part.strip())
            parts.append(part.strip("_") or "page")
        return f"page_{len(path)}_{'__'.join(parts)}"

    def _build_nav_page(
        self,
        title: str,
        layout: list[ConfigSection],
        ctx: RowContext,
        root_tag: str | None = None,
    ) -> DuskyNavigationPage:
        path = list(ctx.get("path") or [])
        if not path or path[-1] != title:
            path.append(title)

        tag = root_tag if root_tag else self._make_nav_tag(path)
        page = DuskyNavigationPage(title=title, tag=tag)

        toolbar = DuskyToolbarView()
        header = Gtk.HeaderBar()
        header.set_show_close_button(False)

        if len(path) == 1:
            header.pack_start(self._create_sidebar_toggle_button())
        else:
            back_btn = Gtk.Button.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.BUTTON)
            back_btn.get_style_context().add_class("flat")
            back_btn.get_style_context().add_class("back-button")
            nav_view = ctx.get("nav_view")
            if nav_view:
                back_btn.connect("clicked", lambda btn: nav_view.pop())
            header.pack_start(back_btn)

        header.set_title(title)
        if len(path) > 1:
            header.set_subtitle(" › ".join(path[:-1]))

        toolbar.add_top_bar(header)

        pref_page = DuskyPreferencesPage()
        self._populate_pref_content(pref_page, layout, ctx)

        toolbar.set_content(pref_page)
        page.set_child(toolbar)
        return page

    def _populate_pref_content(
        self,
        page: DuskyPreferencesPage,
        layout: list[ConfigSection],
        ctx: RowContext,
    ) -> None:
        for section in layout:
            section_type = section.get("type", SectionType.SECTION)

            if section_type == SectionType.GRID_SECTION:
                page.add(self._build_grid_section(section, ctx))
                continue

            if isinstance(section.get("items"), list):
                page.add(self._build_standard_section(section, ctx))
                continue

            group = DuskyPreferencesGroup()
            group.add(self._build_item_row(section, ctx))
            page.add(group)

    def _build_grid_section(
        self,
        section: ConfigSection,
        ctx: RowContext,
    ) -> DuskyPreferencesGroup:
        group = DuskyPreferencesGroup()
        props = section.get("properties", {})
        if not isinstance(props, dict):
            props = {}

        if title := props.get("title"):
            group.set_title(GLib.markup_escape_text(str(title), -1))

        flow = Gtk.FlowBox()
        flow.set_valign(Gtk.Align.START)
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_column_spacing(12)
        flow.set_row_spacing(12)
        flow.set_min_children_per_line(2)
        flow.set_max_children_per_line(3)

        def append_grid_item(grid_item: ConfigItem) -> None:
            item_type = grid_item.get("type", "")
            item_props = grid_item.get("properties", {})
            if not isinstance(item_props, dict):
                item_props = {}

            try:
                match item_type:
                    case ItemType.TOGGLE_CARD:
                        child = rows.GridToggleCard(item_props, grid_item.get("on_toggle"), ctx)
                    case ItemType.GRID_CARD:
                        child = rows.GridCard(item_props, grid_item.get("on_press"), ctx)
                    case _:
                        log.warning(
                            "Unsupported grid item type '%s', defaulting to GridCard",
                            item_type,
                        )
                        child = rows.GridCard(item_props, grid_item.get("on_press"), ctx)
            except Exception as e:
                log.error("Failed to build grid item for type '%s': %s", item_type, e)
                flow.append(self._build_error_row(str(e), str(item_props.get("title", "Unknown"))))
                return

            child.set_name(self._generate_widget_id(grid_item))
            flow.append(child)

        for item in section.get("items", []):
            if item.get("type") == ItemType.DIRECTORY_GENERATOR:
                for gen_item in self._process_directory_generator(item):
                    append_grid_item(gen_item)
            elif item.get("type") == ItemType.FILE_GENERATOR:
                for gen_item in self._process_file_generator(item):
                    append_grid_item(gen_item)
            else:
                append_grid_item(item)

        group.add(flow)
        return group

    def _build_standard_section(
        self,
        section: ConfigSection,
        ctx: RowContext,
    ) -> DuskyPreferencesGroup:
        group = DuskyPreferencesGroup()
        props = section.get("properties", {})

        if title := props.get("title"):
            group.set_title(GLib.markup_escape_text(str(title), -1))
        if desc := props.get("description"):
            group.set_description(GLib.markup_escape_text(str(desc), -1))

        for item in section.get("items", []):
            if item.get("type") == ItemType.DIRECTORY_GENERATOR:
                for gen_item in self._process_directory_generator(item):
                    group.add(self._build_item_row(gen_item, ctx))
            elif item.get("type") == ItemType.FILE_GENERATOR:
                for gen_item in self._process_file_generator(item):
                    group.add(self._build_item_row(gen_item, ctx))
            else:
                group.add(self._build_item_row(item, ctx))

        return group

    def _process_directory_generator(self, config: ConfigItem) -> Iterator[ConfigItem]:
        cache_key = id(config)
        cached = self._directory_generator_cache.get(cache_key)
        if cached is not None:
            yield from cached
            return

        props = config.get("properties", {})
        if not isinstance(props, dict):
            self._directory_generator_cache[cache_key] = ()
            return

        path_str = props.get("path")
        template = config.get("item_template")

        if not isinstance(path_str, str) or not path_str or not isinstance(template, dict):
            self._directory_generator_cache[cache_key] = ()
            return

        base_path = Path(path_str).expanduser()
        if not base_path.is_dir():
            self._directory_generator_cache[cache_key] = ()
            return

        try:
            dirs = sorted(
                (p for p in base_path.iterdir() if p.is_dir()),
                key=lambda p: p.name.casefold(),
            )
        except OSError:
            self._directory_generator_cache[cache_key] = ()
            return

        generated: list[ConfigItem] = []
        for directory in dirs:
            name_pretty = directory.name.replace("_", " ").title()
            variables = {
                "name": directory.name,
                "path": str(directory),
                "name_pretty": name_pretty,
            }
            generated_item = self._inject_variables(template, variables)
            if isinstance(generated_item, dict):
                generated.append(generated_item)

        frozen = tuple(generated)
        self._directory_generator_cache[cache_key] = frozen
        yield from frozen

    def _process_file_generator(self, config: ConfigItem) -> Iterator[ConfigItem]:
        cache_key = id(config)
        cached = self._file_generator_cache.get(cache_key)
        if cached is not None:
            yield from cached
            return

        generated: list[ConfigItem] = []
        props = config.get("properties", {})
        if not isinstance(props, dict):
            self._file_generator_cache[cache_key] = ()
            return

        template = config.get("item_template")
        if not isinstance(template, dict):
            self._file_generator_cache[cache_key] = ()
            return

        path_str = props.get("path", "")
        glob_raw = props.get("glob", "*.conf")
        glob_pattern = glob_raw if isinstance(glob_raw, str) and glob_raw else "*.conf"
        recursive = bool(props.get("recursive", False))

        if not isinstance(path_str, str) or not path_str.strip():
            self._file_generator_cache[cache_key] = ()
            return

        base_path = Path(path_str).expanduser()

        def _iter_files() -> Iterator[Path]:
            try:
                for p in base_path.glob(glob_pattern):
                    if p.is_file() or p.is_symlink():
                        yield p
            except (OSError, PermissionError, ValueError):
                return

            if not recursive:
                return

            try:
                subdirs = sorted(
                    (p for p in base_path.iterdir() if p.is_dir() and not p.is_symlink()),
                    key=lambda p: p.name.casefold(),
                )
            except (OSError, PermissionError):
                return

            for subdir in subdirs:
                try:
                    for p in subdir.glob(glob_pattern):
                        if p.is_file() or p.is_symlink():
                            yield p
                except (OSError, PermissionError, ValueError):
                    continue

        files = sorted(
            _iter_files(),
            key=lambda p: (p.parent != base_path, p.parent.name.casefold(), p.name.casefold()),
        )

        for filepath in files:
            stem = filepath.stem
            is_subdir = filepath.parent != base_path
            subdir_name = filepath.parent.name if is_subdir else ""
            relpath = f"{subdir_name}/{filepath.name}" if is_subdir else filepath.name
            variables = {
                "name": stem,
                "filename": filepath.name,
                "path": str(filepath),
                "name_pretty": stem.replace("_", " ").replace("-", " ").title(),
                "relpath": relpath,
                "subdir": subdir_name,
            }
            gen_item = self._inject_variables(template, variables)
            if isinstance(gen_item, dict):
                generated.append(gen_item)

        frozen = tuple(generated)
        self._file_generator_cache[cache_key] = frozen
        yield from frozen

    def _inject_variables(self, item: Any, vars: dict[str, str]) -> Any:
        if isinstance(item, str):
            res = item
            for k, v in vars.items():
                res = res.replace(f"{{{k}}}", v)
            return res
        if isinstance(item, list):
            return [self._inject_variables(x, vars) for x in item]
        if isinstance(item, dict):
            return {k: self._inject_variables(v, vars) for k, v in item.items()}
        return item

    def _build_item_row(
        self,
        item: ConfigItem | ConfigSection,
        ctx: RowContext,
    ) -> Gtk.ListBoxRow:
        item_type = item.get("type", "")
        props = item.get("properties", {})
        row = None

        try:
            match item_type:
                case ItemType.BUTTON:
                    row = rows.ButtonRow(props, item.get("on_press"), ctx)
                case ItemType.TOGGLE:
                    row = rows.ToggleRow(props, item.get("on_toggle"), ctx)
                case ItemType.GRID_CARD:
                    row = rows.ButtonRow(props, item.get("on_press"), ctx)
                case ItemType.TOGGLE_CARD:
                    row = rows.ToggleRow(props, item.get("on_toggle"), ctx)
                case ItemType.LABEL:
                    row = rows.LabelRow(props, item.get("value"), ctx)
                case ItemType.SLIDER:
                    row = rows.SliderRow(props, item.get("on_change"), ctx)
                case ItemType.SELECTION:
                    row = rows.SelectionRow(props, item.get("on_change"), ctx)
                case ItemType.ENTRY:
                    row = rows.EntryRow(props, item.get("on_action"), ctx)
                case ItemType.NAVIGATION:
                    row = rows.NavigationRow(props, item.get("layout"), ctx)
                case ItemType.EXPANDER:
                    row = rows.ExpanderRow(props, item.get("items"), ctx)
                case ItemType.WARNING_BANNER:
                    row = self._build_warning_banner(props)
                case ItemType.ASYNC_SELECTOR:
                    row = rows.AsyncSelectorRow(props, item.get("on_action"), ctx)
                case _:
                    log.warning("Unknown item type '%s', defaulting to button", item_type)
                    row = rows.ButtonRow(props, item.get("on_press"), ctx)

            if row is not None:
                row.set_name(self._generate_widget_id(item))
            return row

        except Exception as e:
            log.error("Failed to build row for type '%s': %s", item_type, e)
            return self._build_error_row(str(e), str(props.get("title", "Unknown")))

    def _build_warning_banner(self, props: ItemProperties) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.get_style_context().add_class("action-row")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.get_style_context().add_class("warning-banner-box")

        icon = Gtk.Image.new_from_icon_name(ICON_WARNING, Gtk.IconSize.BUTTON)
        icon.set_halign(Gtk.Align.CENTER)
        icon.set_margin_bottom(8)
        icon.add_css_class("warning-banner-icon")
        icon.set_pixel_size(44)

        title = Gtk.Label(label=str(props.get("title", "Warning")))
        title.get_style_context().add_class("title-1")
        title.set_halign(Gtk.Align.CENTER)

        message = Gtk.Label(label=str(props.get("message", "")))
        message.get_style_context().add_class("body")
        message.set_halign(Gtk.Align.CENTER)
        message.set_wrap(True)

        box.append(icon)
        box.append(title)
        box.append(message)
        row.add(box)
        return row

    def _build_error_row(self, error: str, title: str) -> DuskyActionRow:
        row = DuskyActionRow(
            title=GLib.markup_escape_text(f"⚠ {title}", -1),
            subtitle=GLib.markup_escape_text(f"Build error: {error[:80]}", -1),
        )
        row.add_css_class("error")
        row.set_activatable(False)
        return row

    # ─────────────────────────────────────────────────────────────────────────
    # STATE PAGES
    # ─────────────────────────────────────────────────────────────────────────
    def _show_error_state(self, error_message: str) -> None:
        if self._stack is None:
            return

        status = DuskyStatusPage(
            icon_name=ICON_ERROR,
            title="Configuration Error",
            description=GLib.markup_escape_text(error_message, -1),
        )
        status.get_style_context().add_class("error-state")

        hint = Gtk.Label(label="Press Ctrl+R to reload after fixing the configuration.")
        hint.get_style_context().add_class("dim-label")
        hint.set_margin_top(12)
        status.set_child(hint)

        self._stack.add_named(status, ERROR_PAGE_ID)
        self._stack.set_visible_child_name(ERROR_PAGE_ID)

    def _show_empty_state(self) -> None:
        if self._stack is None:
            return

        status = DuskyStatusPage(
            icon_name=ICON_EMPTY,
            title="No Configuration Found",
            description="The configuration file exists but contains no pages.",
        )
        status.get_style_context().add_class("empty-state")
        status.icon.get_style_context().add_class("empty-state-icon")
        status.icon.set_pixel_size(64)

        hint = Gtk.Label(label=f"Add pages to {CONFIG_FILENAME} and press Ctrl+R to reload.")
        hint.get_style_context().add_class("dim-label")
        hint.set_margin_top(12)
        status.set_child(hint)

        self._stack.add_named(status, EMPTY_PAGE_ID)
        self._stack.set_visible_child_name(EMPTY_PAGE_ID)

    # ─────────────────────────────────────────────────────────────────────────
    # UTILITIES
    # ─────────────────────────────────────────────────────────────────────────
    def _toast(self, message: str, timeout: int = DEFAULT_TOAST_TIMEOUT) -> None:
        if self._toast_overlay:
            utility.toast(self._toast_overlay, message, timeout)

# =============================================================================
# ENTRY POINT
# =============================================================================
def main() -> int:
    app = DuskyControlCenter()
    return app.run(sys.argv)

if __name__ == "__main__":
    sys.exit(main())
