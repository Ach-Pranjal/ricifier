"""Generate a final application config using the legacy Gemma pipeline.

Template onboarding and final generation are intentionally separate. This
module consumes an existing application catalog, asks the unchanged legacy
pipeline for wallpaper design decisions, validates the resulting plan, and
renders only policy-approved values.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import ml_model, processor
from .config_generation.policy import PlanResult, validate_plan
from .config_generation.renderers import render_key_value
from .config_generation.schemas import (
    ConfigPlan,
    Manifest,
    ParameterCatalog,
    PlanItem,
)


def load_application(app_dir: Path) -> tuple[Manifest, ParameterCatalog]:
    """Load and validate an onboarded application's manifest and catalog."""
    manifest_path = app_dir / "manifest.json"
    catalog_path = app_dir / "parameters.json"
    template_path = app_dir / "template.conf"
    if not template_path.is_file():
        raise FileNotFoundError(f"missing application template: {template_path}")
    manifest = Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    catalog = ParameterCatalog.model_validate_json(
        catalog_path.read_text(encoding="utf-8"),
    )
    if manifest.id != catalog.app_id:
        raise ValueError("manifest and catalog application IDs do not match")
    return manifest, catalog


def _color(theme: dict[str, Any], role: str) -> str | None:
    value = theme.get(role, {})
    return value.get("color") if isinstance(value, dict) else None


def build_plan(
    app_id: str,
    catalog: ParameterCatalog,
    theme: dict[str, Any],
    aesthetic: dict[str, Any],
) -> ConfigPlan:
    """Map known design roles to matching catalog parameters.

    Unknown application-specific settings are intentionally not guessed. They
    remain available in the template but are omitted from the runtime plan.
    """
    values: dict[str, Any] = {
        "background": _color(theme, "background"),
        "foreground": _color(theme, "foreground"),
        "cursor": _color(theme, "accent"),
        "selection_background": (
            aesthetic.get("visual_hierarchy", {}).get("highlight")
        ),
        "background_opacity": aesthetic.get("effects", {}).get("opacity"),
        "font_size": aesthetic.get("typography", {}).get("size"),
        "window_padding_width": aesthetic.get("geometry", {}).get("padding"),
    }
    items: list[PlanItem] = []
    for parameter in catalog.parameters:
        value = values.get(parameter.name)
        if value is None:
            continue
        items.append(PlanItem(
            parameter_id=parameter.id,
            value=value,
            reason="Derived from the wallpaper design and Gemma consultation.",
        ))
    return ConfigPlan(app_id=app_id, items=items)


def build_default_plan(app_id: str, catalog: ParameterCatalog) -> ConfigPlan:
    """Create a plan from documented defaults without inventing values."""
    return ConfigPlan(
        app_id=app_id,
        items=[
            PlanItem(
                parameter_id=parameter.id,
                value=parameter.default,
                reason="Documented application default.",
            )
            for parameter in catalog.parameters
            if parameter.default is not None
        ],
    )


def _accepted_by_id(result: PlanResult) -> dict[str, tuple[Any, PlanItem]]:
    return {
        item.parameter_id: (value, item)
        for _, value, item in result.accepted
    }


def generate_design(image_path: Path) -> tuple[list[str], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run palette extraction and the unchanged Gemma mood/theme pipeline."""
    data = image_path.read_bytes()
    palette = processor.extract_palette(str(image_path))
    mood = ml_model.analyze_wallpaper(data)
    theme = ml_model.design_theme(data, mood, palette)
    aesthetic = ml_model.generate_aesthetic(data, mood, theme, palette)
    return palette, mood, theme, aesthetic


def render_final_config(
    image_path: Path,
    app_dir: Path,
    output_path: Path,
) -> tuple[PlanResult, dict[str, Any]]:
    """Generate a complete safe config from defaults plus approved overrides."""
    manifest, catalog = load_application(app_dir)
    palette, mood, theme, aesthetic = generate_design(image_path)
    generated_result = validate_plan(
        build_plan(manifest.id, catalog, theme, aesthetic),
        catalog,
        manifest,
    )
    if generated_result.rejected:
        raise ValueError(
            "generated plan was rejected: "
            + "; ".join(f"{item.parameter_id}: {reason}"
                        for item, reason in (
                            (rejection.item, rejection.reason)
                            for rejection in generated_result.rejected
                        ))
        )

    default_result = validate_plan(
        build_default_plan(manifest.id, catalog),
        catalog,
        manifest,
    )
    defaults = _accepted_by_id(default_result)
    generated = _accepted_by_id(generated_result)
    merged: list[tuple[Any, object]] = []
    accepted: list[tuple[Any, object, PlanItem]] = []
    for parameter in catalog.parameters:
        selected = generated.get(parameter.id) or defaults.get(parameter.id)
        if selected is None:
            continue
        value, item = selected
        merged.append((parameter, value))
        accepted.append((parameter, value, item))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_key_value(merged),
        encoding="utf-8",
    )
    return PlanResult(
        accepted=accepted,
        needs_review=default_result.needs_review + generated_result.needs_review,
        rejected=default_result.rejected,
    ), {
        "palette": palette,
        "mood": mood,
        "theme": theme,
        "aesthetic": aesthetic,
        "output": str(output_path),
        "generated_parameter_ids": list(generated),
        "default_parameter_ids": [
            parameter.id for parameter in catalog.parameters
            if parameter.id in defaults and parameter.id not in generated
        ],
        "unconfigured_parameter_ids": [
            parameter.id for parameter in catalog.parameters
            if parameter.id not in generated and parameter.id not in defaults
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a final config from a wallpaper and onboarded app.",
    )
    parser.add_argument("wallpaper", type=Path)
    parser.add_argument("app_dir", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result, design = render_final_config(args.wallpaper, args.app_dir, args.out)
    print(json.dumps({
        "accepted": [item.parameter_id for _, _, item in result.accepted],
        "needs_review": [item.parameter_id for _, _, item in result.needs_review],
        "unconfigured": [
            {"parameter_id": rejection.item.parameter_id, "reason": rejection.reason}
            for rejection in result.rejected
        ],
        "design": design,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
