"""tests/test_main.py — Tests für die Pipeline-Logik in main.py.

Läuft gegen die lokale Docker-DB aus docker-compose.yml.
Voraussetzung: Container mi-postgres-dev läuft auf Port 5433.

DATABASE_URL wird von tests/conftest.py auf mediaimpact_test gesetzt.
Starten mit:
    docker compose up -d
    pytest tests/test_main.py -v
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from crawler import DiscoveredPDF
from db import SourceDoc, write_extraction_result
from main import _process_pdfs
from schemas import ExtractionResult, PriceRule


@pytest.fixture(autouse=True)
def _clean_db():
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute("TRUNCATE pipeline_runs, brands RESTART IDENTITY CASCADE")


def _insert_run() -> int:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        return conn.execute(
            "INSERT INTO pipeline_runs DEFAULT VALUES RETURNING id"
        ).fetchone()[0]


def _make_pdf(url: str, hash_: str) -> DiscoveredPDF:
    return DiscoveredPDF(
        url=url,
        filename=url.rsplit("/", 1)[-1],
        content=b"%PDF-1.4 fake",
        content_hash=hash_,
    )


def _ok_result() -> ExtractionResult:
    return ExtractionResult(
        price_rules=[PriceRule(package_group="Billboard", booking_type="RoC", cpm_euro=60)]
    )


def test_no_api_call_when_hash_already_known():
    """Bereits erfolgreich extrahiertes PDF darf beim zweiten Lauf KEINEN API-Aufruf auslösen."""
    url = "https://example.com/preisliste.pdf"
    hash_ = "abc123def456"

    # Erster Lauf: Extraktion direkt in die DB schreiben (kein API-Aufruf nötig).
    run1 = _insert_run()
    doc = SourceDoc(url=url, content_hash=hash_)
    status1 = write_extraction_result(run1, doc, _ok_result())
    assert status1 == "ok"

    # Zweiter Lauf: _process_pdfs mit demselben PDF aufrufen.
    run2 = _insert_run()
    mock_extractor = MagicMock(name="extract_from_pdf")
    with patch("main.extract_from_pdf", mock_extractor):
        stats = _process_pdfs([_make_pdf(url, hash_)], run2)

    mock_extractor.assert_not_called()
    assert stats["skipped"] == 1
    assert stats.get("ok", 0) == 0
    assert stats.get("error", 0) == 0


def test_api_called_for_new_pdf():
    """Noch unbekanntes PDF muss den Extraktor aufrufen."""
    url = "https://example.com/neu.pdf"
    hash_ = "newhash999"

    run_id = _insert_run()
    mock_extractor = MagicMock(name="extract_from_pdf", return_value=(_ok_result(), None, None))
    with patch("main.extract_from_pdf", mock_extractor):
        stats = _process_pdfs([_make_pdf(url, hash_)], run_id)

    mock_extractor.assert_called_once()
    assert stats.get("ok", 0) == 1


def test_api_called_after_previous_failure():
    """Nach fehlgeschlagener Extraktion muss ein Retry den Extraktor aufrufen."""
    url = "https://example.com/retry.pdf"
    hash_ = "retryhash"

    # Erster Lauf: Extraktion schlägt fehl.
    run1 = _insert_run()
    doc = SourceDoc(url=url, content_hash=hash_)
    status1 = write_extraction_result(run1, doc, None, error="Test-Fehler")
    assert status1 == "error"

    # Zweiter Lauf: Retry muss den Extraktor aufrufen (extraction_ok ist FALSE).
    run2 = _insert_run()
    mock_extractor = MagicMock(name="extract_from_pdf", return_value=(_ok_result(), None, None))
    with patch("main.extract_from_pdf", mock_extractor):
        _process_pdfs([_make_pdf(url, hash_)], run2)

    mock_extractor.assert_called_once()
