"""Test for ml_model.py.

Part 1 runs offline (no API calls, instant).
Part 2 makes 3 real Gemma requests.

Run:
    python test_ml_model.py D:\\path\\to\\wallpaper.jpg
"""
import io
import os
import sys
import time
from PIL import Image

import ml_model as mm
from processor import extract_palette

passed = 0
failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print("PASS:", name)
    else:
        failed += 1
        print("FAIL:", name)


# ================= PART 1: offline tests =================
print("--- Part 1: offline (fake Gemma replies) ---")

real_generate = mm._generate

buf = io.BytesIO()
Image.new("RGB", (8, 8), "#223344").save(buf, format="PNG")
tiny = buf.getvalue()

PALETTE = ["#1b1f2a", "#7a9fc2", "#d6d9e0", "#c26a6a", "#8fb573"]
THEME = {r: {"color": c, "reason": ""} for r, c in
         zip(mm.ROLES, ("#1b1f2a", "#d6d9e0", "#7a9fc2"))}
MOOD = {"mode": "dark", "warmth": 0, "contrast": 3, "style": "", "style_notes": "", "summary": ""}


def fake(reply):
    mm._generate = lambda contents, tries=4: reply


# junk values in the mood must be corrected
fake('{"mode": "purple", "warmth": 99, "contrast": "abc", "style": 5}')
m = mm.analyze_wallpaper(tiny)
check("bad mode falls back to dark", m["mode"] == "dark")
check("warmth is clamped to 5", m["warmth"] == 5)
check("non-number contrast falls back to 3", m["contrast"] == 3)

# fenced JSON is accepted
fake('```json\n{"mode": "light"}\n```')
check("```json fences are stripped", mm.analyze_wallpaper(tiny)["mode"] == "light")

# no JSON at all must raise a clear error
fake("Sorry, I can't help with that.")
try:
    mm.analyze_wallpaper(tiny)
    check("reply with no JSON raises ValueError", False)
except ValueError:
    check("reply with no JSON raises ValueError", True)

# a color that is not in the palette is replaced by the nearest one
fake('{"background": {"color": "#000000", "reason": "x"},'
     ' "foreground": {"color": "nonsense", "reason": "x"},'
     ' "accent": {"color": "#7a9fc3", "reason": "x"}}')
t = mm.design_theme(tiny, MOOD, PALETTE)
check("off-palette colors are snapped into the palette",
      all(t[r]["color"] in PALETTE for r in mm.ROLES))

# the aesthetic step must reject invented values
if hasattr(mm, "generate_aesthetic"):
    fake('{"typography": {"family": "Comic Sans", "size": 500},'
         ' "geometry": {"panel_style": "banana", "corner_radius": -9},'
         ' "visual_hierarchy": {"active_border": "#1b1f2a", "inactive_border": "#1b1f2a"}}')
    a = mm.generate_aesthetic(tiny, MOOD, THEME, PALETTE)
    check("unknown font is replaced by an allowed one", a["typography"]["family"] in mm.FONTS)
    check("font size is clamped to 16", a["typography"]["size"] == 16)
    check("unknown panel style falls back", a["geometry"]["panel_style"] in mm.PANEL_STYLES)
    check("negative radius is clamped to 0", a["geometry"]["corner_radius"] == 0)
    check("active and inactive borders always differ",
          a["visual_hierarchy"]["active_border"] != a["visual_hierarchy"]["inactive_border"])
    check("fallback fonts end with monospace", a["typography"]["fallbacks"][-1] == "monospace")

mm._generate = real_generate

# ================= PART 2: real Gemma run =================
if len(sys.argv) < 2:
    print("\nNo wallpaper given, so Part 2 is skipped.")
else:
    path = os.path.expanduser(sys.argv[1])
    print("\n--- Part 2: real Gemma run on", path, "---")
    palette = extract_palette(path)
    print("palette:", palette)
    check("palette colors are lowercase hex", all(c == c.lower() and c.startswith("#") for c in palette))
    data = open(path, "rb").read()

    mood = mm.analyze_wallpaper(data)
    print("mood:", mood)
    check("mood mode is dark or light", mood["mode"] in ("dark", "light"))
    check("warmth is between -5 and 5", -5 <= mood["warmth"] <= 5)
    check("contrast is between 1 and 5", 1 <= mood["contrast"] <= 5)
    check("style_notes is not empty", len(mood["style_notes"]) > 0)

    time.sleep(2)
    theme = mm.design_theme(data, mood, palette)
    print("theme:", theme)
    check("every chosen color is in the measured palette",
          all(theme[r]["color"] in palette for r in mm.ROLES))
    check("every role has a reason", all(len(theme[r]["reason"]) > 0 for r in mm.ROLES))
    if hasattr(mm, "_contrast"):
        best = max(mm._contrast(theme["background"]["color"], p) for p in palette)
        got = mm._contrast(theme["background"]["color"], theme["foreground"]["color"])
        check("foreground is readable (4.5:1, or the best the palette allows)",
              got >= min(4.5, best) - 0.01)

    if hasattr(mm, "generate_aesthetic"):
        time.sleep(2)
        aes = mm.generate_aesthetic(data, mood, theme, palette)
        print("aesthetic:", aes)
        check("visual style is an allowed label", aes["visual_style"]["label"] in mm.STYLES)
        check("font is from the allowed list", aes["typography"]["family"] in mm.FONTS)
        check("borders come from the palette",
              aes["visual_hierarchy"]["active_border"] in palette
              and aes["visual_hierarchy"]["inactive_border"] in palette)
        check("design rationale is not empty", len(aes["design_rationale"]) > 0)

print(f"\n{passed} passed, {failed} failed.")
sys.exit(1 if failed else 0)