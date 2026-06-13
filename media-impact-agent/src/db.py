"""db.py — Datenbankzugang für die Media-Impact-Pipeline."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import psycopg
from pydantic import ValidationError

from schemas import ExtractionResult

_SCHEMA_SQL = Path(__file__).parent.parent / "sql" / "schema.sql"

# Alle Tabellen, die schema.sql anlegen muss. Wird nach apply_schema() geprüft,
# damit ein Teilabbruch früh und mit klarer Meldung auffällt.
_EXPECTED_TABLES: frozenset[str] = frozenset({
    "pipeline_runs",
    "source_documents",
    "ad_formats",
    "format_booking_options",
    "format_exclusions",
    "format_assets",
    "format_combinations",
    "brands",
    "channels",
    "channel_portals",
    "price_rules",
    "review_queue",
})


@dataclass
class SourceDoc:
    """Metadaten eines heruntergeladenen Quelldokuments."""
    url: str
    content_hash: str
    doc_type: str = "pdf"
    filename: Optional[str] = None


def _connect() -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_URL"])


def _split_sql_statements(sql: str) -> list[str]:
    """Zerlegt ein SQL-Skript in Einzelstatements.

    Behandelt korrekt: -- Kommentare, $tag$ Dollar-Quotes (PL/pgSQL-Blöcke),
    Semikolons als Statement-Trennzeichen.
    """
    statements: list[str] = []
    buf: list[str] = []
    pos = 0
    n = len(sql)

    while pos < n:
        # -- Zeilenkommentar: bis Zeilenende überspringen (aber im Buffer behalten)
        if sql[pos : pos + 2] == "--":
            end = sql.find("\n", pos)
            segment = sql[pos:] if end == -1 else sql[pos : end + 1]
            buf.append(segment)
            pos = n if end == -1 else end + 1
            continue

        # /* ... */ Block-Kommentar: komplett überspringen
        if sql[pos : pos + 2] == "/*":
            end = sql.find("*/", pos + 2)
            segment = sql[pos:] if end == -1 else sql[pos : end + 2]
            buf.append(segment)
            pos = n if end == -1 else end + 2
            continue

        # $tag$ Dollar-Quote — findet öffnendes und schließendes Tag und
        # überspringt alles dazwischen (verhindert falsche ; Splits in PL/pgSQL)
        if sql[pos] == "$":
            close = sql.find("$", pos + 1)
            if close != -1:
                tag = sql[pos : close + 1]
                if re.match(r"^\$[A-Za-z0-9_]*\$$", tag):
                    end_tag = sql.find(tag, close + 1)
                    if end_tag != -1:
                        chunk = sql[pos : end_tag + len(tag)]
                        buf.append(chunk)
                        pos = end_tag + len(tag)
                        continue

        # Semikolon = Statement-Ende
        if sql[pos] == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            pos += 1
            continue

        buf.append(sql[pos])
        pos += 1

    # Letztes Statement ohne abschließendes Semikolon
    stmt = "".join(buf).strip()
    if stmt:
        statements.append(stmt)

    return statements


def apply_schema() -> None:
    """Wendet sql/schema.sql idempotent auf die Datenbank an.

    Läuft im Autocommit-Modus, weil CREATE EXTENSION IF NOT EXISTS innerhalb
    eines expliziten BEGIN/COMMIT auf manchen PostgreSQL-Setups fehlschlägt.

    Teilfehler-Verhalten: Bricht ein Statement mittendrin ab, bleiben die
    bereits ausgeführten DDL-Statements committed (kein Rollback möglich).
    Das ist unkritisch, weil alle Statements IF NOT EXISTS / CREATE OR REPLACE
    verwenden — ein erneuter Aufruf von apply_schema() bringt die DB sicher
    in den vollständigen Zielzustand.

    Nach der Ausführung prüft die Funktion, ob alle erwarteten Tabellen
    vorhanden sind (_EXPECTED_TABLES). Fehlt eine, wird ein RuntimeError
    mit klarer Meldung geworfen, der zum erneuten Aufruf auffordert — statt
    die Pipeline erst bei einem INSERT/SELECT scheitern zu lassen.
    """
    sql = _SCHEMA_SQL.read_text(encoding="utf-8")
    stmts = _split_sql_statements(sql)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        for stmt in stmts:
            conn.execute(stmt)

        # Vollständigkeits-Check: alle erwarteten Tabellen müssen existieren.
        rows = conn.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
              AND table_name = ANY(%s)
            """,
            (list(_EXPECTED_TABLES),),
        ).fetchall()
        found = {row[0] for row in rows}
        missing = _EXPECTED_TABLES - found
        if missing:
            raise RuntimeError(
                f"Schema unvollständig — fehlende Tabellen: {sorted(missing)}. "
                "Führe apply_schema() erneut aus, um die Initialisierung "
                "abzuschließen."
            )


def write_extraction_result(
    run_id: int,
    pdf: SourceDoc,
    result: ExtractionResult | str,
) -> str:
    """Schreibt ein Extraktionsergebnis atomar in die Datenbank.

    Args:
        run_id: ID des laufenden Pipeline-Laufs (pipeline_runs.id).
        pdf:    Metadaten des Quelldokuments (URL, Hash, Typ).
        result: Validiertes ExtractionResult-Objekt ODER roher JSON-String
                aus der API-Antwort (wird intern geparst und validiert).

    Returns:
        'skipped'  — URL + Content-Hash bereits bekannt; keine Aktion.
        'ok'       — Daten erfolgreich in die DB geschrieben.
        'error'    — JSON- oder Validierungsfehler; Eintrag in review_queue.
    """
    with _connect() as conn:
        cur = conn.cursor()

        # 1. Hash-Diffing + Quelldokument in einem atomaren Statement:
        # ON CONFLICT (url, content_hash) DO NOTHING gibt kein RETURNING zurück →
        # source_id ist None → "skipped". Kein separates SELECT nötig, kein Race.
        cur.execute(
            """
            INSERT INTO source_documents (run_id, url, filename, doc_type, content_hash)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (url, content_hash) DO NOTHING
            RETURNING id
            """,
            (run_id, pdf.url, pdf.filename, pdf.doc_type, pdf.content_hash),
        )
        row = cur.fetchone()
        if row is None:
            return "skipped"
        source_id: str = row[0]

        # 3. Parsen + Validieren (nur bei Roh-String aus der API)
        if isinstance(result, str):
            raw = result
            try:
                extraction = ExtractionResult.model_validate(json.loads(raw))
            except json.JSONDecodeError as exc:
                cur.execute(
                    """
                    INSERT INTO review_queue (source_id, error_type, error_detail, raw_response)
                    VALUES (%s, 'json_parse', %s, %s)
                    """,
                    (source_id, str(exc), raw),
                )
                return "error"
            except ValidationError as exc:
                cur.execute(
                    """
                    INSERT INTO review_queue (source_id, error_type, error_detail, raw_response)
                    VALUES (%s, 'validation', %s, %s)
                    """,
                    (source_id, exc.json(), raw),
                )
                return "error"
        else:
            extraction = result

        # 4. Anzeigenformate + Sub-Tabellen (Buchungsoptionen, Ausschlüsse, Assets, Kombinationen)
        for fmt in extraction.ad_formats:
            cur.execute(
                """
                INSERT INTO ad_formats
                    (source_id, format_key, name, device, description, ctr_pct, programmatic)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (format_key) DO UPDATE
                    SET name         = EXCLUDED.name,
                        source_id    = EXCLUDED.source_id,
                        description  = EXCLUDED.description,
                        ctr_pct      = EXCLUDED.ctr_pct,
                        programmatic = EXCLUDED.programmatic,
                        updated_at   = now()
                RETURNING id
                """,
                (
                    source_id, fmt.format_key, fmt.name, fmt.device,
                    fmt.description, fmt.ctr_pct, fmt.programmatic,
                ),
            )
            fmt_id: str = cur.fetchone()[0]

            for opt in fmt.booking_options:
                cur.execute(
                    "INSERT INTO format_booking_options (format_id, option_name)"
                    " VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (fmt_id, opt),
                )
            for excl in fmt.exclusions:
                cur.execute(
                    "INSERT INTO format_exclusions (format_id, exclusion)"
                    " VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (fmt_id, excl),
                )
            for asset in fmt.required_assets:
                cur.execute(
                    "INSERT INTO format_assets (format_id, asset_name)"
                    " VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (fmt_id, asset),
                )
            for combo in fmt.goes_well_with:
                cur.execute(
                    "INSERT INTO format_combinations (format_id, pairs_well_with)"
                    " VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (fmt_id, combo),
                )

        # 5. Channels + Brands (get-or-create) + Channel-Portale
        for ch in extraction.channels:
            demo = ch.demographics
            cur.execute(
                """
                INSERT INTO channels
                    (source_id, name,
                     reach_stationary_mio, reach_mobile_mio, reach_multiscreen_mio,
                     demo_male_pct, demo_employed_pct,
                     demo_higher_edu_pct, demo_hhne_3000_plus_pct)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE
                    SET source_id               = EXCLUDED.source_id,
                        reach_stationary_mio    = EXCLUDED.reach_stationary_mio,
                        reach_mobile_mio        = EXCLUDED.reach_mobile_mio,
                        reach_multiscreen_mio   = EXCLUDED.reach_multiscreen_mio,
                        demo_male_pct           = EXCLUDED.demo_male_pct,
                        demo_employed_pct       = EXCLUDED.demo_employed_pct,
                        demo_higher_edu_pct     = EXCLUDED.demo_higher_edu_pct,
                        demo_hhne_3000_plus_pct = EXCLUDED.demo_hhne_3000_plus_pct,
                        updated_at              = now()
                RETURNING id
                """,
                (
                    source_id, ch.name,
                    ch.reach_stationary_mio,
                    ch.reach_mobile_mio,
                    ch.reach_multiscreen_mio,
                    demo.male_pct if demo else None,
                    demo.employed_pct if demo else None,
                    demo.higher_education_pct if demo else None,
                    demo.hhne_3000_plus_pct if demo else None,
                ),
            )
            ch_id: str = cur.fetchone()[0]

            for portal in ch.portals:
                # Get-or-create für normalisierte Marken — atomar via Upsert.
                # DO UPDATE SET name = EXCLUDED.name ist ein No-Op, erzwingt aber
                # dass RETURNING auch bei bestehendem Conflict die id liefert.
                cur.execute(
                    """
                    INSERT INTO brands (name) VALUES (%s)
                    ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                    RETURNING id
                    """,
                    (portal.brand,),
                )
                brand_id = cur.fetchone()[0]

                cur.execute(
                    """
                    INSERT INTO channel_portals
                        (channel_id, brand_id, sub_areas, stationary, mobile_avail)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (channel_id, brand_id) DO UPDATE
                        SET sub_areas    = EXCLUDED.sub_areas,
                            stationary   = EXCLUDED.stationary,
                            mobile_avail = EXCLUDED.mobile_avail
                    """,
                    (ch_id, brand_id, portal.sub_areas, portal.stationary, portal.mobile_avail),
                )

        # 6. Preise über versionierte SQL-Funktion (NICHT direkt in price_rules schreiben —
        #    die Historisierungslogik steckt in upsert_price_rule)
        for pr in extraction.price_rules:
            cur.execute(
                "SELECT upsert_price_rule(%s, %s, %s, %s)",
                (source_id, pr.package_group, pr.booking_type, pr.cpm_euro * 100),
            )

        # 7. Quelldokument als erfolgreich extrahiert markieren
        cur.execute(
            "UPDATE source_documents SET extraction_ok = TRUE WHERE id = %s",
            (source_id,),
        )

    return "ok"
