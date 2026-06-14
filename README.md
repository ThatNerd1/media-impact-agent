# Media Impact Sales Agent

Prototype for an AI-assisted sales assistant for Media Impact data.

The project turns Media Impact sales and product information from PDFs and structured data sources into a queryable data foundation. On top of this data layer, the system provides an AI assistant that can answer sales-related questions about channels, formats, audiences, prices, and campaign fit.

The long-term vision is a sales workflow in which one sales employee can guide a customer through the full process — from initial request to product recommendation, offer preparation, CRM context, SAP booking, and handover to the technical delivery team.

## Executive Summary

This repository contains an early-stage but functional prototype for a **Media Impact AI Sales Agent**.

The prototype currently focuses on three layers:

1. **Data pipeline**  
   Discover and process relevant Media Impact documents, detect changes, extract structured information, validate the results, and store them in PostgreSQL.

2. **Agent layer**  
   Use the structured data foundation to answer real sales questions with grounded recommendations.

3. **API layer**  
   Expose the agent through a FastAPI interface so that future frontends, Salesforce, Outlook, and SAP integrations can connect to the same backend.

The project is not yet a production system. It is a technical proof of concept that demonstrates the intended architecture and the feasibility of the approach.

The most important next engineering step is the transition from a local prototype to a reproducible pilot architecture: Alembic-managed database migrations, a representative document sample, schema refinement, and then a controlled move toward Azure deployment.

## What the Assistant Is Intended to Solve

Sales teams often need quick, reliable answers to questions that are currently spread across PDFs, rate cards, product sheets, channel factsheets, technical specifications, and internal knowledge.

Typical questions include:

- Which channels fit a specific target audience?
- Which ad formats are available for a campaign goal?
- Which formats are available on mobile, desktop, or multiscreen?
- What CPM ranges or booking options apply?
- Which channel has the right demographic profile?
- Which product or environment should be recommended for a campaign?
- Which source document supports the recommendation?

The assistant is designed to reduce manual PDF search and provide consistent, traceable answers.

## Current Status

**Phase:** Working prototype / internal proof of concept

### Already implemented or demonstrated

- Controlled PDF discovery from Media Impact web pages
- Polite, shallow crawling based on explicit seed pages
- PDF download and SHA-256 hash-based change detection
- Claude-based PDF extraction into structured JSON
- Pydantic validation for extracted formats, channels, demographics, and price rules
- PostgreSQL schema for source tracking, channels, brands, formats, CPM rules, and review queue
- Basic agent layer for answering sales questions from the structured data
- FastAPI interface for HTTP-based access to the assistant
- Local development setup with Docker-based PostgreSQL
- Early sample runs across different Media Impact document types

### Proven milestone

The assistant is no longer only a local script. It can be reached through an HTTP API.

This is important because the same API layer can later be used by:

- an internal web interface,
- Salesforce,
- Outlook / email workflows,
- SAP read-only or write-back workflows,
- other internal systems.

### Not yet production-ready

The following parts are not yet implemented as production features:

- polished web interface for sales users,
- Salesforce integration,
- Outlook / email integration,
- SAP integration,
- authentication and role management,
- deployment to Azure or another cloud environment,
- monitoring and production logging,
- full review UI for failed or uncertain extractions,
- complete ingestion of the full document corpus,
- legally and operationally approved recurring crawling.

## Strategic Vision

The long-term goal is not just a question-answer bot.

The stronger vision is a **horizontal sales process** in which one sales employee can guide the customer through the full journey while the assistant provides the required information and system actions in the background.

```text
Customer contact
	↓
Need and campaign goal
	↓
AI-assisted product, channel, and price recommendation
	↓
Offer preparation
	↓
CRM context / Salesforce
	↓
SAP booking
	↓
Technical handover
	↓
Campaign execution
```

In this vision, the AI assistant acts as the connective layer between data, sales workflow, CRM, email, SAP, and technical delivery.

Important distinction:

- **Today:** the prototype answers sales questions and exposes the agent through an API.
- **Future:** the assistant could support CRM updates, email drafts, SAP lookups, and eventually booking workflows.

SAP write-back and real booking actions should only be considered after a successful pilot and with explicit human approval steps.

## High-Level Architecture

```text
Media Impact Website / PDFs / Product Data
	↓
Crawler
	↓
PDF Discovery + Download
	↓
Hash-Based Change Detection
	↓
Claude Extraction
	↓
Pydantic Validation
	↓
PostgreSQL Data Layer
	↓
Agent Layer
	↓
FastAPI Interface
	↓
Future Web UI / Salesforce / Outlook / SAP
```

## Data Pipeline

### 1. Document Discovery

The crawler visits a controlled list of Media Impact pages and extracts relevant PDF links.

The crawl is intentionally shallow and predictable. It does not recursively scrape the entire website. This makes the process easier to review, safer for a business prototype, and more suitable for controlled internal evaluation.

### 2. Change Detection

Each downloaded document is hashed with SHA-256.

If a document has not changed, the system can skip re-extraction. This keeps recurring runs cheap and efficient.

```text
PDF URL
	↓
Download
	↓
SHA-256 hash
	↓
New / changed / unchanged
```

### 3. AI-Based Extraction

Changed documents are sent to Claude for structured extraction.

The extraction prompt is designed to avoid guessing. If information is missing, the system should preserve uncertainty rather than hallucinate.

The extraction focuses on:

- ad formats,
- devices,
- booking options,
- exclusions,
- required assets,
- channel information,
- portals and brands,
- demographics,
- reach metrics,
- CPM price rules,
- extra fields that do not yet fit the fixed schema.

### 4. Validation

The extracted JSON is validated with Pydantic.

This protects the database from inconsistent or obviously invalid AI output.

Examples:

- percentage values must be plausible,
- CPM values must be plausible,
- devices must follow controlled values,
- missing information should not be invented,
- unexpected but useful fields can be preserved in `extra_data`.

### 5. Storage and Traceability

The PostgreSQL schema is designed around traceability.

Every source document is stored with metadata such as:

- source URL,
- filename,
- document type,
- content hash,
- scrape timestamp,
- extraction status,
- pipeline run ID.

Business objects such as channels, ad formats, brands, and price rules are linked back to the source documents they came from.

This is essential for trustworthy AI answers: the assistant should be able to explain where its answer came from.

## Database Design

The PostgreSQL schema includes:

- `pipeline_runs`  
  Tracks individual pipeline runs.

- `source_documents`  
  Stores metadata for crawled PDFs or HTML sources.

- `ad_formats`  
  Stores extracted advertising formats.

- `format_booking_options`  
  Stores booking options per ad format.

- `format_exclusions`  
  Stores exclusions per ad format.

- `format_assets`  
  Stores required assets per format.

- `format_combinations`  
  Stores recommended or possible format combinations.

- `brands`  
  Normalized brand table.

- `channels`  
  Stores channel-level information, reach data, demographics, and extra structured fields.

- `channel_portals`  
  Connects channels with brands, portals, and device availability.

- `price_rules`  
  Stores CPM rules and validity periods.

- `review_queue`  
  Stores failed, incomplete, or questionable extractions for human review.

The database supports versioned updates. For example, if a CPM changes, the old row can be closed with `valid_until`, and a new active row can be inserted.

## Agent Layer

The assistant uses the structured data foundation to answer sales questions.

Example use case:

```text
Question:
Which channel would fit an automotive campaign targeting a high-income male audience with a CPM budget of 60 €?

Expected answer:
A ranked recommendation with suitable channels, reasoning, demographic fit, available reach information, price context, and caveats where data is incomplete.
```

The assistant should not invent missing data. If the source data does not contain a value, it should say so.

## API Layer

The project uses FastAPI as the API layer.

FastAPI is useful here because it provides:

- a clean HTTP interface,
- automatic OpenAPI documentation,
- an interactive API testing surface,
- a stable integration point for future systems,
- a natural path toward web UI, Salesforce, Outlook, and SAP integrations.

The intended API architecture is:

```text
CLI / Swagger / Web UI / Salesforce / Outlook / SAP
	↓
FastAPI
	↓
Agent Layer
	↓
PostgreSQL
	↓
Source Documents
```

This makes the API the neutral hub of the system.

## Document Coverage and Early Findings

The project is designed for a larger Media Impact document base. Early discovery found several hundred potentially relevant documents.

Initial sample runs suggest that documents fall into different groups:

### 1. Channel factsheets

These work well with the current schema. They usually contain channel information, demographic data, reach metrics, and sometimes price-related information.

### 2. Mediadaten documents

These can be processed, but much of their content may land in `extra_data` because the structure differs from channel factsheets.

### 3. Technical specifications

These contain useful information but are a different document class. They likely need their own schema or extraction path.

### 4. Large price lists and large factsheets

Some large documents can exceed the current extraction token limit. These may need chunking or section-based extraction.

This means the next development step should not be a blind full crawl. The better path is a representative sample across document types, followed by schema refinement.

## Open Technical ToDos Before a Production Pilot

The prototype has reached an important milestone: the agent is accessible both locally and through the FastAPI HTTP interface. The next work package is therefore no longer about proving whether the concept works at all, but about making the prototype robust enough for a controlled pilot.

### 1. Representative Document Sample

Before running a larger crawler job, a representative sample should be completed across 10–15 different PDF/document types.

The sample run is important because Media Impact documents differ significantly in structure. Channel factsheets, mediadaten documents, technical specifications, and price lists may need different extraction strategies.

Planned work:

- run a representative sample of 10–15 document types,
- log success, failure, token usage, and extraction cost per document,
- distinguish schema mismatch from API failures or token-limit failures,
- classify documents into extraction categories,
- decide which document classes should be included in the first production pilot.

Result:

- a realistic understanding of which document types are ready for ingestion and which need separate handling.

### 2. Database Migration Path: Local PostgreSQL to Azure

The current prototype uses a local Docker-based PostgreSQL database. For a cloud-based pilot, the database schema should be managed with Alembic migrations instead of relying only on a static `schema.sql` file.

This is especially important for the transition from local development to an Azure-hosted database.

Planned work:

- introduce Alembic for versioned database migrations,
- create an initial migration from the current PostgreSQL schema,
- make schema changes reproducible across local and Azure environments,
- prepare migration commands for deployment,
- avoid manual schema drift between development and cloud database.

Result:

- the database can move from local prototype setup to Azure without manual, error-prone schema recreation.

### 3. Schema Refinement Before Full Crawl

The current schema is sufficient for the prototype, but several fields should be improved before ingesting the full document corpus.

Planned schema changes:

- convert `device` from a single text value into `TEXT[]`, because many formats are available across multiple device classes,
- promote frequently recurring `extra_data` fields into proper database columns,
- normalize age group fields so the assistant does not compare incompatible demographic cuts,
- add a GIN index on `extra_data` for faster querying of flexible JSON fields,
- improve handling of large documents that exceed extraction token limits.

The `extra_data` field is useful because it prevents information loss. However, fields that appear repeatedly across many documents should eventually become first-class database fields.

### 4. Agent Reliability and Answer Quality

The assistant should remain honest about incomplete or non-comparable data.

Planned work:

- verify that `raw_response` is stored correctly for debugging and review,
- test the age-group prompt fix through the API,
- ensure that non-comparable demographic groups are not ranked as if they used the same definition,
- improve format-to-price matching,
- monitor silent price filtering during larger extraction runs,
- keep questionable extraction results in the review queue instead of accepting them automatically.

Result:

- answers remain grounded, auditable, and less likely to overstate what the data supports.

### 5. API and User Interaction Roadmap

The FastAPI foundation is already in place and has been verified through HTTP requests. The next API-related steps are:

- add or finalize a streaming endpoint,
- prepare multi-turn conversations,
- connect the API to a simple internal web frontend,
- define stable endpoint contracts for future integrations.

This makes FastAPI the central integration layer for the project.

### 6. Full Crawler Run

Only after the representative sample and schema refinements should the full crawler run be executed.

Planned work:

- run the crawler over the full selected document corpus,
- skip unchanged documents via SHA-256 hash-diffing,
- log token usage and cost per document,
- store failed or questionable extractions in the review queue,
- verify that hash-diffing happens before expensive API extraction.

Result:

- a broader structured Media Impact knowledge base with manageable extraction costs.

### 7. Integration Preparation

Once the data foundation and API are stable, integrations can be prepared in a staged way:

1. Salesforce read-only or write-light,
2. Outlook / email draft generation,
3. SAP read-only,
4. SAP write-back only after a successful pilot and with human approval.

The recommended integration order is intentional: Salesforce and Outlook can support the sales process without immediately creating high-risk business transactions. SAP should initially be read-only. Real SAP booking should be treated as a later phase.

## Cost Considerations

The expensive step is AI extraction. However, extraction is only needed when a document is new or changed.

The hash-diffing approach keeps recurring costs low:

```text
Unchanged document
	→ no new extraction
	→ almost no recurring AI cost

Changed document
	→ extract again
	→ update structured data
```

Early estimates suggest that a full initial extraction would likely remain in a manageable cost range. The exact cost depends on document length, output size, token limits, and whether large PDFs must be split into sections.

For production planning, the system should log actual input and output tokens per document so that a reliable cost projection can be calculated from real sample data.

## Setup

### Requirements

- Python 3.11+
- Docker Desktop
- PostgreSQL client tools, optional but useful
- Anthropic API key for extraction

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

Default local development credentials:

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

This structure makes it possible to build robust retry and review behavior later.

## API Usage

The FastAPI layer is intended to expose the assistant through HTTP endpoints.

Typical local development flow:

```bash
uvicorn src.api:app --reload
```

Then open:

```text
http://127.0.0.1:8000/docs
```

Example request shape:

```json
{
	"question": "Which channels fit an automotive campaign targeting a high-income male audience?"
}
```

Depending on the current implementation state, endpoint paths may change. The `/docs` page should be treated as the source of truth for the local API interface.

## Development Principles

### 1. Traceability

Every extracted data point should be traceable to its source document.

### 2. Data Quality Before Speed

The system should reject questionable extraction results rather than silently store wrong data.

### 3. Incremental Processing

Hash-based diffing avoids unnecessary re-extraction of unchanged documents.

### 4. Human-in-the-Loop Readiness

Failed validations should be reviewable instead of discarded.

### 5. Honest AI Behavior

The assistant should clearly state uncertainty and missing data instead of producing unsupported claims.

### 6. Reproducible Deployment

Database schema changes should be versioned through migrations, especially before moving from a local PostgreSQL prototype to Azure.

## Four-Week Continuation Plan

A realistic next pilot can be structured as four one-week phases.

### Week 1: Stabilize Prototype and Prepare Cloud Transition

Goal: make the prototype reproducible, demonstrable, and ready for a later Azure deployment.

Planned work:

- verify the existing FastAPI endpoints through local API tests,
- clean up setup and run instructions,
- introduce Alembic migrations for versioned database schema management,
- create an initial migration from the current PostgreSQL schema,
- prepare the local PostgreSQL setup so it can later be mirrored in Azure,
- define demo questions and expected outputs,
- verify the age-group answer behavior through the API.

Result:

- a stable local prototype with a clear database migration path toward Azure.

### Week 2: Representative Document Sample and Schema Refinement

Goal: validate the data model before ingesting the full document corpus.

Planned work:

- run a representative sample of 10–15 PDF/document types,
- separate factsheets, mediadaten documents, technical specs, and price lists,
- log token usage and extraction cost per document,
- convert `device` to `TEXT[]` if confirmed by sample data,
- promote recurring `extra_data` fields into proper columns,
- add a GIN index for flexible `extra_data` queries,
- improve handling of large documents that hit token limits,
- store uncertain results in the review queue.

Result:

- a validated schema and extraction strategy before the full crawler run.

### Week 3: Salesforce-Light Preparation

Goal: define and prepare a low-risk CRM integration path.

Planned work:

- define Salesforce objects and fields relevant to the assistant,
- design a read-only or write-light integration model,
- prepare API endpoints that could receive opportunity or customer context,
- define how AI recommendations should be stored back as notes, drafts, or suggestions,
- avoid critical automatic CRM changes at this stage.

Result:

- integration concept for using the assistant in the sales process without high operational risk.

### Week 4: Outlook / Email and SAP Read-Only Preparation

Goal: prepare the first end-to-end workflow concept.

Planned work:

- define how incoming email requests could be parsed,
- design answer-draft generation through Outlook or email workflows,
- define SAP read-only use cases such as customer status, booking status, or campaign context,
- explicitly exclude real SAP booking from this phase,
- define human approval points.

Result:

- clear pilot path for combining CRM, email, and SAP context around the assistant.

## Integration Roadmap

### Salesforce

Recommended first enterprise integration.

Initial scope:

- read opportunity or customer context,
- generate recommendation,
- return result as note, draft, or suggested next step.

Avoid in the first phase:

- automatic opportunity changes,
- automatic pricing decisions,
- automatic customer communication.

### Outlook / Email

Recommended second integration.

Initial scope:

- extract intent and requirements from inbound emails,
- generate reply drafts,
- summarize customer requests,
- suggest matching products or channels.

Avoid in the first phase:

- sending emails without human approval.

### SAP

Recommended as read-only first.

Initial scope:

- customer status lookup,
- booking status lookup,
- campaign or order context lookup.

Avoid until after successful pilot:

- automatic booking,
- automatic order changes,
- automatic invoice or billing actions.

## Security and Compliance Notes

This repository is a prototype and should not yet be treated as production-ready.

Before production use:

- clarify the legal basis and internal approval for recurring crawling,
- avoid storing secrets in code or Git history,
- rotate any exposed API keys,
- add authentication and authorization,
- add monitoring and audit logs,
- add rate limits,
- define human approval before CRM, email, or SAP write-back,
- review data protection requirements,
- review vendor and API usage costs,
- define ownership of extracted data quality.

## Suggested Next Step

The next best step is a short continuation pilot:

1. stabilize the FastAPI-accessible prototype,
2. introduce Alembic migrations for the database transition from local PostgreSQL to Azure,
3. finish a representative document sample,
4. refine schemas based on real extraction failures,
5. prepare a minimal demo interface,
6. define Salesforce, Outlook, and SAP integration boundaries,
7. run a live demo with realistic sales questions.

The key decision after this pilot should be:

> Is the assistant accurate and useful enough on a representative document base to justify integration into the real sales workflow?

## Status Disclaimer

This is an early-stage prototype. It demonstrates the intended architecture and key feasibility points, but it is not yet a complete production system.

The most important current distinction is:

- **Built:** data pipeline, extraction concept, schema validation, database foundation, agent layer, API access.
- **Partially validated:** representative extraction across different document types.
- **Planned:** Azure deployment path, Alembic migrations, web interface, Salesforce, Outlook, SAP read-only, SAP write-back.
- **Not recommended yet:** automatic SAP booking or autonomous system changes without human approval.
