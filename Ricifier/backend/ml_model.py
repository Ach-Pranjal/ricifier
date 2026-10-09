import io
import json
import os
import re
import time

from google import genai
from google.genai import errors, types
from PIL import Image

# Change the model without editing code:  export RICER_MODEL="gemma-4-31b-it"
MODEL = os.environ.get("RICER_MODEL", "gemma-4-26b-a4b-it")
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

TEMPERATURE = 0.4  # lower = more stable answers between runs


# ---------- talking to Gemma ----------
def _generate(contents, tries=4):
    """Ask Gemma something. Retry only on temporary errors (429 = rate limit, 500/503 = server busy)."""
    for attempt in range(tries):
        try:
            return client.models.generate_content(
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
    return result
