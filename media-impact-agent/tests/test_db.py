"""tests/test_db.py — Integrationstests für src/db.py.

Läuft gegen die lokale Docker-DB aus docker-compose.yml.
Voraussetzung: Container mi-postgres-dev läuft auf Port 5433.

DATABASE_URL wird von tests/conftest.py auf mediaimpact_test gesetzt.
Starten mit:
    docker compose up -d
    pytest tests/test_db.py -v
"""

import os

import psycopg
import pytest

from db import SourceDoc, load_known_hashes, write_extraction_result
from schemas import AdFormat, ExtractionResult, PriceRule


@pytest.fixture(autouse=True)
def _clean_db():
    """Bereinigt alle Tabellen vor jedem Test für saubere Isolation."""
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        # RESTART IDENTITY setzt die pipeline_runs-Sequenz zurück.
        # CASCADE räumt alle abhängigen Tabellen mit auf (source_documents,
        # price_rules, ad_formats, channels, channel_portals, review_queue, ...).
        conn.execute("TRUNCATE pipeline_runs, brands RESTART IDENTITY CASCADE")


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _insert_run() -> int:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        return conn.execute(
            "INSERT INTO pipeline_runs DEFAULT VALUES RETURNING id"
        ).fetchone()[0]


def _pdf(suffix: str = "") -> SourceDoc:
    return SourceDoc(
        url=f"https://example.com/preisliste{suffix}.pdf",
        content_hash=f"deadbeef{suffix}",
    )


def _result(pkg: str, btype: str, cpm_euro: int) -> ExtractionResult:
    return ExtractionResult(
        price_rules=[PriceRule(package_group=pkg, booking_type=btype, cpm_euro=cpm_euro)]
    )


# ---------------------------------------------------------------------------
# Drei Preis-Fälle laut upsert_price_rule-Spezifikation
# ---------------------------------------------------------------------------

def test_price_rule_inserted():
    """Erster Eintrag → eine aktive Zeile in price_rules."""
    run_id = _insert_run()
    status = write_extraction_result(run_id, _pdf(), _result("Billboard", "RoC", 60))

    assert status == "ok"

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        row = conn.execute(
            "SELECT cpm_euro_cent, valid_until FROM price_rules"
            " WHERE package_group = 'Billboard' AND booking_type = 'RoC'",
        ).fetchone()

    assert row is not None, "Preisregel wurde nicht angelegt"
    assert row[0] == 6000, f"Erwartet 6000 Cent (60 €), got {row[0]}"
    assert row[1] is None, "Neue Preisregel muss valid_until IS NULL haben"


def test_price_rule_unchanged():
    """Gleicher Preis in zwei Läufen → nur eine Zeile, kein Duplikat."""
    run1 = _insert_run()
    write_extraction_result(run1, _pdf("_v1"), _result("Billboard", "RoC", 60))

    run2 = _insert_run()
    status2 = write_extraction_result(run2, _pdf("_v2"), _result("Billboard", "RoC", 60))

    assert status2 == "ok"

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM price_rules"
            " WHERE package_group = 'Billboard' AND booking_type = 'RoC'",
        ).fetchone()[0]

    assert count == 1, f"Erwartet 1 Zeile (unchanged), gefunden {count}"


def test_price_rule_updated():
    """Geänderter Preis → alte Zeile geschlossen, neue aktive Zeile."""
    run1 = _insert_run()
    write_extraction_result(run1, _pdf("_a"), _result("Billboard", "RoC", 60))

    run2 = _insert_run()
    write_extraction_result(run2, _pdf("_b"), _result("Billboard", "RoC", 75))

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute(
            "SELECT cpm_euro_cent, valid_until FROM price_rules"
            " WHERE package_group = 'Billboard' AND booking_type = 'RoC'"
            " ORDER BY valid_from",
        ).fetchall()

    assert len(rows) == 2, f"Erwartet 2 Zeilen (alt + neu), gefunden {len(rows)}"
    old, current = rows
    assert old[0] == 6000, "Alte Zeile: 60 €"
    assert old[1] is not None, "Alte Zeile muss geschlossen sein (valid_until IS NOT NULL)"
    assert current[0] == 7500, "Neue Zeile: 75 €"
    assert current[1] is None, "Neue Zeile muss offen sein (valid_until IS NULL)"


# ---------------------------------------------------------------------------
# Hash-Skip-Logik: nur nach ERFOLGREICHER Extraktion als "fertig" markiert
# ---------------------------------------------------------------------------

def test_failed_extraction_hash_not_blocked():
    """Fehlgeschlagene Extraktion blockiert keinen Retry mit demselben Hash."""
    run1 = _insert_run()
    status1 = write_extraction_result(run1, _pdf("_fail"), None, error="Test-Fehler")
    assert status1 == "error"

    run2 = _insert_run()
    status2 = write_extraction_result(run2, _pdf("_fail"), None, error="Test-Fehler")
    assert status2 == "error", (
        f"Erwartet 'error', bekam '{status2}' — "
        "fehlgeschlagene Extraktion darf Retry nicht als 'skipped' blockieren"
    )


def test_successful_extraction_skips_same_hash():
    """Nach erfolgreicher Extraktion wird dieselbe URL+Hash beim nächsten Lauf übersprungen."""
    run1 = _insert_run()
    status1 = write_extraction_result(run1, _pdf("_succ"), _result("RoB", "RoC", 60))
    assert status1 == "ok"

    run2 = _insert_run()
    status2 = write_extraction_result(run2, _pdf("_succ"), _result("RoB", "RoC", 60))
    assert status2 == "skipped"


def test_load_known_hashes_excludes_failed():
    """load_known_hashes gibt nur Hashes erfolgreich extrahierter Dokumente zurück."""
    run_id = _insert_run()
    write_extraction_result(run_id, _pdf("_lkh_fail"), None, error="Test")

    hashes = load_known_hashes()
    assert _pdf("_lkh_fail").url not in hashes


def test_load_known_hashes_includes_successful():
    """load_known_hashes enthält Hashes von Dokumenten mit extraction_ok = TRUE."""
    run_id = _insert_run()
    doc = _pdf("_lkh_ok")
    write_extraction_result(run_id, doc, _result("BillboardLKH", "RoC", 60))

    hashes = load_known_hashes()
    assert doc.url in hashes
    assert hashes[doc.url] == doc.content_hash


# ---------------------------------------------------------------------------
# Format-Deduplizierung über ON CONFLICT (format_key)
# ---------------------------------------------------------------------------

def test_format_deduplication_across_pdfs():
    """Dasselbe Format aus zwei PDFs → eine Zeile in ad_formats, aktualisierter Name."""
    run1 = _insert_run()
    r1 = ExtractionResult(
        ad_formats=[AdFormat(format_key="billboard_dedup", name="Billboard", device="stationary")]
    )
    write_extraction_result(run1, _pdf("_fmt1"), r1)

    run2 = _insert_run()
    r2 = ExtractionResult(
        ad_formats=[AdFormat(format_key="billboard_dedup", name="Billboard v2", device="stationary")]
    )
    write_extraction_result(run2, _pdf("_fmt2"), r2)

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute(
            "SELECT name FROM ad_formats WHERE format_key = 'billboard_dedup'"
        ).fetchall()

    assert len(rows) == 1, f"Erwartet 1 Zeile, gefunden {len(rows)}"
    assert rows[0][0] == "Billboard v2", "Name muss auf neuesten Wert aktualisiert sein"
