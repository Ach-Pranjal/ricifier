"""Lightweight, cached configuration generation for supported Linux ricing apps.

Documentation is collected only on demand and cached by application/version.
Generated output is rendered from allowlisted, type-checked fields; documentation
and model output never become executable configuration directives directly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable


CACHE_VERSION = 1
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "ricifier" / "docs"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# Each allowlisted key maps to a value kind:
#   color    #rrggbb or #rrggbbaa
#   colorset five space-separated colors (i3 client.* lines)
#   int/float/bool/px  numbers and booleans, formatted natively per app
#   string   restricted free text (font names)
#   frozenset  one of a fixed set of values
APP_SPECS: dict[str, dict[str, Any]] = {
    "kitty": {
        "command": "kitty",
        "version_args": ("--version",),
        "config_name": "kitty.conf",
        "format": "key-value",
        "keys": {
            "font_family": "string", "font_size": "float",
            "foreground": "color", "background": "color", "cursor": "color",
            "selection_foreground": "color", "selection_background": "color",
            "background_opacity": "float", "window_padding_width": "float",
        },
    },
    "i3": {
        "command": "i3",
        "version_args": ("--version",),
        "config_name": "config",
        "format": "i3",
        "keys": {
            "font": "string", "gaps_inner": "int", "gaps_outer": "int",
            "border_width": "int",
            "client_focused": "colorset", "client_unfocused": "colorset",
            "client_focused_inactive": "colorset", "client_urgent": "colorset",
        },
    },
    "polybar": {
        "command": "polybar",
        "version_args": ("--version",),
        "config_name": "config.ini",
        "format": "ini",
        "keys": {
            "font_0": "string", "font_1": "string",
            "background": "color", "foreground": "color", "accent": "color",
            "height": "int", "offset_x": "int", "offset_y": "int",
            "radius": "float",
        },
    },
    "rofi": {
        "command": "rofi",
        "version_args": ("-version",),
        "config_name": "config.rasi",
        "format": "rasi",
        "keys": {
            "font": "string", "background": "color", "foreground": "color",
            "selected": "color", "border": "color",
            "border_radius": "px", "border_width": "px",
            "spacing": "px", "padding": "px",
        },
    },
    "picom": {
        "command": "picom",
        "version_args": ("--version",),
        "config_name": "picom.conf",
        "format": "picom",
        "keys": {
            "backend": frozenset({"xrender", "glx", "egl"}),
            "vsync": "bool", "shadow": "bool",
            "shadow-radius": "int", "shadow-opacity": "float",
            "inactive-opacity": "float", "active-opacity": "float",
            "corner-radius": "int",
            "blur-method": frozenset(
                {"none", "box", "gaussian", "kernel", "dual_kawase"}
            ),
            "blur-strength": "int",
        },
    },
}

# These patterns are checked even though renderers only emit allowlisted keys.
# They protect the final boundary if a future renderer accepts richer input.
BLOCKED_CONFIG_PATTERNS = (
    re.compile(r"(?im)^\s*(exec|exec_always|exec-once|run|shell|script)\b"),
    re.compile(r"(?im)\b(bind(sym|code)?|click-(left|right|middle)|scroll-(up|down))\b.*\b(exec|run|sh|bash|zsh|python|perl)\b"),
    re.compile(r"(?im)\b(allow_remote_control|remote_control_password|listen_on|socket_path)\b"),
    re.compile(r"(?im)^\s*(include|@import|source|load)\b"),
    re.compile(r"(?im)\b(curl|wget|nc|netcat|ssh|socat|powershell|cmd\.exe)\b"),
    re.compile(r"(?im)([;&|`]|\$\(|\$\{).*(sh|bash|zsh|python|perl|ruby|curl|wget)\b"),
)

HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?")
SAFE_TEXT = re.compile(r"[\w .,:=;+@\-]+")


class UnsafeConfigError(ValueError):
    """Raised when generated configuration contains a dangerous directive."""


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
    evidence for the detected version, not executable input.
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

    help_text = _run_text([executable, "--help"], timeout=3)
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


def _number(key: str, value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{key}: expected a number, got a boolean")
    number = float(value)  # raises ValueError on junk
    if not math.isfinite(number):
        raise ValueError(f"{key}: number must be finite")
    return number


def _format_value(key: str, kind: Any, value: Any) -> str:
    """Type-check one value and format it the way config files expect."""
    if isinstance(kind, frozenset):
        text = str(value).strip()
        if text not in kind:
            raise ValueError(f"{key}: expected one of {sorted(kind)}, got {text!r}")
        return text
    if kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{key}: expected true/false")
        return "true" if value else "false"
    if kind in ("int", "px"):
        number = _number(key, value)
        if number != int(number):
            raise ValueError(f"{key}: expected a whole number")
        return f"{int(number)}px" if kind == "px" else str(int(number))
    if kind == "float":
        return f"{_number(key, value):g}"
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
# Per-app renderers. Each takes already-validated, already-formatted values.
# NOTE: avoid ';' followed by words ending in "sh" in comments, since the final
# validate_config() pass would flag them.
# ---------------------------------------------------------------------------

def _render_kitty(v: dict[str, str], keys: dict[str, Any]) -> str:
    return "\n".join(f"{key} {value}" for key, value in v.items())


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
        lines.append(_I3_MAP[key].format(value, value))
    return "\n".join(lines)


def _render_polybar(v: dict[str, str], keys: dict[str, Any]) -> str:
    out = ["[colors]"]
    out += [f"{k} = {v[k]}" for k in ("background", "foreground", "accent") if k in v]
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
    out += [
        "modules-center = date",
        "",
        "[module/date]",
        "type = internal/date",
        "interval = 5",
        "date = %a %H:%M",
        "label = %date%",
    ]
    return "\n".join(out)


def _block(selector: str, props: list[tuple[str, str | None]]) -> list[str]:
    props = [(k, x) for k, x in props if x is not None]
    if not props:
        return []
    return [selector + " {", *[f"  {k}: {x};" for k, x in props], "}", ""]


def _render_rasi(v: dict[str, str], keys: dict[str, Any]) -> str:
    out: list[str] = []
    if "font" in v:
        out += ["configuration {", f'  font: "{v["font"]}";', "}", ""]
    variables = [("bg", v.get("background")), ("fg", v.get("foreground")),
                 ("selected", v.get("selected")), ("accent", v.get("border"))]
    out += _block("*", variables)
    out += _block("window", [
        ("background-color", "@bg" if "background" in v else None),
        ("border", v.get("border_width")),
        ("border-color", "@accent" if "border" in v else None),
        ("border-radius", v.get("border_radius")),
        ("padding", v.get("padding")),
    ])
    out += _block("mainbox", [("spacing", v.get("spacing"))])
    out += _block("listview", [("spacing", v.get("spacing"))])
    fg = "@fg" if "foreground" in v else None
    out += _block("element", [("text-color", fg), ("background-color", "transparent")])
    out += _block("element selected.normal", [
        ("background-color", "@selected" if "selected" in v else None),
        ("text-color", "@bg" if "background" in v else None),
    ])
    out += _block("entry", [("text-color", fg)])
    out += _block("prompt", [("text-color", "@accent" if "border" in v else None)])
    return "\n".join(out).rstrip()


def _render_picom(v: dict[str, str], keys: dict[str, Any]) -> str:
    lines = []
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


def render_config(name: str, settings: dict[str, Any]) -> str:
    """Render only known safe settings, then validate the complete output."""
    if name not in APP_SPECS:
        raise ValueError(f"Unsupported application: {name}")
    keys = APP_SPECS[name]["keys"]
    unknown = set(settings) - set(keys)
    if unknown:
        raise ValueError(f"Unsupported {name} settings: {', '.join(sorted(unknown))}")

    values = {key: _format_value(key, keys[key], settings[key]) for key in settings}
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


def generate_configs(
    theme: dict[str, dict[str, str]],
    aesthetic: dict[str, Any],
    *,
    apps: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Generate safe configs for detected apps from a generic rice design."""
    detected = apps if apps is not None else detect_apps()
    typography = aesthetic.get("typography", {})
    geometry = aesthetic.get("geometry", {})
    effects = aesthetic.get("effects", {})
    hierarchy = aesthetic.get("visual_hierarchy", {})
    background = theme["background"]["color"]
    foreground = theme["foreground"]["color"]
    accent = theme["accent"]["color"]
    inactive = hierarchy.get("inactive_border", background)
    font = typography.get("family", "monospace")
    size = typography.get("size", 12)
    configs: dict[str, dict[str, Any]] = {}

    settings_by_app = {
        "kitty": {
            "font_family": font,
            "font_size": size,
            "foreground": foreground,
            "background": background,
            "cursor": accent,
            "background_opacity": effects.get("opacity", 0.95),
            "window_padding_width": geometry.get("padding", 8),
        },
        "i3": {
            "font": f"pango:{font} {size}",
            "gaps_inner": geometry.get("gaps_inner", 8),
            "gaps_outer": geometry.get("gaps_outer", 8),
            "border_width": geometry.get("border_width", 1),
            # border  background  text  indicator  child_border
            "client_focused": f"{accent} {accent} {background} {accent} {accent}",
            "client_unfocused": f"{inactive} {inactive} {foreground} {inactive} {inactive}",
        },
        "polybar": {
            "font_0": f"{font}:size={size};2",
            "background": background,
            "foreground": foreground,
            "accent": accent,
            "height": geometry.get("padding", 8) + 24,
            "radius": geometry.get("corner_radius", 8),
        },
        "rofi": {
            "font": f"{font} {size}",
            "background": background,
            "foreground": foreground,
            "selected": accent,
            "border": accent,
            "border_radius": geometry.get("corner_radius", 8),
            "border_width": geometry.get("border_width", 2),
            "spacing": geometry.get("gaps_inner", 8),
            "padding": geometry.get("padding", 8),
        },
        "picom": {
            "backend": "glx",
            "vsync": True,
            "shadow": bool(effects.get("shadows", False)),
            "shadow-radius": 12,
            "shadow-opacity": 0.35,
            "inactive-opacity": effects.get("opacity", 0.95),
            "active-opacity": 1.0,
            "corner-radius": geometry.get("corner_radius", 8),
        },
    }

    for name in detected:
        if name not in settings_by_app:
            continue
        text = render_config(name, settings_by_app[name])
        configs[name] = {
            "version": detected[name].get("version", "unknown"),
            "config_name": APP_SPECS[name]["config_name"],
            "settings": settings_by_app[name],
            "text": text,
            "validated": True,
        }
    return configs


EXAMPLE_THEME = {
    "background": {"color": "#1e1e2e"},
    "foreground": {"color": "#cdd6f4"},
    "accent": {"color": "#89b4fa"},
}
EXAMPLE_AESTHETIC = {
    "typography": {"family": "JetBrains Mono", "size": 11},
    "geometry": {"padding": 10, "gaps_inner": 10, "gaps_outer": 6,
                 "border_width": 2, "corner_radius": 10},
    "effects": {"opacity": 0.92, "shadows": True},
    "visual_hierarchy": {"inactive_border": "#313244"},
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate rice configs into ./output")
    parser.add_argument("--all", action="store_true",
                        help="generate for every supported app, even if not installed")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    apps = {name: {"version": "unknown"} for name in APP_SPECS} if args.all else None
    configs = generate_configs(EXAMPLE_THEME, EXAMPLE_AESTHETIC, apps=apps)
    if not configs:
        print("No supported apps found. Re-run with --all to generate anyway.")
        return
    for path in write_configs(configs, output_dir=args.out):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
