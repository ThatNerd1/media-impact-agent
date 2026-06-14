"""tests/conftest.py — Globale Test-Konfiguration für den tests/-Ordner.

Setzt DATABASE_URL **hart** auf mediaimpact_test, bevor irgendein Test-Modul
importiert wird. Damit können weder os.environ.setdefault()-Aufrufe in den
Test-Modulen noch eine extern gesetzte DATABASE_URL die Prod-DB gefährden.
"""
from __future__ import annotations

import os
import urllib.parse

import psycopg
import pytest

# ---------------------------------------------------------------------------
# Test-DB-URL ableiten und hart setzen — MUSS auf Modulebene stehen,
# damit die Zuweisung vor dem Import der Test-Module greift.
# ---------------------------------------------------------------------------
_base_url = os.environ.get(
    "DATABASE_URL",
    "postgresql://miuser:mipass@127.0.0.1:5433/mediaimpact",
)
_parsed = urllib.parse.urlparse(_base_url)

# Wir ersetzen nur den Datenbanknamen — Host, Port und Credentials bleiben.
_TEST_DB_URL = _parsed._replace(path="/mediaimpact_test").geturl()
_ADMIN_DB_URL = _parsed._replace(path="/postgres").geturl()

# Hard-Override, NICHT setdefault — schützt vor einer gesetzten Prod-URL.
os.environ["DATABASE_URL"] = _TEST_DB_URL


@pytest.fixture(scope="session", autouse=True)
def _setup_test_db():
    """Legt mediaimpact_test an (falls nötig) und spielt das Schema ein.

    Sicherheitsanker: assertiert, dass DATABASE_URL auf mediaimpact_test zeigt.
    CREATE DATABASE braucht autocommit (nicht in Transaktionen erlaubt).
    apply_schema() ist idempotent — wiederholte Aufrufe sind unschädlich.
    """
    current_url = os.environ["DATABASE_URL"]

    # Defensiv-Check: stellt sicher, dass kein Code-Pfad nach unserem Setzen
    # DATABASE_URL wieder auf die Prod-DB umgebogen hat.
    if "mediaimpact_test" not in current_url:
        raise RuntimeError(
            f"DATABASE_URL zeigt NICHT auf mediaimpact_test: {current_url!r}\n"
            "Tests würden gegen die Produktion laufen — Abbruch."
        )

    # Test-DB anlegen, falls nicht vorhanden.
    # try/except statt EXISTS-Prüfung + CREATE, um TOCTOU bei parallelen Läufen zu vermeiden.
    with psycopg.connect(_ADMIN_DB_URL, autocommit=True) as conn:
        try:
            conn.execute("CREATE DATABASE mediaimpact_test")
        except psycopg.errors.DuplicateDatabase:
            pass  # DB existiert bereits — kein Problem

    # Schema idempotent einspielen (IF NOT EXISTS / CREATE OR REPLACE überall).
    from db import apply_schema
    apply_schema()
