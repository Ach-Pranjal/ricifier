"""End-to-end wallpaper test for Ricifier.

This intentionally makes real Gemini requests. It is useful for checking the
complete wallpaper -> mood -> theme -> aesthetic -> five app configs path.

Run from the project root:

    GEMINI_API_KEY=your-key python backend/test_ml_model.py wallpaper.jpg

After the first run, the generated design can be reused without an API call:

    python backend/test_ml_model.py --mood-json output/mood.json --apps kitty rofi
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from PIL import UnidentifiedImageError

from app_configs import APP_SPECS, generate_configs, write_configs
from processor import extract_palette


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the real Ricifier wallpaper-to-config pipeline."
    )
    parser.add_argument(
        "wallpaper", type=Path, nargs="?",
        help="Path to a wallpaper image; omit it when --mood-json is used",
    )
    parser.add_argument(
        "--mood-json", type=Path,
        help="Previously generated mood/design JSON to reuse without Gemini",
    )
    parser.add_argument(
        "--apps", nargs="+", choices=sorted(APP_SPECS), metavar="APP",
        help="Apps to generate (default: all five)",
    )
    parser.add_argument(
        "--gemini-configs", action="store_true",
        help="ask Gemini for per-app appearance refinements",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("output"),
        help="Directory for generated app configs (default: output)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    import ml_model as mm

    if bool(args.wallpaper) == bool(args.mood_json):
        print("ERROR: provide exactly one of a wallpaper image or --mood-json.", file=sys.stderr)
        return 2
    try:
        if args.mood_json:
            if not args.mood_json.is_file():
                print(f"ERROR: mood JSON does not exist: {args.mood_json}", file=sys.stderr)
                return 2
            saved = json.loads(args.mood_json.read_text(encoding="utf-8"))
            mood = saved.get("mood", {})
            theme = saved["theme"]
            aesthetic = saved["aesthetic"]
        else:
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                print("ERROR: GEMINI_API_KEY is not set.", file=sys.stderr)
                return 2
            if not args.wallpaper.is_file():
                print(f"ERROR: wallpaper does not exist: {args.wallpaper}", file=sys.stderr)
                return 2
            data = args.wallpaper.read_bytes()
            palette = extract_palette(args.wallpaper)
            mood = mm.analyze_wallpaper(data)
            theme = mm.design_theme(data, mood, palette)
            aesthetic = mm.generate_aesthetic(data, mood, theme, palette)

        selected = args.apps or list(APP_SPECS)
        apps = {name: {"version": "test"} for name in selected}
        errors: dict[str, str] = {}
        configs = generate_configs(
            theme,
            aesthetic,
            mood=mood,
            apps=apps,
            errors=errors,
        )
        if args.gemini_configs:
            configs = mm.refine_configs_with_gemini(
                data if not args.mood_json else None,
                mood, theme, aesthetic, configs, apps,
            )
        if errors:
            for name, message in errors.items():
                print(f"ERROR: {name}: {message}", file=sys.stderr)
            return 1
        if set(configs) != set(selected):
            missing = sorted(set(selected) - set(configs))
            print(f"ERROR: missing generated apps: {', '.join(missing)}", file=sys.stderr)
            return 1

        written = write_configs(configs, output_dir=args.out)
        if not args.mood_json:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / "mood.json").write_text(
                json.dumps({
                    "mood": mood,
                    "theme": theme,
                    "aesthetic": aesthetic,
                    "palette": palette,
                }, indent=2),
                encoding="utf-8",
            )
    except (OSError, UnidentifiedImageError, ValueError, RuntimeError) as error:
        print(f"ERROR: pipeline failed: {error}", file=sys.stderr)
        return 1

    print("PASS: real Gemini pipeline completed")
    print(f"mood: {json.dumps(mood, ensure_ascii=False)}")
    print(f"style: {aesthetic['visual_style']['label']}")
    print(f"apps: {', '.join(sorted(configs))}")
    if not args.mood_json:
        print(f"saved: {args.out / 'mood.json'}")
    for path in written:
        print(f"wrote: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
