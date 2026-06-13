-- schema.sql — Relationale Datenbankstruktur für den Media Impact Sales Agent
--
-- Konventionen:
--   - Alle Primärschlüssel: UUID (gen_random_uuid())
--   - Timestamps: TIMESTAMPTZ (immer mit Zeitzone)
--   - Soft-Delete über is_active statt physischem Löschen
--   - Jede Fachzeile referenziert source_documents.id für vollständige
--     Rückverfolgbarkeit (welches PDF, welcher Lauf, welcher Hash)

-- ---------------------------------------------------------------------------
-- Erweiterungen
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()


-- ---------------------------------------------------------------------------
-- 1. PIPELINE-VERSIONIERUNG
-- ---------------------------------------------------------------------------

-- Jeder wöchentliche Lauf bekommt eine run_id. So lässt sich jederzeit
-- nachvollziehen, aus welchem Lauf ein Datensatz stammt.
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              SERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'running'   -- running | done | failed
                    CHECK (status IN ('running', 'done', 'failed')),
    notes           TEXT
);

-- Jedes heruntergeladene Dokument (PDF oder HTML-Seite) wird hier erfasst.
-- content_hash ist der SHA-256 der Roh-Bytes. Ändert er sich nicht, wird das
-- Dokument in diesem Lauf nicht neu extrahiert (Hash-Diffing).
CREATE TABLE IF NOT EXISTS source_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          INTEGER NOT NULL REFERENCES pipeline_runs(id),
    url             TEXT NOT NULL,
    filename        TEXT,
    doc_type        TEXT NOT NULL                     -- 'pdf' | 'html_spec'
                    CHECK (doc_type IN ('pdf', 'html_spec')),
    content_hash    TEXT NOT NULL,                    -- SHA-256 Hex
    scraped_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    extraction_ok   BOOLEAN NOT NULL DEFAULT FALSE,   -- TRUE nach erfolgreicher Extraktion
    UNIQUE (url, content_hash)                        -- gleiche URL + gleicher Hash = kein Duplikat
);

CREATE INDEX IF NOT EXISTS idx_source_documents_url
    ON source_documents (url);
CREATE INDEX IF NOT EXISTS idx_source_documents_run_id
    ON source_documents (run_id);


-- ---------------------------------------------------------------------------
-- 2. ANZEIGENFORMATE
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ad_formats (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id           UUID NOT NULL REFERENCES source_documents(id),
    format_key          TEXT NOT NULL UNIQUE,         -- stabiler Schlüssel, z. B. 'dynamic_fireplace'
    name                TEXT NOT NULL,
    device              TEXT NOT NULL
                        CHECK (device IN ('stationary', 'mobile', 'multiscreen')),
    description         TEXT,
    ctr_pct             NUMERIC(5,2),                 -- durchschnittliche CTR in %
    programmatic        TEXT,
    rating_ctr          SMALLINT CHECK (rating_ctr BETWEEN 1 AND 5),
    rating_viewability  SMALLINT CHECK (rating_viewability BETWEEN 1 AND 5),
    rating_size         SMALLINT CHECK (rating_size BETWEEN 1 AND 5),
    rating_interactivity SMALLINT CHECK (rating_interactivity BETWEEN 1 AND 5),
    rating_customisability SMALLINT CHECK (rating_customisability BETWEEN 1 AND 5),
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Buchungsoptionen als eigene Tabelle (1 Format : N Optionen)
CREATE TABLE IF NOT EXISTS format_booking_options (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    format_id   UUID NOT NULL REFERENCES ad_formats(id) ON DELETE CASCADE,
    option_name TEXT NOT NULL,
    UNIQUE (format_id, option_name)
);

-- Ausschlüsse (z. B. "nicht buchbar auf bild.de")
CREATE TABLE IF NOT EXISTS format_exclusions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    format_id   UUID NOT NULL REFERENCES ad_formats(id) ON DELETE CASCADE,
    exclusion   TEXT NOT NULL,
    UNIQUE (format_id, exclusion)
);

-- Pflicht-Assets (z. B. "Billboard (SPECS)", "zwei Sitebars")
CREATE TABLE IF NOT EXISTS format_assets (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    format_id   UUID NOT NULL REFERENCES ad_formats(id) ON DELETE CASCADE,
    asset_name  TEXT NOT NULL,
    UNIQUE (format_id, asset_name)
);

-- Kombinationsempfehlungen ("goes well with")
CREATE TABLE IF NOT EXISTS format_combinations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    format_id       UUID NOT NULL REFERENCES ad_formats(id) ON DELETE CASCADE,
    pairs_well_with TEXT NOT NULL,
    UNIQUE (format_id, pairs_well_with)
);

CREATE INDEX IF NOT EXISTS idx_ad_formats_device
    ON ad_formats (device);
CREATE INDEX IF NOT EXISTS idx_ad_formats_is_active
    ON ad_formats (is_active);


-- ---------------------------------------------------------------------------
-- 3. MEDIENMARKEN (BRANDS)
-- ---------------------------------------------------------------------------

-- Zentrale Markentabelle, normalisiert. BILD taucht in vielen Channels auf —
-- ohne Normalisierung wäre der Name dutzendfach dupliziert.
CREATE TABLE IF NOT EXISTS brands (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ---------------------------------------------------------------------------
-- 4. CHANNELS
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS channels (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id               UUID NOT NULL REFERENCES source_documents(id),
    name                    TEXT NOT NULL UNIQUE,     -- z. B. 'Technology', 'Football'
    -- Reichweite in Millionen Unique User
    reach_stationary_mio    NUMERIC(6,2),
    reach_mobile_mio        NUMERIC(6,2),
    reach_multiscreen_mio   NUMERIC(6,2),
    -- Demografie (Prozent-Werte 0–100)
    demo_male_pct           SMALLINT CHECK (demo_male_pct BETWEEN 0 AND 100),
    demo_employed_pct       SMALLINT CHECK (demo_employed_pct BETWEEN 0 AND 100),
    demo_higher_edu_pct     SMALLINT CHECK (demo_higher_edu_pct BETWEEN 0 AND 100),
    demo_hhne_3000_plus_pct SMALLINT CHECK (demo_hhne_3000_plus_pct BETWEEN 0 AND 100),
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Welche Marke ist in welchem Channel auf welchen Geräten?
-- Eine Zeile = ein Portal-Eintrag (z. B. BILD im Technology-Channel, stationär + mobil)
CREATE TABLE IF NOT EXISTS channel_portals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_id      UUID NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    brand_id        UUID NOT NULL REFERENCES brands(id),
    sub_areas       TEXT,                             -- z. B. 'Digital, Games, BILD.gg'
    stationary      BOOLEAN NOT NULL DEFAULT FALSE,
    mobile_avail    TEXT NOT NULL DEFAULT 'no'
                    CHECK (mobile_avail IN ('yes', 'only_mew', 'no')),
    UNIQUE (channel_id, brand_id)
);

CREATE INDEX IF NOT EXISTS idx_channel_portals_channel_id
    ON channel_portals (channel_id);
CREATE INDEX IF NOT EXISTS idx_channel_portals_brand_id
    ON channel_portals (brand_id);


-- ---------------------------------------------------------------------------
-- 5. CPM-PREISREGELN
-- ---------------------------------------------------------------------------

-- Jede Zeile entspricht einer Zelle der Preismatrix:
-- Format-Gruppe (Zeile) × Paket (Spalte) → CPM in Euro
CREATE TABLE IF NOT EXISTS price_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID NOT NULL REFERENCES source_documents(id),
    -- Welches Format ist betroffen? In der Praxis MEIST NULL: die echte
    -- CPM-Matrix preist Format-GRUPPEN ("Mobile Content Ad 6:1 + 4:1"), nicht
    -- einzelne format_keys. Dieser FK ist daher optional und nur gesetzt, wenn
    -- sich eine Gruppe eindeutig genau einem ad_format zuordnen lässt.
    format_id       UUID REFERENCES ad_formats(id),
    package_group   TEXT NOT NULL,                    -- z. B. 'Mobile Content Ad 2:1'
    booking_type    TEXT NOT NULL,                    -- z. B. 'RoC' (Run of Channel)
    -- Preise in Euro-Cent statt Dezimal, um Rundungsfehler zu vermeiden
    -- (6000 = 60 €). Für die Anzeige durch 100 teilen.
    -- Obergrenze 12000 (120€) konsistent mit schemas.py CPM_MAX_EUR.
    cpm_euro_cent   INTEGER NOT NULL
                    CHECK (cpm_euro_cent BETWEEN 3000 AND 12000),  -- 30€–120€
    valid_from      TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_until     TIMESTAMPTZ,                      -- NULL = aktuell gültig
    -- Versionierung (siehe upsert_price_rule unten):
    --   Ein Preis ist eindeutig identifiziert durch package_group + booking_type.
    --   Solange er gilt, ist valid_until NULL. Ändert sich der Betrag, wird die
    --   alte Zeile mit valid_until=now() geschlossen und eine neue eröffnet.
    -- Der Partial-Unique-Index erzwingt: pro (package_group, booking_type) darf
    --   es nur EINE aktuell gültige Zeile (valid_until IS NULL) geben.
    CONSTRAINT price_rules_cpm_nonneg CHECK (cpm_euro_cent > 0)
);

-- Höchstens eine aktive Preiszeile pro Format-Gruppe + Buchungsart.
-- Verhindert die Duplikate, die bei einem wiederholten Lauf sonst entstünden.
CREATE UNIQUE INDEX IF NOT EXISTS uq_price_rules_active
    ON price_rules (package_group, booking_type)
    WHERE valid_until IS NULL;

CREATE INDEX IF NOT EXISTS idx_price_rules_format_id
    ON price_rules (format_id);


-- ---------------------------------------------------------------------------
-- 6. REVIEW-QUEUE (fehlgeschlagene Validierungen)
-- ---------------------------------------------------------------------------

-- Extraktionen, die die Pydantic-Validierung nicht bestehen, landen hier.
-- Ein Mensch oder ein erneuter Lauf kann sie später aufgreifen.
CREATE TABLE IF NOT EXISTS review_queue (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID NOT NULL REFERENCES source_documents(id),
    queued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    error_type      TEXT NOT NULL,                    -- 'json_parse' | 'validation' | 'api_error'
    error_detail    TEXT NOT NULL,
    raw_response    TEXT,                             -- rohe API-Antwort zur Fehleranalyse
    resolved        BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_at     TIMESTAMPTZ,
    resolved_by     TEXT                              -- Username oder 'auto'
);

CREATE INDEX IF NOT EXISTS idx_review_queue_resolved
    ON review_queue (resolved)
    WHERE resolved = FALSE;                           -- Partial Index: nur offene Einträge


-- ---------------------------------------------------------------------------
-- 7. HILFSFUNKTION: updated_at automatisch setzen
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_ad_formats_updated_at
    BEFORE UPDATE ON ad_formats
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE TRIGGER trg_channels_updated_at
    BEFORE UPDATE ON channels
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ---------------------------------------------------------------------------
-- 8. VERSIONIERTES SCHREIBEN VON PREISEN
-- ---------------------------------------------------------------------------

-- Schreibt einen Preis versioniert. Verhalten:
--   - Existiert keine aktive Zeile (package_group, booking_type): neu anlegen.
--   - Existiert eine aktive Zeile mit GLEICHEM Betrag: nichts tun (kein Duplikat).
--   - Existiert eine aktive Zeile mit ANDEREM Betrag: alte mit valid_until=now()
--     schließen und neue aktive Zeile anlegen (echte Preishistorie).
-- Gibt zurück: 'inserted' | 'unchanged' | 'updated'
CREATE OR REPLACE FUNCTION upsert_price_rule(
    p_source_id     UUID,
    p_package_group TEXT,
    p_booking_type  TEXT,
    p_cpm_euro_cent INTEGER,
    p_format_id     UUID DEFAULT NULL
) RETURNS TEXT AS $$
DECLARE
    existing_cent INTEGER;
BEGIN
    SELECT cpm_euro_cent INTO existing_cent
    FROM price_rules
    WHERE package_group = p_package_group
      AND booking_type = p_booking_type
      AND valid_until IS NULL;

    IF NOT FOUND THEN
        INSERT INTO price_rules
            (source_id, format_id, package_group, booking_type, cpm_euro_cent)
        VALUES
            (p_source_id, p_format_id, p_package_group, p_booking_type, p_cpm_euro_cent);
        RETURN 'inserted';
    END IF;

    IF existing_cent = p_cpm_euro_cent THEN
        RETURN 'unchanged';
    END IF;

    -- Preis hat sich geändert: alte Zeile schließen, neue eröffnen.
    UPDATE price_rules
    SET valid_until = now()
    WHERE package_group = p_package_group
      AND booking_type = p_booking_type
      AND valid_until IS NULL;

    INSERT INTO price_rules
        (source_id, format_id, package_group, booking_type, cpm_euro_cent)
    VALUES
        (p_source_id, p_format_id, p_package_group, p_booking_type, p_cpm_euro_cent);
    RETURN 'updated';
END;
$$ LANGUAGE plpgsql;
