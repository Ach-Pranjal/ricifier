"""Lightweight, cached configuration generation for supported Linux ricing apps.

Documentation is collected only on demand and cached by application/version.
Generated output is rendered from allowlisted, type-checked, range-checked
fields; documentation and model output never become executable configuration
directives directly.

Every generated value carries a reason and a source:
  "model"     a design choice that came from the model's mood/aesthetic output
  "computed"  something code measured or fixed (contrast, clamping, derivation)
This is what powers the "why does this parameter have this value" feature.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable


CACHE_VERSION = 1
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "ricifier" / "docs"
_HERE = Path(__file__).resolve().parent
# Project-level output/ when this file lives in backend/, else next to the file.
DEFAULT_OUTPUT_DIR = (_HERE.parent if _HERE.name == "backend" else _HERE) / "output"

ANSI_NAMES = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]

# Each allowlisted key maps to a value kind:
#   "color"      #rrggbb or #rrggbbaa
#   "colorset"   five space-separated colors (i3 client.* lines)
#   "bool"       true/false (the strings "true"/"false" are accepted too)
#   "string"     restricted free text (font names)
#   frozenset    one of a fixed set of values
#   ("float", lo, hi) / ("int", lo, hi) / ("px", lo, hi)
#                numbers; out-of-range values are clamped and the clamp is recorded
APP_SPECS: dict[str, dict[str, Any]] = {
    "kitty": {
        "command": "kitty",
        "version_args": ("--version",),
        "help_args": ("--help",),
        "config_name": "kitty.conf",
        "format": "key-value",
        "keys": {
            "font_family": "string", "font_size": ("float", 6, 32),
            "foreground": "color", "background": "color", "cursor": "color",
            "selection_foreground": "color", "selection_background": "color",
            "background_opacity": ("float", 0.3, 1.0),
            "window_padding_width": ("float", 0, 40),
            "window_border_width": ("float", 0, 10),
            "window_border_radius": ("float", 0, 40),
            "active_border_color": "color", "inactive_border_color": "color",
            "bell_border_color": "color", "inactive_text_alpha": ("float", 0, 1),
            "cursor_shape": frozenset({"block", "beam", "underline"}),
            "tab_bar_edge": frozenset({"top", "bottom", "left", "right"}),
            "tab_bar_style": frozenset({"fade", "slant", "separator", "powerline"}),
            "tab_bar_align": frozenset({"start", "center", "end"}),
            "tab_powerline_style": frozenset({"angled", "slanted", "round"}),
            "tab_bar_show_new_tab_button": "bool",
            "tab_bar_min_tabs": ("int", 0, 50),
            "tab_bar_background": "color", "tab_bar_margin_color": "color",
            "active_tab_foreground": "color", "active_tab_background": "color",
            "inactive_tab_foreground": "color", "inactive_tab_background": "color",
            "tab_separator": "string", "scrollbar": frozenset({"scrolled", "hovered", "always", "never"}),
            "scrollbar_handle_color": "color", "scrollbar_track_color": "color",
            "scrollbar_handle_opacity": ("float", 0, 1),
        },
    },
    "i3": {
        "command": "i3",
        "version_args": ("--version",),
        "help_args": ("--help",),
        "config_name": "config",
        "format": "i3",
        "keys": {
            "font": "string",
            "gaps_inner": ("int", 0, 60), "gaps_outer": ("int", 0, 60),
            "border_width": ("int", 0, 8),
            "client_focused": "colorset", "client_unfocused": "colorset",
            "client_focused_inactive": "colorset", "client_urgent": "colorset",
            "title_align": frozenset({"left", "center", "right"}),
            "titlebar_border_thickness": ("int", 0, 8),
        },
    },
    "polybar": {
        "command": "polybar",
        "version_args": ("--version",),
        "help_args": ("--help",),
        "config_name": "config.ini",
        "format": "ini",
        "keys": {
            "font_0": "string", "font_1": "string",
            "background": "color", "foreground": "color", "accent": "color",
            "tray_background": "color", "tray_foreground": "color",
            "height": ("int", 16, 64),
            "offset_x": ("int", 0, 100), "offset_y": ("int", 0, 100),
            "radius": ("float", 0, 20),
            "modules_left": "string", "modules_right": "string",
            "modules_center": "string",
            "tray_position": frozenset({"left", "right", "none"}),
            "module_margin": ("int", 0, 20),
            "separator": "string",
        },
    },
    "rofi": {
        "command": "rofi",
        "version_args": ("-version",),
        "help_args": ("-help",),
        "config_name": "config.rasi",
        "format": "rasi",
        "keys": {
            "font": "string", "background": "color", "foreground": "color",
            "selected": "color", "selected_text": "color", "border": "color",
            "border_radius": ("px", 0, 30), "border_width": ("px", 0, 8),
            "spacing": ("px", 0, 40), "padding": ("px", 0, 40),
            "selected_active": "color", "urgent": "color",
            "placeholder": "color", "children": "color",
        },
    },
    "picom": {
        "command": "picom",
        "version_args": ("--version",),
        "help_args": ("--help",),
        "config_name": "picom.conf",
        "format": "picom",
        "keys": {
            "backend": frozenset({"xrender", "glx", "egl"}),
            "vsync": "bool", "shadow": "bool",
            "shadow-radius": ("int", 0, 40), "shadow-opacity": ("float", 0, 1),
            "inactive-opacity": ("float", 0.3, 1.0),
            "active-opacity": ("float", 0.3, 1.0),
            "corner-radius": ("int", 0, 30),
            "blur-method": frozenset(
                {"none", "box", "gaussian", "kernel", "dual_kawase"}
            ),
            "blur-strength": ("int", 0, 20),
            "fade": "bool", "fade-delta": ("int", 1, 100),
            "inactive-dim": ("float", 0, 1),
        },
    },
}
# The 16 terminal colors are what make ls, git and editors look themed.
APP_SPECS["kitty"]["keys"].update({f"color{i}": "color" for i in range(16)})

# These patterns are checked even though renderers only emit allowlisted keys.
# They protect the final boundary if a future renderer accepts richer input.
BLOCKED_CONFIG_PATTERNS = (
    re.compile(r"(?im)^\s*(exec|exec_always|exec-once|run|shell|script)\b"),
    re.compile(r"(?im)\b(bind(sym|code)?|click-(left|right|middle)|scroll-(up|down))\b.*\b(exec|run|sh|bash|zsh|python|perl)\b"),
    re.compile(r"(?im)\b(allow_remote_control|remote_control_password|listen_on|socket_path)\b"),
    re.compile(r"(?im)^\s*(include|@import|source|load)\b"),
    re.compile(r"(?im)\b(curl|wget|nc|netcat|ssh|socat|powershell|cmd\.exe)\b"),
    # \b before the group: ordinary words that merely end in "sh" must not match.
    re.compile(r"(?im)([;&|`]|\$\(|\$\{).*\b(sh|bash|zsh|python|perl|ruby|curl|wget)\b"),
)

HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?")
SAFE_TEXT = re.compile(r"[\w .,:=;+@\-]+")


class UnsafeConfigError(ValueError):
    """Raised when generated configuration contains a dangerous directive."""


# ---------------------------------------------------------------------------
# Detection and documentation
# ---------------------------------------------------------------------------

def _run_text(command: list[str], timeout: float = 3) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (result.stdout + "\n" + result.stderr).strip()


def detect_apps() -> dict[str, dict[str, Any]]:
    """Detect supported applications without reading documentation."""
    detected = {}
    for name, spec in APP_SPECS.items():
        executable = shutil.which(spec["command"])
        if not executable:
            continue
        version = _run_text([executable, *spec["version_args"]]).splitlines()
        detected[name] = {
            "command": executable,
            "version": version[0].strip() if version else "unknown",
            "config_name": spec["config_name"],
            "format": spec["format"],
        }
    return detected


def _cache_path(name: str, version: str, cache_dir: Path) -> Path:
    key = hashlib.sha256(f"{name}:{version}".encode()).hexdigest()[:16]
    return cache_dir / f"{name}-{key}.json"


def collect_documentation(
    name: str,
    *,
    version: str | None = None,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    refresh: bool = False,
) -> dict[str, Any]:
    """Collect compact local help evidence once and cache it by app version.

    The returned schema is still allowlisted by APP_SPECS. Documentation is
    evidence for the detected version (for example, to ground explanations of
    why a value was chosen), never executable input.
    """
    if name not in APP_SPECS:
        raise ValueError(f"Unsupported application: {name}")
    spec = APP_SPECS[name]
    executable = shutil.which(spec["command"])
    if not executable:
        raise FileNotFoundError(f"{spec['command']} is not installed")
    detected_version = version or (
        _run_text([executable, *spec["version_args"]]).splitlines() or ["unknown"]
    )[0]
    path = _cache_path(name, detected_version, cache_dir)
    if path.exists() and not refresh:
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("cache_version") == CACHE_VERSION:
                return cached
        except (OSError, json.JSONDecodeError):
            pass  # corrupt or stale cache: rebuild below

    help_text = _run_text([executable, *spec["help_args"]], timeout=3)
    man_text = _run_text(["man", "-P", "cat", name], timeout=5) if shutil.which("man") else ""
    payload = {
        "cache_version": CACHE_VERSION,
        "application": name,
        "version": detected_version,
        "documentation_sources": {
            "help": bool(help_text),
            "man": bool(man_text),
        },
        "help_excerpt": help_text[:12000],
        "man_excerpt": man_text[:12000],
        "safe_keys": sorted(spec["keys"]),
        "format": spec["format"],
    }
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


# ---------------------------------------------------------------------------
# Colors and contrast (kept here so the module is standalone)
# ---------------------------------------------------------------------------

def _hex6(color: str) -> str:
    """Normalize #rrggbb or #rrggbbaa to lowercase #rrggbb."""
    return str(color).strip()[:7].lower()


def _rgb(color: str) -> tuple[int, int, int]:
    c = _hex6(color)
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def _to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def luminance(color: str) -> float:
    def f(c: int) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(color)
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def mix(color: str, target: tuple[int, int, int], amount: float) -> str:
    return _to_hex(tuple(round(a + (t - a) * amount) for a, t in zip(_rgb(color), target)))


def ensure_contrast(fg: str, bg: str, minimum: float = 4.5) -> str:
    """Nudge fg toward white or black until it reaches the contrast minimum."""
    fg, bg = _hex6(fg), _hex6(bg)
    if contrast(fg, bg) >= minimum:
        return fg
    target = (255, 255, 255) if luminance(bg) < 0.5 else (0, 0, 0)
    new = fg
    for _ in range(20):
        new = mix(new, target, 0.1)
        if contrast(new, bg) >= minimum:
            return new
    return max(("#000000", "#ffffff"), key=lambda c: contrast(c, bg))


# ---------------------------------------------------------------------------
# Value checking
# ---------------------------------------------------------------------------

def validate_config(name: str, text: str) -> None:
    """Reject executable, remote-control, include, and network directives."""
    if name not in APP_SPECS:
        raise ValueError(f"Unsupported application: {name}")
    for pattern in BLOCKED_CONFIG_PATTERNS:
        match = pattern.search(text)
        if match:
            raise UnsafeConfigError(
                f"Blocked unsafe {name} configuration near: {match.group(0).strip()!r}"
            )


def _clean_value(value: Any) -> str:
    value = str(value).strip()
    if any(char in value for char in "\x00\r\n"):
        raise UnsafeConfigError("Control characters are not allowed in configuration values")
    if re.search(
        r"(?i)\b(exec|exec_always|exec-once|shell|script|curl|wget|ssh|bash|sh|python|perl)\b",
        value,
    ):
        raise UnsafeConfigError("Executable or network commands are not allowed in values")
    return value


def _n(value: Any, default: float) -> float:
    """Lenient number read for model output: accepts 10, "10", "10px"; else default."""
    if isinstance(value, bool):
        return default
    try:
        if isinstance(value, str):
            value = value.strip().lower().removesuffix("px")
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def as_bool(value: Any, default: bool = False) -> bool:
    """Read a boolean from model output. Note bool("false") would be True."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "yes", "on", "1"):
            return True
        if text in ("false", "no", "off", "0"):
            return False
    return default


def _number(
    key: str, value: Any, lo: float | None = None, hi: float | None = None,
    *, whole: bool = False, notes: list[str] | None = None,
) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{key}: expected a number, got a boolean")
    if isinstance(value, str):
        value = value.strip().lower().removesuffix("px")
    number = float(value)  # raises ValueError on junk
    if not math.isfinite(number):
        raise ValueError(f"{key}: number must be finite")
    if whole:
        number = float(round(number))
    if lo is not None and hi is not None and not lo <= number <= hi:
        clamped = max(lo, min(hi, number))
        if notes is not None:
            notes.append(f"{key}: {number:g} was outside {lo:g} to {hi:g}, clamped to {clamped:g}")
        number = clamped
    return number


def _format_value(key: str, kind: Any, value: Any, notes: list[str] | None = None) -> str:
    """Type-check and range-check one value, formatted the way config files expect."""
    lo = hi = None
    if isinstance(kind, tuple):
        kind, lo, hi = kind
    if isinstance(kind, frozenset):
        text = str(value).strip()
        if text not in kind:
            raise ValueError(f"{key}: expected one of {sorted(kind)}, got {text!r}")
        return text
    if kind == "bool":
        if isinstance(value, bool) or (
            isinstance(value, str) and value.strip().lower() in ("true", "false")
        ):
            return "true" if as_bool(value) else "false"
        raise ValueError(f"{key}: expected true/false")
    if kind in ("int", "px"):
        number = _number(key, value, lo, hi, whole=True, notes=notes)
        return f"{int(number)}px" if kind == "px" else str(int(number))
    if kind == "float":
        return f"{_number(key, value, lo, hi, notes=notes):g}"
    if kind == "color":
        text = str(value).strip()
        if not HEX_COLOR.fullmatch(text):
            raise UnsafeConfigError(f"{key}: expected #rrggbb color, got {text!r}")
        return text
    if kind == "colorset":
        parts = str(value).split()
        if len(parts) != 5 or not all(HEX_COLOR.fullmatch(p) for p in parts):
            raise UnsafeConfigError(f"{key}: expected five #rrggbb colors")
        return " ".join(parts)
    if kind == "string":
        text = _clean_value(value)
        if not SAFE_TEXT.fullmatch(text):
            raise UnsafeConfigError(f"{key}: contains characters that are not allowed")
        return text
    raise ValueError(f"{key}: unknown value kind {kind!r}")


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def installed_fonts() -> frozenset[str]:
    """Lowercased family names known to fontconfig (empty if fc-list is missing)."""
    out = _run_text(["fc-list", ":", "family"], timeout=5)
    names = set()
    for line in out.splitlines():
        for part in line.split(","):
            if part.strip():
                names.add(part.strip().lower())
    return frozenset(names)


def pick_font(wanted: str, fallback: str = "monospace") -> tuple[str, str | None]:
    """Return (font, note). Falls back only when fontconfig is available and lacks the font."""
    fonts = installed_fonts()
    if not fonts or wanted.lower() in fonts:
        return wanted, None
    return fallback, f"font '{wanted}' is not installed, using '{fallback}'"


# ---------------------------------------------------------------------------
# Per-app renderers. Each takes already-validated, already-formatted values.
# NOTE: in comments, avoid a ';' followed by words ending in "sh" on the same
# line, since the final validate_config() pass could flag them.
# ---------------------------------------------------------------------------

def _render_kitty(v: dict[str, str], keys: dict[str, Any]) -> str:
    lines = ["# Generated by ricifier. Review before using."]
    lines += [f"{key} {value}" for key, value in v.items()]
    return "\n".join(lines)


_I3_MAP = {
    "font": "font {}",
    "gaps_inner": "gaps inner {}",
    "gaps_outer": "gaps outer {}",
    "border_width": "default_border pixel {}\ndefault_floating_border pixel {}",
    "client_focused": "client.focused {}",
    "client_unfocused": "client.unfocused {}",
    "client_focused_inactive": "client.focused_inactive {}",
    "client_urgent": "client.urgent {}",
}


def _render_i3(v: dict[str, str], keys: dict[str, Any]) -> str:
    lines = [
        "# Appearance settings generated by ricifier.",
        "# This is a snippet, not a full config. Merge it into your i3 config.",
        "# gaps need i3 4.22 or newer (or i3-gaps).",
    ]
    for key, value in v.items():
        if key in _I3_MAP:
            lines.append(_I3_MAP[key].format(value, value))
        elif key == "title_align":
            lines.append(f"title_align {value}")
        elif key == "titlebar_border_thickness":
            lines.append(f"titlebar_border_thickness {value}")
    return "\n".join(lines)


def _render_polybar(v: dict[str, str], keys: dict[str, Any]) -> str:
    out = [
        "# Generated by ricifier. Review before using.",
        "# Built-in modules are intentionally static and do not execute shell commands.",
        "[colors]",
    ]
    out += [f"{k} = {v[k]}" for k in
            ("background", "foreground", "accent", "tray_background", "tray_foreground")
            if k in v]
    out += ["", "[bar/main]", "width = 100%"]
    for src, dst in (("height", "height"), ("radius", "radius"),
                     ("offset_x", "offset-x"), ("offset_y", "offset-y")):
        if src in v:
            out.append(f"{dst} = {v[src]}")
    if "background" in v:
        out.append("background = ${colors.background}")
    if "foreground" in v:
        out.append("foreground = ${colors.foreground}")
    for src, dst in (("font_0", "font-0"), ("font_1", "font-1")):
        if src in v:
            out.append(f"{dst} = {v[src]}")
    for src, dst in (("modules_left", "modules-left"), ("modules_right", "modules-right"),
                     ("modules_center", "modules-center"), ("tray_position", "tray-position"),
                     ("module_margin", "module-margin"), ("separator", "module-separator")):
        if src in v:
            out.append(f"{dst} = {v[src]}")
    if "tray_position" in v and v["tray_position"] != "none":
        out += [
            "tray-padding = 2",
            "tray-detached = false",
            "tray-maxsize = 16",
            "tray-background = ${colors.background}",
        ]
    out += [
        "",
        "[module/i3]",
        "type = internal/i3",
        "format = <label-state> <label-mode>",
        "label = %name%",
        "label-focused = %name%",
        "label-focused-foreground = ${colors.accent}",
        "label-unfocused = %name%",
        "label-unfocused-foreground = ${colors.foreground}",
        "label-visible = %name%",
        "label-visible-foreground = ${colors.foreground}",
        "label-urgent = %name%",
        "label-urgent-foreground = ${colors.accent}",
        "label-mode = %mode%",
        "label-mode-foreground = ${colors.accent}",
        "",
        "[module/cpu]",
        "type = internal/cpu",
        "interval = 2",
        "format-prefix = CPU ",
        "format-prefix-foreground = ${colors.accent}",
        "label = %percentage:2%%",
        "",
        "[module/memory]",
        "type = internal/memory",
        "interval = 2",
        "format-prefix = RAM ",
        "format-prefix-foreground = ${colors.accent}",
        "label = %percentage_used:2%%",
        "",
        "[module/date]",
        "type = internal/date",
        "interval = 5",
        "date = %a %H:%M",
        "label = %date%",
        "label-foreground = ${colors.foreground}",
        "",
        "[module/pulseaudio]",
        "type = internal/pulseaudio",
        "use-ui-max = true",
        "interval = 2",
        "format-volume-prefix = VOL ",
        "format-volume-prefix-foreground = ${colors.accent}",
        "label-volume = %percentage:2%%",
        "label-muted = muted",
        "label-muted-foreground = ${colors.accent}",
        "",
        "[module/filesystem]",
        "type = internal/fs",
        "mount-0 = /",
        "interval = 30",
        "format-mounted-prefix = DISK ",
        "format-mounted-prefix-foreground = ${colors.accent}",
        "label-mounted = %percentage_used:2%%",
    ]
    return "\n".join(out)


def _block(selector: str, props: list[tuple[str, str | None]]) -> list[str]:
    props = [(k, x) for k, x in props if x is not None]
    if not props:
        return []
    return [selector + " {", *[f"  {k}: {x};" for k, x in props], "}", ""]


def _render_rasi(v: dict[str, str], keys: dict[str, Any]) -> str:
    out: list[str] = ["// Generated by ricifier. Review before using.", ""]
    if "font" in v:
        out += ["configuration {", f'  font: "{v["font"]}";', "}", ""]
    variables = [("bg", v.get("background")), ("fg", v.get("foreground")),
                 ("selected", v.get("selected")), ("accent", v.get("border")),
                 ("seltext", v.get("selected_text")), ("selected-active", v.get("selected_active")),
                 ("urgent", v.get("urgent")), ("placeholder", v.get("placeholder")),
                 ("children", v.get("children"))]
    out += _block("*", variables)
    out += _block("window", [
        ("background-color", "@bg" if "background" in v else None),
        ("border", v.get("border_width")),
        ("border-color", "@accent" if "border" in v else None),
        ("border-radius", v.get("border_radius")),
        ("padding", v.get("padding")),
    ])
    out += _block("mainbox", [
        ("background-color", "@bg" if "background" in v else None),
        ("spacing", v.get("spacing")),
        ("padding", "0"),
    ])
    out += _block("inputbar", [
        ("background-color", "@bg" if "background" in v else None),
        ("text-color", "@fg" if "foreground" in v else None),
        ("spacing", v.get("spacing")),
        ("padding", "0"),
    ])
    out += _block("listview", [
        ("background-color", "@bg" if "background" in v else None),
        ("spacing", v.get("spacing")),
        ("padding", "0"),
        ("columns", "1"),
        ("lines", "8"),
    ])
    fg = "@fg" if "foreground" in v else None
    out += _block("element", [
        ("text-color", fg),
        ("background-color", "@bg" if "background" in v else None),
        ("padding", v.get("padding")),
        ("border-radius", v.get("border_radius")),
    ])
    selected_text = "@seltext" if "selected_text" in v else ("@bg" if "background" in v else None)
    out += _block("element selected.normal", [
        ("background-color", "@selected" if "selected" in v else None),
        ("text-color", selected_text),
        ("border-radius", v.get("border_radius")),
    ])
    out += _block("element selected.active", [
        ("background-color", "@selected-active" if "selected_active" in v else "@selected"),
        ("text-color", selected_text),
        ("border-radius", v.get("border_radius")),
    ])
    out += _block("element urgent", [
        ("background-color", "@urgent" if "urgent" in v else None),
        ("text-color", selected_text),
    ])
    out += _block("entry", [("text-color", fg)])
    out += _block("prompt", [("text-color", "@accent" if "border" in v else None)])
    return "\n".join(out).rstrip()


def _render_picom(v: dict[str, str], keys: dict[str, Any]) -> str:
    lines = ["# Generated by ricifier. Appearance options only, merge into your picom.conf."]
    for key, value in v.items():
        if isinstance(keys[key], frozenset):
            value = f'"{value}"'
        lines.append(f"{key} = {value};")
    return "\n".join(lines)


RENDERERS: dict[str, Callable[[dict[str, str], dict[str, Any]], str]] = {
    "kitty": _render_kitty,
    "i3": _render_i3,
    "polybar": _render_polybar,
    "rofi": _render_rasi,
    "picom": _render_picom,
}


def render_config(name: str, settings: dict[str, Any], notes: list[str] | None = None) -> str:
    """Render only known safe settings, then validate the complete output.

    settings maps key -> raw value. Out-of-range numbers are clamped and each
    clamp is appended to `notes` when a list is supplied.
    """
    if name not in APP_SPECS:
        raise ValueError(f"Unsupported application: {name}")
    keys = APP_SPECS[name]["keys"]
    unknown = set(settings) - set(keys)
    if unknown:
        raise ValueError(f"Unsupported {name} settings: {', '.join(sorted(unknown))}")

    values = {key: _format_value(key, keys[key], settings[key], notes) for key in settings}
    text = RENDERERS[name](values, keys)
    validate_config(name, text)
    return text + "\n"


def write_configs(
    configs: dict[str, dict[str, Any]],
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> list[Path]:
    """Write validated config text to <output_dir>/<app>/<config_name>.

    Nothing is written outside output_dir, and nothing touches ~/.config.
    Returns the list of files written.
    """
    written = []
    for name, config in configs.items():
        if name not in APP_SPECS:
            raise ValueError(f"Unsupported application: {name}")
        validate_config(name, config["text"])  # re-check hand-built dicts
        target_dir = output_dir / name
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / APP_SPECS[name]["config_name"]
        target.write_text(config["text"], encoding="utf-8")
        written.append(target)
    return written


# ---------------------------------------------------------------------------
# Theme -> per-app settings
# ---------------------------------------------------------------------------

def _theme_color(theme: dict[str, Any], name: str) -> str:
    try:
        value = theme[name]["color"]
    except (KeyError, TypeError):
        raise ValueError(f"theme is missing {name}.color") from None
    if not HEX_COLOR.fullmatch(str(value).strip()):
        raise ValueError(f"theme {name}.color is not a #rrggbb color: {value!r}")
    return _hex6(value)


def _ansi_colors(theme: dict[str, Any]) -> list[tuple[str, bool]] | None:
    """16 (color, derived) pairs from theme['ansi'], or None if absent or invalid.

    Accepts a list of 16 colors, or a dict with the 8 ANSI names (the bright
    variants are then derived by code and marked as derived).
    """
    raw = theme.get("ansi")
    ok = lambda c: isinstance(c, str) and HEX_COLOR.fullmatch(c.strip())
    if isinstance(raw, (list, tuple)) and len(raw) == 16 and all(ok(c) for c in raw):
        return [(_hex6(c), False) for c in raw]
    if isinstance(raw, dict) and all(ok(raw.get(n)) for n in ANSI_NAMES):
        normal = [_hex6(raw[n]) for n in ANSI_NAMES]
        bright = [mix(c, (255, 255, 255), 0.25) for c in normal]
        return [(c, False) for c in normal] + [(c, True) for c in bright]
    return None


def generate_configs(
    theme: dict[str, Any],
    aesthetic: dict[str, Any],
    *,
    mood: dict[str, Any] | None = None,
    apps: dict[str, dict[str, Any]] | None = None,
    errors: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Generate safe configs for detected apps from a generic rice design.

    A failure in one app is recorded in `errors` (if given) and never stops the
    others. Each returned config includes `reasons` (key -> reason and source)
    and `notes` (clamps, font fallbacks).

    ``mood`` is passed separately from the aesthetic because it is generated by
    an earlier model step. For CLI callers, an older ``aesthetic["mood"]`` value
    remains accepted for compatibility.
    """
    detected = apps if apps is not None else detect_apps()
    typography = aesthetic.get("typography", {})
    geometry = aesthetic.get("geometry", {})
    effects = aesthetic.get("effects", {})
    hierarchy = aesthetic.get("visual_hierarchy", {})
    mood = mood or aesthetic.get("mood") or {}
    given_reasons = aesthetic.get("reasons", {}) or {}
    mood_mode = mood.get("mode") if isinstance(mood, dict) else None
    warmth = _n(mood.get("warmth"), 0) if isinstance(mood, dict) else 0
    mood_contrast = _n(mood.get("contrast"), 3) if isinstance(mood, dict) else 3
    style_label = aesthetic.get("visual_style", {}).get("label", "minimal")
    panel_style = geometry.get("panel_style", "bordered")
    soft_style = style_label in ("soft", "glass") or panel_style in ("floating", "transparent")
    harsh_style = style_label in ("cyberpunk", "brutalist", "retro") or mood_contrast >= 4
    suffix = (
        f" (mood: {mood.get('style', mood_mode or 'unspecified')})"
        if isinstance(mood, dict) and mood else ""
    )

    def S(group: str, default: str, value: Any, source: str = "model") -> dict[str, Any]:
        reason = given_reasons.get(group) or (default + suffix)
        return {"value": value, "reason": reason, "source": source}

    background = _theme_color(theme, "background")
    foreground_raw = _theme_color(theme, "foreground")
    accent = _theme_color(theme, "accent")
    inactive = _hex6(hierarchy.get("inactive_border", background))
    if not HEX_COLOR.fullmatch(inactive):
        inactive = background

    shared_notes: list[str] = []
    requested_font = str(typography.get("family", "monospace"))
    font, font_note = pick_font(requested_font)
    if font_note:
        shared_notes.append(font_note)
    size = min(32.0, max(6.0, _n(typography.get("size"), 12)))
    size_text = f"{size:g}"
    padding = _n(geometry.get("padding"), 8)
    gaps_inner = _n(geometry.get("gaps_inner"), 8)
    gaps_outer = _n(geometry.get("gaps_outer"), 8)
    border_width = _n(geometry.get("border_width"), 1)
    radius = _n(geometry.get("corner_radius"), 8)
    opacity = _n(effects.get("opacity"), 0.95)
    shadows = as_bool(effects.get("shadows"), False)
    blur = as_bool(effects.get("blur"), False)
    blur_radius = _n(effects.get("blur_radius"), 0)

    # Keep the model's aesthetic as the starting point, then apply consistent
    # mood/style adjustments across applications that expose similar concepts.
    if soft_style:
        gaps_inner = max(gaps_inner, 8)
        gaps_outer = max(gaps_outer, 6)
        radius = max(radius, 8)
        shadows = True
    if harsh_style:
        gaps_inner = min(gaps_inner, 8)
        gaps_outer = min(gaps_outer, 8)
        radius = min(radius, 4)
        opacity = max(opacity, 0.95)
    if mood_mode == "light":
        opacity = max(opacity, 0.9)
    elif mood_mode == "dark":
        opacity = min(opacity, 0.98)
    if blur:
        blur_radius = max(blur_radius, 4)
    active_border = _hex6(hierarchy.get("active_border", accent))
    highlight = _hex6(hierarchy.get("highlight", accent))
    if not HEX_COLOR.fullmatch(active_border):
        active_border = accent
    if not HEX_COLOR.fullmatch(highlight):
        highlight = accent
    if active_border == inactive and active_border != accent:
        active_border = accent
    if highlight == inactive and highlight != accent:
        highlight = accent
    font_1 = f"{font}:size={size_text};2"

    def checked_text(raw: str, backdrop: str, what: str) -> dict[str, Any]:
        """Text color setting with a measured contrast, fixed if it is too low."""
        fixed = ensure_contrast(raw, backdrop)
        if fixed != _hex6(raw):
            reason = (f"{what}: {raw} had only {contrast(raw, backdrop):.1f}:1 contrast, "
                      f"adjusted to {contrast(fixed, backdrop):.1f}:1 (minimum 4.5:1)")
            return {"value": fixed, "reason": reason, "source": "computed"}
        return S("colors", f"{what}, contrast {contrast(fixed, backdrop):.1f}:1 (passes 4.5:1)", fixed)

    foreground_s = checked_text(foreground_raw, background, "Text color on the background")
    foreground = foreground_s["value"]
    on_accent_s = checked_text(background, accent, "Text color on accent areas")
    on_accent = on_accent_s["value"]
    on_inactive_s = checked_text(foreground, inactive, "Text color on inactive areas")
    on_inactive = on_inactive_s["value"]
    focused_source = "computed" if on_accent_s["source"] == "computed" else "model"
    unfocused_source = "computed" if on_inactive_s["source"] == "computed" else "model"

    kitty: dict[str, dict[str, Any]] = {
        "font_family": S("typography", "Monospace font for the terminal", font),
        "font_size": S("typography", "Comfortable reading size", size_text),
        "foreground": foreground_s,
        "background": S("colors", "Terminal background color", background),
        "cursor": S("colors", "Cursor uses the accent color so it is easy to find", accent),
        "background_opacity": S("effects", "Window transparency", opacity),
        "window_padding_width": S("geometry", "Space between the text and the window edge", padding),
        "window_border_width": S("geometry", "Terminal window border thickness", border_width),
        "window_border_radius": S("geometry", "Terminal window corner radius", radius),
        "active_border_color": S("colors", "Active terminal border", active_border),
        "inactive_border_color": S("colors", "Inactive terminal border", inactive),
        "bell_border_color": S("colors", "Bell notification border", highlight),
        "inactive_text_alpha": S("effects", "Inactive terminal text opacity", max(0.55, opacity - 0.2)),
        "cursor_shape": S("visual_hierarchy", "Cursor shape remains visible in the terminal", "beam"),
        "tab_bar_edge": S("visual_hierarchy", "Tab bar position", "bottom"),
        "tab_bar_style": S(
            "visual_hierarchy", "Tab bar style follows the visual language",
            "powerline" if style_label in ("cyberpunk", "retro", "brutalist") else "slant"),
        "tab_bar_align": S("visual_hierarchy", "Tab alignment", "start"),
        "tab_powerline_style": S("visual_hierarchy", "Powerline tab separator style", "angled"),
        "tab_bar_show_new_tab_button": S("visual_hierarchy", "Keep the new-tab control available", True),
        "tab_bar_min_tabs": S("visual_hierarchy", "Show tabs when multiple tabs exist", 1),
        "tab_bar_background": S("colors", "Tab bar background", background),
        "tab_bar_margin_color": S("colors", "Tab bar margin color", background),
        "active_tab_foreground": S("colors", "Active tab text", on_accent),
        "active_tab_background": S("colors", "Active tab background", active_border),
        "inactive_tab_foreground": S("colors", "Inactive tab text", foreground),
        "inactive_tab_background": S("colors", "Inactive tab background", inactive),
        "tab_separator": S("visual_hierarchy", "Tab separator", " - "),
        "scrollbar": S("visual_hierarchy", "Scrollbar visibility", "scrolled"),
        "scrollbar_handle_color": S("colors", "Scrollbar handle", highlight),
        "scrollbar_track_color": S("colors", "Scrollbar track", inactive),
        "scrollbar_handle_opacity": S("effects", "Scrollbar handle opacity", min(1.0, opacity)),
    }
    ansi = _ansi_colors(theme)
    if ansi:
        for i, (color, derived) in enumerate(ansi):
            name = ANSI_NAMES[i % 8]
            if derived:
                kitty[f"color{i}"] = {
                    "value": color, "source": "computed",
                    "reason": f"Bright {name}: color{i - 8} mixed 25% toward white"}
            elif i not in (0, 7):
                fixed = ensure_contrast(color, background, 3.0)
                if fixed != color:
                    kitty[f"color{i}"] = {
                        "value": fixed, "source": "computed",
                        "reason": (f"ANSI {name}: {color} had {contrast(color, background):.1f}:1 "
                                   f"contrast, adjusted to {contrast(fixed, background):.1f}:1 "
                                   f"(minimum 3:1 for terminal colors)")}
                else:
                    kitty[f"color{i}"] = S("colors", f"ANSI {name}, tinted to the theme", color)
            else:
                kitty[f"color{i}"] = S("colors", f"ANSI {name}, tinted to the theme", color)

    settings_by_app: dict[str, dict[str, dict[str, Any]]] = {
        "kitty": kitty,
        "i3": {
            "font": S("typography", "Font for window titles", f"pango:{font} {size_text}"),
            "gaps_inner": S("geometry", "Space between windows", gaps_inner),
            "gaps_outer": S("geometry", "Space between windows and screen edge", gaps_outer),
            "border_width": S("geometry", "Window border thickness", border_width),
            # border  background  text  indicator  child_border
            "client_focused": {
                "value": f"{active_border} {active_border} {on_accent} {active_border} {active_border}",
                "reason": f"Focused window uses the active hierarchy border. {on_accent_s['reason']}",
                "source": focused_source},
            "client_unfocused": {
                "value": f"{inactive} {inactive} {on_inactive} {inactive} {inactive}",
                "reason": f"Unfocused windows use a quieter color. {on_inactive_s['reason']}",
                "source": unfocused_source},
            "client_focused_inactive": {
                "value": f"{highlight} {highlight} {on_accent} {highlight} {highlight}",
                "reason": "Inactive focused windows use the hierarchy highlight color.",
                "source": "model"},
            "title_align": S("visual_hierarchy", "Window title alignment", "center"),
            "titlebar_border_thickness": S("geometry", "Title bar border thickness", border_width),
        },
        "polybar": {
            "font_0": S("typography", "Bar font", f"{font}:size={size_text};2"),
            "font_1": S("typography", "Secondary bar font", font_1),
            "background": S("colors", "Bar background matches the theme", background),
            "foreground": foreground_s,
            "accent": S("colors", "Accent color for highlights", highlight),
            "height": S("geometry", "Bar height scales with the padding", padding + 24),
            "radius": S("geometry", "Bar corner rounding", radius),
            "modules_left": S("visual_hierarchy", "Left bar modules", "i3"),
            "modules_center": S("visual_hierarchy", "Center bar modules", "cpu memory"),
            "modules_right": S(
                "visual_hierarchy", "Right bar modules",
                "filesystem pulseaudio date"),
            "tray_position": S("visual_hierarchy", "System tray position", "right"),
            "module_margin": S("geometry", "Spacing between bar modules", max(2, int(gaps_inner))),
            "separator": S("visual_hierarchy", "Separator between bar modules", "-"),
            "tray_background": S("colors", "System tray background", background),
            "tray_foreground": S("colors", "System tray foreground", foreground),
        },
        "rofi": {
            "font": S("typography", "Launcher font", f"{font} {size_text}"),
            "background": S("colors", "Launcher background", background),
            "foreground": foreground_s,
            "selected": S("colors", "Selected row uses the hierarchy highlight color", highlight),
            "selected_text": on_accent_s,
            "border": S("colors", "Border uses the active hierarchy color", active_border),
            "border_radius": S("geometry", "Corner rounding", radius),
            "border_width": S("geometry", "Border thickness", max(border_width, 1)),
            "spacing": S("geometry", "Space between list items", gaps_inner),
            "padding": S("geometry", "Inner padding", padding),
            "selected_active": S("colors", "Active selected row", active_border),
            "urgent": S("colors", "Urgent row", highlight),
            "placeholder": S("colors", "Placeholder text", inactive),
            "children": S("colors", "Nested element text", foreground),
        },
        "picom": {
            "backend": S("effects", "GLX backend for smooth rendering", "glx"),
            "vsync": S("effects", "Avoid screen tearing", True),
            "shadow": S("effects", "Window shadows follow the style", shadows),
            "shadow-radius": S("effects", "Soft shadow spread", max(8, blur_radius or 12)),
            "shadow-opacity": S(
                "effects",
                "Subtle shadow strength follows the generated mood warmth",
                0.35 if soft_style and warmth >= 0 else 0.2),
            "inactive-opacity": S("effects", "Dim unfocused windows slightly", opacity),
            "active-opacity": S("effects", "Focused windows stay fully opaque", 1.0),
            "corner-radius": S("geometry", "Window corner rounding", radius),
            "blur-method": S(
                "effects", "Blur method follows the generated transparency style",
                "dual_kawase" if blur else "none"),
            "blur-strength": S(
                "effects", "Blur strength follows the generated aesthetic",
                min(20, max(0, blur_radius))),
            "fade": S("effects", "Fade transitions follow the generated aesthetic", soft_style),
            "fade-delta": S("effects", "Fade transition speed", 10),
            "inactive-dim": S("effects", "Inactive window dimming", max(0.0, min(1.0, 1.0 - opacity))),
        },
    }

    configs: dict[str, dict[str, Any]] = {}
    for name in detected:
        if name not in settings_by_app:
            continue
        settings = settings_by_app[name]
        notes = list(shared_notes)
        try:
            text = render_config(name, {k: s["value"] for k, s in settings.items()}, notes)
        except (ValueError, TypeError, UnsafeConfigError) as exc:
            if errors is not None:
                errors[name] = str(exc)
            continue
        configs[name] = {
            "version": detected[name].get("version", "unknown"),
            "config_name": APP_SPECS[name]["config_name"],
            "settings": {k: s["value"] for k, s in settings.items()},
            "reasons": {k: {"reason": s["reason"], "source": s["source"]}
                        for k, s in settings.items()},
            "notes": notes,
            "text": text,
            "validated": True,
        }
    return configs


EXAMPLE_THEME = {
    "background": {"color": "#1e1e2e"},
    "foreground": {"color": "#cdd6f4"},
    "accent": {"color": "#89b4fa"},
    "ansi": {
        "black": "#45475a", "red": "#f38ba8", "green": "#a6e3a1", "yellow": "#f9e2af",
        "blue": "#89b4fa", "magenta": "#f5c2e7", "cyan": "#94e2d5", "white": "#bac2de",
    },
}
EXAMPLE_AESTHETIC = {
    "mood": "calm, soft evening",
    "typography": {"family": "JetBrains Mono", "size": 11},
    "geometry": {"padding": 10, "gaps_inner": 10, "gaps_outer": 6,
                 "border_width": 2, "corner_radius": 10},
    "effects": {"opacity": 0.92, "shadows": True},
    "visual_hierarchy": {"inactive_border": "#313244"},
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate rice configs into the output folder")
    parser.add_argument("--all", action="store_true",
                        help="generate for every supported app, even if not installed")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--input", type=Path,
                        help='JSON file shaped like {"theme": {...}, "aesthetic": {...}}')
    parser.add_argument("--reasons", action="store_true",
                        help="print why each value was chosen")
    args = parser.parse_args()

    theme, aesthetic = EXAMPLE_THEME, EXAMPLE_AESTHETIC
    if args.input:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        theme, aesthetic = data["theme"], data.get("aesthetic", {})
        mood = data.get("mood")
    else:
        mood = None

    apps = {name: {"version": "unknown"} for name in APP_SPECS} if args.all else None
    errors: dict[str, str] = {}
    configs = generate_configs(theme, aesthetic, mood=mood, apps=apps, errors=errors)
    for name, message in errors.items():
        print(f"skipped {name}: {message}")
    if not configs:
        print("No configs generated. Re-run with --all to generate for apps that are not installed.")
        return
    for path in write_configs(configs, output_dir=args.out):
        print(f"wrote {path}")
    for name, config in configs.items():
        for note in config["notes"]:
            print(f"note ({name}): {note}")
    if args.reasons:
        for name, config in configs.items():
            print(f"\n[{name}]")
            for key, info in config["reasons"].items():
                print(f"  {key} = {config['settings'][key]}  [{info['source']}] {info['reason']}")


if __name__ == "__main__":
    main()
