"""extractor.py — Extrahiert strukturierte Daten aus PDFs via Claude API.

Schickt ein (geändertes) PDF an die Claude API mit einem schema-spezifischen
Prompt, parst die JSON-Antwort und validiert sie gegen die Pydantic-Schemas.
Validierung schlägt fehl -> Ergebnis geht in die Review-Queue, nicht in die DB.

Voraussetzung: Umgebungsvariable ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import base64
import json
import os

import anthropic
from pydantic import ValidationError

from schemas import ExtractionResult

MODEL = "claude-sonnet-4-6"  # Sweet Spot Preis/Qualität für Extraktion
MAX_TOKENS = 4096

SYSTEM_PROMPT = """Du bist ein präziser Datenextraktor für Media-Impact-Mediaunterlagen.
Extrahiere strukturierte Daten für ein Sales-Agent-System.

Regeln:
- Gib AUSSCHLIESSLICH gültiges JSON zurück. Kein Markdown, keine Erklärungen.
- Fehlende Werte als null setzen, nicht raten.
- Bei der CPM-Preismatrix: jede Zeile/Spalte-Kombination als eigene price_rule.
  Die Achsen (Format-Gruppe und Paket) müssen aus den Schlüsseln klar hervorgehen.
- Erfinde niemals Werte. Lieber null als eine plausible Vermutung.

Das JSON muss dieser Struktur folgen:
{
  "ad_formats": [{"format_key","name","device","ctr_pct","description",
                  "booking_options","exclusions","programmatic",
                  "required_assets","goes_well_with"}],
  "channels": [{"name","portals":[{"brand","sub_areas","stationary","mobile_avail"}],
                "demographics":{"male_pct","employed_pct","higher_education_pct",
                                "hhne_3000_plus_pct"},
                "reach_stationary_mio","reach_mobile_mio","reach_multiscreen_mio"}],
  "price_rules": [{"package_group","booking_type","cpm_euro"}]
}
mobile_avail muss einer von: "yes", "only_mew", "no" sein.
device muss einer von: "stationary", "mobile", "multiscreen" sein.
"""

USER_INSTRUCTION = (
    "Extrahiere alle Anzeigenformate, Channels (inkl. Demografie und Reichweite) "
    "und CPM-Preisregeln aus diesem Dokument. Gib nur das JSON-Objekt zurück."
)


def _client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY ist nicht gesetzt.")
    return anthropic.Anthropic()


def _strip_code_fences(text: str) -> str:
    """Entfernt versehentliche ```json ... ```-Umrandungen, falls vorhanden."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.endswith("```"):
            t = t.rsplit("```", 1)[0]
    return t.strip()


def extract_from_pdf(pdf_bytes: bytes) -> tuple[ExtractionResult | None, str | None]:
    """Extrahiert und validiert. Gibt (Ergebnis, None) bei Erfolg zurück,
    oder (None, Fehlertext) wenn etwas schiefgeht -> Review-Queue.
    """
    client = _client()
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode()

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {"type": "text", "text": USER_INSTRUCTION},
                ],
            }],
        )
    except anthropic.APIError as exc:
        return None, f"API-Fehler: {exc}"

    raw_text = "".join(
        block.text for block in response.content if block.type == "text"
    )
    cleaned = _strip_code_fences(raw_text)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return None, f"Antwort war kein gültiges JSON: {exc}"

    try:
        result = ExtractionResult.model_validate(data)
    except ValidationError as exc:
        return None, f"Validierung fehlgeschlagen: {exc}"

    return result, None
