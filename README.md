# Media Impact Sales Agent

Prototype pipeline for a future AI-assisted sales assistant for Media Impact data.

The project collects publicly available Media Impact sales and product information, extracts structured data from PDFs, validates it against explicit schemas, and prepares it for storage in a relational database. The resulting data layer can later serve as the foundation for a sales-facing AI assistant that answers product, format, channel, pricing, and campaign-related questions.

## Executive Summary

This repository is an early-stage technical prototype for a **Media Impact AI Sales Agent**.

The current focus is not yet a full end-user application. Instead, the repository implements the data foundation needed for such an assistant:

1. discover relevant Media Impact PDF documents,
2. detect whether documents changed,
3. extract structured sales/product data from PDFs,
4. validate extracted data with Pydantic schemas,
5. prepare the data for PostgreSQL storage,
6. preserve traceability from every extracted data point back to its source document.

The long-term goal is to enable a sales assistant that can answer questions such as:

* Which ad formats are available for a given channel or device?
* Which formats fit a specific campaign goal?
* What CPM ranges or booking options are available?
* Which brands, portals, or channels match a target audience?
* Which information source supports a given recommendation?

## Current Status

**Phase:** Prototype / Phase 1 data pipeline

Implemented or sketched so far:

* PDF discovery from defined Media Impact website pages
* polite, shallow crawling with explicit seed pages
* PDF download and SHA-256 hash-based change detection
* Claude-based PDF extraction into structured JSON
* Pydantic validation for extracted formats, channels, demographics, and price rules
* PostgreSQL schema for source tracking, ad formats, channels, brands, CPM price rules, and review queue
* Docker-based local PostgreSQL setup
* basic project structure for tests and further development

Not yet included:

* production-ready web interface
* Salesforce integration
* Outlook / email integration
* SAP integration
* automated deployment
* user authentication / role management
* complete human review UI
* production monitoring

## Why This Matters

Sales teams often need to answer complex product and media-planning questions quickly. Relevant information is spread across PDFs, rate cards, specification sheets, product pages, and internal knowledge.

This prototype explores how that information can be turned into a structured, queryable data foundation for an AI assistant.

The intended value is:

* faster access to media product information,
* better consistency in sales answers,
* reduced manual lookup in PDFs and product sheets,
* traceable AI answers based on source documents,
* a possible foundation for CRM, email, and SAP-assisted workflows.

## Repository Structure

```text
media-impact-agent/
├── CLAUDE.md
├── README.md
├── requirements.txt
├── docker-compose.yml
├── conftest.py
├── sql/
│   └── schema.sql
├── src/
│   ├── crawler.py
│   ├── extractor.py
│   └── schemas.py
└── tests/
```

### Important Files

| File                 | Purpose                                                                                                                         |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `src/crawler.py`     | Finds Media Impact PDF links, downloads PDFs, and detects changed documents via SHA-256 hashes.                                 |
| `src/extractor.py`   | Sends PDFs to the Claude API and extracts structured JSON for the sales-agent data model.                                       |
| `src/schemas.py`     | Defines Pydantic models and validation rules for ad formats, channels, demographics, and price rules.                           |
| `sql/schema.sql`     | Defines the PostgreSQL schema for source documents, pipeline runs, ad formats, brands, channels, price rules, and review queue. |
| `docker-compose.yml` | Starts a local PostgreSQL database for development.                                                                             |
| `CLAUDE.md`          | Internal development instructions and quality workflow for AI-assisted coding.                                                  |

## High-Level Architecture

```text
Media Impact Website
	↓
Crawler
	↓
PDF Discovery + Download
	↓
Hash-Based Change Detection
	↓
Claude PDF Extraction
	↓
Pydantic Validation
	↓
PostgreSQL Data Layer
	↓
Future Sales Agent / API / Web App
```

## Data Pipeline

### 1. Discover Documents

The crawler visits a controlled list of Media Impact pages and extracts PDF links.

The crawl is intentionally shallow and predictable. It does not recursively scrape the full website. This keeps the process easier to review, safer for the target website, and more suitable for a business prototype.

### 2. Detect Changes

Each downloaded PDF is hashed with SHA-256.

If the hash is unchanged, the expensive extraction step can be skipped. If the hash is new or changed, the document is marked for extraction.

### 3. Extract Structured Data

Changed PDFs are sent to the Claude API with a strict extraction prompt.

The extractor asks the model to return only valid JSON and to avoid guessing missing values. The extraction focuses on:

* ad formats,
* devices,
* CTR information,
* booking options,
* exclusions,
* required assets,
* channel information,
* portals and brands,
* demographics,
* reach metrics,
* CPM price rules,
* additional document fields via `extra_data`.

### 4. Validate Extracted Data

The extracted JSON is validated with Pydantic.

This is important because AI extraction can be incomplete or inconsistent. The schemas define allowed values, expected structures, and plausibility ranges.

Examples:

* percentage values must be between 0 and 100,
* CPM values must be within a plausible range,
* devices must be one of `stationary`, `mobile`, or `multiscreen`,
* mobile availability must use controlled values,
* unexpected information is preserved in `extra_data`.

Invalid extraction results should not silently enter the database. They are intended to go into a review queue.

### 5. Store with Traceability

The database schema is designed around traceability.

Every source document is stored with:

* URL,
* filename,
* document type,
* content hash,
* scrape timestamp,
* extraction status,
* pipeline run ID.

Business entities such as ad formats, channels, and price rules reference the source document they came from. This allows later AI answers to cite or trace their origin.

## Database Design

The PostgreSQL schema includes:

* `pipeline_runs`
  Tracks each pipeline execution.

* `source_documents`
  Stores downloaded PDF or HTML source metadata, including hashes.

* `ad_formats`
  Stores extracted advertising formats.

* `format_booking_options`
  Stores booking options per ad format.

* `format_exclusions`
  Stores exclusions per ad format.

* `format_assets`
  Stores required assets per ad format.

* `format_combinations`
  Stores combination recommendations.

* `brands`
  Normalized brand table.

* `channels`
  Stores channels, reach metrics, demographics, and additional extracted data.

* `channel_portals`
  Connects channels with brands and device availability.

* `price_rules`
  Stores CPM rules with validity periods.

* `review_queue`
  Stores failed or questionable extractions for later human review.

The schema also supports versioned price updates. If a CPM price changes, the old active row can be closed with `valid_until`, and a new active price row can be inserted.

## Setup

### Requirements

* Python 3.11+
* Docker Desktop
* PostgreSQL client tools, optional but useful
* Anthropic API key for extraction

### Install Python Dependencies

```bash
python -m venv .venv
```

Windows PowerShell:

```bash
.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### Configure API Key

Set the Anthropic API key as an environment variable.

Windows PowerShell:

```powershell
$env:ANTHROPIC_API_KEY = "your_api_key_here"
```

macOS / Linux:

```bash
export ANTHROPIC_API_KEY="your_api_key_here"
```

Do not commit API keys or secrets to the repository.

### Start PostgreSQL

```bash
docker compose up -d
```

The development database is exposed on:

```text
127.0.0.1:5433
```

Default development credentials from `docker-compose.yml`:

```text
POSTGRES_USER=miuser
POSTGRES_PASSWORD=mipass
POSTGRES_DB=mediaimpact
```

### Apply Database Schema

Example:

```bash
psql "postgresql://miuser:mipass@127.0.0.1:5433/mediaimpact" -f sql/schema.sql
```

## Running the Crawler

From the project root:

```bash
python src/crawler.py
```

The crawler prints discovered PDF URLs and indicates whether a document is new, changed, or unchanged.

## Extraction Flow

The intended extraction flow is:

```text
PDF bytes
	→ Claude API
	→ JSON response
	→ Pydantic validation
	→ accepted result or review queue
```

The extractor returns:

```text
(result, error, raw_response)
```

Successful extraction:

```text
(ExtractionResult, None, raw_response)
```

Failed extraction:

```text
(None, error_message, raw_response_or_none)
```

This makes it possible to build robust retry and review behavior later.

## Development Principles

The project follows four core principles:

### 1. Traceability

Every extracted data point should be traceable to its original source document.

### 2. Data Quality Before Speed

The system should reject questionable extractions rather than silently storing wrong data.

### 3. Incremental Processing

Hash-based diffing avoids unnecessary re-extraction of unchanged documents.

### 4. Human-in-the-Loop Readiness

Failed validations should be reviewable instead of being discarded.

## Roadmap

### Phase 1: Stabilize Data Pipeline

Goal: make the current pipeline reliable enough for repeated internal runs.

Planned work:

* complete and clean seed page list,
* improve crawler logging,
* add tests for PDF discovery and hash-diffing,
* connect extraction output to PostgreSQL writes,
* store failed validations in `review_queue`.

### Phase 2: Expand Data Basis and Quality Checks

Goal: build a more complete and reliable data foundation.

Planned work:

* parse structured HTML spec pages separately,
* improve schema coverage for real Media Impact documents,
* add source-level metadata,
* add extraction confidence / review markers,
* improve handling of partial documents and large PDFs.

### Phase 3: Internal API / Web Prototype

Goal: expose the data foundation to a simple internal user interface.

Planned work:

* FastAPI endpoints for formats, channels, brands, and prices,
* simple search/query interface,
* source references in responses,
* basic authentication for internal testing,
* demo questions for sales use cases.

### Phase 4: Integration Readiness

Goal: prepare the assistant for enterprise workflow integration.

Possible next integrations:

* Salesforce read-only or write-light,
* Outlook / email draft generation,
* SAP read-only status and booking context,
* later SAP write-back only after a successful pilot.

## Security and Compliance Notes

This repository is a prototype and should not yet be treated as production-ready.

Before production use:

* verify Media Impact website terms and robots.txt,
* clarify legal basis for recurring scraping,
* avoid storing secrets in code or Git history,
* add proper authentication and authorization,
* add logging and monitoring,
* add rate limits,
* review data protection requirements,
* define a human approval step before any CRM, email, or SAP write-back.

## Suggested Next Step

For a continuation pilot, the most realistic next step is:

1. stabilize the pipeline,
2. connect extraction results to PostgreSQL,
3. build a small FastAPI layer,
4. create a minimal internal demo UI,
5. test with real sales questions.

This would turn the current technical prototype into a demonstrable internal proof of concept.

## Status Disclaimer

This is an early-stage prototype. It demonstrates the intended architecture and core extraction approach, but it is not yet a complete production system.
