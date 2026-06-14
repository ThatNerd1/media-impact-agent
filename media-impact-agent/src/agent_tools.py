"""agent_tools.py — Read-only DB query functions for the Media Impact Sales Agent.

All functions return plain dicts/lists; no raw psycopg rows leak out.
All queries are parameterised — no string interpolation of user values.
"""

from __future__ import annotations

import decimal
import os
from typing import Any

import psycopg
import psycopg.rows


def _get_conn() -> psycopg.Connection:
    return psycopg.connect(
        os.environ["DATABASE_URL"],
        row_factory=psycopg.rows.dict_row,
    )


def _clean(row: dict) -> dict:
    """Convert Decimal → float so results are JSON-serialisable without a custom encoder."""
    return {
        k: float(v) if isinstance(v, decimal.Decimal) else v
        for k, v in row.items()
    }


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------

def find_channels_by_demographics(
    min_male_pct: int | None = None,
    min_hhne_3000_pct: int | None = None,
    min_reach_multiscreen_mio: float | None = None,
    min_reach_stationary_mio: float | None = None,
    min_reach_mobile_mio: float | None = None,
    min_employed_pct: int | None = None,
    min_higher_edu_pct: int | None = None,
) -> list[dict[str, Any]]:
    """Return active channels whose demographics and reach match all supplied thresholds.

    All parameters are optional lower bounds; omit any to skip that filter.
    Results are ordered by multiscreen reach (highest first).
    """
    conditions: list[str] = ["c.is_active = TRUE"]
    params: list[Any] = []

    if min_male_pct is not None:
        conditions.append("c.demo_male_pct >= %s")
        params.append(min_male_pct)
    if min_hhne_3000_pct is not None:
        conditions.append("c.demo_hhne_3000_plus_pct >= %s")
        params.append(min_hhne_3000_pct)
    if min_reach_multiscreen_mio is not None:
        conditions.append("c.reach_multiscreen_mio >= %s")
        params.append(min_reach_multiscreen_mio)
    if min_reach_stationary_mio is not None:
        conditions.append("c.reach_stationary_mio >= %s")
        params.append(min_reach_stationary_mio)
    if min_reach_mobile_mio is not None:
        conditions.append("c.reach_mobile_mio >= %s")
        params.append(min_reach_mobile_mio)
    if min_employed_pct is not None:
        conditions.append("c.demo_employed_pct >= %s")
        params.append(min_employed_pct)
    if min_higher_edu_pct is not None:
        conditions.append("c.demo_higher_edu_pct >= %s")
        params.append(min_higher_edu_pct)

    sql = (
        "SELECT"
        "  c.name,"
        "  c.reach_stationary_mio,"
        "  c.reach_mobile_mio,"
        "  c.reach_multiscreen_mio,"
        "  c.demo_male_pct,"
        "  c.demo_employed_pct,"
        "  c.demo_higher_edu_pct,"
        "  c.demo_hhne_3000_plus_pct"
        " FROM channels c"
        f" WHERE {' AND '.join(conditions)}"
        " ORDER BY c.reach_multiscreen_mio DESC NULLS LAST"
    )

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_clean(row) for row in rows]


def find_formats(
    device: str | None = None,
    min_ctr_pct: float | None = None,
    min_rating_viewability: int | None = None,
    min_rating_interactivity: int | None = None,
) -> list[dict[str, Any]]:
    """Return active ad formats matching device and performance filters.

    device must be one of: 'stationary', 'mobile', 'multiscreen'.
    Ratings are 1–5; CTR is a percentage (e.g. 0.5 means 0.5 %).
    Results are ordered by CTR (highest first).
    """
    conditions: list[str] = ["f.is_active = TRUE"]
    params: list[Any] = []

    if device is not None:
        conditions.append("f.device = %s")
        params.append(device)
    if min_ctr_pct is not None:
        # IS NULL guard: NULL >= X is NULL in SQL, which silently drops formats
        # without measured CTR. Include them so callers see all available formats.
        conditions.append("(f.ctr_pct IS NULL OR f.ctr_pct >= %s)")
        params.append(min_ctr_pct)
    if min_rating_viewability is not None:
        conditions.append("f.rating_viewability >= %s")
        params.append(min_rating_viewability)
    if min_rating_interactivity is not None:
        conditions.append("f.rating_interactivity >= %s")
        params.append(min_rating_interactivity)

    sql = (
        "SELECT"
        "  f.format_key,"
        "  f.name,"
        "  f.device,"
        "  f.description,"
        "  f.ctr_pct,"
        "  f.programmatic,"
        "  f.rating_ctr,"
        "  f.rating_viewability,"
        "  f.rating_size,"
        "  f.rating_interactivity,"
        "  f.rating_customisability"
        " FROM ad_formats f"
        f" WHERE {' AND '.join(conditions)}"
        " ORDER BY f.ctr_pct DESC NULLS LAST"
    )

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_clean(row) for row in rows]


def get_prices(package_group: str | None = None) -> list[dict[str, Any]]:
    """Return currently active CPM price rules (valid_until IS NULL).

    cpm_euro is the CPM in euros (already divided by 100 from the stored cent value).
    Optionally filter by package_group using a case-insensitive partial match.
    """
    conditions: list[str] = ["valid_until IS NULL"]
    params: list[Any] = []

    if package_group is not None:
        conditions.append("package_group ILIKE %s")
        params.append(f"%{package_group}%")

    sql = (
        "SELECT"
        "  package_group,"
        "  booking_type,"
        "  ROUND(cpm_euro_cent / 100.0, 2) AS cpm_euro,"
        "  valid_from"
        " FROM price_rules"
        f" WHERE {' AND '.join(conditions)}"
        " ORDER BY package_group, booking_type"
    )

    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_clean(row) for row in rows]


def find_channels_by_extra_attribute(
    key: str,
    min_value: float | None = None,
    max_value: float | None = None,
) -> list[dict[str, Any]]:
    """Return active channels whose extra_data contains *key*.

    Optionally restrict to a numeric range [min_value, max_value].
    Without range filters all rows with the key are returned regardless of
    value type.  With a range filter, rows whose value is non-numeric or
    whose key is absent are silently excluded — no crash.
    All user-supplied values go through %s parameters; *key* is never
    interpolated as SQL text, so JSONB-operator injection is not possible.
    """
    # The SELECT extracts the key's text value; its %s must come first.
    select_params: list[Any] = [key]

    where_conditions: list[str] = ["c.is_active = TRUE", "c.extra_data ? %s"]
    where_params: list[Any] = [key]

    if min_value is not None:
        # CASE WHEN guards against optimizer reordering the regex and the cast.
        where_conditions.append(
            "(CASE WHEN c.extra_data->>%s ~ '^-?[0-9]+(\\.[0-9]+)?$'"
            " THEN (c.extra_data->>%s)::numeric >= %s ELSE FALSE END)"
        )
        where_params.extend([key, key, min_value])
    if max_value is not None:
        where_conditions.append(
            "(CASE WHEN c.extra_data->>%s ~ '^-?[0-9]+(\\.[0-9]+)?$'"
            " THEN (c.extra_data->>%s)::numeric <= %s ELSE FALSE END)"
        )
        where_params.extend([key, key, max_value])

    sql = (
        "SELECT c.name, c.reach_multiscreen_mio,"
        " c.extra_data->>%s AS matched_value"
        " FROM channels c"
        f" WHERE {' AND '.join(where_conditions)}"
        " ORDER BY c.name"
    )

    with _get_conn() as conn:
        rows = conn.execute(sql, select_params + where_params).fetchall()
    return [_clean(row) for row in rows]


def get_extra_data(
    object_type: str,
    name: str,
) -> dict[str, Any] | None:
    """Return the complete extra_data dict for a channel or format.

    object_type: 'channel' or 'format' (anything else → None).
    name: channel name (case-insensitive) or format name / format_key.
    Returns None if not found.
    """
    if object_type == "channel":
        sql = (
            "SELECT extra_data FROM channels"
            " WHERE name ILIKE %s AND is_active = TRUE LIMIT 1"
        )
        params: tuple[Any, ...] = (name,)
    elif object_type == "format":
        # Prefer exact format_key match over name match; break ties by name.
        sql = (
            "SELECT extra_data FROM ad_formats"
            " WHERE (format_key = %s OR name ILIKE %s) AND is_active = TRUE"
            " ORDER BY (format_key = %s) DESC, name"
            " LIMIT 1"
        )
        params = (name, name, name)
    else:
        return None

    with _get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
    return row["extra_data"] if row else None


def find_portals_by_topic(topic: str) -> list[dict[str, Any]]:
    """Return channel portals whose sub_areas TEXT[] contains a value matching topic.

    Matching is case-insensitive and uses a partial substring match so that
    e.g. 'Sport' also finds 'eSport' or 'Motorsport'.
    """
    sql = """
        SELECT
            ch.name  AS channel_name,
            b.name   AS brand_name,
            cp.sub_areas,
            cp.stationary,
            cp.mobile_avail
        FROM channel_portals cp
        JOIN channels ch ON ch.id = cp.channel_id
        JOIN brands   b  ON b.id  = cp.brand_id
        WHERE ch.is_active = TRUE
          AND EXISTS (
              SELECT 1
              FROM unnest(cp.sub_areas) AS area
              WHERE area ILIKE %s
          )
        ORDER BY ch.name, b.name
    """
    with _get_conn() as conn:
        rows = conn.execute(sql, (f"%{topic}%",)).fetchall()
    return [_clean(row) for row in rows]
