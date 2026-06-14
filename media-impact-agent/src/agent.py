"""agent.py — Media Impact Sales Agent (Anthropic tool-use loop).

Reads ANTHROPIC_API_KEY and DATABASE_URL from environment variables.
Entry point: run_agent(user_query) -> str
"""

from __future__ import annotations

import json
import os
from typing import Any

import anthropic

from agent_tools import (
    find_channels_by_demographics,
    find_formats,
    find_portals_by_topic,
    get_prices,
)

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

_TOOL_FN_MAP = {
    "find_channels_by_demographics": find_channels_by_demographics,
    "find_formats": find_formats,
    "get_prices": get_prices,
    "find_portals_by_topic": find_portals_by_topic,
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "find_channels_by_demographics",
        "description": (
            "Sucht nach Media-Impact-Channels (Themenumfelder), die demographische "
            "und Reichweiten-Kriterien erfüllen. Gibt Channel-Namen mit Reichweiten "
            "(Mio. Unique User) und Demographie-Prozentsätzen zurück."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "min_male_pct": {
                    "type": "integer",
                    "description": "Mindestanteil männlicher Nutzer in Prozent (0–100).",
                },
                "min_hhne_3000_pct": {
                    "type": "integer",
                    "description": (
                        "Mindestanteil der Nutzer mit Haushalts-Nettoeinkommen ≥ 3000 € "
                        "in Prozent (0–100)."
                    ),
                },
                "min_reach_multiscreen_mio": {
                    "type": "number",
                    "description": "Mindest-Multiscreen-Reichweite in Mio. Unique User.",
                },
                "min_reach_stationary_mio": {
                    "type": "number",
                    "description": "Mindest-Desktop-Reichweite in Mio. Unique User.",
                },
                "min_reach_mobile_mio": {
                    "type": "number",
                    "description": "Mindest-Mobile-Reichweite in Mio. Unique User.",
                },
                "min_employed_pct": {
                    "type": "integer",
                    "description": "Mindestanteil berufstätiger Nutzer in Prozent (0–100).",
                },
                "min_higher_edu_pct": {
                    "type": "integer",
                    "description": "Mindestanteil Nutzer mit höherem Bildungsabschluss in Prozent (0–100).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "find_formats",
        "description": (
            "Sucht nach Anzeigenformaten nach Gerätekategorie und Performance-Metriken. "
            "Gibt Format-Name, Gerät, durchschnittliche CTR, Programmatic-Verfügbarkeit "
            "und Qualitätsbewertungen (1–5) zurück."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device": {
                    "type": "string",
                    "enum": ["stationary", "mobile", "multiscreen"],
                    "description": "Ziel-Gerätekategorie.",
                },
                "min_ctr_pct": {
                    "type": "number",
                    "description": "Mindest-CTR in Prozent (z. B. 0.5 für 0,5 %).",
                },
                "min_rating_viewability": {
                    "type": "integer",
                    "description": "Mindest-Viewability-Bewertung (1–5).",
                },
                "min_rating_interactivity": {
                    "type": "integer",
                    "description": "Mindest-Interaktivitäts-Bewertung (1–5).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_prices",
        "description": (
            "Gibt aktuell gültige CPM-Preisregeln in Euro zurück (valid_until IS NULL). "
            "Optionaler Filter auf package_group (Teilstring, case-insensitive). "
            "CPM-Preise beziehen sich auf Run-of-Channel-Buchungen."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "package_group": {
                    "type": "string",
                    "description": (
                        "Teilname der Format-Gruppe zur Filterung, "
                        "z. B. 'Mobile Content' oder 'Fireplace'."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "find_portals_by_topic",
        "description": (
            "Findet Channel-Portale (Marke + Channel-Kombination), deren sub_areas-Array "
            "das gesuchte Thema enthält. Nützlich für thematisches Targeting, "
            "z. B. 'Sport', 'Games', 'Auto', 'Reise'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": (
                        "Thema-Stichwort, das in den Portal-Sub-Areas gesucht wird, "
                        "z. B. 'Sport', 'Games', 'Auto'."
                    ),
                },
            },
            "required": ["topic"],
        },
    },
]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """Du bist ein erfahrener Media-Sales-Berater für Media Impact, \
den größten deutschen Digital-Vermarkter (Axel Springer, Funke, u.a.).

Deine Aufgabe ist es, Werbekunden bei der Auswahl der optimalen Channels, \
Anzeigenformate und Budgets zu beraten.

Verbindliche Regeln:
1. Antworte AUSSCHLIESSLICH auf Basis der Tool-Ergebnisse. Erfinde niemals \
   Reichweiten, Demografie-Werte, Format-Namen oder Preise.
2. Wenn ein Tool leere Ergebnisse liefert, sage das klar und empfehle \
   alternative Filter — aber erfinde keine Daten.
3. Begründe jede Empfehlung konkret: nenne Reichweite, Demografie-Werte \
   und CPM aus den Tool-Daten.
4. Fasse deine finale Empfehlung in 2–3 prägnanten Sätzen zusammen.
5. Antworte auf Deutsch, wenn der Nutzer auf Deutsch schreibt; auf Englisch, \
   wenn der Nutzer auf Englisch schreibt.
"""

# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def _call_tool(name: str, tool_input: dict[str, Any]) -> str:
    fn = _TOOL_FN_MAP.get(name)
    if fn is None:
        return json.dumps({"error": f"Unbekanntes Tool: {name}"}, ensure_ascii=False)
    result = fn(**tool_input)
    return json.dumps(result, ensure_ascii=False, default=str)


def run_agent(user_query: str, *, max_iterations: int = 10) -> str:
    """Run the sales agent and return the final text recommendation."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_query}]

    for _ in range(max_iterations):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Append the assistant turn so the next request has full context.
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            for block in response.content:
                if block.type == "text":
                    return block.text
            return ""

        if response.stop_reason != "tool_use":
            break

        # Execute all tool calls and collect results.
        tool_results: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "tool_use":
                result_str = _call_tool(block.name, block.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    }
                )

        messages.append({"role": "user", "content": tool_results})

    return "Entschuldigung, ich konnte keine abschließende Antwort generieren."
