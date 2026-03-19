from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "output" / "pdf"
PDF_PATH = OUTPUT_DIR / "neuralclaw-app-summary.pdf"


TITLE = "NeuralClaw App Summary"
SUBTITLE = "Repo-based one-page overview"

WHAT_IT_IS = (
    "NeuralClaw is a Python agent framework and runtime built around five cortices: "
    "Perception, Memory, Reasoning, Action, and Evolution. The repo packages a CLI, "
    "gateway service, provider routing, memory stores, skills, browser and desktop "
    "control, and federation support."
)

WHO_ITS_FOR = (
    "Primary user: developers building or operating Python-based AI agents that need "
    "multi-channel chat, tool use, memory, browser or desktop automation, and optional "
    "swarm or federation capabilities."
)

WHAT_IT_DOES = [
    "Runs an interactive CLI chat client and a long-running gateway service.",
    "Routes requests across OpenAI, Anthropic, OpenRouter, proxy, local, and session-backed providers.",
    "Connects Telegram, Discord, Slack, Signal, WhatsApp, and Web channel adapters.",
    "Applies intake, intent classification, threat screening, vision, and output filtering.",
    "Stores episodic, semantic, procedural, identity, and optional vector memory.",
    "Executes built-in skills plus browser and desktop automation actions.",
    "Adds observability, audit replay, dashboard surfaces, and swarm or federation flows.",
]

HOW_IT_WORKS = [
    "Entry points: `neuralclaw` CLI commands in `cli.py`; runtime orchestration in `gateway.py`.",
    "Flow: channel adapter -> trust controller -> perception -> memory retrieval -> fast-path or deliberate or reflective reasoning -> action -> output filter -> delivery, storage, audit, and evolution ticks.",
    "Coordination: `NeuralBus` publishes events; `Telemetry` and `Traceline` consume them for logs and traces.",
    "Core services: provider router, skill registry, policy engine, idempotency store, audit logger, and health checks.",
    "Data layer: SQLite-backed episodic, semantic, procedural, identity, and traceline stores with optional vector memory.",
    "Optional subsystems: session runtime, dashboard, browser cortex, desktop cortex, delegation mesh, consensus, and federation bridge.",
]

HOW_TO_RUN = [
    "Prereq: Python 3.12+.",
    "Install from the checkout: `pip install -e .`",
    "If using browser-session providers: `python -m playwright install chromium`",
    "Initialize config and provider credentials: `neuralclaw init`",
    "Start a local chat: `neuralclaw chat`",
    "Start configured channels and services: `neuralclaw gateway`",
]

EVIDENCE = (
    "Evidence: README.md | docs/architecture.md | docs/getting-started.md | "
    "pyproject.toml | neuralclaw/cli.py | neuralclaw/gateway.py"
)


def wrap_text(text: str, font_name: str, font_size: float, max_width: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if stringWidth(trial, font_name, font_size) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_wrapped_text(
    canv: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    font_name: str,
    font_size: float,
    leading: float,
    color=colors.HexColor("#243042"),
) -> float:
    canv.setFillColor(color)
    canv.setFont(font_name, font_size)
    for line in wrap_text(text, font_name, font_size, width):
        canv.drawString(x, y, line)
        y -= leading
    return y


def draw_bullets(
    canv: canvas.Canvas,
    items: list[str],
    x: float,
    y: float,
    width: float,
    font_name: str = "Helvetica",
    font_size: float = 8.4,
    leading: float = 10.2,
    bullet_indent: float = 11,
) -> float:
    canv.setFillColor(colors.HexColor("#243042"))
    canv.setFont(font_name, font_size)
    for item in items:
        wrapped = wrap_text(item, font_name, font_size, width - bullet_indent)
        canv.drawString(x, y, "-")
        for idx, line in enumerate(wrapped):
            canv.drawString(x + bullet_indent, y - (idx * leading), line)
        y -= leading * len(wrapped) + 2
    return y


def draw_section_box(
    canv: canvas.Canvas,
    title: str,
    x: float,
    y_top: float,
    width: float,
    height: float,
    fill: colors.Color = colors.HexColor("#F6F8FB"),
) -> tuple[float, float]:
    canv.setFillColor(fill)
    canv.setStrokeColor(colors.HexColor("#D6DDE8"))
    canv.roundRect(x, y_top - height, width, height, 10, fill=1, stroke=1)
    canv.setFillColor(colors.HexColor("#0E3A5D"))
    canv.setFont("Helvetica-Bold", 10)
    canv.drawString(x + 12, y_top - 18, title)
    return x + 12, y_top - 34


def build_pdf() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    page_width, page_height = letter
    canv = canvas.Canvas(str(PDF_PATH), pagesize=letter)
    canv.setTitle(TITLE)

    margin = 0.42 * inch
    gutter = 0.22 * inch
    col_width = (page_width - (2 * margin) - gutter) / 2

    canv.setFillColor(colors.white)
    canv.rect(0, 0, page_width, page_height, fill=1, stroke=0)

    canv.setFillColor(colors.HexColor("#0E3A5D"))
    canv.roundRect(margin, page_height - 0.95 * inch, page_width - 2 * margin, 0.62 * inch, 14, fill=1, stroke=0)
    canv.setFillColor(colors.white)
    canv.setFont("Helvetica-Bold", 19)
    canv.drawString(margin + 16, page_height - 0.58 * inch, TITLE)
    canv.setFont("Helvetica", 9)
    canv.drawString(margin + 16, page_height - 0.78 * inch, SUBTITLE)
    canv.drawRightString(page_width - margin - 16, page_height - 0.58 * inch, "v0.8.0")
    canv.setFont("Helvetica", 8)
    canv.drawRightString(page_width - margin - 16, page_height - 0.78 * inch, "Python framework")

    left_x = margin
    right_x = margin + col_width + gutter
    top_y = page_height - 1.1 * inch

    # Left column
    inner_x, inner_y = draw_section_box(canv, "What It Is", left_x, top_y, col_width, 92)
    inner_y = draw_wrapped_text(canv, WHAT_IT_IS, inner_x, inner_y, col_width - 24, "Helvetica", 8.7, 11.2)

    inner_x, inner_y = draw_section_box(canv, "Who It's For", left_x, top_y - 102, col_width, 74)
    inner_y = draw_wrapped_text(canv, WHO_ITS_FOR, inner_x, inner_y, col_width - 24, "Helvetica", 8.7, 11.2)

    inner_x, inner_y = draw_section_box(canv, "What It Does", left_x, top_y - 186, col_width, 240)
    draw_bullets(canv, WHAT_IT_DOES, inner_x, inner_y, col_width - 24)

    inner_x, inner_y = draw_section_box(canv, "How To Run", left_x, top_y - 436, col_width, 184)
    draw_bullets(canv, HOW_TO_RUN, inner_x, inner_y, col_width - 24)

    # Right column
    inner_x, inner_y = draw_section_box(canv, "How It Works", right_x, top_y, col_width, 426)
    draw_bullets(canv, HOW_IT_WORKS, inner_x, inner_y, col_width - 24)

    inner_x, inner_y = draw_section_box(canv, "Repo Evidence", right_x, top_y - 436, col_width, 104)
    draw_wrapped_text(canv, EVIDENCE, inner_x, inner_y, col_width - 24, "Helvetica", 8.2, 10.5, color=colors.HexColor("#4A5568"))

    footer_y = 22
    canv.setStrokeColor(colors.HexColor("#D6DDE8"))
    canv.line(margin, footer_y + 8, page_width - margin, footer_y + 8)
    canv.setFillColor(colors.HexColor("#667085"))
    canv.setFont("Helvetica", 7.5)
    canv.drawString(margin, footer_y - 2, "Generated from repository evidence only.")
    canv.drawRightString(page_width - margin, footer_y - 2, str(PDF_PATH.relative_to(ROOT)))

    canv.showPage()
    canv.save()
    return PDF_PATH


if __name__ == "__main__":
    path = build_pdf()
    print(path)
