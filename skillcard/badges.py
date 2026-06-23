"""badges.py -- map a card to shields.io endpoint JSON (SPEC.md section F).

Maps ``card.json`` to the shields.io endpoint payload
``{schemaVersion: 1, label, message, color}`` per metric (scan, trigger, tasks,
signed, card). A single color-threshold config (:data:`THRESHOLDS`) drives every
badge. Shields requires every served endpoint to return HTTP 200, so the
contract is "always a valid badge dict": a metrics-absent card (draft/beta/
deprecated cards may omit the metrics block) yields a neutral grey "n/a" badge
for the numeric metrics rather than raising. Reads directly from the card, so
there is no second source of truth.
"""

from __future__ import annotations

from typing import Any

NA_COLOR = "lightgrey"  # neutral grey, reserved for absent/unknown data only

# The single color-threshold config that drives every badge.
THRESHOLDS = {
    # scan: severity band -> shields color (scan is required, always present).
    "severity": {
        "LOW": "brightgreen",
        "MEDIUM": "yellow",
        "HIGH": "orange",
        "CRITICAL": "red",
    },
    # trigger + tasks share these numeric bands: descending (floor, color),
    # first floor <= value wins. The 0.0 floor guarantees a hit for any present
    # value in [0, 1], so grey "n/a" is reserved exclusively for absent data.
    "numeric": [
        (0.90, "brightgreen"),
        (0.80, "green"),
        (0.70, "yellowgreen"),
        (0.60, "yellow"),
        (0.0, "orange"),
    ],
    "signed": "blue",
    "card": "informational",
}

METRICS = ("scan", "trigger", "tasks", "signed", "card")


def _make(label: str, message: str, color: str) -> dict[str, Any]:
    """A shields endpoint payload with the four keys in canonical order."""
    return {"schemaVersion": 1, "label": label, "message": message, "color": color}


def _neutral(label: str) -> dict[str, Any]:
    """The grey 'n/a' badge: the servable result when a metric is absent."""
    return _make(label, "n/a", NA_COLOR)


def _band_color(value: float, bands: list[tuple[float, str]]) -> str:
    """First color whose floor is <= value (bands are ordered descending)."""
    for floor, color in bands:
        if value >= floor:
            return color
    return NA_COLOR  # unreachable while bands end at a 0.0 floor


def _scan_badge(card: dict[str, Any]) -> dict[str, Any]:
    severity = (card.get("scan") or {}).get("severity")
    if not severity:
        return _neutral("scan")
    return _make("scan", severity, THRESHOLDS["severity"].get(severity, NA_COLOR))


def _trigger_badge(card: dict[str, Any]) -> dict[str, Any]:
    metrics = card.get("metrics") or {}
    precision = metrics.get("trigger_precision")
    recall = metrics.get("trigger_recall")
    if precision is None or recall is None:
        return _neutral("trigger")
    message = f"P {precision:.2f} / R {recall:.2f}"
    color = _band_color((precision + recall) / 2, THRESHOLDS["numeric"])
    return _make("trigger", message, color)


def _tasks_badge(card: dict[str, Any]) -> dict[str, Any]:
    rate = (card.get("metrics") or {}).get("task_completion_rate")
    if rate is None:
        return _neutral("tasks")
    return _make("tasks", f"{round(rate * 100)}%", _band_color(rate, THRESHOLDS["numeric"]))


def _signed_badge(card: dict[str, Any]) -> dict[str, Any]:
    # v1/v2 integrity is content_hash + a signed git tag + the human review tick,
    # so the message is "hash+tag"; "oms" is reserved for v3 once a cryptographic
    # signature is present in the card.
    message = "oms" if card.get("signature") else "hash+tag"
    return _make("signed", message, THRESHOLDS["signed"])


def _card_badge(card: dict[str, Any]) -> dict[str, Any]:
    version = card.get("card_version")
    if not version:
        return _neutral("card")
    return _make("card", version, THRESHOLDS["card"])


_BUILDERS = {
    "scan": _scan_badge,
    "trigger": _trigger_badge,
    "tasks": _tasks_badge,
    "signed": _signed_badge,
    "card": _card_badge,
}


def badge(card: dict[str, Any], metric: str) -> dict[str, Any]:
    """Build one shields endpoint badge for *metric* from a parsed ``card.json``.

    Never raises on missing card data: an absent metrics block yields a neutral
    grey "n/a" badge so the served endpoint can still return HTTP 200. An unknown
    *metric* name is a caller error and raises :class:`ValueError`.
    """
    try:
        builder = _BUILDERS[metric]
    except KeyError:
        raise ValueError(
            f"unknown badge metric {metric!r}; expected one of {', '.join(METRICS)}"
        ) from None
    return builder(card)


def all_badges(card: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """All five badges keyed by metric name. Never raises."""
    return {metric: badge(card, metric) for metric in METRICS}
