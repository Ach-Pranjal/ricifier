import io, json, os, re, time
from PIL import Image
from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
MODEL = os.environ.get("RICER_MODEL", "gemma-4-31b-it")


# ---------- helpers ----------
def _load_image(path: str, max_side: int = 1024) -> bytes:
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _extract_json(text: str) -> dict:
    text = re.sub(r"^```\w*\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start:end + 1])


def ask(contents, temperature: float = 0.4, tries: int = 3) -> str:
    """Single place that talks to the model. Retries on errors like 500/429."""
    for i in range(tries):
        try:
            r = client.models.generate_content(
                model=MODEL,
                contents=contents,
                config=types.GenerateContentConfig(temperature=temperature),
            )
            return r.text
        except Exception as e:
            print(f"[ask] attempt {i + 1} failed: {e}")
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


# ---------- describe the wallpaper ----------
DESCRIBE_PROMPT = """You are a desktop theme designer. You are given a wallpaper and the color
palette that was extracted from it.

Palette:
{palette}

Return ONLY a JSON object with exactly these keys, no markdown:
{{
  "mood": "short phrase describing the feeling of the image",
  "mode": "dark" or "light",
  "style_notes": "one sentence on borders, contrast and shape feel",
  "explanation": "2-3 sentences on why this palette suits the mood, naming at least two of the actual hex colors"
}}"""

KEYS = ("mood", "mode", "style_notes", "explanation")


def describe(image_path: str, palette: dict) -> dict:
    image = types.Part.from_bytes(data=_load_image(image_path), mime_type="image/jpeg")
    prompt = DESCRIBE_PROMPT.format(palette=json.dumps(palette))
    for attempt in range(3):
        try:
            d = _extract_json(ask([image, prompt], temperature=0.6))
            if all(isinstance(d.get(k), str) for k in KEYS) and d["mode"] in ("dark", "light"):
                return {k: d[k] for k in KEYS}
        except Exception as e:
            print(f"[describe] attempt {attempt + 1}: {e}")
    # fallback so a text failure never breaks the theme
    return {"mood": "unknown", "mode": palette.get("mode", "dark"),
            "style_notes": "", "explanation": "Description unavailable."}


def build_theme(image_path: str, palette: dict) -> dict:
    return {**describe(image_path, palette), **palette}