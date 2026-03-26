from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Match:
    term: str
    weight: float


DEFAULT_PROFILES: dict[str, list[Match]] = {
    # Starter profile for dexterous robotic hand manipulation.
    "dexterous_hand": [
        Match("in-hand", 5.0),
        Match("in hand", 5.0),
        Match("dexterous", 4.0),
        Match("dexterous hand", 5.0),
        Match("robotic hand", 4.0),
        Match("multi-finger", 4.5),
        Match("multifinger", 4.5),
        Match("multi finger", 4.0),
        Match("regrasp", 4.0),
        Match("re-grasp", 4.0),
        Match("anthropomorphic", 4.0),
        Match("anthropomorphic hand", 5.0),
        Match("five-finger", 5.0),
        Match("five finger", 5.0),
        Match("humanoid hand", 5.0),
        Match("shadow hand", 5.0),
        Match("allegro hand", 4.5),
        Match("fingertip", 3.0),
        Match("tactile", 4.5),
        Match("force-torque", 2.5),
        Match("force torque", 2.5),
        Match("grasp", 1.0),
        Match("grasping", 1.0),
        Match("manipulation", 1.0),
        Match("object manipulation", 2.0),
        Match("teleoperation", 2.5),
        Match("tele-op", 2.5),
        Match("retargeting", 3.5),
        Match("hand-object", 3.5),
        Match("hand object", 3.5),
        Match("hand pose", 2.0),
        Match("finger", 2.0),
    ],
    "general": [],
}


def score_text(text: str, profile_terms: list[Match]) -> tuple[float, list[str]]:
    if not profile_terms:
        return (0.0, [])
    hay = (text or "").lower()
    matched: list[Match] = []
    for m in profile_terms:
        if m.term in hay:
            matched.append(m)
    score = float(sum(m.weight for m in matched))
    matched_terms = [m.term for m in sorted(matched, key=lambda x: (-x.weight, x.term))]
    return (score, matched_terms)


def merge_profiles(base: dict[str, list[Match]], override: dict[str, list[Match]]) -> dict[str, list[Match]]:
    merged = dict(base)
    merged.update(override)
    return merged


def parse_profiles_from_config(cfg: dict) -> dict[str, list[Match]]:
    """
    Optional config schema:

    - profiles: { "<name>": [ {"term": "...", "weight": 1.0}, ... ], ... }

    This *replaces* that profile's term list entirely (not additive).
    """
    profiles = cfg.get("profiles")
    if profiles is None:
        return {}
    if not isinstance(profiles, dict):
        raise SystemExit("config.profiles must be an object")

    out: dict[str, list[Match]] = {}
    for name, items in profiles.items():
        if not isinstance(name, str) or not name.strip():
            raise SystemExit("config.profiles keys must be non-empty strings")
        if not isinstance(items, list):
            raise SystemExit(f"config.profiles.{name} must be a list")
        terms: list[Match] = []
        for idx, it in enumerate(items):
            if not isinstance(it, dict):
                raise SystemExit(f"config.profiles.{name}[{idx}] must be an object")
            term = it.get("term")
            weight = it.get("weight")
            if not isinstance(term, str) or not term.strip():
                raise SystemExit(f"config.profiles.{name}[{idx}].term must be a non-empty string")
            try:
                w = float(weight)
            except Exception:
                raise SystemExit(f"config.profiles.{name}[{idx}].weight must be a number")
            terms.append(Match(term=term.strip().lower(), weight=w))
        out[name.strip()] = terms
    return out

