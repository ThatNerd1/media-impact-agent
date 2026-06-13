"""main.py — Orchestriert die Media-Impact-Datenpipeline (Phase 1).

Ablauf:
  1. Pipeline-Lauf starten
  2. PDF-URLs crawlen (oder lokale Test-PDF laden)
  3. Bekannte Hashes aus DB → nur geänderte PDFs herunterladen
  4. Jedes PDF extrahieren
  5. Ergebnisse in DB schreiben
  6. Lauf abschließen
  7. Zusammenfassung ausgeben

Voraussetzungen:
    DATABASE_URL      — PostgreSQL-Verbindungsstring
                        (default: postgresql://miuser:mipass@localhost:5433/mediaimpact)
    ANTHROPIC_API_KEY — Claude-API-Schlüssel (muss gesetzt sein)

Schnelltest mit einer lokalen PDF (kein Crawling):
    python src/main.py --test-pdf /pfad/zur/datei.pdf
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# src/ in den Importpfad aufnehmen, damit Geschwistermodule direkt importierbar sind.
sys.path.insert(0, str(Path(__file__).parent))

from crawler import SEED_PAGES, DiscoveredPDF, compute_hash, crawl_for_pdfs, download_changed
from db import (
    SourceDoc,
    apply_schema,
    finish_run,
    load_known_hashes,
    start_run,
    write_extraction_result,
)
from extractor import extract_from_pdf

_DEFAULT_DB = "postgresql://miuser:mipass@localhost:5433/mediaimpact"
os.environ.setdefault("DATABASE_URL", _DEFAULT_DB)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def _check_env() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY ist nicht gesetzt.")


def _load_test_pdf(path: str) -> DiscoveredPDF:
    p = Path(path).resolve()
    if not p.exists():
        sys.exit(f"Datei nicht gefunden: {p}")
    data = p.read_bytes()
    return DiscoveredPDF(
        url=f"file://{p.as_posix()}",
        filename=p.name,
        content=data,
        content_hash=compute_hash(data),
    )


def _process_pdfs(pdfs: list[DiscoveredPDF], run_id: int) -> dict[str, int]:
    """Extrahiert jedes PDF und schreibt das Ergebnis in die DB."""
    stats: dict[str, int] = {"ok": 0, "skipped": 0, "error": 0}

    for pdf in pdfs:
        log.info("Extrahiere: %s", pdf.filename)
        result, err = extract_from_pdf(pdf.content)

        source_doc = SourceDoc(
            url=pdf.url,
            content_hash=pdf.content_hash,
            filename=pdf.filename,
        )

        if result is not None:
            status = write_extraction_result(run_id, source_doc, result)
        else:
            assert err is not None
            # Extractor-Fehlertext als Roh-String übergeben → write_extraction_result
            # erkennt keinen validen JSON → Eintrag landet in review_queue.
            status = write_extraction_result(run_id, source_doc, err)

        stats[status] = stats.get(status, 0) + 1
        log.info("  → %s", status)

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Media-Impact-Datenpipeline")
    parser.add_argument(
        "--test-pdf",
        metavar="PATH",
        help="Lokale PDF für Schnelltest (überspringt Crawling)",
    )
    args = parser.parse_args()

    _check_env()
    apply_schema()

    run_id = start_run()
    log.info("Pipeline-Lauf gestartet (id=%d)", run_id)

    found_count = 0
    pdfs: list[DiscoveredPDF] = []
    stats: dict[str, int] = {"ok": 0, "skipped": 0, "error": 0}

    try:
        if args.test_pdf:
            log.info("Testmodus: %s", args.test_pdf)
            pdfs = [_load_test_pdf(args.test_pdf)]
            found_count = 1
        else:
            log.info("Crawle %d Seed-Pages …", len(SEED_PAGES))
            pdf_urls = crawl_for_pdfs(SEED_PAGES)
            found_count = len(pdf_urls)
            log.info("Gefunden: %d PDF-URLs", found_count)

            known_hashes = load_known_hashes()
            log.info("Bekannte Hashes in DB: %d", len(known_hashes))

            pdfs = download_changed(pdf_urls, known_hashes)
            log.info("Geänderte / neue PDFs: %d", len(pdfs))

        stats = _process_pdfs(pdfs, run_id)
        finish_run(run_id, "done")

    except Exception:
        log.exception("Unerwarteter Fehler — markiere Lauf als 'failed'")
        try:
            finish_run(run_id, "failed")
        except Exception:
            log.exception("Konnte Lauf %d nicht als 'failed' markieren", run_id)
        raise

    log.info(
        "Lauf %d abgeschlossen | "
        "gefunden: %d | geändert/neu: %d | ok: %d | übersprungen: %d | review_queue: %d",
        run_id,
        found_count,
        len(pdfs),
        stats.get("ok", 0),
        stats.get("skipped", 0),
        stats.get("error", 0),
    )


if __name__ == "__main__":
    main()
