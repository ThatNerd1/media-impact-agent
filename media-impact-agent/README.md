# Media Impact Sales Agent — Phase 1

Pipeline, die Mediadaten von der Media-Impact-Website scrapt, aus PDFs
strukturierte Daten extrahiert und für einen späteren Sales-Agenten aufbereitet.

## Aufbau (Phase 1)

```
media-impact-agent/
├── CLAUDE.md            Anweisungen für Claude Code (inkl. Codex-Review-Workflow)
├── requirements.txt     Python-Abhängigkeiten
├── README.md            diese Datei
└── src/
    ├── crawler.py       findet PDFs, lädt sie, Hash-Diffing
    ├── schemas.py       Pydantic-Modelle + Plausibilitätsregeln (Qualität)
    └── extractor.py     PDF -> Claude API -> validiertes JSON
```

## Setup

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt
```

API-Key als Umgebungsvariable setzen (niemals in den Code):

```bash
# Windows (PowerShell):
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

## Workflow: Code baut, Codex kontrolliert

Dieses Projekt nutzt zwei Coding-Agenten. Claude Code schreibt den Code; nach
jeder fertigen Datei lässt es sie von Codex reviewen:

```bash
codex exec "Review die Datei src/crawler.py auf Fehler und Sicherheitsprobleme. Kurze, konkrete Punkteliste."
```

Die genaue Regel steht in `CLAUDE.md`. Vor dem ersten automatischen Einsatz
einmal von Hand testen, dass `codex exec "..."` sauber eine Antwort liefert.

## Nächste Schritte (noch offen)

- Seitenliste in `crawler.py` um die echten Übersichtsseiten (Display, Specs,
  Brands) erweitern, damit alle relevanten PDFs gefunden werden.
- HTML-Spec-Seiten unter `/specs/` separat parsen (sind bereits strukturiert,
  brauchen kein LLM).
- Datenbank-Schicht (Phase 2): PostgreSQL-Schema + Schreiben der validierten
  Daten, inkl. `source_documents` mit `content_hash` und `run_id`.
- Review-Queue für fehlgeschlagene Validierungen.
- Wöchentlicher Zeitplan (Phase 2): Azure Function mit Timer-Trigger.

## Rechtlicher Hinweis

Vor produktivem, wiederkehrendem Scraping die robots.txt und Nutzungsbedingungen
von Media Impact prüfen und im Zweifel den Betreiber kontaktieren.
