"""Documentation-first application onboarding.

The model assists with extracting metadata, but persisted catalogs are validated
by the Pydantic schema and remain the source of truth at runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .renderers import render_template
from .schemas import (
    Capability,
    ClassifiedBy,
    ConfigFile,
    ConfigSpec,
    Constraints,
    DocKind,
    DocSource,
    DocStatus,
    ExtractedBy,
    Manifest,
    ParameterCatalog,
    ParameterRecord,
    ParamType,
    Risk,
    RiskLevel,
    SourceRef,
    SupportInfo,
    SupportStatus,
    Syntax,
    SyntaxStyle,
    Tier,
    Verification,
    VerificationStatus,
    VersionSpec,
)

EXTRACTOR_VERSION = "1"
MAX_DOCUMENT_BYTES = 2_000_000
SETTING_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
DENIED_TOKENS = {
    "exec", "execute", "shell", "command", "commands", "cmd", "script",
    "map", "keymap", "env", "environment", "include", "source", "startup",
    "remote", "launch", "hook", "hooks", "program", "pager", "path",
    "paths", "dir", "directory", "file", "files", "plugin", "plugins",
}


class _VisibleText(HTMLParser):
    """Extract visible documentation text while preserving useful line breaks."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def handle_data(self, data: str) -> None:
        for line in data.splitlines():
            line = " ".join(line.split())
            if line:
                self.lines.append(line)


def read_document(source: str, *, timeout: float = 20) -> tuple[str, DocKind]:
    """Read a local path, file URL, or HTTPS URL with a bounded response size."""
    def normalize(text: str) -> str:
        if "<html" not in text[:2000].lower():
            return text
        parser = _VisibleText()
        parser.feed(text)
        return "\n".join(parser.lines)

    parsed = urlparse(source)
    if parsed.scheme in ("", "file"):
        path = Path(parsed.path if parsed.scheme == "file" else source).expanduser()
        return normalize(path.read_text(encoding="utf-8")), DocKind.USER_FILE
    if parsed.scheme != "https":
        raise ValueError("documentation sources must be local files or HTTPS URLs")
    request = Request(source, headers={"User-Agent": "Ricifier/1"})
    with urlopen(request, timeout=timeout) as response:
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_DOCUMENT_BYTES:
            raise ValueError("documentation source is larger than the 2 MB limit")
        data = response.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError("documentation source is larger than the 2 MB limit")
    return normalize(data.decode("utf-8", errors="replace")), DocKind.USER_URL


def _source_id(index: int, source: str) -> str:
    digest = hashlib.sha256(source.encode()).hexdigest()[:10]
    return f"source-{index}-{digest}"


def _safe_name(name: str) -> bool:
    tokens = re.split(r"[_.-]", name.lower())
    return bool(SETTING_NAME.fullmatch(name)) and not any(
        token in DENIED_TOKENS for token in tokens
    )


def _infer_type(value: str) -> tuple[ParamType, Constraints, object]:
    value = value.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return ParamType.COLOR, Constraints(pattern=r"^#[0-9a-fA-F]{6}$"), value.lower()
    if value.lower() in {"true", "false", "yes", "no", "on", "off"}:
        return ParamType.BOOL, Constraints(), value.lower() in {"true", "yes", "on"}
    try:
        number = float(value)
        if "." not in value and "e" not in value.lower():
            return ParamType.INT, Constraints(), int(number)
        return ParamType.FLOAT, Constraints(), number
    except ValueError:
        pass
    return ParamType.STRING, Constraints(pattern=r"^[A-Za-z0-9_. -]{1,200}$"), value


_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20,
}


def _number(value: str) -> float:
    return float(_NUMBER_WORDS.get(value.lower(), value))


def _document_constraints(
    default_text: str,
    block: list[str],
) -> tuple[ParamType, Constraints, object, str]:
    """Infer bounds, enum values, units, and a compact description from prose."""
    param_type, constraints, default = _infer_type(default_text)
    prose = " ".join(block)
    description = prose[:500]

    unit_match = re.search(r"\b(?:in|measured in)\s+(pts?|pixels?|px|percent|%)\b", prose, re.I)
    if unit_match:
        constraints.unit = unit_match.group(1).lower()

    range_match = re.search(
        r"\b(?:between|from)\s+(-?\d+(?:\.\d+)?|[a-z]+)\s+(?:and|to)\s+(-?\d+(?:\.\d+)?|[a-z]+)",
        prose,
        re.I,
    )
    if range_match:
        try:
            constraints.min = _number(range_match.group(1))
            constraints.max = _number(range_match.group(2))
        except ValueError:
            pass

    enum_match = re.search(
        r"\b(?:can be one of|can be|may be|must be|valid values? (?:are|include)|possible values? (?:are|include)):\s*",
        prose,
        re.I,
    )
    if enum_match:
        tail = block[0:]  # preserve line boundaries for choice detection
        choices: list[str] = []
        for index, line in enumerate(tail):
            if index == 0 and enum_match.group(0).strip() not in line:
                continue
            candidate = line.strip(" ,.:;")
            if (
                re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", candidate)
                and candidate.lower() not in {"the", "a", "an", "one"}
            ):
                if index + 1 < len(tail) and tail[index + 1][:1].isupper():
                    choices.append(candidate)
        if choices:
            constraints.enum_values = list(dict.fromkeys(choices))
            param_type = ParamType.ENUM
            if default not in constraints.enum_values:
                constraints.enum_values.insert(0, str(default))

    return param_type, constraints, default, description


def _add_record(
    records: list[ParameterRecord],
    seen: set[str],
    app_id: str,
    name: str,
    default_text: str,
    source_id: str,
    line_number: int,
    block: list[str] | None = None,
) -> None:
    """Add one conservative setting if it is safe and has not been seen."""
    if not _safe_name(name) or name in seen:
        return
    seen.add(name)
    param_type, constraints, default = _infer_type(default_text)
    description = f"Configuration setting {name}."
    if block:
        param_type, constraints, default, description = _document_constraints(
            default_text, block,
        )
    capability = Capability.COLORS if param_type is ParamType.COLOR else Capability.UNKNOWN
    risk = RiskLevel.SAFE if capability is Capability.COLORS else RiskLevel.REVIEW
    records.append(ParameterRecord(
        id=f"{app_id}.{name}",
        name=name,
        syntax=Syntax(style=SyntaxStyle.KEY_VALUE),
        type=param_type,
        constraints=constraints,
        default=default,
        description=description,
        capability=capability,
        keywords=[name.replace("_", " "), name],
        risk=Risk(level=risk, classified_by=ClassifiedBy.RULE),
        sources=[SourceRef(source_id=source_id, line_range=(line_number, line_number))],
        verification=Verification(
            status=VerificationStatus.REVIEWED,
            extracted_by=ExtractedBy.DETERMINISTIC,
        ),
    ))


def extract_parameters(
    app_id: str,
    text: str,
    source_id: str,
) -> ParameterCatalog:
    """Extract conservative settings from plain text or Sphinx-style HTML text."""
    records: list[ParameterRecord] = []
    seen: set[str] = set()
    lines = text.splitlines()
    setting_markers = [
        index for index in range(1, len(lines) - 2)
        if lines[index] == "¶"
        and lines[index - 1] == lines[index + 1]
        and SETTING_NAME.fullmatch(lines[index - 1] or "")
    ]
    marker_by_name = {
        lines[index - 1]: index for index in setting_markers
    }
    for line_number, line in enumerate(lines, 1):
        match = re.match(
            r"^\s*([A-Za-z][A-Za-z0-9_.-]{0,63})\s+"
            r"(#[0-9a-fA-F]{6}|[-+]?\d+(?:\.\d+)?|true|false|yes|no|on|off)"
            r"\s*(?:#.*)?$",
            line,
            re.I,
        )
        if match and match.group(1) not in marker_by_name:
            _add_record(
                records, seen, app_id, match.group(1), match.group(2),
                source_id, line_number,
            )

    # Sphinx configuration pages commonly expose:
    # name, "¶", name, default, description.
    for marker_number, index in enumerate(setting_markers):
        name = lines[index - 1] if index else ""
        repeated_name = lines[index + 1]
        default = lines[index + 2]
        next_marker = (
            setting_markers[marker_number + 1]
            if marker_number + 1 < len(setting_markers)
            else len(lines)
        )
        block = lines[index + 3:next_marker]
        if (
            name == repeated_name
            and SETTING_NAME.fullmatch(name)
            and re.fullmatch(
                r"#[0-9a-fA-F]{6}|[-+]?\d+(?:\.\d+)?|true|false|yes|no|on|off|[A-Za-z][A-Za-z0-9_.-]*",
                default,
                re.I,
            )
        ):
            _add_record(
                records, seen, app_id, name, default, source_id, index + 2,
                block,
            )

        # Some documentation groups several settings under one heading:
        # heading, "¶", name, ",", name, "¶", name, default, name, default.
        group_end = next_marker
        group = lines[index + 1:group_end]
        for offset, candidate in enumerate(group[:-1]):
            if not SETTING_NAME.fullmatch(candidate):
                continue
            candidate_default = group[offset + 1]
            if re.fullmatch(
                r"#[0-9a-fA-F]{6}|[-+]?\d+(?:\.\d+)?|true|false|yes|no|on|off",
                candidate_default,
                re.I,
            ):
                _add_record(
                    records, seen, app_id, candidate, candidate_default,
                    source_id, index + offset + 2,
                )
    return ParameterCatalog(app_id=app_id, parameters=records)


def onboard(
    app_id: str,
    display_name: str,
    sources: list[str],
    output_dir: Path,
    *,
    config_format: str = "key-value",
    config_path: str = "~/.config/{app}/{app}.conf",
) -> dict[str, Path]:
    """Create a manifest, catalog, source snapshot, and reusable template."""
    if not re.fullmatch(r"^[a-z0-9][a-z0-9_-]*$", app_id):
        raise ValueError("app id must contain lowercase letters, numbers, '_' or '-'")
    if not sources:
        raise ValueError("at least one documentation source is required")
    if config_format != "key-value":
        raise ValueError("the first renderer supports only key-value configuration")

    output_dir.mkdir(parents=True, exist_ok=True)
    combined: list[str] = []
    doc_sources: list[DocSource] = []
    for index, source in enumerate(sources, 1):
        text, kind = read_document(source)
        source_id = _source_id(index, source)
        digest = hashlib.sha256(text.encode()).hexdigest()
        doc_sources.append(DocSource(
            id=source_id,
            kind=kind,
            uri=source,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            content_hash=digest,
            status=DocStatus.INGESTED,
        ))
        (output_dir / f"{source_id}.txt").write_text(text, encoding="utf-8")
        combined.append(text)

    source_id = doc_sources[0].id
    catalog = extract_parameters(app_id, "\n".join(combined), source_id)
    manifest = Manifest(
        id=app_id,
        display_name=display_name,
        tier=Tier.GENERIC,
        config=ConfigSpec(
            format=config_format,
            files=[ConfigFile(
                role="main",
                path=config_path.format(app=app_id),
            )],
        ),
        version=VersionSpec(),
        doc_sources=doc_sources,
        support=SupportInfo(
            status=SupportStatus.EXPERIMENTAL,
            renderer="generic:key-value",
        ),
    )
    manifest.catalog.built_from = {
        source.id: source.content_hash or "" for source in doc_sources
    }
    manifest.catalog.extractor_version = EXTRACTOR_VERSION
    manifest.catalog.built_at = datetime.now(timezone.utc).isoformat()

    paths = {
        "manifest": output_dir / "manifest.json",
        "catalog": output_dir / "parameters.json",
        "template": output_dir / "template.conf",
    }
    paths["manifest"].write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    paths["catalog"].write_text(catalog.model_dump_json(indent=2), encoding="utf-8")
    paths["template"].write_text(
        render_template(catalog.parameters), encoding="utf-8",
    )
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Onboard an application from documentation.")
    parser.add_argument("app_id")
    parser.add_argument("--name", required=True, dest="display_name")
    parser.add_argument("--docs", nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--format", default="key-value")
    parser.add_argument("--config-path", default="~/.config/{app}/{app}.conf")
    args = parser.parse_args(argv)
    paths = onboard(
        args.app_id, args.display_name, args.docs, args.out,
        config_format=args.format, config_path=args.config_path,
    )
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
