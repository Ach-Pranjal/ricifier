"""Deterministic policy: what may be generated, retrieved, and accepted.

Nothing here calls a model. The model only proposes; this module decides.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .schemas import (
    Capability,
    ClassifiedBy,
    ConfigPlan,
    ExtractedBy,
    Manifest,
    ParameterCatalog,
    ParameterRecord,
    ParamType,
    PlanItem,
    RiskLevel,
    VerificationStatus,
)

# Strictness order: higher wins.
_RANK = {RiskLevel.SAFE: 0, RiskLevel.REVIEW: 1, RiskLevel.DENIED: 2}

# Default risk per capability (the taxonomy table from the handoff).
CAPABILITY_DEFAULT: dict[Capability, RiskLevel] = {
    Capability.COLORS: RiskLevel.SAFE,
    Capability.TYPOGRAPHY: RiskLevel.SAFE,
    Capability.GEOMETRY: RiskLevel.SAFE,       # bounds come from constraints
    Capability.VISUAL_EFFECTS: RiskLevel.SAFE,
    Capability.LAYOUT: RiskLevel.SAFE,         # bounds come from constraints
    Capability.BEHAVIOR: RiskLevel.REVIEW,
    Capability.EXECUTION: RiskLevel.DENIED,
    Capability.SYSTEM: RiskLevel.DENIED,
    Capability.UNKNOWN: RiskLevel.DENIED,      # denied until reviewed
}


def _strictest(*levels: RiskLevel) -> RiskLevel:
    return max(levels, key=lambda lv: _RANK[lv])


def effective_risk(param: ParameterRecord, manifest: Manifest) -> RiskLevel:
    """Capability default + app overrides + the parameter's own risk; strictest wins."""
    levels = [CAPABILITY_DEFAULT[param.capability], param.risk.level]
    ov = manifest.support.policy_overrides
    if param.capability in ov.deny_capabilities or param.id in ov.deny_parameters:
        levels.append(RiskLevel.DENIED)
    return _strictest(*levels)


def reclassify(param: ParameterRecord, new_level: RiskLevel, by: ClassifiedBy,
               reason: str | None = None) -> ParameterRecord:
    """Change a parameter's risk. An LLM may raise risk but never lower it."""
    lowering = _RANK[new_level] < _RANK[param.risk.level]
    if lowering and by is ClassifiedBy.LLM:
        raise PermissionError("an LLM classification may not lower a parameter's risk")
    updated = param.model_copy(deep=True)
    updated.risk.level = new_level
    updated.risk.classified_by = by
    updated.risk.reason = reason
    return updated


# --------------------------------------------------------------------------
# Versions
# --------------------------------------------------------------------------

def _vtuple(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v)
    if not nums:
        raise ValueError(f"unparseable version: {v!r}")
    return tuple(int(n) for n in nums)


def version_in_range(installed: str | None, since: str | None, until: str | None) -> bool:
    """True if `installed` is within [since, until]. Unknown installed version passes."""
    if installed is None:
        return True
    cur = _vtuple(installed)
    if since and cur < _vtuple(since):
        return False
    if until and cur > _vtuple(until):
        return False
    return True


# --------------------------------------------------------------------------
# Eligibility and retrieval
# --------------------------------------------------------------------------

def eligibility(param: ParameterRecord, manifest: Manifest,
                installed_version: str | None = None,
                allow_review: bool = False) -> tuple[bool, str]:
    """Can this parameter be offered to the model / accepted in a plan?"""
    # `==` rather than `is`: these are str enums, so a plain string assigned
    # after construction (pydantic does not re-validate on assignment) still compares correctly.
    if param.verification.status == VerificationStatus.CONFLICT:
        return False, "conflicting documentation"
    if (param.verification.extracted_by == ExtractedBy.LLM
            and param.verification.status == VerificationStatus.EXTRACTED):
        return False, "LLM-extracted record has not been reviewed"
    if not version_in_range(installed_version, param.versions.since, param.versions.until):
        return False, f"not available in version {installed_version}"
    risk = effective_risk(param, manifest)
    if risk is RiskLevel.DENIED:
        return False, "denied by policy"
    if risk is RiskLevel.REVIEW and not allow_review:
        return False, "requires opt-in review"
    return True, "ok"


_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def retrieve(catalog: ParameterCatalog, manifest: Manifest, query: str, *,
             installed_version: str | None = None,
             capabilities: set[Capability] | None = None,
             allow_review: bool = False,
             limit: int = 20) -> list[ParameterRecord]:
    """Keyword retrieval. Policy filtering happens BEFORE scoring, so denied or
    out-of-version parameters can never reach the model."""
    q = _tokens(query)
    scored: list[tuple[int, ParameterRecord]] = []
    for p in catalog.parameters:
        ok, _ = eligibility(p, manifest, installed_version, allow_review)
        if not ok:
            continue
        if capabilities and p.capability not in capabilities:
            continue
        score = 0
        score += 3 * len(q & _tokens(p.name.replace("_", " ")))
        score += 2 * len(q & _tokens(" ".join(p.keywords)))
        score += 1 * len(q & _tokens(p.description))
        if capabilities or score > 0:
            scored.append((score, p))
    scored.sort(key=lambda t: (-t[0], t[1].id))
    return [p for _, p in scored[:limit]]


# --------------------------------------------------------------------------
# Value validation
# --------------------------------------------------------------------------

_DEFAULT_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_FORBIDDEN_CHARS = re.compile(r"[\x00-\x1f\x7f]")  # blocks newline/CR injection of extra config lines
_MAX_STRING = 200


def validate_value(param: ParameterRecord, value: object) -> tuple[bool, object, str | None]:
    """Return (ok, normalized_value, error). Pure function, no side effects."""
    c = param.constraints
    t = param.type

    def fail(msg: str) -> tuple[bool, object, str | None]:
        return False, None, msg

    if t is ParamType.LIST:
        return fail("list parameters are not supported yet")

    if t is ParamType.BOOL:
        if isinstance(value, bool):
            return True, value, None
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return True, value.lower() == "true", None
        return fail("expected a boolean")

    if t is ParamType.INT:
        if isinstance(value, bool):
            return fail("expected an integer")
        if isinstance(value, float):
            if not value.is_integer():
                return fail("expected an integer")
            value = int(value)
        try:
            num = int(value)  # accepts ints and numeric strings like "12"
        except (TypeError, ValueError):
            return fail("expected an integer")
        if c.min is not None and num < c.min:
            return fail(f"below minimum {c.min:g}")
        if c.max is not None and num > c.max:
            return fail(f"above maximum {c.max:g}")
        return True, num, None

    if t is ParamType.FLOAT:
        if isinstance(value, bool):
            return fail("expected a number")
        try:
            fnum = float(value)
        except (TypeError, ValueError):
            return fail("expected a number")
        if fnum != fnum or fnum in (float("inf"), float("-inf")):
            return fail("expected a finite number")
        if c.min is not None and fnum < c.min:
            return fail(f"below minimum {c.min:g}")
        if c.max is not None and fnum > c.max:
            return fail(f"above maximum {c.max:g}")
        return True, fnum, None

    # Remaining types are text-like: color, enum, string, font.
    if not isinstance(value, str):
        return fail("expected a string")
    if _FORBIDDEN_CHARS.search(value):
        return fail("control characters (including newlines) are not allowed")
    if len(value) > _MAX_STRING:
        return fail(f"longer than {_MAX_STRING} characters")
    text = value.strip()
    if not text:
        return fail("empty value")

    if t is ParamType.COLOR:
        pattern = re.compile(c.pattern) if c.pattern else _DEFAULT_COLOR
        if not pattern.fullmatch(text):
            return fail("not a valid color")
        return True, text.lower(), None

    if t is ParamType.ENUM:
        if text not in (c.enum_values or []):
            return fail(f"must be one of {c.enum_values}")
        return True, text, None

    if c.pattern and not re.fullmatch(c.pattern, text):
        return fail("does not match the required pattern")
    return True, text, None


# --------------------------------------------------------------------------
# Plan validation
# --------------------------------------------------------------------------

@dataclass
class Rejection:
    item: PlanItem
    reason: str


@dataclass
class PlanResult:
    accepted: list[tuple[ParameterRecord, object, PlanItem]] = field(default_factory=list)
    needs_review: list[tuple[ParameterRecord, object, PlanItem]] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)


def validate_plan(plan: ConfigPlan, catalog: ParameterCatalog, manifest: Manifest, *,
                  installed_version: str | None = None,
                  allowed_ids: set[str] | None = None) -> PlanResult:
    """Check every item against the catalog and policy.

    `allowed_ids` is the set of parameter ids that were actually retrieved and
    shown to the model; anything outside it is out of scope and rejected.
    """
    result = PlanResult()
    seen: set[str] = set()

    if plan.app_id != manifest.id:
        for it in plan.items:
            result.rejected.append(Rejection(it, "plan is for a different application"))
        return result

    for it in plan.items:
        param = catalog.get(it.parameter_id)
        if param is None:
            result.rejected.append(Rejection(it, "unknown parameter"))
            continue
        if allowed_ids is not None and it.parameter_id not in allowed_ids:
            result.rejected.append(Rejection(it, "outside the requested scope"))
            continue
        if it.parameter_id in seen:
            result.rejected.append(Rejection(it, "duplicate parameter in plan"))
            continue

        # Review-level params are checked with allow_review=True, then routed to needs_review.
        ok, why = eligibility(param, manifest, installed_version, allow_review=True)
        if not ok:
            result.rejected.append(Rejection(it, why))
            continue

        valid, norm, err = validate_value(param, it.value)
        if not valid:
            result.rejected.append(Rejection(it, f"invalid value: {err}"))
            continue

        seen.add(it.parameter_id)
        if effective_risk(param, manifest) is RiskLevel.REVIEW:
            result.needs_review.append((param, norm, it))
        else:
            result.accepted.append((param, norm, it))
    return result
