"""Real test for ml_model_new.py (uses 2 Gemma API requests).

Run it with a wallpaper:
    python test_ml_model_new.py ~/path/to/wallpaper.jpg
"""
import sys

import ml_model as mm
from processor import extract_palette

if len(sys.argv) < 2:
    print("Usage: python test_ml_model_new.py ~/path/to/wallpaper.jpg")
    sys.exit(1)

passed = 0


def check(name, condition):
    """Print PASS or FAIL for one small test."""
    global passed
    if condition:
        passed += 1
        print("PASS:", name)
    else:
        print("FAIL:", name)
        sys.exit(1)


path = sys.argv[1]
print("Real Gemma run on", path)
palette = extract_palette(path)
print("palette:", palette)
data = open(path, "rb").read()

mood = mm.analyze_wallpaper(data)
print("mood:", mood)
check("mood mode is dark or light", mood["mode"] in ("dark", "light"))
check("warmth is between -5 and 5", -5 <= mood["warmth"] <= 5)
check("contrast is between 1 and 5", 1 <= mood["contrast"] <= 5)
check("style_notes is not empty", len(mood["style_notes"]) > 0)

theme = mm.design_theme(data, mood, palette)
print("theme:", theme)
check("every chosen color is in the measured palette",
      all(theme[r]["color"] in palette for r in mm.ROLES))
check("every role has a reason",
      all(len(theme[r]["reason"]) > 0 for r in mm.ROLES))

print("\nAll", passed, "tests passed.")
