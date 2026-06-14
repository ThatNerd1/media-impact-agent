"""tests/test_agent_tools.py — Integration tests for src/agent_tools.py.

Runs against the local test DB (mediaimpact_test) set up by tests/conftest.py.
Start the container first:
    docker compose up -d
    pytest tests/test_agent_tools.py -v
"""

from __future__ import annotations

import os

import psycopg
import pytest

from agent_tools import (
    find_channels_by_demographics,
    find_channels_by_extra_attribute,
    find_formats,
    find_portals_by_topic,
    get_extra_data,
    get_prices,
)


# ---------------------------------------------------------------------------
# find_channels_by_demographics
# ---------------------------------------------------------------------------

def test_find_channels_no_filters_returns_list():
    rows = find_channels_by_demographics()
    assert isinstance(rows, list)


def test_find_channels_result_shape():
    rows = find_channels_by_demographics()
    for row in rows:
        assert "name" in row
        assert "reach_multiscreen_mio" in row
        assert "demo_male_pct" in row
        assert "demo_hhne_3000_plus_pct" in row


def test_find_channels_zero_reach_returns_all_active():
    rows = find_channels_by_demographics(min_reach_multiscreen_mio=0.0)
    assert isinstance(rows, list)


def test_find_channels_impossible_filter_returns_empty():
    # No channel can have > 100 % male users.
    rows = find_channels_by_demographics(min_male_pct=101)
    assert rows == []


def test_find_channels_multiscreen_filter_respected():
    threshold = 5.0
    rows = find_channels_by_demographics(min_reach_multiscreen_mio=threshold)
    for row in rows:
        if row["reach_multiscreen_mio"] is not None:
            assert row["reach_multiscreen_mio"] >= threshold


def test_find_channels_ordered_by_multiscreen_desc():
    rows = find_channels_by_demographics()
    reaches = [r["reach_multiscreen_mio"] for r in rows if r["reach_multiscreen_mio"] is not None]
    assert reaches == sorted(reaches, reverse=True)


# ---------------------------------------------------------------------------
# Fixture: mobile ad_format with ctr_pct=NULL
# ---------------------------------------------------------------------------

_FX_FORMAT_KEY = "_fixture_mobile_null_ctr"
_FX_URL = "https://test.example/null-ctr-fixture"
_FX_HASH = "abc000fixture000null000ctr"


@pytest.fixture
def _mobile_null_ctr_format():
    """Insert a mobile ad_format with ctr_pct=NULL into the test DB, then clean up.

    FK chain: pipeline_runs → source_documents → ad_formats.
    Pre-cleanup handles leftovers from previously crashed test runs.
    """
    db_url = os.environ["DATABASE_URL"]
    assert "mediaimpact_test" in db_url, (
        f"Safety: fixture must only run against test DB, got {db_url!r}"
    )

    # Remove any leftover rows from a previously crashed run
    with psycopg.connect(db_url) as conn:
        conn.execute("DELETE FROM ad_formats WHERE format_key = %s", (_FX_FORMAT_KEY,))
        conn.execute(
            "DELETE FROM source_documents WHERE url = %s AND content_hash = %s",
            (_FX_URL, _FX_HASH),
        )

    run_id = source_id = None
    with psycopg.connect(db_url) as conn:
        (run_id,) = conn.execute(
            "INSERT INTO pipeline_runs (status) VALUES ('done') RETURNING id"
        ).fetchone()
        (source_id,) = conn.execute(
            """INSERT INTO source_documents (run_id, url, doc_type, content_hash, extraction_ok)
               VALUES (%s, %s, 'pdf', %s, TRUE) RETURNING id""",
            (run_id, _FX_URL, _FX_HASH),
        ).fetchone()
        conn.execute(
            """INSERT INTO ad_formats
                   (source_id, format_key, name, device, ctr_pct, is_active)
               VALUES (%s, %s, 'Fixture Mobile Null-CTR Format', 'mobile', NULL, TRUE)""",
            (source_id, _FX_FORMAT_KEY),
        )

    yield _FX_FORMAT_KEY

    with psycopg.connect(db_url) as conn:
        conn.execute("DELETE FROM ad_formats WHERE format_key = %s", (_FX_FORMAT_KEY,))
        conn.execute("DELETE FROM source_documents WHERE id = %s", (source_id,))
        conn.execute("DELETE FROM pipeline_runs WHERE id = %s", (run_id,))


# ---------------------------------------------------------------------------
# find_formats
# ---------------------------------------------------------------------------

def test_find_formats_no_filters_returns_list():
    rows = find_formats()
    assert isinstance(rows, list)


def test_find_formats_result_shape():
    rows = find_formats()
    for row in rows:
        assert "format_key" in row
        assert "device" in row
        assert "name" in row


def test_find_formats_device_filter():
    for device in ("stationary", "mobile", "multiscreen"):
        rows = find_formats(device=device)
        for row in rows:
            assert row["device"] == device


def test_find_formats_unknown_device_returns_empty():
    rows = find_formats(device="nonexistent_device_xyz")
    assert rows == []


def test_find_formats_ctr_filter_respected():
    threshold = 0.5
    rows = find_formats(min_ctr_pct=threshold)
    for row in rows:
        if row["ctr_pct"] is not None:
            assert row["ctr_pct"] >= threshold


def test_find_formats_null_ctr_not_excluded_by_min_ctr_filter(_mobile_null_ctr_format):
    # A mobile format with ctr_pct=NULL must survive any min_ctr_pct filter.
    # Before the fix, NULL >= X evaluated to NULL in SQL and silently dropped these rows.
    all_mobile = find_formats(device="mobile")
    null_ctr_keys = {r["format_key"] for r in all_mobile if r["ctr_pct"] is None}
    assert null_ctr_keys, "test precondition: there must be mobile formats with NULL ctr_pct"

    filtered = find_formats(device="mobile", min_ctr_pct=0.0)
    filtered_keys = {r["format_key"] for r in filtered}
    missing = null_ctr_keys - filtered_keys
    assert not missing, (
        f"min_ctr_pct=0.0 wrongly excluded NULL-CTR mobile formats: {missing}"
    )


def test_find_formats_mobile_with_high_ctr_threshold_includes_null_ctr(_mobile_null_ctr_format):
    # Even a threshold higher than any known mobile CTR must still return formats
    # whose CTR is unmeasured (NULL), not an empty list.
    rows = find_formats(device="mobile", min_ctr_pct=0.99)
    null_ctr_rows = [r for r in rows if r["ctr_pct"] is None]
    assert null_ctr_rows, (
        "device='mobile' + min_ctr_pct=0.99 returned no NULL-CTR formats; "
        "these should be included because their CTR is simply not measured"
    )


# ---------------------------------------------------------------------------
# get_prices
# ---------------------------------------------------------------------------

def test_get_prices_no_filter_returns_list():
    rows = get_prices()
    assert isinstance(rows, list)


def test_get_prices_result_shape():
    rows = get_prices()
    for row in rows:
        assert "package_group" in row
        assert "booking_type" in row
        assert "cpm_euro" in row


def test_get_prices_cpm_in_valid_range():
    rows = get_prices()
    for row in rows:
        # Schema enforces 3000–12000 cent → 30–120 €
        assert 30.0 <= float(row["cpm_euro"]) <= 120.0


def test_get_prices_package_group_filter():
    # Any string filter should return a list (may be empty).
    rows = get_prices(package_group="Mobile")
    assert isinstance(rows, list)
    for row in rows:
        assert "mobile" in row["package_group"].lower()


def test_get_prices_nonexistent_group_returns_empty():
    rows = get_prices(package_group="XYZZY_NONEXISTENT_PACKAGE_42")
    assert rows == []


# ---------------------------------------------------------------------------
# find_portals_by_topic
# ---------------------------------------------------------------------------

def test_find_portals_by_topic_returns_list():
    rows = find_portals_by_topic("Sport")
    assert isinstance(rows, list)


def test_find_portals_result_shape():
    rows = find_portals_by_topic("Sport")
    for row in rows:
        assert "channel_name" in row
        assert "brand_name" in row
        assert "sub_areas" in row
        assert "stationary" in row
        assert "mobile_avail" in row


def test_find_portals_no_match_returns_empty():
    rows = find_portals_by_topic("XYZZY_NONEXISTENT_TOPIC_99")
    assert rows == []


def test_find_portals_case_insensitive():
    upper = find_portals_by_topic("SPORT")
    lower = find_portals_by_topic("sport")
    assert upper == lower


# ---------------------------------------------------------------------------
# Fixtures for extra_data tests
# ---------------------------------------------------------------------------

_FX_CHANNEL_NAME = "_fixture_extra_data_channel"
_FX_CHANNEL_EXTRA = {
    "female_pct": 65,
    "age_20_39_pct": 45,
    "age_16_29_pct": 30,
    "data_source": "IVW",
}

_FX_FORMAT_KEY2 = "_fixture_extra_data_format"
_FX_FORMAT_EXTRA = {
    "material_deadline_standard_days": 5,
    "surcharge_eur": 500,
    "category": "Premium",
    "format_group": "Impactful",
}
_FX_URL2 = "https://test.example/extra-data-fixture"
_FX_HASH2 = "abc111fixture111extra111data"


@pytest.fixture
def _extra_data_channel():
    """Insert a channel with known extra_data, then clean up."""
    db_url = os.environ["DATABASE_URL"]
    assert "mediaimpact_test" in db_url

    with psycopg.connect(db_url) as conn:
        conn.execute("DELETE FROM channels WHERE name = %s", (_FX_CHANNEL_NAME,))

    run_id = source_id = None
    with psycopg.connect(db_url) as conn:
        (run_id,) = conn.execute(
            "INSERT INTO pipeline_runs (status) VALUES ('done') RETURNING id"
        ).fetchone()
        (source_id,) = conn.execute(
            """INSERT INTO source_documents (run_id, url, doc_type, content_hash, extraction_ok)
               VALUES (%s, %s, 'pdf', %s, TRUE) RETURNING id""",
            (run_id, _FX_URL2, _FX_HASH2),
        ).fetchone()
        conn.execute(
            """INSERT INTO channels (source_id, name, extra_data)
               VALUES (%s, %s, %s)""",
            (source_id, _FX_CHANNEL_NAME, psycopg.types.json.Jsonb(_FX_CHANNEL_EXTRA)),
        )

    yield _FX_CHANNEL_NAME

    with psycopg.connect(db_url) as conn:
        conn.execute("DELETE FROM channels WHERE name = %s", (_FX_CHANNEL_NAME,))
        conn.execute("DELETE FROM source_documents WHERE id = %s", (source_id,))
        conn.execute("DELETE FROM pipeline_runs WHERE id = %s", (run_id,))


@pytest.fixture
def _extra_data_format():
    """Insert a format with known extra_data, then clean up."""
    db_url = os.environ["DATABASE_URL"]
    assert "mediaimpact_test" in db_url

    _url = "https://test.example/extra-data-format-fixture"
    _hash = "abc222fixture222format222extra"

    with psycopg.connect(db_url) as conn:
        conn.execute("DELETE FROM ad_formats WHERE format_key = %s", (_FX_FORMAT_KEY2,))
        conn.execute(
            "DELETE FROM source_documents WHERE url = %s AND content_hash = %s",
            (_url, _hash),
        )

    run_id = source_id = None
    with psycopg.connect(db_url) as conn:
        (run_id,) = conn.execute(
            "INSERT INTO pipeline_runs (status) VALUES ('done') RETURNING id"
        ).fetchone()
        (source_id,) = conn.execute(
            """INSERT INTO source_documents (run_id, url, doc_type, content_hash, extraction_ok)
               VALUES (%s, %s, 'pdf', %s, TRUE) RETURNING id""",
            (run_id, _url, _hash),
        ).fetchone()
        conn.execute(
            """INSERT INTO ad_formats (source_id, format_key, name, device, extra_data)
               VALUES (%s, %s, 'Fixture Extra-Data Format', 'stationary', %s)""",
            (source_id, _FX_FORMAT_KEY2,
             psycopg.types.json.Jsonb(_FX_FORMAT_EXTRA)),
        )

    yield _FX_FORMAT_KEY2

    with psycopg.connect(db_url) as conn:
        conn.execute("DELETE FROM ad_formats WHERE format_key = %s", (_FX_FORMAT_KEY2,))
        conn.execute("DELETE FROM source_documents WHERE id = %s", (source_id,))
        conn.execute("DELETE FROM pipeline_runs WHERE id = %s", (run_id,))


# ---------------------------------------------------------------------------
# find_channels_by_extra_attribute
# ---------------------------------------------------------------------------

def test_find_channels_by_extra_attribute_key_present(_extra_data_channel):
    rows = find_channels_by_extra_attribute("female_pct")
    names = [r["name"] for r in rows]
    assert _FX_CHANNEL_NAME in names


def test_find_channels_by_extra_attribute_result_shape(_extra_data_channel):
    rows = find_channels_by_extra_attribute("female_pct")
    for row in rows:
        assert "name" in row
        assert "matched_value" in row
        assert "reach_multiscreen_mio" in row


def test_find_channels_by_extra_attribute_min_value_match(_extra_data_channel):
    # female_pct = 65, so min_value=60 must include the fixture channel.
    rows = find_channels_by_extra_attribute("female_pct", min_value=60)
    names = [r["name"] for r in rows]
    assert _FX_CHANNEL_NAME in names


def test_find_channels_by_extra_attribute_min_value_no_match(_extra_data_channel):
    # female_pct = 65, so min_value=70 must exclude the fixture channel.
    rows = find_channels_by_extra_attribute("female_pct", min_value=70)
    names = [r["name"] for r in rows]
    assert _FX_CHANNEL_NAME not in names


def test_find_channels_by_extra_attribute_max_value_match(_extra_data_channel):
    rows = find_channels_by_extra_attribute("female_pct", max_value=70)
    names = [r["name"] for r in rows]
    assert _FX_CHANNEL_NAME in names


def test_find_channels_by_extra_attribute_max_value_no_match(_extra_data_channel):
    rows = find_channels_by_extra_attribute("female_pct", max_value=60)
    names = [r["name"] for r in rows]
    assert _FX_CHANNEL_NAME not in names


def test_find_channels_by_extra_attribute_missing_key_returns_empty(_extra_data_channel):
    rows = find_channels_by_extra_attribute("nonexistent_key_xyz")
    names = [r["name"] for r in rows]
    assert _FX_CHANNEL_NAME not in names


def test_find_channels_by_extra_attribute_non_numeric_value_no_crash(_extra_data_channel):
    # data_source = "IVW" — a string, not numeric.
    # Passing min_value must not raise; the channel is simply excluded.
    rows = find_channels_by_extra_attribute("data_source", min_value=0)
    assert isinstance(rows, list)
    names = [r["name"] for r in rows]
    assert _FX_CHANNEL_NAME not in names


def test_find_channels_by_extra_attribute_non_numeric_no_range(_extra_data_channel):
    # Without numeric filter, non-numeric keys still work (key-existence check).
    rows = find_channels_by_extra_attribute("data_source")
    names = [r["name"] for r in rows]
    assert _FX_CHANNEL_NAME in names


# ---------------------------------------------------------------------------
# get_extra_data
# ---------------------------------------------------------------------------

def test_get_extra_data_channel(_extra_data_channel):
    result = get_extra_data("channel", _FX_CHANNEL_NAME)
    assert result is not None
    assert result["female_pct"] == 65
    assert result["data_source"] == "IVW"


def test_get_extra_data_channel_case_insensitive(_extra_data_channel):
    result = get_extra_data("channel", _FX_CHANNEL_NAME.upper())
    assert result is not None
    assert "female_pct" in result


def test_get_extra_data_format(_extra_data_format):
    # Look up by format_key (exact match)
    result = get_extra_data("format", _FX_FORMAT_KEY2)
    assert result is not None
    assert result["surcharge_eur"] == 500
    assert result["category"] == "Premium"


def test_get_extra_data_format_by_name(_extra_data_format):
    # Look up by human-readable name (ILIKE match)
    result = get_extra_data("format", "Fixture Extra-Data Format")
    assert result is not None
    assert result["format_group"] == "Impactful"


def test_get_extra_data_not_found(_extra_data_channel):
    result = get_extra_data("channel", "XYZZY_NONEXISTENT_CHANNEL_42")
    assert result is None


def test_get_extra_data_unknown_type():
    result = get_extra_data("brand", "anything")
    assert result is None
