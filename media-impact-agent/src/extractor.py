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
MAX_TOKENS = 16384

SYSTEM_PROMPT = """Du bist ein präziser Datenextraktor für Media-Impact-Mediaunterlagen.
Extrahiere strukturierte Daten für ein Sales-Agent-System.

Regeln:
- Gib AUSSCHLIESSLICH gültiges JSON zurück. Kein Markdown, keine Erklärungen.
- Fehlende Werte als null setzen, nicht raten.
- Bei der CPM-Preismatrix: jede Zeile/Spalte-Kombination als eigene price_rule.
  Die Achsen (Format-Gruppe und Paket) müssen aus den Schlüsseln klar hervorgehen.
- Erfinde niemals Werte. Lieber null als eine plausible Vermutung.
- VOLLSTÄNDIGKEIT: Erfasse das Dokument lückenlos. Bekannte Informationen kommen
  in die dafür vorgesehenen Felder. ALLES andere (unerwartete Metriken,
  Altersgruppen, Affinitäten, Sonderkonditionen, Zusatzangaben jeder Art), das
  im Dokument steht und keinem festen Feld entspricht, gehört als strukturiertes
  key-value-Objekt in "extra_data". Lieber ein Feld zu viel in extra_data als
  eines auslassen. Erfinde aber keine Werte — nur erfassen, was im Dokument steht.

Das JSON muss dieser Struktur folgen:
{
  "ad_formats": [{"format_key","name","device","ctr_pct","description",
                  "booking_options","exclusions","programmatic",
                  "required_assets","goes_well_with",
                  "extra_data": {<beliebige weitere Schlüssel-Wert-Paare>}}],
  "channels": [{"name","portals":[{"brand","sub_areas","stationary","mobile_avail"}],
                "demographics":{"male_pct","employed_pct","higher_education_pct",
                                "hhne_3000_plus_pct"},
                "reach_stationary_mio","reach_mobile_mio","reach_multiscreen_mio",
                "extra_data": {<beliebige weitere Schlüssel-Wert-Paare>}}],
  "price_rules": [{"package_group","booking_type","cpm_euro",
                   "extra_data": {<beliebige weitere Schlüssel-Wert-Paare>}}]
}
mobile_avail muss einer von: "yes", "only_mew", "no" sein.
device muss einer von: "stationary", "mobile", "multiscreen" sein.
extra_data ist immer ein Objekt ({}), niemals null oder ein Array.
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


def extract_from_pdf(
    pdf_bytes: bytes,
) -> tuple[ExtractionResult | None, str | None, str | None]:
    """Extrahiert und validiert ein PDF.

    Rückgabe: (Ergebnis, Fehlertext, rohe_Modellantwort)
    - Erfolg:  (ExtractionResult, None, raw_text)
    - Fehler:  (None, Fehlerbeschreibung, raw_text | None)
      raw_text ist None, wenn kein API-Response empfangen wurde (Netzwerk-/Auth-Fehler).
    """
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode()

    try:
        client = _client()
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
        return None, f"API-Fehler: {exc}", None
    except RuntimeError as exc:
        # z. B. fehlendes ANTHROPIC_API_KEY zur Laufzeit
        return None, f"Konfigurationsfehler: {exc}", None

    raw_text = "".join(
        block.text for block in response.content if block.type == "text"
    )

    if response.stop_reason == "max_tokens":
        return None, (
            f"Modell-Ausgabe durch max_tokens={MAX_TOKENS} abgeschnitten — "
            "das JSON ist unvollständig. "
            "Erhöhe MAX_TOKENS oder teile das Dokument in kleinere Abschnitte auf."
        ), raw_text
    elif response.stop_reason != "end_turn":
        return None, (
            f"Unerwarteter stop_reason={response.stop_reason!r} — "
            "das JSON ist möglicherweise unvollständig."
        ), raw_text

    cleaned = _strip_code_fences(raw_text)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return None, f"Antwort war kein gültiges JSON: {exc}", raw_text

    try:
        result = ExtractionResult.model_validate(data)
    except ValidationError as exc:
        return None, f"Validierung fehlgeschlagen: {exc}", raw_text

    return result, None, raw_text
