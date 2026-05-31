"""Anthropic client wrapper for EIA section drafting.

The LLM only ever sees the already-computed metrics and risk scores and is
instructed to write *from* them, never to invent environmental data. If no API
key is configured or any call fails, this module reports unavailability and the
caller falls back to deterministic templates.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger("impatika.llm")

SYSTEM_PROMPT = """You are Impatika, an AI Environmental Impact Assessment (EIA) engine.
You draft EIA report sections for planners and consultants.

Hard rules:
- Write ONLY from the metrics, risk scores and project data provided. Never invent
  species, protected areas, datasets, figures or citations.
- Where the data says a layer is unavailable or a value is "not assessed", state that
  explicitly as a data gap rather than filling it in.
- Reference the specific computed metrics and risk levels in your prose.
- Align recommendations with IFC Performance Standards / World Bank ESF / EU EIA
  Directive conventions, but do NOT give legal advice — environmental guidance only.
- Be professional, scientific, evidence-based and concise. No filler.
"""


def is_available() -> bool:
    return bool(settings.anthropic_api_key)


def generate_report_sections(
    context: dict[str, Any],
    sections: list[dict[str, str]],
    model: str | None = None,
) -> dict[str, str] | None:
    """Return {section_id: markdown_body} for each requested section, or None
    if the LLM is unavailable or the call fails."""
    if not is_available():
        return None

    try:
        from anthropic import Anthropic
    except ImportError:
        logger.warning("anthropic package not installed; using template fallback.")
        return None

    section_spec = "\n".join(f"- {s['id']}: {s['title']} — {s['guidance']}" for s in sections)
    user_prompt = (
        "Draft the following EIA report sections for the assessment below.\n\n"
        f"SECTIONS (write each one):\n{section_spec}\n\n"
        "ASSESSMENT DATA (JSON — your only source of facts):\n"
        f"{json.dumps(context, indent=2, default=str)}\n\n"
        "Return ONLY a JSON object whose keys are the section ids above and whose "
        "values are the markdown body for that section (no headings inside the value). "
        "Do not wrap the JSON in code fences."
    )

    try:
        client = Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=model or settings.impatika_model,
            max_tokens=4096,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
        return _parse_sections(text, sections)
    except Exception as exc:  # noqa: BLE001 — any API/parse failure falls back to templates
        logger.warning("LLM drafting failed (%s); using template fallback.", exc)
        return None


def _parse_sections(text: str, sections: list[dict[str, str]]) -> dict[str, str] | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        logger.warning("LLM response was not JSON; using template fallback.")
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        logger.warning("Could not parse LLM JSON; using template fallback.")
        return None
    ids = {s["id"] for s in sections}
    result = {k: str(v) for k, v in data.items() if k in ids and v}
    return result or None
