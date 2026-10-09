import sys
from processor import extract_palette
from ml_model import analyze_wallpaper, design_theme

path = sys.argv[1]
palette = extract_palette(path)
print("palette:", palette)

data = open(path, "rb").read()
mood = analyze_wallpaper(data)
print("mood:", mood)

theme = design_theme(data, mood, palette)
print("theme:", theme)
