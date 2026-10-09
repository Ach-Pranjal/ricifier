import io
import json
import os
import re
import shutil
import subprocess
import sys
import time

from google import genai
from google.genai import errors, types
from PIL import Image

# Change the model without editing code:  export RICER_MODEL="gemma-4-31b-it"
MODEL = os.environ.get("RICER_MODEL", "gemma-4-26b-a4b-it")
client = None

TEMPERATURE = 0.4  # lower = more stable answers between runs


# ---------- talking to Gemma ----------
def _get_client():
    """Create the Gemini client only when an API request is actually needed."""
    global client
    if client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Configure it before analyzing a wallpaper."
            )
        client = genai.Client(api_key=api_key)
    return client


def _generate(contents, tries=4):
    """Ask Gemma something. Retry only on temporary errors (429 = rate limit, 500/503 = server busy)."""
    for attempt in range(tries):
        try:
            return _get_client().models.generate_content(
                model=MODEL,
                contents=contents,
                config=types.GenerateContentConfig(temperature=TEMPERATURE),
            ).text
        except errors.APIError as e:
            if e.code in (429, 500, 503) and attempt < tries - 1:
                time.sleep(5 * (attempt + 1))  # wait 5s, then 10s, then 15s
                continue
            raise  # any other error: stop and show it


def _parse_json(text):
    """Gemma's reply is text. Remove ```json fences, cut out the part between the first { and the last }, read it as data."""
    text = re.sub(r"^```\w*\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("Gemma's reply had no JSON object. Reply was: " + text[:200])
    return json.loads(text[start:end + 1])


def _load_image(data):
    """Shrink the wallpaper so it uploads fast, and wrap it in the form the API wants."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((1024, 1024))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")


# ---------- step 1: the mood ----------
MOOD_PROMPT = """You are helping theme a Linux terminal from a wallpaper.
Look at the image and describe its mood. Reply with ONLY a JSON object, no other text:
{
  "mode": "dark" or "light" (which suits a terminal theme for this wallpaper),
  "warmth": integer from -5 (very cool) to 5 (very warm),
  "contrast": integer from 1 (soft, gentle) to 5 (harsh, punchy),
  "style": a short phrase of 2 to 4 words, like "moody neon" or "soft pastel",
  "style_notes": one sentence describing the look and feel of the image (contrast, shapes, texture), like "Strong contrast between dark silhouettes and soft, pastel-toned highlights creates a clean, vector-like feel.",
  "summary": one sentence explaining why you chose these
}"""


def _clamp(value, low, high, default):
    """Turn value into an integer between low and high. If it is not a number, use default."""
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _clean_mood(mood):
    """Make sure the mood always has the right keys and sensible values, even if Gemma was sloppy."""
    return {
        "mode": mood.get("mode") if mood.get("mode") in ("dark", "light") else "dark",
        "warmth": _clamp(mood.get("warmth"), -5, 5, 0),
        "contrast": _clamp(mood.get("contrast"), 1, 5, 3),
        "style": str(mood.get("style", "")),
        "style_notes": str(mood.get("style_notes", "")),
        "summary": str(mood.get("summary", "")),
    }


def analyze_wallpaper(data):
    """data = the wallpaper file's bytes. Returns the mood as a Python dict."""
    reply = _generate([_load_image(data), MOOD_PROMPT])
    return _clean_mood(_parse_json(reply))


# ---------- step 2: the roles ----------
THEME_PROMPT = """You are theming a Linux terminal from a wallpaper.
Mood of the wallpaper: <<MOOD>>
Colors measured from the wallpaper (you MUST choose only from this list): <<PALETTE>>

Pick three colors from the list and explain each choice. Reply with ONLY a JSON object, no other text:
{
  "background": {"color": "<hex from the list>", "reason": "<one sentence>"},
  "foreground": {"color": "<hex from the list>", "reason": "<one sentence>"},
  "accent": {"color": "<hex from the list>", "reason": "<one sentence>"}
}
Rules:
- If the mood mode is dark, the background must be one of the darkest colors. If it is light, one of the lightest.
- The foreground (the text color) must be very different in lightness from the background. If no color in the list is light or dark enough, pick the closest one. The code will adjust it.
- The accent should be the most striking color that is not the background or foreground."""

ROLES = ("background", "foreground", "accent")


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def _nearest(color, palette):
    """Find the palette color closest to `color`."""
    c = _hex_to_rgb(color)
    return min(palette, key=lambda p: sum((x - y) ** 2 for x, y in zip(c, _hex_to_rgb(p))))


def _luminance(hex_color):
    """Return the relative luminance of a hex color."""
    r, g, b = (component / 255 for component in _hex_to_rgb(hex_color))

    def linearize(component):
        return (component / 12.92 if component <= 0.03928
                else ((component + 0.055) / 1.055) ** 2.4)

    return (0.2126 * linearize(r)
            + 0.7152 * linearize(g)
            + 0.0722 * linearize(b))


def _contrast(first, second):
    """Return the WCAG contrast ratio between two hex colors."""
    first_luminance = _luminance(first)
    second_luminance = _luminance(second)
    brighter, darker = sorted((first_luminance, second_luminance), reverse=True)
    return (brighter + 0.05) / (darker + 0.05)


def design_theme(data, mood, palette):
    """Ask Gemma to assign roles from the palette. Returns {role: {color, reason}}."""
    prompt = (THEME_PROMPT
              .replace("<<MOOD>>", json.dumps(mood))
              .replace("<<PALETTE>>", ", ".join(palette)))
    theme = _parse_json(_generate([_load_image(data), prompt]))

    # safety check: every role must exist, and every color must really be in the palette
    result = {}
    for i, role in enumerate(ROLES):
        item = theme.get(role)
        if not isinstance(item, dict):
            item = {}
        color = str(item.get("color", "")).lower()
        reason = str(item.get("reason", "No reason given."))
        if color not in palette:
            try:
                color = _nearest(color, palette)
                reason += " (adjusted to the closest measured color)"
            except (ValueError, IndexError):  # Gemma wrote something that isn't a hex code
                color = palette[i % len(palette)]
                reason += " (Gemma gave no valid color, so a measured one was used)"
        result[role] = {"color": color, "reason": reason}

    # Ensure the selected foreground is as readable as this palette allows.
    background = result["background"]["color"]
    foreground = result["foreground"]["color"]
    best = max(palette, key=lambda p: _contrast(background, p))
    if _contrast(background, foreground) < min(4.5, _contrast(background, best)):
        result["foreground"] = {
            "color": best,
            "reason": result["foreground"]["reason"] + " (changed for readability)",
        }

    return result


# ---------- step 3: visual ricing specification ----------
STYLES = (
    "minimal",
    "soft",
    "retro",
    "cyberpunk",
    "glass",
    "brutalist",
)
PANEL_STYLES = ("flat", "bordered", "floating", "transparent")

AESTHETIC_PROMPT = """You are designing a Linux desktop rice from a wallpaper.
Mood: <<MOOD>>
Theme colors (use only these hex colors): <<THEME>>
Measured palette (use only these hex colors for borders and highlights): <<PALETTE>>

Return ONLY this JSON object, with no markdown:
{
  "visual_style": {
    "label": one of <<STYLES>>,
    "reason": "one sentence"
  },
  "typography": {
    "family": one of <<FONTS>>,
  "suggested_family": "the best-looking font, even if it is not installed",
  "size": integer 9 to 16,
  "weight": "regular" or "medium" or "bold",
  "line_height": number 1.0 to 2.0,
  "fallbacks": ["one or more fallback font names"],
  "installed": true or false,
  "fallback_family": "an installed font to use if family is unavailable",
  "install_hint": "short instruction, or empty string when already installed",
  "reason": "one sentence"
  },
  "geometry": {
    "panel_style": "flat" or "bordered" or "floating" or "transparent",
    "corner_radius": integer 0 to 20,
    "border_width": integer 0 to 4,
    "gaps_inner": integer 0 to 20,
    "gaps_outer": integer 0 to 20,
    "padding": integer 0 to 24,
    "reason": "one sentence"
  },
  "effects": {
    "opacity": number 0.7 to 1.0,
    "shadows": true or false,
    "blur": true or false,
    "blur_radius": integer 0 to 24,
    "reason": "one sentence"
  },
  "visual_hierarchy": {
    "active_border": "<hex from the palette>",
    "inactive_border": "<hex from the palette>",
    "highlight": "<hex from the palette>",
    "reason": "one sentence"
  },
  "design_rationale": "two or three sentences explaining how the choices fit the wallpaper"
}

Soft moods suit rounded corners, wider gaps, shadows and blur. Harsh moods suit
sharp corners, tighter spacing and stronger borders. Active and inactive borders
must be visibly different when the palette allows it."""


def _choose_palette_color(value, palette, fallback):
    """Return a palette color, snapping invalid model output to the nearest one."""
    return _border_color(value, palette, fallback)


def generate_aesthetic(data, mood, theme, palette):
    """Generate and validate the richer visual specification used for ricing."""
    prompt = (AESTHETIC_PROMPT
              .replace("<<MOOD>>", json.dumps(mood))
              .replace("<<THEME>>", json.dumps(
                  {role: theme[role]["color"] for role in ROLES}))
              .replace("<<PALETTE>>", ", ".join(palette))
              .replace("<<STYLES>>", ", ".join(STYLES))
              .replace("<<FONTS>>", ", ".join(FONTS)))
    raw = _parse_json(_generate([_load_image(data), prompt]))
    if not isinstance(raw, dict):
        raw = {}

    visual_style = _sect(raw, "visual_style")
    typography = _sect(raw, "typography")
    geometry = _sect(raw, "geometry")
    effects = _sect(raw, "effects")
    hierarchy = _sect(raw, "visual_hierarchy")

    background = theme["background"]["color"]
    foreground = theme["foreground"]["color"]
    accent = theme["accent"]["color"]
    inactive_border = _choose_palette_color(
        hierarchy.get("inactive_border"), palette, background)
    active_border = _choose_palette_color(
        hierarchy.get("active_border"), palette, accent)
    if active_border == inactive_border and len(palette) > 1:
        active_border = max(
            (color for color in palette if color != inactive_border),
            key=lambda color: _contrast(background, color),
        )
    highlight = _choose_palette_color(hierarchy.get("highlight"), palette, accent)
    suggested_family = _pick(
        typography.get("suggested_family", typography.get("family")),
        FONT_CATALOG,
        "JetBrains Mono",
    )
    installed_fonts = detect_installed_fonts()
    effective_family = (
        suggested_family
        if suggested_family in installed_fonts
        else _pick_installed_font(installed_fonts)
    )
    fallback_family = _pick_installed_font(installed_fonts)

    return {
        "visual_style": {
            "label": _pick(visual_style.get("label"), STYLES, "minimal"),
            "reason": _reason(visual_style),
        },
        "typography": {
            "family": effective_family,
            "suggested_family": suggested_family,
            "size": _clamp(typography.get("size"), 9, 16, 12),
            "weight": _pick(
                typography.get("weight"),
                ("regular", "medium", "bold"),
                "regular",
            ),
            "line_height": _clamp_float(
                typography.get("line_height"), 1.0, 2.0, 1.3),
            "fallbacks": [
                str(font) for font in typography.get("fallbacks", [])
                if isinstance(font, str)
            ] or ["monospace"],
            "installed": suggested_family in installed_fonts,
            "fallback_family": fallback_family,
            "install_hint": (
                ""
                if suggested_family in installed_fonts
                else f"Install '{suggested_family}' or use '{fallback_family}'."
            ),
            "reason": _reason(typography),
        },
        "geometry": {
            "panel_style": _pick(
                geometry.get("panel_style"), PANEL_STYLES, "bordered"),
            "corner_radius": _clamp(
                geometry.get("corner_radius"), 0, 20, 8),
            "border_width": _clamp(
                geometry.get("border_width"), 0, 4, 1),
            "gaps_inner": _clamp(
                geometry.get("gaps_inner"), 0, 20, 8),
            "gaps_outer": _clamp(
                geometry.get("gaps_outer"), 0, 20, 8),
            "padding": _clamp(geometry.get("padding"), 0, 24, 8),
            "reason": _reason(geometry),
        },
        "effects": {
            "opacity": _clamp_float(
                effects.get("opacity"), 0.7, 1.0, 0.95),
            "shadows": bool(effects.get("shadows", False)),
            "blur": bool(effects.get("blur", False)),
            "blur_radius": _clamp(
                effects.get("blur_radius"), 0, 24, 0),
            "reason": _reason(effects),
        },
        "visual_hierarchy": {
            "active_border": active_border,
            "inactive_border": inactive_border,
            "highlight": highlight,
            "reason": _reason(hierarchy),
        },
        "design_rationale": str(
            raw.get("design_rationale", "No design rationale given.")),
    }


# ---------- step 4: layout, shape and fonts ----------
FONT_CATALOG = (
    "JetBrains Mono",
    "Fira Code",
    "Iosevka",
    "Hack",
    "CaskaydiaCove Nerd Font",
    "MesloLGS Nerd Font",
    "Mononoki Nerd Font",
    "JetBrainsMono Nerd Font",
    "monospace",
)
FONTS = list(FONT_CATALOG)
BAR_POSITIONS = ("top", "bottom")
BORDER_STYLES = ("sharp", "rounded", "pill")

STYLE_PROMPT = """You are designing the layout of a Linux desktop from a wallpaper.
Mood of the wallpaper: <<MOOD>>
Chosen colors: <<THEME>>

Choose the layout. Reply with ONLY a JSON object, no other text:
{
  "font": {"family": one of <<FONTS>>, "size": integer 9 to 16, "reason": "<one sentence>"},
  "shape": {"style": "sharp" or "rounded" or "pill", "radius": integer 0 to 16, "border_width": integer 0 to 4, "reason": "<one sentence>"},
  "spacing": {"gaps_inner": integer 0 to 20, "gaps_outer": integer 0 to 20, "padding": integer 0 to 24, "reason": "<one sentence>"},
  "opacity": {"value": number 0.7 to 1.0, "reason": "<one sentence>"},
  "bar": {"position": "top" or "bottom", "height": integer 18 to 36, "floating": true or false, "reason": "<one sentence>"}
}
Plain text only, no markdown. Soft moods suit rounded shapes, larger gaps and lower opacity.
Harsh, high-contrast moods suit sharp shapes, small gaps and full opacity."""


def _pick(value, options, default):
    """Return value if it is one of the allowed options, otherwise the default."""
    return value if value in options else default


def _clamp_float(value, low, high, default):
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default

def _sect(raw, key):
    item = raw.get(key)
    return item if isinstance(item, dict) else {}

def _reason(item):
    return str(item.get("reason", "No reason given.")) if isinstance(item, dict) else "No reason given."

def _border_color(value, palette, fallback):
    try:
        return str(value).lower() if str(value).lower() in palette else _nearest(str(value), palette)
    except (ValueError, IndexError):
        return fallback


def detect_installed_fonts():
    """Return known font families installed on Linux, plus the generic fallback."""
    installed = {"monospace"}
    fc_list = shutil.which("fc-list")
    if not fc_list:
        return installed

    try:
        completed = subprocess.run(
            [fc_list, ":", "family"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return installed

    available = {name.strip() for name in completed.stdout.splitlines() if name.strip()}
    for font in FONT_CATALOG:
        if font in available:
            installed.add(font)
    return installed


def _pick_installed_font(installed_fonts):
    """Choose the first catalog font that is usable on the current machine."""
    return next((font for font in FONT_CATALOG if font in installed_fonts), "monospace")


def design_style(data, mood, theme):
    """Ask Gemma for font, shape, spacing, opacity and bar layout. Everything is validated."""
    prompt = (STYLE_PROMPT
              .replace("<<MOOD>>", json.dumps(mood))
              .replace("<<THEME>>", json.dumps({r: theme[r]["color"] for r in ROLES}))
              .replace("<<FONTS>>", ", ".join(FONTS)))
    raw = _parse_json(_generate([_load_image(data), prompt]))
    g = lambda key: raw.get(key) if isinstance(raw.get(key), dict) else {}

    font, shape, spacing = g("font"), g("shape"), g("spacing")
    opacity, bar = g("opacity"), g("bar")

    return {
        "font": {
            "family": _pick(font.get("family"), FONTS, "monospace"),
            "size": _clamp(font.get("size"), 9, 16, 12),
            "reason": _reason(font),
        },
        "shape": {
            "style": _pick(shape.get("style"), BORDER_STYLES, "rounded"),
            "radius": _clamp(shape.get("radius"), 0, 16, 6),
            "border_width": _clamp(shape.get("border_width"), 0, 4, 2),
            "reason": _reason(shape),
        },
        "spacing": {
            "gaps_inner": _clamp(spacing.get("gaps_inner"), 0, 20, 8),
            "gaps_outer": _clamp(spacing.get("gaps_outer"), 0, 20, 8),
            "padding": _clamp(spacing.get("padding"), 0, 24, 8),
            "reason": _reason(spacing),
        },
        "opacity": {
            "value": _clamp_float(opacity.get("value"), 0.7, 1.0, 0.95),
            "reason": _reason(opacity),
        },
        "bar": {
            "position": _pick(bar.get("position"), BAR_POSITIONS, "top"),
            "height": _clamp(bar.get("height"), 18, 36, 26),
            "floating": bool(bar.get("floating", False)),
            "reason": _reason(bar),
        },
    }


def main(argv=None):
    """Analyze one wallpaper from the command line and print the complete rice."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("Usage: python ml_model.py <wallpaper-path>", file=sys.stderr)
        return 2

    image_path = args[0]
    try:
        with open(image_path, "rb") as image_file:
            data = image_file.read()

        from processor import extract_palette

        palette = extract_palette(image_path)
        mood = analyze_wallpaper(data)
        theme = design_theme(data, mood, palette)
        aesthetic = generate_aesthetic(data, mood, theme, palette)
        from app_configs import detect_apps, generate_configs, write_configs

        apps = detect_apps()
        configs = generate_configs(theme, aesthetic, apps=apps)
        write_configs(configs)
        print(json.dumps({
            "palette": palette,
            "mood": mood,
            "theme": theme,
            "aesthetic": aesthetic,
            "detected_apps": apps,
            "configs": configs,
        }, indent=2))
    except (OSError, ValueError, RuntimeError) as error:
        print(f"ml_model.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())