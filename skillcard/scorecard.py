"""scorecard.py -- render a card to a deterministic SVG scorecard.

Maps ``card.json`` to a single bordered "skill scorecard" graphic: identity
(name/version/status), summary, and the four quality lenses (triggering, quality,
cost, security) plus a provenance footer. The card is composed with Rich
renderables and rendered headless through Textual's pilot
(:meth:`textual.app.App.run_test`) so the screen can be exported to SVG with no
TTY -- the one thing a CI asset step needs. The export goes through Rich's
:meth:`rich.console.Console.export_svg` with a chrome-free template
(:data:`_CARD_SVG_FORMAT`) rather than Textual's ``export_screenshot``, which
would wrap every card in a fake macOS terminal window (frame, title bar, and
traffic-light dots) -- redundant on top of the card's own border. Output is
deterministic (byte-identical across runs) because the pilot disables animation
and the export emits stable element ids and a fixed embedded font, so a committed
scorecard never churns while its ``card.json`` is unchanged.

A single colour-threshold config (:data:`THRESHOLDS`) drives every value's
colour, mirroring :mod:`skillcard.badges` -- same shape (a severity map plus
descending numeric floors), but Rich colour names rather than shields names,
since the render target differs.

The contract mirrors badges: a renderer never raises on missing card data. Most
cards are sparse -- ``metrics`` is required only for ``status: stable`` cards, so
draft/beta cards omit the whole block, and ``tool_call_delta`` / ``token_efficiency``
are optional everywhere. Absent metrics degrade to a muted "not yet measured"
line or an "n/a" cell; the identity, summary, security, and provenance always
render. Reads directly from the card, so there is no second source of truth.

:func:`render_card` renders one skill; :func:`render_rollup` renders a corpus
summary (an aggregate security/scoring posture across a cabinet's cards). The
counting stays in the caller; both share this module's layout so the SVG look is
defined in one place.
"""

from __future__ import annotations

import asyncio
import io
from typing import Any

from rich.console import Console, Group
from rich.table import Table
from rich.text import Text

NA = "grey50"  # muted grey, reserved for absent/unknown data only

# The single colour-threshold config that drives the scorecard, in Rich colour
# names. Mirrors skillcard.badges.THRESHOLDS in shape so the two stay in step.
THRESHOLDS = {
    # lifecycle status -> dot colour for the header marker.
    "status": {
        "stable": "green",
        "beta": "yellow",
        "draft": "grey50",
        "deprecated": "red",
    },
    # scan severity band -> colour (scan is required, always present).
    "severity": {
        "LOW": "green",
        "MEDIUM": "yellow",
        "HIGH": "orange1",
        "CRITICAL": "red",
    },
    # triggering + quality share these numeric bands: descending (floor, colour),
    # first floor <= value wins. The 0.0 floor guarantees a hit for any value in
    # [0, 1], so muted grey is reserved exclusively for absent data.
    "numeric": [
        (0.90, "green"),
        (0.80, "chartreuse1"),
        (0.70, "yellow"),
        (0.60, "gold1"),
        (0.0, "red"),
    ],
}

# Headless canvas geometry. The card is a fixed 64 cells wide (see the CSS), so
# SIM_WIDTH leaves one cell of margin each side. Height is fitted to the card per
# render (a measure pass, then a snug pass) so a sparse card is cropped to its
# content instead of floating in dead space; MEASURE_HEIGHT is a generous canvas
# for the measure pass (never clips) and V_MARGIN is the breathing room kept
# around the fitted card. Everything here is constant, so the fit is deterministic.
SIM_WIDTH = 66
MEASURE_HEIGHT = 60
V_MARGIN = 2

# A chrome-free SVG template for Rich's ``Console.export_svg``. Textual's
# ``export_screenshot`` calls ``export_svg`` with Rich's default format, which
# wraps the output in a fake macOS terminal window (a rounded frame, a title bar,
# and three traffic-light dots) -- redundant on top of the card's own border and
# reads as a screenshot artifact. This template keeps Rich's font + cell layout
# but drops the chrome: the viewBox is the content box (``terminal_width`` x
# ``terminal_height``), the matrix sits at the origin, and the card's own
# ``$surface`` background (painted per cell by Textual) is the only backdrop. The
# braces Rich fills are single; literal CSS braces are doubled for ``str.format``.
_CARD_SVG_FORMAT = """<svg class="skill-scorecard" viewBox="0 0 {terminal_width} {terminal_height}" xmlns="http://www.w3.org/2000/svg">
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


def _export_clean(app) -> str:
    """Export the running app's screen to SVG with no terminal-window chrome.

    Mirrors :meth:`textual.app.App.export_screenshot` (build a recording Rich
    console, print the screen render), but exports through
    :meth:`rich.console.Console.export_svg` with :data:`_CARD_SVG_FORMAT` instead
    of Rich's default, so the result is just the card -- no window frame, title
    bar, or traffic-light dots. ``title=""`` keeps Rich's deterministic
    content-hashed ``unique_id`` stable across runs.
    """
    width, height = app.size
    console = Console(
        width=width,
        height=height,
        file=io.StringIO(),
        force_terminal=True,
        color_system="truecolor",
        record=True,
        legacy_windows=False,
        safe_box=False,
    )
    screen_render = app.screen._compositor.render_update(
        full=True, screen_stack=app.app._background_screens, simplify=False
    )
    console.print(screen_render)
    return console.export_svg(title="", code_format=_CARD_SVG_FORMAT)


def _band_color(value: float, bands: list[tuple[float, str]]) -> str:
    """First colour whose floor is <= value (bands are ordered descending)."""
    for floor, color in bands:
        if value >= floor:
            return color
    return NA  # unreachable while bands end at a 0.0 floor


def _bar(value: float, width: int = 18) -> str:
    """A unicode meter: filled blocks for *value* in [0, 1], the rest light."""
    filled = max(0, min(width, round(value * width)))
    return "█" * filled + "░" * (width - filled)


def _metric_rows(rows: list[tuple[str, float | None]]) -> Table:
    """A label / value / bar grid. A ``None`` value renders a muted 'n/a' row."""
    t = Table.grid(expand=True)
    t.add_column(justify="left", width=13)
    t.add_column(justify="right", width=6)
    t.add_column(justify="left")
    for label, value in rows:
        if value is None:
            t.add_row(Text("  " + label), Text("n/a", style=NA), Text(""))
            continue
        color = _band_color(value, THRESHOLDS["numeric"])
        t.add_row(
            Text("  " + label),
            Text(f"{value:.2f}"),
            Text("  " + _bar(value), style=color),
        )
    return t


def _kv_rows(rows: list[tuple[str, str | None, str]]) -> Table:
    """A label / value grid. A ``None`` value renders a muted 'n/a' cell."""
    t = Table.grid(expand=True)
    t.add_column(justify="left", width=13)
    t.add_column(justify="left")
    for label, value, style in rows:
        if value is None:
            t.add_row(Text("  " + label), Text("n/a", style=NA))
            continue
        t.add_row(Text("  " + label), Text(value, style=style))
    return t


def _header(card: dict[str, Any]) -> Table:
    name = card.get("name", "?")
    version = card.get("version", "")
    status = card.get("status", "draft")
    dot = THRESHOLDS["status"].get(status, NA)
    t = Table.grid(expand=True)
    t.add_column(justify="left")
    t.add_column(justify="right")
    t.add_row(
        Text.assemble((name, "bold white"), (f"  v{version}", "dim")),
        Text.assemble(("● ", dot), (status, "white")),
    )
    return t


def _provenance(card: dict[str, Any]) -> str:
    """The footer line: the metrics harness if measured, else the scan source."""
    metrics = card.get("metrics") or {}
    harness = metrics.get("harness")
    if harness:
        return f"harness  {harness}"
    scan = card.get("scan") or {}
    tool = scan.get("tool", "?")
    date = scan.get("date", "")
    return f"scan  {tool} · {date}"


def _security_cell(card: dict[str, Any]) -> tuple[str, str]:
    """The security one-liner ``<score> / <severity>`` and its colour."""
    scan = card.get("scan") or {}
    severity = scan.get("severity")
    if not severity:
        return ("n/a", NA)
    score = scan.get("score")
    color = THRESHOLDS["severity"].get(severity, NA)
    return (f"{score} / {severity}", color)


def _body(card: dict[str, Any]) -> Group:
    """Assemble the card's renderable. Optional sections degrade, never crash."""
    parts: list[Any] = [
        _header(card),
        Text(card.get("summary", ""), style="dim italic"),
        Text(""),
    ]

    metrics = card.get("metrics")
    if metrics:
        near = metrics.get("near_miss_precision")
        trig: list[tuple[str, float | None]] = [
            ("Precision", metrics.get("trigger_precision")),
            ("Recall", metrics.get("trigger_recall")),
        ]
        if near is not None:
            trig.append(("Near-miss", near))
        parts += [
            Text("TRIGGERING", style="bold cyan"),
            _metric_rows(trig),
            Text(""),
            Text("QUALITY", style="bold cyan"),
            _metric_rows(
                [
                    ("Task pass", metrics.get("task_completion_rate")),
                    ("Eval pass", metrics.get("eval_pass_rate")),
                ]
            ),
            Text(""),
            Text("COST", style="bold cyan"),
            _kv_rows(
                [
                    ("Tool calls", _delta(metrics.get("tool_call_delta")), "yellow"),
                    ("Tokens", _pct_delta(metrics.get("token_efficiency")), "yellow"),
                ]
            ),
            Text(""),
        ]
    else:
        parts += [
            Text("QUALITY", style="bold cyan"),
            Text("  not yet measured — beta", style="dim italic"),
            Text(""),
        ]

    sec_msg, sec_color = _security_cell(card)
    parts += [
        Text("SECURITY", style="bold cyan"),
        _kv_rows([("SkillSpector", sec_msg, sec_color)]),
        Text(""),
        Text(_provenance(card), style="dim"),
    ]
    return Group(*parts)


def _delta(value: float | None) -> str | None:
    """A signed tool-call delta vs baseline, or ``None`` when unmeasured."""
    if value is None:
        return None
    return f"{value:+.1f} vs baseline"


def _pct_delta(value: float | None) -> str | None:
    """A signed token delta (a fraction) as a percent, or ``None`` if absent."""
    if value is None:
        return None
    return f"{value:+.0%} vs baseline"


SEVERITY_ORDER = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def _rollup_body(summary: dict[str, Any]) -> Group:
    """Assemble the aggregate rollup renderable from a corpus *summary* dict.

    *summary* keys: ``title``, ``total``, ``carded``, ``with_metrics``,
    ``severity_counts`` ({band: n}), ``worst``. Every field degrades: a corpus
    with nothing carded still renders a valid (empty) posture.
    """
    title = summary.get("title", "corpus")
    total = summary.get("total", 0)
    carded = summary.get("carded", 0)
    counts = summary.get("severity_counts") or {}
    worst = summary.get("worst")

    header = Table.grid(expand=True)
    header.add_column(justify="left")
    header.add_column(justify="right")
    header.add_row(
        Text(title, style="bold white"),
        Text(f"{carded}/{total} carded", style="dim"),
    )

    sev = Table.grid(expand=True)
    sev.add_column(justify="left", width=12)
    sev.add_column(justify="right", width=4)
    sev.add_column(justify="left")
    for band in SEVERITY_ORDER:
        n = int(counts.get(band, 0))
        color = THRESHOLDS["severity"][band]
        meter = ("█" * n) if n else ""
        # A zero band is muted so the eye lands on the bands that are populated.
        style = color if n else NA
        sev.add_row(Text("  " + band), Text(str(n), style=style), Text("  " + meter, style=color))

    worst_color = THRESHOLDS["severity"].get(worst, NA) if worst else NA
    parts: list[Any] = [
        header,
        Text("Security posture across the carded corpus.", style="dim italic"),
        Text(""),
        Text("SECURITY", style="bold cyan"),
        sev,
        _kv_rows([("Worst band", worst or "n/a", worst_color)]),
        Text(""),
        Text("SCORING", style="bold cyan"),
        _kv_rows(
            [("Full metrics", f"{summary.get('with_metrics', 0)}/{carded} skills", "white")]
        ),
        Text(""),
        Text("generated · skillcard scorecard", style="dim"),
    ]
    return Group(*parts)


def _build_app(card: dict[str, Any], *, rollup: bool = False):
    """A one-screen Textual app showing the card. Imported lazily (heavy dep)."""
    from textual.app import App, ComposeResult
    from textual.containers import Container
    from textual.widgets import Static

    body = _rollup_body(card) if rollup else _body(card)
    title = "SKILL SCORECARDS" if rollup else "SKILL SCORECARD"

    class _Scorecard(App):
        CSS = """
        Screen { align: center middle; }
        #card {
            width: 64;
            height: auto;
            border: round cyan;
            border-title-color: cyan;
            padding: 0 1;
            background: $surface;
        }
        """

        def compose(self) -> ComposeResult:
            c = Container(Static(body), id="card")
            c.border_title = title
            yield c

    return _Scorecard()


async def _render_async(payload: dict[str, Any], *, rollup: bool) -> str:
    # Pass 1 -- measure: lay the card out on a tall canvas and read its height,
    # so the final SVG is cropped to the content rather than floating in dead
    # space. Pass 2 -- render: re-render on a canvas sized to the card + margin.
    measure = _build_app(payload, rollup=rollup)
    async with measure.run_test(size=(SIM_WIDTH, MEASURE_HEIGHT)) as pilot:
        await pilot.pause()
        card_height = measure.query_one("#card").outer_size.height
    app = _build_app(payload, rollup=rollup)
    async with app.run_test(size=(SIM_WIDTH, card_height + V_MARGIN)) as pilot:
        await pilot.pause()
        return _export_clean(app)


def render_card(card: dict[str, Any]) -> str:
    """Render a parsed ``card.json`` to a deterministic SVG string.

    *card* is a parsed card dict (validate it with
    :meth:`schema.schema.SkillCard.model_validate` first). Never raises on
    missing optional metrics: absent sections degrade to muted placeholders.
    Requires the ``scorecard`` extra (``pip install califa-cards[scorecard]``);
    Textual is imported lazily so the rest of the package needs it only here.
    """
    return asyncio.run(_render_async(card, rollup=False))


def render_rollup(summary: dict[str, Any]) -> str:
    """Render a corpus *summary* to a deterministic aggregate-scorecard SVG.

    The cabinet-side counterpart to :func:`render_card`: it takes an already
    aggregated *summary* (``title``, ``total``, ``carded``, ``with_metrics``,
    ``severity_counts``, ``worst``) rather than a single card, so the
    file-walking and counting stay in the cabinet while the rendering stays
    here -- one home for the SVG layout. Never raises; an empty corpus renders
    a valid empty posture.
    """
    return asyncio.run(_render_async(summary, rollup=True))
