"""Lightweight, cached configuration generation for supported Linux ricing apps.

Documentation is collected only on demand and cached by application/version.
Generated output is rendered from allowlisted fields; documentation and model
output never become executable configuration directives directly.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


CACHE_VERSION = 1
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "ricifier" / "docs"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output"

APP_SPECS: dict[str, dict[str, Any]] = {
    "kitty": {
        "command": "kitty",
        "version_args": ("--version",),
        "config_name": "kitty.conf",
        "format": "key-value",
        "safe_keys": {
            "font_family", "font_size", "foreground", "background",
            "cursor", "selection_foreground", "selection_background",
            "background_opacity", "window_padding_width",
        },
    },
    "i3": {
        "command": "i3",
        "version_args": ("--version",),
        "config_name": "config",
        "format": "i3",
        "safe_keys": {
            "font", "gaps_inner", "gaps_outer", "border_width",
            "client_focused", "client_unfocused", "client_focused_inactive",
            "client_urgent",
        },
    },
    "polybar": {
        "command": "polybar",
        "version_args": ("--version",),
        "config_name": "config.ini",
        "format": "ini",
        "safe_keys": {
            "font_0", "font_1", "background", "foreground", "accent",
            "height", "offset_x", "offset_y", "radius",
        },
    },
    "rofi": {
        "command": "rofi",
        "version_args": ("-version",),
        "config_name": "config.rasi",
        "format": "rasi",
        "safe_keys": {
            "font", "background", "foreground", "selected",
            "border", "border_radius", "spacing", "padding",
        },
    },
    "picom": {
        "command": "picom",
        "version_args": ("--version",),
        "config_name": "picom.conf",
        "format": "picom",
        "safe_keys": {
            "backend", "vsync", "shadow", "shadow-radius",
            "shadow-opacity", "inactive-opacity", "active-opacity",
            "corner-radius", "blur-method", "blur-strength",
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
        return json.loads(path.read_text(encoding="utf-8"))

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
        "safe_keys": sorted(spec["safe_keys"]),
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


def render_config(name: str, settings: dict[str, Any]) -> str:
    """Render only known safe settings, then validate the complete output."""
    if name not in APP_SPECS:
        raise ValueError(f"Unsupported application: {name}")
    spec = APP_SPECS[name]
    unknown = set(settings) - spec["safe_keys"]
    if unknown:
        raise ValueError(f"Unsupported {name} settings: {', '.join(sorted(unknown))}")

    if spec["format"] == "key-value":
        text = "\n".join(f"{key} {_clean_value(settings[key])}" for key in settings)
    elif spec["format"] == "ini":
        text = "[bar]\n" + "\n".join(
            f"{key} = {_clean_value(settings[key])}" for key in settings
        )
    elif spec["format"] == "rasi":
        text = "* {\n" + "\n".join(
            f"  {key}: {_clean_value(settings[key])};" for key in settings
        ) + "\n}"
    else:
        text = "\n".join(f"{key} = {_clean_value(settings[key])};" for key in settings)

    validate_config(name, text)
    return text + "\n"


def write_configs(
    configs: dict[str, dict[str, Any]],
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> None:
    """Write validated generated configuration text to the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, config in configs.items():
        config_name = APP_SPECS[name]["config_name"]
        (output_dir / config_name).write_text(
            config["text"],
            encoding="utf-8",
        )


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
            "client_focused": f"{accent} {accent} {background} {accent} {accent}",
            "client_unfocused": (
                f"{hierarchy.get('inactive_border', background)} "
                f"{hierarchy.get('inactive_border', background)} "
                f"{background} {hierarchy.get('inactive_border', background)} "
                f"{hierarchy.get('inactive_border', background)}"
            ),
        },
        "polybar": {
            "font_0": f"{font}:{size};2",
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
