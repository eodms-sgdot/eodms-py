# Additional dependencies required by this script (not part of the core eodms package):
#   pip install fiona shapely
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import click
import fiona
from pystac_client import Client, ItemSearch
from pystac_client.stac_api_io import StacApiIO
from shapely.geometry import shape

# Allow running this script directly from the tests directory.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from eodms import aaa, config


class LoggingStacApiIO(StacApiIO):
    def __init__(self, auth_label: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.auth_label = auth_label

    def request(self, href, method=None, headers=None, parameters=None):
        request_method = method or 'GET'
        print(f"Using {self.auth_label} catalog: {request_method} {href}")
        return super().request(href, method=method, headers=headers, parameters=parameters)


def parse_aoi_file(aoi_file: str) -> List[Dict[str, Any]]:
    """Read polygon features from a GeoJSON, shapefile, or geopackage and return WKT strings."""
    try:
        with fiona.open(aoi_file) as src:
            features = list(src)
    except Exception as e:
        raise ValueError(f"Could not open AOI file '{aoi_file}': {e}")

    polygons = []
    for feature in features:
        geom = feature.get('geometry')
        if geom is None or geom.get('type') not in ('Polygon', 'MultiPolygon'):
            continue
        name = (feature.get('properties') or {}).get('name')
        polygons.append({'name': name, 'wkt': shape(geom).wkt})

    if not polygons:
        raise ValueError("No polygon geometries found in AOI file.")
    if len(polygons) > 5:
        raise ValueError(f"AOI file contains {len(polygons)} polygons; maximum is 5.")

    print(f"Loaded {len(polygons)} polygon(s) from AOI file.")
    return polygons


def parse_filter_text(filter_text: Optional[str]) -> Optional[str]:
    """Normalize a CQL2 text filter string."""
    if not filter_text:
        return None

    filter_text = filter_text.strip()
    if not filter_text:
        return None

    filter_text = re.sub(r"\s*(<=|>=|<>|=|<|>)\s*", r" \1 ", filter_text)
    filter_text = re.sub(r"\s+", " ", filter_text).strip()
    return filter_text


def build_spatial_filter_expression(
    geometry_wkt: Optional[str],
    geometry_field: str = "geometry",
    spatial_op: str = "S_INTERSECTS",
) -> Optional[str]:
    """Build a CQL2 spatial expression from a WKT geometry string."""
    if not geometry_wkt:
        return None

    geometry_wkt = geometry_wkt.strip()
    if not geometry_wkt:
        return None

    op = (spatial_op or "S_INTERSECTS").strip().upper()
    if op == "S_INTERSECT":
        op = "S_INTERSECTS"

    return f"{op}({geometry_field}, {geometry_wkt})"


def compose_filter(
    filter_text: Optional[str] = None,
    geometry_wkt: Optional[str] = None,
    geometry_field: str = "geometry",
) -> Optional[str]:
    """Compose a normalized CQL2 filter with optional spatial predicate."""
    base_filter = parse_filter_text(filter_text)
    spatial_filter = build_spatial_filter_expression(
        geometry_wkt=geometry_wkt,
        geometry_field=geometry_field,
    )

    if base_filter and spatial_filter:
        return f"({base_filter}) AND {spatial_filter}"

    return base_filter or spatial_filter


def save_items_geojson(items: List[Dict[str, Any]], output_file: str):
    """Save item dictionaries as a GeoJSON FeatureCollection."""
    feature_collection = {
        "type": "FeatureCollection",
        "features": items or [],
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(feature_collection, f, indent=2)

    print(f"Saved {len(feature_collection['features'])} items to {output_file}")


def open_client(env: str, username: Optional[str], password: Optional[str]) -> Client:
    """Create an authenticated/unauthenticated pystac_client Client."""
    domain_config = config.get_domain_config(env)
    domain = domain_config['domain']
    search_endpoint = f"{domain}/search"
    verify_ssl = domain_config.get('verify_ssl', True)

    stac_api_io = LoggingStacApiIO("unauthenticated")
    stac_api_io.session.verify = verify_ssl

    if username and password:
        aaa_api = aaa.AAA_API(username, password, env)
        access_token = aaa_api.get_access_token()
        if access_token:
            stac_api_io.session.headers.update({"Authorization": f"Bearer {access_token}"})
            stac_api_io.auth_label = "authenticated"
        else:
            print("Authentication token unavailable; using unauthenticated catalog access.")

    client = Client.open(search_endpoint, stac_io=stac_api_io)
    client.add_conforms_to("FILTER")
    client.add_conforms_to("QUERY")
    return client


def get_item_by_uuid(client: Client, collection: str, item_uuid: str) -> Optional[Dict[str, Any]]:
    """Get a single STAC item by collection and UUID using pure pystac_client."""
    if not collection:
        print("Collection is required when --uuid is provided.")
        return None

    collection_obj = client.get_collection(collection)
    if collection_obj is None:
        print(f"Collection not found: {collection}")
        return None

    item = collection_obj.get_item(item_uuid)
    if item is None:
        print(f"Item not found: {collection}/{item_uuid}")
        return None

    return item.to_dict() if hasattr(item, "to_dict") else item


def stac_search_direct(
    client: Client,
    collections: List[str],
    bbox: Optional[List[float]],
    datetime_range: Optional[str],
    limit: int,
    filter_text: Optional[str],
) -> List[Dict[str, Any]]:
    """Run direct collection/item searches with ItemSearch and return deduplicated items."""
    search_params: Dict[str, Any] = {'limit': limit}
    if bbox:
        search_params['bbox'] = bbox
    if datetime_range:
        search_params['datetime'] = datetime_range
    if filter_text:
        search_params['filter'] = filter_text
        search_params['filter_lang'] = 'cql2-text'

    items: List[Dict[str, Any]] = []
    seen_item_ids = set()
    seen_page_tokens = set()
    seen_page_signatures = set()
    page_count = 0
    print(f"Searching up to limit of {limit}...")

    for collection_id in collections:
        if len(items) >= limit:
            break

        collection = client.get_collection(collection_id)
        if collection is None:
            print(f"Collection not found: {collection_id}")
            continue

        remaining = limit - len(items)
        item_search = ItemSearch(
            url=collection.get_single_link('items').href,
            method='GET',
            client=client,
            max_items=remaining,
            **search_params,
        )

        for page in item_search.pages_as_dicts():
            page_count += 1
            page_items = page.get('features', [])
            page_item_ids = tuple(
                item.get('id')
                for item in page_items
                if isinstance(item, dict)
            )

            page_token = None
            for link in page.get('links', []):
                if isinstance(link, dict) and link.get('rel') == 'next' and link.get('href'):
                    parsed_next = urlparse(link['href'])
                    query = parse_qs(parsed_next.query)
                    vals = query.get('page_token')
                    if vals:
                        page_token = vals[0]
                    break

            if page_token is not None and page_token in seen_page_tokens:
                print(
                    "Detected repeated page_token during pagination; "
                    "stopping to avoid an infinite loop."
                )
                break

            if page_token is not None:
                seen_page_tokens.add(page_token)

            # If 'next' points back to self without a token, signature repeat catches the loop.
            page_signature = (collection_id, page_item_ids, page_token)
            if page_signature in seen_page_signatures:
                print(
                    "Detected repeated page content during pagination; "
                    "stopping to avoid an infinite loop."
                )
                break
            seen_page_signatures.add(page_signature)

            new_items = 0
            duplicate_items = 0
            for item in page_items:
                item_id = item.get('id') if isinstance(item, dict) else None
                item_key = (collection_id, item_id)
                if item_key in seen_item_ids:
                    duplicate_items += 1
                    continue
                seen_item_ids.add(item_key)
                items.append(item)
                new_items += 1
                if len(items) >= limit:
                    break

            print(
                f"Page {page_count} ({page_token}): +{new_items} new, "
                f"{duplicate_items} duplicates, {len(items)} collected"
            )
            if len(items) >= limit:
                break

    print(f"Found {len(items)} items (limited to {limit})")
    return items


def stac_search_catalog(
    client: Client,
    collections: List[str],
    bbox: Optional[List[float]],
    datetime_range: Optional[str],
    limit: int,
    filter_text: Optional[str],
) -> List[Dict[str, Any]]:
    """Run direct catalog.search and return deduplicated items."""
    collections_param: Any = collections[0] if len(collections) == 1 else collections

    search_params: Dict[str, Any] = {
        'method': 'GET',
        'collections': collections_param,
        'limit': limit,
        'max_items': limit,
    }
    if bbox:
        search_params['bbox'] = bbox
    if datetime_range:
        search_params['datetime'] = datetime_range
    if filter_text:
        search_params['filter'] = filter_text
        search_params['filter_lang'] = 'cql2-text'

    print(f"Searching up to limit of {limit} with catalog.search...")
    results = client.search(**search_params)

    items: List[Dict[str, Any]] = []
    seen_item_ids = set()
    seen_page_tokens = set()
    seen_page_signatures = set()
    page_count = 0

    for page in results.pages_as_dicts():
        page_count += 1
        page_items = page.get('features', [])
        page_item_ids = tuple(
            item.get('id')
            for item in page_items
            if isinstance(item, dict)
        )

        page_token = None
        for link in page.get('links', []):
            if isinstance(link, dict) and link.get('rel') == 'next' and link.get('href'):
                parsed_next = urlparse(link['href'])
                query = parse_qs(parsed_next.query)
                vals = query.get('page_token')
                if vals:
                    page_token = vals[0]
                break

        if page_token is not None and page_token in seen_page_tokens:
            print(
                "Detected repeated page_token during catalog.search pagination; "
                "stopping to avoid an infinite loop."
            )
            break

        if page_token is not None:
            seen_page_tokens.add(page_token)

        page_signature = (page_item_ids, page_token)
        if page_signature in seen_page_signatures:
            print(
                "Detected repeated page content during catalog.search pagination; "
                "stopping to avoid an infinite loop."
            )
            break
        seen_page_signatures.add(page_signature)

        new_items = 0
        duplicate_items = 0
        for item in page_items:
            item_id = item.get('id') if isinstance(item, dict) else None
            if item_id is not None and item_id in seen_item_ids:
                duplicate_items += 1
                continue
            if item_id is not None:
                seen_item_ids.add(item_id)
            items.append(item)
            new_items += 1
            if len(items) >= limit:
                break

        print(
            f"Page {page_count} ({page_token}): matched={page.get('numberMatched')}, "
            f"returned={page.get('numberReturned', len(page_items))}, +{new_items} new, "
            f"{duplicate_items} duplicates, {len(items)} collected"
        )
        if len(items) >= limit:
            break

    print(f"Found {len(items)} items (limited to {limit})")
    return items


def run(
    eodms_user,
    eodms_pwd,
    collection,
    env,
    download_dir,
    datetime_range=None,
    bbox=None,
    uuid=None,
    limit=100,
    output=None,
    filter_text=None,
    s_intersect=None,
    aoi=None,
    search_method='itemsearch',
):
    _ = download_dir  # Kept for CLI parity with stac_dds_test.py

    client = open_client(env, eodms_user, eodms_pwd)

    # If UUID is provided, skip search and fetch the item directly.
    if uuid:
        item = get_item_by_uuid(client, collection, uuid)
        if item and output:
            save_items_geojson([item], output)
        return

    if not collection:
        print("Collection is required for search mode.")
        return

    s_intersect_list: List[Dict[str, Any]] = []
    if aoi:
        try:
            s_intersect_list = parse_aoi_file(aoi)
        except ValueError as e:
            print(f"Error parsing AOI file: {e}")
            return
    elif s_intersect:
        s_intersect_list = [{'name': None, 'wkt': s_intersect}]

    if not s_intersect_list:
        s_intersect_list = [{'name': None, 'wkt': None}]

    all_items: List[Dict[str, Any]] = []
    seen_ids = set()

    for idx, geometry_entry in enumerate(s_intersect_list, start=1):
        geometry_name = geometry_entry.get('name')
        geometry_wkt = geometry_entry.get('wkt')
        if geometry_wkt:
            label = geometry_name if geometry_name else f"polygon {idx}"
            print(f"Searching AOI geometry: {label}")

        composed_filter = compose_filter(filter_text=filter_text, geometry_wkt=geometry_wkt)
        if search_method == 'catalog-search':
            items = stac_search_catalog(
                client=client,
                collections=[collection],
                bbox=bbox,
                datetime_range=datetime_range,
                limit=limit,
                filter_text=composed_filter,
            )
        else:
            items = stac_search_direct(
                client=client,
                collections=[collection],
                bbox=bbox,
                datetime_range=datetime_range,
                limit=limit,
                filter_text=composed_filter,
            )

        for item in items:
            item_id = item.get('id') if isinstance(item, dict) else None
            if item_id and item_id in seen_ids:
                continue
            if item_id:
                seen_ids.add(item_id)
            all_items.append(item)

    if output:
        save_items_geojson(all_items, output)


@click.command(context_settings={'help_option_names': ['-h', '--help']})
@click.option('--username', '-u', required=False, help='The EODMS username.')
@click.option('--password', '-p', required=False, help='The EODMS password.')
@click.option('--collection', '-c', required=False, help='The collection name.', default=None)
@click.option('--uuid', required=False, default=None, help='The UUID of the item to fetch (skips search).')
@click.option('--datetime', '-d', required=False, default=None,
              help='Temporal filter as ISO 8601 string or range (e.g., "2023-01-01/2023-12-31").')
@click.option('--bbox', '-b', required=False, default=None,
              help='Bounding box as comma-separated values: west,south,east,north (e.g., "-100,45,-95,50").')
@click.option('--limit', '-l', required=False, default=1000, type=int,
              help='Maximum number of items to fetch from search (default: 1000).')
@click.option('--filter', '-f', 'filter_text', required=False, default=None,
              help="CQL2 text filter expression (e.g., beam_mnemonic LIKE 'SC30M%' AND relative_orbit = 10).")
@click.option('--s-intersect', 's_intersect', required=False, default=None,
              help='WKT geometry used with S_INTERSECTS on geometry (e.g., "POLYGON((-100.0 45.0, -99.2 45.6, -98.3 45.4, -97.4 46.0, -96.6 45.7, -96.1 46.5, -96.8 47.2, -97.9 47.5, -99.1 47.0, -100.0 46.1, -100.0 45.0))").')
@click.option('--aoi', required=False, default=None, type=click.Path(exists=True),
              help='GeoJSON file with 1-5 polygon(s) to search for (e.g., aoi.geojson).')
@click.option('--output', '-o', required=False, default=None,
              help='Output GeoJSON filename (e.g., results.geojson).')
@click.option('--search-method', required=False, default='itemsearch',
              type=click.Choice(['itemsearch', 'catalog-search'], case_sensitive=False),
              help='Search backend: "itemsearch" (collection items endpoint) or "catalog-search" (catalog.search).')
@click.option('--env', '-e', required=False, default='prod', help='Defaults to "prod". If "staging", define `EODMS_STAGING_DOMAIN` env variable.')
@click.option('--download_dir', '-dl', required=False, default='.',
              help='Accepted for parity with stac_dds_test.py. Not used in this pure pystac_client script.')
def cli(username, password, collection, uuid, datetime, bbox, limit, filter_text, s_intersect, aoi, output, search_method, env, download_dir):
    """Pure pystac_client search/fetch test with CLI parity to stac_dds_test.py."""
    bbox_list = None
    if bbox:
        try:
            bbox_list = [float(x.strip()) for x in bbox.split(',')]
            if len(bbox_list) != 4:
                raise ValueError("Bounding box must have exactly 4 values")
        except ValueError as e:
            click.echo(f"Error parsing bbox: {e}", err=True)
            return

    run(
        username,
        password,
        collection,
        env,
        download_dir,
        datetime,
        bbox_list,
        uuid,
        limit,
        output,
        filter_text,
        s_intersect,
        aoi,
        search_method,
    )


if __name__ == '__main__':
    cli()
