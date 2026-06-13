"""tests/test_db.py — Integrationstests für src/db.py.

Läuft gegen die lokale Docker-DB aus docker-compose.yml.
Voraussetzung: Container mi-postgres-dev läuft auf Port 5433.

Starten mit:
    docker compose up -d
    DATABASE_URL=postgresql://miuser:mipass@localhost:5433/mediaimpact pytest tests/test_db.py -v

Oder mit dem Default-Wert (wenn Credentials nicht geändert wurden):
    pytest tests/test_db.py -v
"""

import os

import psycopg
import pytest

from db import SourceDoc, apply_schema, write_extraction_result
from schemas import ExtractionResult, PriceRule

_DEFAULT_DB = "postgresql://miuser:mipass@localhost:5433/mediaimpact"
os.environ.setdefault("DATABASE_URL", _DEFAULT_DB)


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Wendet das Schema einmalig pro Test-Session an."""
    apply_schema()


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
