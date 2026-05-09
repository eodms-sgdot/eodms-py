import os
import warnings
from datetime import datetime, timedelta, timezone

import pytest
import requests

from eodms.search import Search_API


REAL_SATELLITE_ID = "RCM-1"
REAL_RELATIVE_ORBIT = 16
REAL_BEAM_MNEMONIC = "SC30MCPA"


def _print_live(message: str, capsys=None):
    """Print to the terminal even when pytest output capture is enabled."""
    if capsys is None:
        print(message, flush=True)
        return

    with capsys.disabled():
        print(message, flush=True)


class _FakeLink:
    def __init__(self, href: str):
        self.href = href


class _FakeCollection:
    def __init__(self, collection_id: str, queryables: dict):
        self.id = collection_id
        self._queryables = queryables

    def get_queryables(self):
        return self._queryables

    def get_single_link(self, rel: str):
        assert rel == "items"
        return _FakeLink("https://example.test/search/collections/RCMImageProducts/items")


class _FakeClient:
    def __init__(self, collection: _FakeCollection):
        self._collection = collection

    def get_collections(self):
        return [self._collection]

    def get_collection(self, collection_id: str):
        if collection_id == self._collection.id:
            return self._collection
        return None


def _make_api_with_client(fake_client: _FakeClient) -> Search_API:
    api = object.__new__(Search_API)
    api.client = fake_client
    api.search_endpoint = "https://example.test/search"
    return api


def _collection_probe_params(collection):
    """Return a datetime range and an S_INTERSECTS polygon expression from collection extent."""
    # Temporal: use the collection's own start date so there is guaranteed data.
    try:
        start = collection.extent.temporal.intervals[0][0]
        if start is None:
            start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    except Exception:
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    datetime_range = (
        f"{start.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        f"/{end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )

    # Spatial: derive a small polygon centred on the collection bbox.
    try:
        west, south, east, north = collection.extent.spatial.bboxes[0]
        cx = (west + east) / 2
        cy = (south + north) / 2
        half = max(0.5, min(min(abs(east - west), abs(north - south)) / 4, 5.0))
        probe_polygon = (
            f"POLYGON(("
            f"{cx - half:.4f} {cy - half:.4f}, "
            f"{cx + half:.4f} {cy - half:.4f}, "
            f"{cx + half:.4f} {cy + half:.4f}, "
            f"{cx - half:.4f} {cy + half:.4f}, "
            f"{cx - half:.4f} {cy - half:.4f}"
            f"))"
        )
    except Exception:
        probe_polygon = "POLYGON((-100 45, -95 45, -95 50, -100 50, -100 45))"

    return datetime_range, probe_polygon


def _iter_live_queryables(api: Search_API):
    for collection in api.client.get_collections():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                queryables = collection.get_queryables()
            except Exception:
                continue

        properties = queryables.get("properties", {}) if isinstance(queryables, dict) else {}
        if not properties:
            continue

        try:
            items_link = collection.get_single_link("items")
            items_url = items_link.href
        except Exception:
            items_url = f"{api.search_endpoint}/collections/{collection.id}/items"

        probe_datetime, probe_polygon = _collection_probe_params(collection)

        for field_name, field_schema in properties.items():
            yield collection.id, items_url, queryables, field_name, field_schema, probe_datetime, probe_polygon


def _build_probe_request(
    session: requests.Session,
    items_url: str,
    expr: str,
    datetime_range: str,
) -> requests.PreparedRequest:
    return session.prepare_request(
        requests.Request(
            "GET",
            items_url,
            params={
                "limit": 1,
                "datetime": datetime_range,
                "filter": expr,
                "filter-lang": "cql2-text",
            },
        )
    )


def _build_live_probe_expression(
    field_name: str,
    field_schema: dict,
    probe_datetime: str,
    probe_polygon: str,
) -> str:
    """Build a probe expression using values from collection extents when possible."""
    field_type = field_schema.get("type") if isinstance(field_schema, dict) else None
    field_format = field_schema.get("format") if isinstance(field_schema, dict) else None

    if field_type == "geometry-any":
        return f"S_INTERSECTS({field_name}, {probe_polygon})"

    # Ensure datetime-like string queryables use date-only format (YYYY-MM-DD)
    # while remaining inside the collection temporal extent.
    if field_type == "string" and (field_format == "date-time" or "datetime" in field_name.lower()):
        start_iso = probe_datetime.split("/")[0]
        start_date = start_iso.split("T")[0]
        return f"{field_name} >= DATE('{start_date}')"

    return Search_API.build_cql2_example(field_name, field_schema)


def test_extract_filter_fields_handles_geometry_and_strings():
    expr = (
        "S_INTERSECTS(geometry, POLYGON((-100 45, -95 45, -95 50, -100 50, -100 45))) "
        f"AND satellite_id = '{REAL_SATELLITE_ID}' AND relative_orbit = {REAL_RELATIVE_ORBIT}"
    )
    fields = Search_API.extract_filter_fields(expr)

    assert "geometry" in fields
    assert "satellite_id" in fields
    assert "relative_orbit" in fields
    assert "POLYGON" not in fields


def test_extract_filter_fields_accepts_s_intersect_alias():
    expr = "S_INTERSECT(geometry, POLYGON((-100 45, -95 45, -95 50, -100 50, -100 45)))"
    fields = Search_API.extract_filter_fields(expr)

    assert "S_INTERSECT" not in fields
    assert "geometry" in fields


def test_validate_filter_fields_reports_unknown_properties():
    queryables = {
        "properties": {
            "satellite_id": {"type": "string"},
            "relative_orbit": {"type": "integer"},
            "beam_mnemonic": {"type": "string"},
        }
    }
    expr = (
        f"satellite_id = '{REAL_SATELLITE_ID}' AND relative_orbit = {REAL_RELATIVE_ORBIT} "
        f"AND beam_mnemonic = '{REAL_BEAM_MNEMONIC}' AND cloud_cover < 10"
    )

    invalid = Search_API.validate_filter_fields(expr, queryables)

    assert invalid == ["cloud_cover"]


def test_parse_filter_text_normalizes_integer_comparison_spacing():
    parsed = Search_API.parse_filter_text(f"relative_orbit={REAL_RELATIVE_ORBIT}")
    assert parsed == f"relative_orbit = {REAL_RELATIVE_ORBIT}"


def test_parse_filter_text_empty_returns_none():
    assert Search_API.parse_filter_text("   ") is None


def test_build_spatial_filter_expression_normalizes_singular_alias():
    expr = Search_API.build_spatial_filter_expression(
        "POLYGON((-100 45, -95 45, -95 50, -100 50, -100 45))",
        spatial_op="S_INTERSECT",
    )

    assert expr == "S_INTERSECTS(geometry, POLYGON((-100 45, -95 45, -95 50, -100 50, -100 45)))"


def test_compose_filter_combines_attribute_and_geometry_filters():
    expr = Search_API.compose_filter(
        filter_text=f"relative_orbit={REAL_RELATIVE_ORBIT}",
        geometry_wkt="POLYGON((-100 45, -95 45, -95 50, -100 50, -100 45))",
    )

    assert expr == (
        f"(relative_orbit = {REAL_RELATIVE_ORBIT}) AND "
        "S_INTERSECTS(geometry, POLYGON((-100 45, -95 45, -95 50, -100 50, -100 45)))"
    )


def test_compose_filter_returns_geometry_filter_when_no_attribute_filter():
    expr = Search_API.compose_filter(
        geometry_wkt="POLYGON((-100 45, -95 45, -95 50, -100 50, -100 45))"
    )

    assert expr == "S_INTERSECTS(geometry, POLYGON((-100 45, -95 45, -95 50, -100 50, -100 45)))"


def test_stac_search_skips_request_when_filter_field_invalid(monkeypatch, capsys):
    queryables = {"properties": {"relative_orbit": {"type": "integer"}}}
    collection = _FakeCollection("RCMImageProducts", queryables)
    api = _make_api_with_client(_FakeClient(collection))

    class _ShouldNotBeCalledItemSearch:
        def __init__(self, *args, **kwargs):
            raise AssertionError("ItemSearch should not run for invalid filter fields")

    monkeypatch.setattr("eodms.search.ItemSearch", _ShouldNotBeCalledItemSearch)

    items = api.stac_search(
        collections=["RCMImageProducts"],
        limit=10,
        filter=f"satellite_id = '{REAL_SATELLITE_ID}'",
        filter_lang="cql2-text",
    )

    captured = capsys.readouterr()
    assert items == []
    assert "Invalid filter field(s) for collection 'RCMImageProducts': satellite_id" in captured.out


def test_stac_search_runs_when_filter_fields_valid(monkeypatch):
    queryables = {
        "properties": {
            "satellite_id": {"type": "string"},
            "relative_orbit": {"type": "integer"},
        }
    }
    collection = _FakeCollection("RCMImageProducts", queryables)
    api = _make_api_with_client(_FakeClient(collection))

    class _FakeItemSearch:
        def __init__(self, *args, **kwargs):
            self._kwargs = kwargs

        def url_with_parameters(self):
            return "https://example.test/search?filter=satellite_id%20%3D%20'RCM-1'%20AND%20relative_orbit%20%3D%2016"

        def pages_as_dicts(self):
            return [{"features": [{"id": "item-1"}, {"id": "item-2"}]}]

    monkeypatch.setattr("eodms.search.ItemSearch", _FakeItemSearch)

    items = api.stac_search(
        collections=["RCMImageProducts"],
        limit=1,
        filter=f"satellite_id = '{REAL_SATELLITE_ID}' AND relative_orbit = {REAL_RELATIVE_ORBIT}",
        filter_lang="cql2-text",
    )

    assert items == [{"id": "item-1"}]


def test_stac_search_ignores_sortby_when_unsupported(monkeypatch, capsys):
    queryables = {"properties": {"satellite_id": {"type": "string"}}}
    collection = _FakeCollection("RCMImageProducts", queryables)
    api = _make_api_with_client(_FakeClient(collection))

    captured_kwargs = {}

    class _FakeItemSearch:
        def __init__(self, *args, **kwargs):
            captured_kwargs.update(kwargs)

        def url_with_parameters(self):
            return "https://example.test/search?sortby=-datetime"

        def pages_as_dicts(self):
            return [{"features": [{"id": "item-1"}]}]

    monkeypatch.setattr("eodms.search.ItemSearch", _FakeItemSearch)

    items = api.stac_search(
        collections=["RCMImageProducts"],
        limit=1,
        sortby="-datetime",
    )

    captured = capsys.readouterr()
    assert items == [{"id": "item-1"}]
    assert "sortby" not in captured_kwargs
    assert "sortby is not supported by this server and will be ignored." in captured.out


def test_stac_search_prints_progress_for_each_page(monkeypatch, capsys):
    queryables = {"properties": {"satellite_id": {"type": "string"}}}
    collection = _FakeCollection("RCMImageProducts", queryables)
    api = _make_api_with_client(_FakeClient(collection))

    class _FakeItemSearch:
        def __init__(self, *args, **kwargs):
            self._kwargs = kwargs

        def url_with_parameters(self):
            return "https://example.test/search?limit=3"

        def pages_as_dicts(self):
            return [
                {"features": [{"id": "item-1"}, {"id": "item-2"}]},
                {"features": [{"id": "item-3"}]},
            ]

    monkeypatch.setattr("eodms.search.ItemSearch", _FakeItemSearch)

    items = api.stac_search(
        collections=["RCMImageProducts"],
        limit=3,
    )

    captured = capsys.readouterr()
    assert items == [{"id": "item-1"}, {"id": "item-2"}, {"id": "item-3"}]
    assert "Fetched page 1 for RCMImageProducts: 2 items (0 collected so far)" in captured.out
    assert "Fetched page 2 for RCMImageProducts: 1 items (2 collected so far)" in captured.out


@pytest.mark.integration
def test_queryable_examples_do_not_return_500(capsys):
    """Network test: probes each live queryable and fails on HTTP 500."""

    env = os.getenv("EODMS_ENV", "prod")
    selected_collections = {
        name.strip()
        for name in os.getenv("EODMS_QUERYABLES_COLLECTIONS", "").split(",")
        if name.strip()
    }

    api = Search_API(None, env)
    session = requests.Session()
    session.verify = getattr(api.client._stac_io, "session", session).verify

    tested = 0
    failures = []
    diff_lines = []
    for collection_id, items_url, queryables, field_name, field_schema, probe_datetime, probe_polygon in _iter_live_queryables(api):
        if selected_collections and collection_id not in selected_collections:
            continue

        field_type = field_schema.get("type") if isinstance(field_schema, dict) else None
        expr = _build_live_probe_expression(field_name, field_schema, probe_datetime, probe_polygon)
        invalid = Search_API.validate_filter_fields(expr, queryables)
        assert invalid == [], f"Example expression has invalid fields for {collection_id}.{field_name}: {expr}"

        prepared = _build_probe_request(session, items_url, expr, probe_datetime)
        prepared_url = prepared.url or ""

        response = None
        try:
            response = session.send(prepared, timeout=30)
        except requests.exceptions.ReadTimeout as exc:
            pytest.fail(
                f"Read timeout for {collection_id}.{field_name} at {prepared_url}: {exc}"
            )
        assert response is not None

        tested += 1

        label = f"{collection_id}.{field_name} ({field_type}): HTTP {response.status_code} ({expr})"
        if response.status_code == 500:
            failures.append(
                f"{collection_id}.{field_name}: {prepared_url} -> 500 {response.text}"
            )
            diff_lines.append(f"- FAIL  {label}")
            _print_live(f"\033[31m  FAIL  {label}\033[0m", capsys)
        else:
            diff_lines.append(f"+ PASS  {label}")
            _print_live(f"\033[32m  PASS  {label}\033[0m", capsys)

    # Write diff-formatted summary that renders with color in GitHub Markdown.
    report_path = os.path.join(os.path.dirname(__file__), "queryables_report.diff.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("```diff\n")
        f.write("\n".join(diff_lines))
        f.write("\n```\n")
    _print_live(f"\nReport written to {report_path}", capsys)

    assert tested > 0, "No live queryables were tested"
    assert not failures, "Live queryable filters returned HTTP 500:\n" + "\n".join(failures)

