#!/usr/bin/env python3

import argparse
import datetime
import http.client
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Self
from urllib.error import URLError

# Consolidated WMO weather code lookup.
WEATHER_CODES: dict[int, tuple[str, str]] = {
    0: ("", "Clear sky"),
    1: ("", "Mainly clear"),
    2: ("", "Partly cloudy"),
    3: ("", "Overcast"),
    45: ("󰖑", "Fog"),
    48: ("󰖑", "Depositing rime fog"),
    51: ("", "Light drizzle"),
    53: ("", "Moderate drizzle"),
    55: ("", "Dense drizzle"),
    56: ("", "Light freezing drizzle"),
    57: ("", "Dense freezing drizzle"),
    61: ("", "Slight rain"),
    63: ("", "Moderate rain"),
    65: ("", "Heavy rain"),
    66: ("", "Light freezing rain"),
    67: ("", "Heavy freezing rain"),
    71: ("", "Slight snow"),
    73: ("", "Moderate snow"),
    75: ("", "Heavy snow"),
    77: ("", "Snow grains"),
    80: ("", "Slight rain showers"),
    81: ("", "Moderate rain showers"),
    82: ("", "Violent rain showers"),
    85: ("", "Slight snow showers"),
    86: ("", "Heavy snow showers"),
    95: ("", "Thunderstorm"),
    96: ("", "Thunderstorm with slight hail"),
    99: ("", "Thunderstorm with heavy hail"),
}

IMPERIAL_COUNTRIES = {"US", "LR", "MM"}
STATE_FILE = Path.home() / ".config" / "dusky" / "settings" / "waybar_weather"
TIME_STATE_FILE = Path.home() / ".config" / "dusky" / "settings" / "waybar_weather_time"
IS_BACKGROUND = False

HTTP_HEADERS = {
    "User-Agent": "waybar-weather/2.0 (Arch Linux; Python 3.14)",
    "Accept": "application/json",
}

type JsonDict = dict[str, Any]
type CssClass = str | list[str]


@dataclass(slots=True, frozen=True)
class RequestKey:
    source: str
    unit_pref: str
    lat: float | None = None
    lon: float | None = None

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> Self:
        source = "manual" if args.lat is not None else "ip"
        unit_pref = "fahrenheit" if args.fahrenheit else "celsius" if args.celsius else "auto"
        return cls(source=source, unit_pref=unit_pref, lat=args.lat, lon=args.lon)

    @classmethod
    def from_json(cls, raw: object) -> Self | None:
        if not isinstance(raw, dict):
            return None

        source = raw.get("source")
        unit_pref = raw.get("unit_pref")
        lat = raw.get("lat")
        lon = raw.get("lon")

        if source not in {"manual", "ip"} or unit_pref not in {"auto", "celsius", "fahrenheit"}:
            return None

        if source == "manual":
            if not is_finite_number(lat) or not is_finite_number(lon):
                return None
            return cls(source=source, unit_pref=unit_pref, lat=float(lat), lon=float(lon))

        return cls(source=source, unit_pref=unit_pref)

    def to_json(self) -> JsonDict:
        data: JsonDict = {
            "source": self.source,
            "unit_pref": self.unit_pref,
        }
        if self.source == "manual":
            data["lat"] = self.lat
            data["lon"] = self.lon
        return data


@dataclass(slots=True)
class StateRecord:
    payload: JsonDict
    saved_at: float
    request_key: RequestKey | None = None
    effective_unit: str | None = None
    country_code: str = ""
    city: str = ""
    lat: float | None = None
    lon: float | None = None


def is_finite_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def parse_latitude(value: str) -> float:
    try:
        latitude = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Latitude must be a number.") from exc

    if not math.isfinite(latitude) or not -90.0 <= latitude <= 90.0:
        raise argparse.ArgumentTypeError("Latitude must be between -90 and 90.")
    return latitude


def parse_longitude(value: str) -> float:
    try:
        longitude = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Longitude must be a number.") from exc

    if not math.isfinite(longitude) or not -180.0 <= longitude <= 180.0:
        raise argparse.ArgumentTypeError("Longitude must be between -180 and 180.")
    return longitude


def parse_interval(value: str) -> int:
    try:
        interval = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Interval must be a positive integer.") from exc

    if interval <= 0:
        raise argparse.ArgumentTypeError("Interval must be greater than 0.")
    return interval


def json_dumps(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def normalize_country_code(value: object) -> str:
    return value.strip().upper() if isinstance(value, str) else ""


def normalize_city(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def normalize_payload(raw: object) -> JsonDict | None:
    if not isinstance(raw, dict):
        return None

    text = raw.get("text")
    tooltip = raw.get("tooltip")
    alt = raw.get("alt", "Weather")
    css_class = raw.get("class", "weather")

    if not isinstance(text, str) or not isinstance(tooltip, str):
        return None

    if not isinstance(alt, str):
        alt = "Weather"

    if isinstance(css_class, list):
        css_class = [item for item in css_class if isinstance(item, str)] or ["weather"]
    elif not isinstance(css_class, str):
        css_class = "weather"

    return {
        "text": text,
        "alt": alt,
        "tooltip": tooltip,
        "class": css_class,
    }


def emit_payload(payload: JsonDict) -> None:
    print(json_dumps(payload), flush=True)


def fail_gracefully(message: str, tooltip: str = "") -> None:
    if IS_BACKGROUND:
        current_time = time.time()
        _, last_success = load_time_state(None)
        write_time_state(current_time, last_success)
        sys.exit(0)

    emit_payload({
        "text": "󰖐 Err",
        "alt": "Error",
        "tooltip": tooltip or message,
        "class": "error",
    })
    raise SystemExit(0)


def make_offline_payload(payload: JsonDict) -> JsonDict:
    cached = dict(payload)

    css_class = cached.get("class", "weather")
    if isinstance(css_class, str):
        class_list = [css_class]
    elif isinstance(css_class, list):
        class_list = [item for item in css_class if isinstance(item, str)] or ["weather"]
    else:
        class_list = ["weather"]

    if "offline" not in class_list:
        class_list.append("offline")

    tooltip = cached.get("tooltip", "")
    if not isinstance(tooltip, str):
        tooltip = ""

    offline_note = "⚠ Offline — showing cached weather"
    if offline_note not in tooltip:
        tooltip = f"{tooltip.rstrip()}\n\n<span color='#ff6b6b'>{offline_note}</span>".lstrip()

    cached["tooltip"] = tooltip
    cached["class"] = class_list
    return cached


def emit_cached_or_fail(state: StateRecord | None, error_tooltip: str) -> None:
    if IS_BACKGROUND:
        current_time = time.time()
        _, last_success = load_time_state(state)
        write_time_state(current_time, last_success)
        sys.exit(0)

    if state is not None:
        emit_payload(make_offline_payload(state.payload))
        raise SystemExit(0)

    fail_gracefully("Network Offline", error_tooltip)


def load_time_state(state: StateRecord | None) -> tuple[float, float]:
    try:
        raw_text = TIME_STATE_FILE.read_text(encoding="utf-8")
        data = json.loads(raw_text)
        return float(data.get("last_attempt", 0.0)), float(data.get("last_success", 0.0))
    except Exception:
        if state is not None:
            return state.saved_at, state.saved_at
        return 0.0, 0.0


def write_time_state(last_attempt: float, last_success: float) -> None:
    data = {
        "last_attempt": last_attempt,
        "last_success": last_success,
    }
    temp_path: Path | None = None
    try:
        TIME_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=TIME_STATE_FILE.parent,
            delete=False,
            prefix=f".{TIME_STATE_FILE.name}.",
            suffix=".tmp",
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(json_dumps(data))
            temp_file.flush()
            os.fsync(temp_file.fileno())
        temp_path.replace(TIME_STATE_FILE)
    except OSError:
        with suppress(OSError):
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)


def spawn_background_fetch(args: argparse.Namespace) -> None:
    script_path = os.path.abspath(__file__)
    args_to_pass = [arg for arg in sys.argv[1:] if arg != "--background-fetch"]
    try:
        subprocess.Popen(
            [sys.executable, script_path, "--background-fetch"] + args_to_pass,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


def is_state_fresh(state: StateRecord, ttl_seconds: int) -> bool:
    return (time.time() - state.saved_at) < ttl_seconds


def load_state() -> StateRecord | None:
    try:
        raw_text = STATE_FILE.read_text(encoding="utf-8")
        mtime = STATE_FILE.stat().st_mtime
    except OSError:
        return None

    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError:
        return None

    # New wrapped state format.
    if isinstance(raw, dict) and raw.get("version") == 2:
        payload = normalize_payload(raw.get("payload"))
        if payload is None:
            return None

        saved_at = raw.get("saved_at")
        if not is_finite_number(saved_at):
            saved_at = mtime

        request_key = RequestKey.from_json(raw.get("request_key"))

        effective_unit = raw.get("effective_unit")
        if effective_unit not in {"metric", "imperial"}:
            effective_unit = None

        cached_lat = raw.get("lat")
        cached_lon = raw.get("lon")

        return StateRecord(
            payload=payload,
            saved_at=float(saved_at),
            request_key=request_key,
            effective_unit=effective_unit,
            country_code=normalize_country_code(raw.get("country_code")),
            city=normalize_city(raw.get("city")),
            lat=float(cached_lat) if is_finite_number(cached_lat) else None,
            lon=float(cached_lon) if is_finite_number(cached_lon) else None,
        )

    # Legacy plain payload support.
    payload = normalize_payload(raw)
    if payload is None:
        return None

    return StateRecord(payload=payload, saved_at=mtime)


def write_state(record: StateRecord) -> None:
    wrapped: JsonDict = {
        "version": 2,
        "saved_at": record.saved_at,
        "payload": record.payload,
        "request_key": record.request_key.to_json() if record.request_key else None,
        "effective_unit": record.effective_unit,
        "country_code": record.country_code,
        "city": record.city,
        "lat": record.lat,
        "lon": record.lon,
    }

    data = json_dumps(wrapped)
    temp_path: Path | None = None

    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=STATE_FILE.parent,
            delete=False,
            prefix=f".{STATE_FILE.name}.",
            suffix=".tmp",
        ) as temp_file:
            # Assign immediately before risky I/O operations
            temp_path = Path(temp_file.name)
            temp_file.write(data)
            temp_file.flush()
            os.fsync(temp_file.fileno())

        temp_path.replace(STATE_FILE)

        with suppress(OSError):
            dir_fd = os.open(STATE_FILE.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)

    except OSError:
        with suppress(OSError):
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)


def fetch_json(url: str, params: dict[str, object] | None = None, timeout: float = 5.0) -> JsonDict | None:
    if params:
        query = urllib.parse.urlencode(params)
        url = f"{url}?{query}"

    request = urllib.request.Request(url, headers=HTTP_HEADERS)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            data = json.loads(response.read())
    except (URLError, TimeoutError, OSError, http.client.HTTPException, json.JSONDecodeError, UnicodeDecodeError):
        return None

    return data if isinstance(data, dict) else None


# IP location result: (lat, lon, country_code, city, utc_offset_str, isp)
type IpLocationResult = tuple[float | None, float | None, str, str, str, str]


def extract_ipwho_location(data: JsonDict | None) -> IpLocationResult:
    if not data or data.get("success") is not True:
        return None, None, "", "", "", ""

    lat = data.get("latitude")
    lon = data.get("longitude")
    if not is_finite_number(lat) or not is_finite_number(lon):
        return None, None, "", "", "", ""

    tz = data.get("timezone", {})
    utc_offset = tz.get("utc", "") if isinstance(tz, dict) else ""

    conn = data.get("connection", {})
    isp = conn.get("isp", "") if isinstance(conn, dict) else ""

    return float(lat), float(lon), normalize_country_code(data.get("country_code")), normalize_city(data.get("city")), str(utc_offset), str(isp)


def extract_ipapi_location(data: JsonDict | None) -> IpLocationResult:
    if not data or data.get("error"):
        return None, None, "", "", "", ""

    lat = data.get("latitude")
    lon = data.get("longitude")
    if not is_finite_number(lat) or not is_finite_number(lon):
        return None, None, "", "", "", ""

    utc_offset = data.get("utc_offset", "")
    isp = data.get("org", "")

    return float(lat), float(lon), normalize_country_code(data.get("country_code")), normalize_city(data.get("city")), str(utc_offset), str(isp)


def get_ip_location() -> IpLocationResult:
    services = (
        ("https://ipwho.is/", extract_ipwho_location),
        ("https://ipapi.co/json/", extract_ipapi_location),
    )

    for url, extractor in services:
        location = extractor(fetch_json(url, timeout=5.0))
        if location[0] is not None and location[1] is not None:
            return location

    return None, None, "", "", "", ""


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def get_system_utc_offset_str() -> str:
    """Return system UTC offset as a string like '+05:30' or '-08:00'."""
    offset = datetime.datetime.now(datetime.timezone.utc).astimezone().utcoffset()
    if offset is None:
        return ""
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    total_seconds = abs(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    return f"{sign}{hours:02d}:{minutes:02d}"


def parse_utc_offset_seconds(offset_str: str) -> int | None:
    """Parse a UTC offset string like '+05:30' or '+0530' into seconds."""
    if not offset_str:
        return None
    s = offset_str.strip()
    if not s:
        return None
    sign = 1
    if s[0] in "+-":
        sign = -1 if s[0] == "-" else 1
        s = s[1:]
    # Remove colon: "05:30" -> "0530"
    s = s.replace(":", "")
    if len(s) < 3 or not s.isdigit():
        return None
    hours = int(s[:-2])
    minutes = int(s[-2:])
    return sign * (hours * 3600 + minutes * 60)


# Known datacenter / cloud / VPN provider keywords.
# These ISPs host VPN exit nodes, CDN edges, or cloud instances — not residential users.
_DATACENTER_KEYWORDS: frozenset[str] = frozenset({
    "cloudflare", "amazon", "aws", "google cloud", "microsoft", "azure",
    "digitalocean", "linode", "akamai", "ovh", "hetzner", "vultr", "oracle",
    "fastly", "mullvad", "nordvpn", "protonvpn", "proton ag", "expressvpn",
    "surfshark", "cyberghost", "private internet", "ipvanish", "windscribe",
    "hide.me", "tunnelbear", "hotspot shield", "zenmate", "kaspersky",
    "warp", "1.1.1.1",
})


def is_datacenter_isp(isp: str) -> bool:
    """Check if the ISP name matches a known datacenter / VPN provider."""
    if not isp:
        return False
    isp_lower = isp.lower()
    return any(keyword in isp_lower for keyword in _DATACENTER_KEYWORDS)


def is_vpn_likely(
    ip_lat: float,
    ip_lon: float,
    ip_utc_offset: str,
    ip_isp: str,
    cached_state: StateRecord | None,
) -> bool:
    """Detect probable VPN/proxy using three layers:

    Layer 1: Timezone mismatch — IP-reported UTC offset vs system UTC offset.
             Catches cross-timezone VPNs (e.g. US exit node while in India).
    Layer 2: Datacenter ISP + distance — IP comes from a known cloud/VPN
             provider AND location jumped >100 km from cached.
             Catches same-timezone VPNs (e.g. Cloudflare WARP routing to Delhi).
    Layer 3: Normal ISP + distance — IP comes from a regular residential ISP
             but location changed. This is NOT flagged as VPN, allowing the
             script to self-correct if a previous cache was set during VPN use.

    Returns True if the IP location is likely from a VPN exit node.
    """
    # Layer 1: Timezone mismatch.
    system_offset = parse_utc_offset_seconds(get_system_utc_offset_str())
    ip_offset = parse_utc_offset_seconds(ip_utc_offset)

    if system_offset is not None and ip_offset is not None:
        if abs(system_offset - ip_offset) > 3600:
            return True

    # Layer 2: Datacenter ISP + significant location change.
    datacenter = is_datacenter_isp(ip_isp)

    if (
        datacenter
        and cached_state is not None
        and cached_state.lat is not None
        and cached_state.lon is not None
    ):
        distance = haversine_km(cached_state.lat, cached_state.lon, ip_lat, ip_lon)
        if distance > 100:
            return True

    # Layer 3 (implicit): Normal ISP with distance change → NOT VPN.
    # This allows self-correction when VPN is turned off.
    return False


def reverse_geocode(lat: float, lon: float) -> tuple[str, str]:
    # Primary: BigDataCloud reverse geocoder.
    data = fetch_json(
        "https://api.bigdatacloud.net/data/reverse-geocode-client",
        params={
            "latitude": lat,
            "longitude": lon,
            "localityLanguage": "en",
        },
        timeout=5.0,
    )

    if data:
        country_code = normalize_country_code(data.get("countryCode"))
        city = normalize_city(data.get("city")) or normalize_city(data.get("locality"))
        if country_code:
            return country_code, city

    return "", ""


def resolve_unit(
    args: argparse.Namespace,
    country_code: str,
    matching_state: StateRecord | None,
) -> str:
    if args.fahrenheit:
        return "imperial"
    if args.celsius:
        return "metric"
        
    # If geolocation succeeded, unconditionally establish the unit by region.
    if country_code:
        return "imperial" if country_code in IMPERIAL_COUNTRIES else "metric"
        
    # Fallback only when offline or if geolocation explicitly failed.
    if matching_state and matching_state.effective_unit in {"metric", "imperial"}:
        return matching_state.effective_unit
        
    return "metric"


def as_float(value: object) -> float:
    if not is_finite_number(value):
        raise TypeError("Expected a finite number.")
    return float(value)


def as_int(value: object) -> int:
    if isinstance(value, bool):
        raise TypeError("Booleans are not valid integers.")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    raise TypeError("Expected an integer.")


def round_half_away_from_zero(value: float) -> int:
    return math.floor(value + 0.5) if value >= 0 else -math.floor(-value + 0.5)


def parse_weather_data(weather_data: JsonDict) -> tuple[int, int, int, int, int]:
    current = weather_data.get("current")
    daily = weather_data.get("daily")

    if not isinstance(current, dict) or not isinstance(daily, dict):
        raise TypeError("Missing current or daily weather data.")

    temp = round_half_away_from_zero(as_float(current.get("temperature_2m")))
    weather_code = as_int(current.get("weather_code"))

    daily_temp_max = daily.get("temperature_2m_max")
    daily_temp_min = daily.get("temperature_2m_min")
    daily_precip = daily.get("precipitation_probability_max")

    if not isinstance(daily_temp_max, list) or not daily_temp_max:
        temp_max = temp
    else:
        temp_max = round_half_away_from_zero(as_float(daily_temp_max[0]))

    if not isinstance(daily_temp_min, list) or not daily_temp_min:
        temp_min = temp
    else:
        temp_min = round_half_away_from_zero(as_float(daily_temp_min[0]))

    if not isinstance(daily_precip, list) or not daily_precip or daily_precip[0] is None:
        precip_prob = 0
    else:
        precip_prob = round_half_away_from_zero(as_float(daily_precip[0]))

    return temp, weather_code, temp_max, temp_min, precip_prob


def build_weather_payload(
    temp: int,
    weather_code: int,
    temp_max: int,
    temp_min: int,
    precip_prob: int,
    unit: str,
    city: str,
) -> JsonDict:
    icon, weather_desc = WEATHER_CODES.get(weather_code, ("", "Unknown"))
    temp_symbol = "°F" if unit == "imperial" else "°C"

    tooltip = (
        f"<span size='xx-large'>{temp}{temp_symbol}</span>\n"
        f"<big>{icon} {weather_desc}</big>\n"
        f" {temp_max}{temp_symbol}   {temp_min}{temp_symbol}   {precip_prob}%"
    )

    return {
        "text": f"{icon}   {temp}{temp_symbol}",
        "alt": city or "Weather",
        "tooltip": tooltip,
        "class": "weather",
    }


def main() -> None:
    global IS_BACKGROUND
    parser = argparse.ArgumentParser(description="Waybar weather module")
    parser.add_argument("--lat", type=parse_latitude, help="Latitude override")
    parser.add_argument("--lon", type=parse_longitude, help="Longitude override")
    parser.add_argument(
        "-i",
        "--interval",
        type=parse_interval,
        default=1800,
        help="Update interval in seconds",
    )
    parser.add_argument(
        "--background-fetch",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    unit_group = parser.add_mutually_exclusive_group()
    unit_group.add_argument("-c", "--celsius", action="store_true", help="Force Celsius")
    unit_group.add_argument("-f", "--fahrenheit", action="store_true", help="Force Fahrenheit")

    args = parser.parse_args()

    if (args.lat is None) != (args.lon is None):
        parser.error("Arguments --lat and --lon must be provided together.")

    if args.background_fetch:
        IS_BACKGROUND = True

    request_key = RequestKey.from_args(args)
    state = load_state()
    matching_state = state if state and state.request_key == request_key else None

    current_time = time.time()
    last_attempt, last_success = load_time_state(matching_state)

    if args.background_fetch:
        # Worker mode: do the actual network requests
        lat: float
        lon: float
        country_code = ""
        city = ""

        if args.lat is None:
            ip_lat, ip_lon, country_code, city, ip_utc_offset, ip_isp = get_ip_location()
            if ip_lat is None or ip_lon is None:
                emit_cached_or_fail(state, "Failed to determine location and no cached weather is available.")

            # VPN/proxy detection: prefer cached location when VPN is likely.
            if is_vpn_likely(ip_lat, ip_lon, ip_utc_offset, ip_isp, state):
                if state and state.lat is not None and state.lon is not None:
                    lat, lon = state.lat, state.lon
                    country_code = state.country_code or country_code
                    city = state.city or city
                else:
                    lat, lon = ip_lat, ip_lon
            else:
                lat, lon = ip_lat, ip_lon
        else:
            lat, lon = args.lat, args.lon
            if not args.celsius and not args.fahrenheit:
                country_code, city = reverse_geocode(lat, lon)
                if not country_code and matching_state:
                    country_code = matching_state.country_code
                    city = city or matching_state.city
            elif matching_state:
                city = matching_state.city

        unit = resolve_unit(args, country_code, matching_state)
        temp_unit = "fahrenheit" if unit == "imperial" else "celsius"

        weather_data = fetch_json(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,weather_code",
                "temperature_unit": temp_unit,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto",
                "forecast_days": 1,
            },
            timeout=10.0,
        )

        if not weather_data or weather_data.get("error"):
            reason = weather_data.get("reason") if isinstance(weather_data, dict) else None
            error_tooltip = str(reason) if reason else "Failed to fetch weather and no cached weather is available."
            emit_cached_or_fail(state, error_tooltip)

        try:
            temp, weather_code, temp_max, temp_min, precip_prob = parse_weather_data(weather_data)
        except (TypeError, ValueError, IndexError, AttributeError):
            emit_cached_or_fail(state, "Malformed response from the weather service.")

        payload = build_weather_payload(
            temp=temp,
            weather_code=weather_code,
            temp_max=temp_max,
            temp_min=temp_min,
            precip_prob=precip_prob,
            unit=unit,
            city=city,
        )

        write_state(
            StateRecord(
                payload=payload,
                saved_at=current_time,
                request_key=request_key,
                effective_unit=unit,
                country_code=country_code,
                city=city,
                lat=lat,
                lon=lon,
            )
        )
        write_time_state(current_time, current_time)
        return

    else:
        # Query mode: print cache and potentially spawn background worker
        is_fresh = matching_state and (current_time - last_success < args.interval)

        if is_fresh:
            emit_payload(matching_state.payload)
            return

        # Cache is stale or missing/unmatched
        # Trigger background fetch if we haven't attempted recently or if config changed
        config_changed = (state is not None) and (matching_state is None)
        if config_changed or (current_time - last_attempt > args.interval):
            # Optimistically write last_attempt before spawning to block multiple spawns
            write_time_state(current_time, last_success)
            spawn_background_fetch(args)

        if matching_state:
            # Emit offline/stale payload
            emit_payload(make_offline_payload(matching_state.payload))
        else:
            emit_payload({
                "text": "󰖐 Loading...",
                "alt": "Loading",
                "tooltip": "Fetching weather in background...",
                "class": "weather",
            })


if __name__ == "__main__":
    main()
