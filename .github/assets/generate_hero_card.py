#!/usr/bin/env python3
"""Generate the README hero: a Textual-rendered skill card for califa-cards.

Califa Cards defines the skill-card format, so its hero is the standard applied to
itself — a meta "califa-cards" card rendered in the same dark Textual style as the
per-skill scorecards. The QUALITY block is repurposed as a legend that demonstrates
the colour scale every real metric is graded on (green at 0.90+ down to red below
0.60); the SECURITY block carries the project's real SkillSpector self-scan result.

The card is composed with Rich renderables and rendered headless through Textual's
pilot, then exported via Rich's ``Console.export_svg`` with a chrome-free template
(no fake terminal window) — the same approach as ``skillcard.scorecard``. Output is
a single dark SVG, deterministic (byte-identical across runs), committed as
``hero-card.svg`` and referenced at the top of the README. GitHub renders the
``<style>``-based SVG via ``<img>`` fine; it only strips ``@media`` theme queries,
so the card is dark in both light and dark mode (the intended terminal aesthetic).

Requires Textual (``pip install textual==8.2.7``). Run:
    python3 .github/assets/generate_hero_card.py
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any

from rich.console import Console, Group
from rich.table import Table
from rich.text import Text

NA = "grey50"

# The single colour-threshold config, in Rich colour names — the same scale the
# scorecard renderer uses, and the one the QUALITY legend below illustrates.
THRESHOLDS = {
    "status": {"stable": "green", "beta": "yellow", "draft": "grey50", "deprecated": "red"},
    "severity": {"LOW": "green", "MEDIUM": "yellow", "HIGH": "orange1", "CRITICAL": "red"},
    "numeric": [(0.90, "green"), (0.80, "chartreuse1"), (0.70, "yellow"), (0.60, "gold1"), (0.0, "red")],
}

# Headless canvas geometry; height is fitted to the card (measure pass, then a snug
# pass) so the SVG crops to the content. The card is 74 cells wide.
SIM_WIDTH = 78
MEASURE_HEIGHT = 90
V_MARGIN = 2

# The colour-scale legend shown in place of real QUALITY metrics: one row per band,
# a representative score that lands in that band, so the bar takes the band's colour.
QUALITY_LEGEND = [("≥ 0.90", 0.95), ("≥ 0.80", 0.85), ("≥ 0.70", 0.75),
                  ("≥ 0.60", 0.65), ("< 0.60", 0.45)]

# --- the card -----------------------------------------------------------------

CARD: dict[str, Any] = {
    "title": "SKILL CARD",
    "name": "califa-cards",
    "version": "0.9.1",
    "status": "beta",
    "summary": "A portable, versioned format for documenting and scoring Claude Skills "
               "— carded by its own standard.",
    "when": "Use to give a Claude skill a machine-readable card: identity and provenance, "
            "triggering, measured quality, and a SkillSpector scan — generated from the "
            "skill's own inputs and gated in CI so the card can't drift from the truth.",
    "output": {"type": "Card", "format": "card.json (machine) + skill-card.md (human view)"},
    "dependencies": ["pydantic>=2", "jinja2>=3", "pyyaml>=6", "python>=3.12"],
    "quality_legend": True,
    "scan": {"score": 13, "severity": "LOW",
             "note": "self-scan of the skillcard package, gated by `make check` on every change"},
    "footer": "spec + tooling · self-carded · skillspector@a5092dd",
}


def _band_color(value: float) -> str:
    for floor, color in THRESHOLDS["numeric"]:
        if value >= floor:
            return color
    return NA


def _bar(value: float, width: int = 20) -> str:
    filled = max(0, min(width, round(value * width)))
    return "█" * filled + "░" * (width - filled)


def _metric_rows(rows: list[tuple[str, float]]) -> Table:
    t = Table.grid(expand=True)
    t.add_column(justify="left", width=13)
    t.add_column(justify="right", width=6)
    t.add_column(justify="left")
    for label, value in rows:
        t.add_row(Text("  " + label), Text(f"{value:.2f}"),
                  Text("  " + _bar(value), style=_band_color(value)))
    return t


def _kv_rows(rows: list[tuple[str, str, str]]) -> Table:
    t = Table.grid(expand=True)
    t.add_column(justify="left", width=13)
    t.add_column(justify="left")
    for label, value, style in rows:
        t.add_row(Text("  " + label), Text(value, style=style))
    return t


def _header_row(card: dict[str, Any]) -> Table:
    dot = THRESHOLDS["status"].get(card["status"], NA)
    t = Table.grid(expand=True)
    t.add_column(justify="left")
    t.add_column(justify="right")
    t.add_row(
        Text.assemble((card["name"], "bold white"), (f"  v{card['version']}", "dim")),
        Text.assemble(("● ", dot), (card["status"], "white")),
    )
    return t


def _section(title: str) -> Text:
    return Text(title, style="bold cyan")


def _body(card: dict[str, Any]) -> Group:
    parts: list[Any] = [
        _header_row(card),
        Text(card["summary"], style="dim italic"),
        Text(""),
        _section("WHEN TO USE"),
        Text("  " + card["when"], style="dim"),
        Text(""),
    ]
    out = card["output"]
    parts += [
        _section("OUTPUT"),
        _kv_rows([("Type", out["type"], "white"), ("Format", out["format"], "white")]),
        Text(""),
        _section("DEPENDENCIES"),
        *[Text("  " + dep, style="white") for dep in card["dependencies"]],
        Text(""),
    ]
    if card.get("quality_legend"):
        parts += [
            _section("QUALITY"),
            Text("  the colour scale every metric is graded on", style="dim italic"),
            _metric_rows(QUALITY_LEGEND),
        ]
    elif card.get("metrics"):
        m = card["metrics"]
        rows = [("Precision", m["trigger_precision"]), ("Recall", m["trigger_recall"])]
        if m.get("near_miss_precision") is not None:
            rows.append(("Near-miss", m["near_miss_precision"]))
        rows += [("Task pass", m["task_completion_rate"]), ("Eval pass", m["eval_pass_rate"])]
        parts += [_section("QUALITY"), _metric_rows(rows)]
    parts.append(Text(""))
    sev = card["scan"]["severity"]
    parts += [
        _section("SECURITY"),
        _kv_rows([("SkillSpector", f"{card['scan']['score']} / {sev}",
                   THRESHOLDS["severity"].get(sev, NA))]),
        Text("  " + card["scan"]["note"], style="dim"),
        Text(""),
        Text(card["footer"], style="dim"),
    ]
    return Group(*parts)


# Chrome-free Rich export template: the card on its own border, no fake terminal
# window (frame / title bar / traffic-light dots). Single braces are Rich fields;
# literal CSS braces are doubled for ``str.format``.
_CARD_SVG_FORMAT = """<svg class="skill-hero" viewBox="0 0 {terminal_width} {terminal_height}" xmlns="http://www.w3.org/2000/svg">
    <style>
    @font-face {{
        font-family: "Fira Code";
        src: local("FiraCode-Regular"),
                url("https://cdnjs.cloudflare.com/ajax/libs/firacode/6.2.0/woff2/FiraCode-Regular.woff2") format("woff2"),
                url("https://cdnjs.cloudflare.com/ajax/libs/firacode/6.2.0/woff/FiraCode-Regular.woff") format("woff");
        font-style: normal;
        font-weight: 400;
    }}
    @font-face {{
        font-family: "Fira Code";
        src: local("FiraCode-Bold"),
                url("https://cdnjs.cloudflare.com/ajax/libs/firacode/6.2.0/woff2/FiraCode-Bold.woff2") format("woff2"),
                url("https://cdnjs.cloudflare.com/ajax/libs/firacode/6.2.0/woff/FiraCode-Bold.woff") format("woff");
        font-style: bold;
        font-weight: 700;
    }}
    .{unique_id}-matrix {{
        font-family: Fira Code, monospace;
        font-size: {char_height}px;
        line-height: {line_height}px;
        font-variant-east-asian: full-width;
    }}
    {styles}
    </style>
    <defs>
    <clipPath id="{unique_id}-clip-terminal">
      <rect x="0" y="0" width="{terminal_width}" height="{terminal_height}" />
    </clipPath>
    {lines}
    </defs>
    <g clip-path="url(#{unique_id}-clip-terminal)">
    {backgrounds}
    <g class="{unique_id}-matrix">
    {matrix}
    </g>
    </g>
</svg>
"""


def _build_app(card: dict[str, Any]):
    from textual.app import App, ComposeResult
    from textual.containers import Container
    from textual.widgets import Static

    body = _body(card)

    class _Hero(App):
        CSS = """
        Screen { align: center middle; }
        #card {
            width: 74;
            height: auto;
            border: round cyan;
            border-title-color: cyan;
            padding: 1 2;
            background: $surface;
        }
        """

        def compose(self) -> ComposeResult:
            container = Container(Static(body), id="card")
            container.border_title = card["title"]
            yield container

    return _Hero()


def _export_clean(app) -> str:
    """Export the running app's screen to SVG with no terminal-window chrome."""
    width, height = app.size
    console = Console(width=width, height=height, file=io.StringIO(), force_terminal=True,
                      color_system="truecolor", record=True, legacy_windows=False, safe_box=False)
    console.print(app.screen._compositor.render_update(
        full=True, screen_stack=app.app._background_screens, simplify=False))
    return console.export_svg(title="", code_format=_CARD_SVG_FORMAT)


async def _render(card: dict[str, Any]) -> str:
    measure = _build_app(card)
    async with measure.run_test(size=(SIM_WIDTH, MEASURE_HEIGHT)) as pilot:
        await pilot.pause()
        card_height = measure.query_one("#card").outer_size.height
    app = _build_app(card)
    async with app.run_test(size=(SIM_WIDTH, card_height + V_MARGIN)) as pilot:
        await pilot.pause()
        return _export_clean(app)


def main() -> None:
    out = Path(__file__).resolve().parent / "hero-card.svg"
    out.write_text(asyncio.run(_render(CARD)), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
