"""
CNP-OPS-004 — Rule registry.

Loads rule definitions from the YAML catalog and exposes
them as typed RuleDefinition objects. Disabled rules are
loaded but filtered from the active set.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from .models import ReflexSpec, RuleDefinition

log = logging.getLogger("cnp.ops.rules")

_CATALOG_PATH = Path(__file__).parent / "catalog" / "rules.yaml"


def _parse_reflex(raw: dict[str, Any] | None) -> ReflexSpec | None:
    if not raw:
        return None
    return ReflexSpec(
        action_type=raw["action_type"],
        payload=raw.get("payload", {}),
        safety_level=int(raw.get("safety_level", 2)),
        requires_human=bool(raw.get("requires_human", False)),
    )


def load_rules(path: Path | None = None) -> dict[str, RuleDefinition]:
    """
    Load and parse the YAML rule catalog.
    Returns a dict keyed by rule_id.
    Skips rules with enabled=false.
    """
    catalog_path = path or _CATALOG_PATH
    try:
        raw = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.error("Rule catalog not found: %s", catalog_path)
        return {}
    except yaml.YAMLError as e:
        log.error("Failed to parse rule catalog: %s", e)
        return {}

    rules: dict[str, RuleDefinition] = {}
    for entry in raw.get("rules", []):
        if not entry.get("enabled", True):
            log.debug("Rule %s is disabled — skipping", entry.get("rule_id"))
            continue
        try:
            rd = RuleDefinition(
                rule_id=entry["rule_id"],
                name=entry["name"],
                scope=entry["scope"],
                anomaly_type=entry["anomaly_type"],
                category=entry["category"],
                severity=entry["severity"],
                consecutive_hits=entry.get("when", {}).get("consecutive_hits", 1),
                suppress_for_sec=int(entry.get("suppress_for_sec", 300)),
                confidence=float(entry.get("confidence", 0.8)),
                default_reflex=_parse_reflex(entry.get("default_reflex")),
                requires_human_above_level=int(
                    entry.get("requires_human_above_level", 3)
                ),
                enabled=bool(entry.get("enabled", True)),
            )
            rules[rd.rule_id] = rd
        except (KeyError, TypeError, ValueError) as exc:
            log.error("Skipping malformed rule entry %s: %s", entry.get("rule_id"), exc)

    log.info("Loaded %d active rules from catalog", len(rules))
    return rules


# Module-level singleton — loaded once at import time.
# Tests can reload by calling load_rules(custom_path) directly.
RULES: dict[str, RuleDefinition] = load_rules()


def get_rule(rule_id: str) -> RuleDefinition | None:
    return RULES.get(rule_id)


def active_node_rules() -> list[RuleDefinition]:
    return [r for r in RULES.values() if r.scope == "node"]


def active_zone_rules() -> list[RuleDefinition]:
    return [r for r in RULES.values() if r.scope == "zone"]
