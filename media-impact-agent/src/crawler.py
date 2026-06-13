"""crawler.py — Findet und lädt Media-Impact-PDFs, mit Hash-basiertem Diffing.

Verantwortlich für:
- Crawlen der Media-Impact-Site, um aktuelle PDF-URLs zu finden
- Herunterladen der PDFs
- Berechnen eines SHA-256-Hashes pro Datei (Fingerabdruck)
- Vergleich mit zuletzt gesehenem Hash, sodass nur GEÄNDERTE PDFs
  später neu extrahiert werden

Hinweis: Vor produktivem Einsatz robots.txt und Nutzungsbedingungen von
Media Impact prüfen. Dieser Crawler hält bewusst Pausen zwischen Requests.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

BASE_URL = "https://www.mediaimpact.de/en/"
# Höfliche Pause zwischen Requests (Sekunden), um den Server nicht zu belasten.
REQUEST_DELAY_S = 1.5
# User-Agent transparent setzen, damit der Betreiber den Traffic zuordnen kann.
USER_AGENT = "MediaImpactSalesAgent/0.1 (internal data pipeline; contact: ops@example.com)"

# Bekannte Übersichtsseiten, aus denen PDF-Links extrahiert werden.
# Flaches Crawling: nur diese Seiten werden besucht, keine Rekursion.
SEED_PAGES: list[str] = [
    # Startseite
    BASE_URL,

    # --- Display ---
    "https://www.mediaimpact.de/en/display/",

    # --- Specs — Übersicht aller Werbeformat-Spezifikationsseiten ---
    "https://www.mediaimpact.de/en/specs/",

    # --- Brands — Übersicht + individuelle Markenseiten ---
    "https://www.mediaimpact.de/en/advertise/_brands/",
    "https://www.mediaimpact.de/en/brands/bild/",
    "https://www.mediaimpact.de/en/brands/bild-am-sonntag/",
    "https://www.mediaimpact.de/en/brands/bild-regional/",
    "https://www.mediaimpact.de/en/brands/bz/",
    "https://www.mediaimpact.de/en/brands/welt/",
    "https://www.mediaimpact.de/en/brands/welt-regional/",
    "https://www.mediaimpact.de/en/brands/auto-bild/",
    "https://www.mediaimpact.de/en/brands/business-insider/",
    "https://www.mediaimpact.de/en/brands/computer-bild/",
    "https://www.mediaimpact.de/en/brands/sport-bild/",
    "https://www.mediaimpact.de/en/brands/premium-gruppe/",
    "https://www.mediaimpact.de/en/brands/fitbook/",
    "https://www.mediaimpact.de/en/brands/myhomebook/",
    "https://www.mediaimpact.de/en/brands/petbook/",
    "https://www.mediaimpact.de/en/brands/toralarm/",
    "https://www.mediaimpact.de/en/brands/techbook/",
    "https://www.mediaimpact.de/en/brands/travelbook/",
    "https://www.mediaimpact.de/en/brands/icon-group-2/",

    # --- Channel — Werbekanal-Übersichtsseiten ---
    "https://www.mediaimpact.de/en/advertise/digital/",
    "https://www.mediaimpact.de/en/advertise/print/",
    "https://www.mediaimpact.de/en/advertise/native/",
    "https://www.mediaimpact.de/en/advertise/programmatic/",
    "https://www.mediaimpact.de/en/advertise/data/",
    "https://www.mediaimpact.de/en/advertise/events/",
    "https://www.mediaimpact.de/en/advertise/special-interest/",
    "https://www.mediaimpact.de/en/advertise/research/",
    "https://www.mediaimpact.de/en/performance/",
]


@dataclass
class DiscoveredPDF:
    """Eine gefundene PDF samt Metadaten für das Diffing."""
    url: str
    filename: str
    content: bytes
    content_hash: str


def compute_hash(data: bytes) -> str:
    """SHA-256-Fingerabdruck der Roh-Bytes. Gleiche Datei -> gleicher Hash."""
    return hashlib.sha256(data).hexdigest()


def find_pdf_links(client: httpx.Client, page_url: str) -> set[str]:
    """Holt eine Seite und gibt alle absoluten PDF-Links darauf zurück."""
    resp = client.get(page_url)
    resp.raise_for_status()
    tree = HTMLParser(resp.text)

    pdf_urls: set[str] = set()
    for node in tree.css("a[href]"):
        href = node.attributes.get("href", "")
        if href.lower().endswith(".pdf"):
            pdf_urls.add(urljoin(page_url, href))
    return pdf_urls


def crawl_for_pdfs(seed_pages: list[str]) -> set[str]:
    """Durchsucht eine Liste bekannter Seiten nach PDF-Links.

    Bewusst flach gehalten (nur die übergebenen Seiten, kein tiefes
    Rekursions-Crawling), um den Server zu schonen und vorhersehbar zu bleiben.
    Die Seitenliste sollte die Display-/Specs-/Brands-Übersichten enthalten.
    """
    all_pdfs: set[str] = set()
    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=30.0,
        follow_redirects=True,
    ) as client:
        for page in seed_pages:
            try:
                found = find_pdf_links(client, page)
                all_pdfs.update(found)
            except httpx.HTTPError as exc:
                # Eine fehlerhafte Seite darf den ganzen Lauf nicht stoppen.
                print(f"[warn] Konnte {page} nicht laden: {exc}")
            time.sleep(REQUEST_DELAY_S)
    return all_pdfs


def download_pdf(client: httpx.Client, url: str) -> DiscoveredPDF:
    """Lädt eine einzelne PDF und berechnet ihren Hash."""
    resp = client.get(url)
    resp.raise_for_status()
    content = resp.content
    filename = Path(urlparse(url).path).name
    return DiscoveredPDF(
        url=url,
        filename=filename,
        content=content,
        content_hash=compute_hash(content),
    )


def download_changed(
    pdf_urls: set[str],
    known_hashes: dict[str, str],
) -> list[DiscoveredPDF]:
    """Lädt PDFs und gibt nur die zurück, deren Hash sich geändert hat.

    Args:
        pdf_urls: gefundene PDF-URLs
        known_hashes: Mapping url -> zuletzt gesehener Hash (aus der DB)

    Returns:
        Liste der NEUEN oder GEÄNDERTEN PDFs, die neu extrahiert werden müssen.
    """
    changed: list[DiscoveredPDF] = []
    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=60.0,
        follow_redirects=True,
    ) as client:
        for url in sorted(pdf_urls):
            try:
                pdf = download_pdf(client, url)
            except httpx.HTTPError as exc:
                print(f"[warn] Download fehlgeschlagen {url}: {exc}")
                continue

            if known_hashes.get(url) == pdf.content_hash:
                # Unverändert -> teure Extraktion überspringen.
                print(f"[skip] unverändert: {pdf.filename}")
            else:
                print(f"[new ] geändert/neu: {pdf.filename}")
                changed.append(pdf)
            time.sleep(REQUEST_DELAY_S)
    return changed


if __name__ == "__main__":
    urls = crawl_for_pdfs(SEED_PAGES)
    print(f"\nGefundene PDFs: {len(urls)}")
    for u in sorted(urls):
        print(f"  {u}")
