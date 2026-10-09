"""Pydantic models for the application manifest and parameter catalog.

Both top-level documents carry ``schema_version`` so a field change later is a
migration, not a rewrite.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------

class Tier(str, Enum):
    FIRST_CLASS = "first_class"
    GENERIC = "generic"


class SupportStatus(str, Enum):
    VERIFIED = "verified"          # tested templates + regression tests
    DOCUMENTED = "documented"      # catalog exists, no tests
    EXPERIMENTAL = "experimental"  # user-supplied docs only


class DocKind(str, Enum):
    OFFICIAL = "official"
    USER_URL = "user_url"
    USER_FILE = "user_file"


class DocStatus(str, Enum):
    PENDING = "pending"
    INGESTED = "ingested"
    STALE = "stale"
    FAILED = "failed"


class Capability(str, Enum):
    COLORS = "colors"
    TYPOGRAPHY = "typography"
    GEOMETRY = "geometry"
    VISUAL_EFFECTS = "visual_effects"
    LAYOUT = "layout"
    BEHAVIOR = "behavior"
    EXECUTION = "execution"
    SYSTEM = "system_modifications"
    UNKNOWN = "unknown"


class ParamType(str, Enum):
    COLOR = "color"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    ENUM = "enum"
    STRING = "string"
    FONT = "font"
    LIST = "list"


class RiskLevel(str, Enum):
    SAFE = "safe"
    REVIEW = "review"
    DENIED = "denied"


class ClassifiedBy(str, Enum):
    RULE = "rule"
    LLM = "llm"
    HUMAN = "human"


class VerificationStatus(str, Enum):
    EXTRACTED = "extracted"
    REVIEWED = "reviewed"
    TESTED = "tested"
    CONFLICT = "conflict"


class ExtractedBy(str, Enum):
    DETERMINISTIC = "deterministic"
    LLM = "llm"
    MANUAL = "manual"


class SyntaxStyle(str, Enum):
    KEY_VALUE = "key_value"      # kitty: `background #000000`
    REPEATABLE = "repeatable"    # kitty: multiple `map` lines
    TOML_PATH = "toml_path"      # alacritty: [colors.primary] background = "..."


class _Model(BaseModel):
    """Base: reject unknown fields so typos in JSON fail loudly."""
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------

class ConfigFile(_Model):
    role: str = "main"
    path: str  # may contain ~; expanded at apply time, never at load time


class ConfigSpec(_Model):
    format: str  # e.g. "kitty-conf", "toml", "unknown"
    files: list[ConfigFile] = Field(default_factory=list)


class VersionSpec(_Model):
    # Fixed argv defined by us, never user-supplied. Empty for generic apps.
    detect_argv: list[str] = Field(default_factory=list)
    documented: str | None = None
    supported_range: str | None = None


class DocSource(_Model):
    id: str
    kind: DocKind
    uri: str
    doc_version: str | None = None
    retrieved_at: str | None = None
    content_hash: str | None = None
    normalized_path: str | None = None
    status: DocStatus = DocStatus.PENDING


class CatalogInfo(_Model):
    path: str = "parameters.json"
    # source_id -> content hash the records were extracted from
    built_from: dict[str, str] = Field(default_factory=dict)
    extractor_version: str | None = None
    built_at: str | None = None


class PolicyOverrides(_Model):
    """Per-app tightening only. There is deliberately no 'allow' field."""
    deny_capabilities: list[Capability] = Field(default_factory=list)
    deny_parameters: list[str] = Field(default_factory=list)


class SupportInfo(_Model):
    status: SupportStatus = SupportStatus.EXPERIMENTAL
    renderer: str | None = None  # "builtin:kitty", "generic:toml", or None
    policy_overrides: PolicyOverrides = Field(default_factory=PolicyOverrides)


class Manifest(_Model):
    schema_version: Literal[1] = SCHEMA_VERSION
    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")]
    display_name: str
    tier: Tier
    config: ConfigSpec
    version: VersionSpec = Field(default_factory=VersionSpec)
    doc_sources: list[DocSource] = Field(default_factory=list)
    catalog: CatalogInfo = Field(default_factory=CatalogInfo)
    support: SupportInfo = Field(default_factory=SupportInfo)

    @model_validator(mode="after")
    def _check(self) -> "Manifest":
        ids = [d.id for d in self.doc_sources]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate doc source ids")

        unknown = set(self.catalog.built_from) - set(ids)
        if unknown:
            raise ValueError(f"catalog.built_from references unknown sources: {sorted(unknown)}")

        # Never claim more than the data supports.
        if self.support.status is SupportStatus.VERIFIED:
            if self.tier is not Tier.FIRST_CLASS:
                raise ValueError("only first_class apps can be 'verified'")
            if not self.support.renderer:
                raise ValueError("'verified' requires a renderer")
        if self.config.format == "unknown" and self.support.renderer:
            raise ValueError("unknown config format cannot have a renderer")
        if self.tier is Tier.GENERIC and self.support.status is not SupportStatus.EXPERIMENTAL:
            raise ValueError("generic apps must be 'experimental'")
        if self.support.renderer and not (
            self.support.renderer.startswith("builtin:")
            or self.support.renderer.startswith("generic:")
        ):
            raise ValueError("renderer must start with 'builtin:' or 'generic:'")
        return self

    def stale_sources(self) -> list[str]:
        """Source ids whose current hash differs from what the catalog was built from."""
        stale = []
        for d in self.doc_sources:
            built = self.catalog.built_from.get(d.id)
            if d.content_hash and built != d.content_hash:
                stale.append(d.id)
        return stale


# --------------------------------------------------------------------------
# Parameter records
# --------------------------------------------------------------------------

class Syntax(_Model):
    style: SyntaxStyle = SyntaxStyle.KEY_VALUE
    path: list[str] = Field(default_factory=list)  # toml_path: ["window", "padding"]


class Constraints(_Model):
    min: float | None = None
    max: float | None = None
    enum_values: list[str] | None = None
    pattern: str | None = None
    unit: str | None = None


class Risk(_Model):
    level: RiskLevel = RiskLevel.REVIEW
    reason: str | None = None
    classified_by: ClassifiedBy = ClassifiedBy.RULE


class VersionRange(_Model):
    since: str | None = None
    until: str | None = None


class SourceRef(_Model):
    source_id: str
    heading_path: list[str] = Field(default_factory=list)
    line_range: tuple[int, int] | None = None


class Verification(_Model):
    status: VerificationStatus = VerificationStatus.EXTRACTED
    extracted_by: ExtractedBy = ExtractedBy.DETERMINISTIC


class ParameterRecord(_Model):
    id: str
    name: str
    syntax: Syntax = Field(default_factory=Syntax)
    type: ParamType
    constraints: Constraints = Field(default_factory=Constraints)
    default: str | int | float | bool | None = None
    description: str = ""
    capability: Capability = Capability.UNKNOWN
    keywords: list[str] = Field(default_factory=list)
    risk: Risk = Field(default_factory=Risk)
    versions: VersionRange = Field(default_factory=VersionRange)
    sources: list[SourceRef] = Field(default_factory=list)
    verification: Verification = Field(default_factory=Verification)

    @model_validator(mode="after")
    def _check(self) -> "ParameterRecord":
        if self.type is ParamType.ENUM and not self.constraints.enum_values:
            raise ValueError("enum parameters need constraints.enum_values")
        c = self.constraints
        if c.min is not None and c.max is not None and c.min > c.max:
            raise ValueError("constraints.min > constraints.max")
        if self.syntax.style is SyntaxStyle.TOML_PATH and not self.syntax.path:
            raise ValueError("toml_path syntax requires a non-empty path")
        if self.risk.level is RiskLevel.SAFE and self.capability in (
            Capability.EXECUTION, Capability.SYSTEM, Capability.UNKNOWN
        ):
            raise ValueError(f"capability '{self.capability.value}' cannot be risk 'safe'")
        return self


class ParameterCatalog(_Model):
    schema_version: Literal[1] = SCHEMA_VERSION
    app_id: str
    parameters: list[ParameterRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> "ParameterCatalog":
        ids = [p.id for p in self.parameters]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate parameter ids: {sorted(dupes)}")
        bad = [i for i in ids if not i.startswith(self.app_id + ".")]
        if bad:
            raise ValueError(f"parameter ids must start with '{self.app_id}.': {bad}")
        return self

    def get(self, param_id: str) -> ParameterRecord | None:
        return next((p for p in self.parameters if p.id == param_id), None)


# --------------------------------------------------------------------------
# Gemma plan (output side)
# --------------------------------------------------------------------------

class PlanItem(_Model):
    parameter_id: str
    value: str | int | float | bool
    reason: str = ""
    source_ref: str | None = None
    uncertainty: str | None = None


class ConfigPlan(_Model):
    app_id: str
    items: list[PlanItem] = Field(default_factory=list)
