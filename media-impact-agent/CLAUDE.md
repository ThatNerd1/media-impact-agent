# CLAUDE.md — Projektanweisungen für Claude Code

## Projektziel
Eine Pipeline, die Mediadaten von der Media-Impact-Website scrapt, aus PDFs
strukturierte Daten extrahiert und sie in eine relationale Datenbank schreibt.
Diese Daten bilden später die Basis für einen Sales-Agenten. Das System läuft
regelmäßig (wöchentlich), um aktuell zu bleiben.

Aktueller Stand: **Phase 1** — Crawler + Extraktions-Pipeline.

## Arbeitsweise: Code baut, Codex kontrolliert
Dieses Projekt nutzt einen Zwei-Agenten-Workflow zur Qualitätssicherung:
- **Claude Code (du)** schreibst und änderst den Code.
- **Codex** (OpenAIs CLI) reviewt jede fertige Datei als unabhängige zweite Meinung.

### Verbindliche Regel
Nachdem du eine Code-Datei erstellt oder wesentlich geändert hast, MUSST du sie
von Codex reviewen lassen, bevor du die Aufgabe als erledigt betrachtest. Rufe
dazu im Terminal auf:

```bash
codex exec "Review die Datei <PFAD> auf Korrektheit, Fehler, Sicherheitsprobleme und Robustheit. Gib eine kurze, konkrete Liste von Punkten aus. Wenn alles in Ordnung ist, sage das explizit."
```

Lies die Ausgabe von Codex (sie kommt auf stdout), arbeite berechtigte Punkte
ein und dokumentiere kurz, was du übernommen oder bewusst verworfen hast. Bei
Uneinigkeit entscheidest du begründet — du musst nicht jeden Vorschlag umsetzen.

### Wichtig
- Führe `codex exec` immer mit einer präzisen, eng umrissenen Frage aus.
- Übergib keine Geheimnisse (API-Keys) im Prompt-Text.
- Codex läuft auf Windows in einer eingeschränkten Sandbox — es reviewt lesend,
  schreibt aber nicht selbst am Code. Das Schreiben bleibt bei dir.

## Technische Leitplanken
- Sprache: Python 3.11+
- Abhängigkeiten in `requirements.txt` pflegen.
- Secrets (z. B. ANTHROPIC_API_KEY) NUR aus Umgebungsvariablen lesen,
  niemals im Code hardcoden, niemals committen.
- Vor jedem Netzwerkzugriff auf Media Impact: robots.txt und Nutzungsbedingungen
  respektieren; höfliche Rate-Limits einhalten (Pause zwischen Requests).
- Extrahierte Daten immer gegen ein Schema validieren (Pydantic), bevor sie
  weiterverarbeitet werden. Fehlgeschlagene Validierung -> Review-Queue, nicht
  stillschweigend verwerfen.

## Priorität
Datenqualität und Wartbarkeit vor Geschwindigkeit. Lieber ein Dokument korrekt
ablehnen als falsch übernehmen.
