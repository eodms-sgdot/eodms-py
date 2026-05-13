import json
import os
import sys
from typing import Optional, List, Dict, Any
import click

# Allow running this script directly from the tests directory.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from eodms import dds, aaa, search

def download(dds_api, collection, item_uuid, download_dir):

    item_info = dds_api.get_item(collection, item_uuid)
    
    if item_info is None:
        print(f"Item not found: Collection={collection}, Feature ID={item_uuid}")
        return None

    if 'download_url' not in item_info.keys():
        print(f"No download URL found for item: Collection={collection}, Feature ID={item_uuid} item_info={item_info}")
        return None

    dds_api.download_item(os.path.abspath(download_dir))

    return item_info


def save_items_geojson(items: List[Dict[str, Any]], output_file: str):
    """Save item dictionaries as a GeoJSON FeatureCollection."""
    feature_collection = {
        "type": "FeatureCollection",
        "features": items or [],
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(feature_collection, f, indent=2)

    print(f"Saved {len(feature_collection['features'])} items to {output_file}")


def parse_aoi_geojson(aoi_file: str) -> List[Dict[str, Any]]:
    """
    Parse GeoJSON AOI file and extract polygon geometries with optional names.
    
    Args:
        aoi_file: Path to GeoJSON file containing 1-5 polygons.
        
    Returns:
        List of geometry dicts with keys: name, wkt.
        
    Raises:
        ValueError: If polygons are not valid or count is outside 1-5 range.
    """
    try:
        with open(aoi_file, 'r', encoding='utf-8') as f:
            geojson_data = json.load(f)
    except FileNotFoundError:
        raise ValueError(f"AOI file not found: {aoi_file}")
    except json.JSONDecodeError:
        raise ValueError(f"AOI file is not valid JSON: {aoi_file}")
    
    polygons = []
    
    # Extract features from FeatureCollection or use feature directly
    if geojson_data.get('type') == 'FeatureCollection':
        features = geojson_data.get('features', [])
    elif geojson_data.get('type') == 'Feature':
        features = [geojson_data]
    else:
        features = []
    
    # Extract polygon geometries
    for feature in features:
        props = feature.get('properties', {}) if isinstance(feature, dict) else {}
        geometry_name = props.get('name')
        geometry = feature.get('geometry', {})
        if geometry.get('type') == 'Polygon':
            polygons.append({'name': geometry_name, 'geometry': geometry})
        elif geometry.get('type') == 'MultiPolygon':
            # Flatten MultiPolygon into individual polygons
            for idx, poly in enumerate(geometry.get('coordinates', []), start=1):
                polygons.append({
                    'name': f"{geometry_name} part {idx}" if geometry_name else None,
                    'geometry': {'type': 'Polygon', 'coordinates': poly},
                })
    
    if not polygons:
        raise ValueError("No polygons found in AOI GeoJSON file.")
    
    if len(polygons) > 5:
        raise ValueError(f"AOI file contains {len(polygons)} polygons; maximum is 5.")
    
    # Convert GeoJSON polygons to WKT format
    wkt_polygons = []
    for polygon_entry in polygons:
        polygon = polygon_entry.get('geometry', {})
        coords = polygon.get('coordinates', [])
        if not coords:
            raise ValueError("Polygon has no coordinates.")
        
        # coords[0] is the outer ring (lon, lat) pairs
        ring = coords[0]
        # Convert to WKT: POLYGON((lon lat, lon lat, ...))
        wkt_coords = ', '.join(f"{lon} {lat}" for lon, lat in ring)
        wkt = f"POLYGON(({wkt_coords}))"
        wkt_polygons.append({'name': polygon_entry.get('name'), 'wkt': wkt})
    
    print(f"Loaded {len(wkt_polygons)} polygon(s) from AOI file.")
    return wkt_polygons

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
):
    # Create shared AAA instance
    aaa_api = aaa.AAA_API(eodms_user, eodms_pwd, env) if eodms_user and eodms_pwd else None

    dds_api = dds.DDS_API(aaa_api, env)

    # If UUID is provided, skip search and download directly
    if uuid:
        print(f"Downloading image with UUID: {uuid}")
        download(dds_api, collection, uuid, download_dir)
        return

    # Build list of s_intersect geometries to search
    s_intersect_list: List[Dict[str, Any]] = []
    if aoi:
        try:
            s_intersect_list = parse_aoi_geojson(aoi)
        except ValueError as e:
            print(f"Error parsing AOI file: {e}")
            return
    elif s_intersect:
        s_intersect_list = [{'name': None, 'wkt': s_intersect}]
    
    # If no geometry specified, do a single search without geometry
    if not s_intersect_list:
        s_intersect_list = [{'name': None, 'wkt': None}]
    
    # Search using pystac_client with shared AAA instance
    search_api = search.Search_API(aaa_api, env)
    all_items = []
    seen_ids = set()
    
    for idx, geometry_entry in enumerate(s_intersect_list, start=1):
        geometry_name = geometry_entry.get('name')
        geometry_wkt = geometry_entry.get('wkt')
        if geometry_wkt:
            label = geometry_name if geometry_name else f"polygon {idx}"
            print(f"Searching AOI geometry: {label}")
        parsed_filter = search.compose_filter(filter_text=filter_text, geometry_wkt=geometry_wkt)
        
        items = search_api.stac_search(
            collections=[collection] if collection else None,
            datetime=datetime_range,
            bbox=bbox,
            limit=limit,
            filter=parsed_filter,
            filter_lang='cql2-text' if parsed_filter else None,
        )
        
        # Deduplicate items by ID
        if items:
            for item in items:
                item_id = item.get('id')
                if item_id not in seen_ids:
                    all_items.append(item)
                    seen_ids.add(item_id)
    
    items = all_items if all_items else None

    if items is not None and output:
        save_items_geojson(items, output)
    
    if items and len(items) > 0 and eodms_user and eodms_pwd:
        uuid = items[0].get('id')
        print(f"Downloading the first image (UUID: {uuid}) from the list")
        download(dds_api, collection, uuid, download_dir)
    elif items and len(items) > 0:
        print("No credentials provided, skipping download.")


@click.command(context_settings={'help_option_names': ['-h', '--help']})
@click.option('--username', '-u', required=False, help='The EODMS username.')
@click.option('--password', '-p', required=False, help='The EODMS password.')
@click.option('--collection', '-c', required=False, help='The collection name.', default=None)
@click.option('--uuid', required=False, default=None, help='The UUID of the image to download (skips search).')
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
@click.option('--env', '-e', required=False, default='prod', help='Defaults to "prod". If "staging", define `EODMS_STAGING_DOMAIN` env variable.')
@click.option('--download_dir', '-dl', required=False, default='.',
              help='The download directory.')
def cli(username, password, collection, uuid, datetime, bbox, limit, filter_text, s_intersect, aoi, output, env, download_dir):
    """
    Search and Download images from EODMS STAC catalog and DDS.
    
    Examples:
    
    \b
    # Search and download first RCM image
    python stac_dds_test.py -u USER -p PASS -c RCMImageProducts
    
    \b
    # Search with datetime filter
    python stac_dds_test.py -u USER -p PASS -c RCMImageProducts -d "2023-01-01/2023-12-31"
    
    \b
    # Search with bounding box (west,south,east,north)
    python stac_dds_test.py -u USER -p PASS -c RCMImageProducts -b "-100,45,-95,50"
    
    \b
    # Search with S_INTERSECTS geometry filter
    python stac_dds_test.py -u USER -p PASS -c RCMImageProducts --s-intersect "POLYGON((-100.0 45.0, -99.2 45.6, -98.3 45.4, -97.4 46.0, -96.6 45.7, -96.1 46.5, -96.8 47.2, -97.9 47.5, -99.1 47.0, -100.0 46.1, -100.0 45.0))"
    
    
    \b
    # Search with AOI from GeoJSON file (1-5 polygons)
    python stac_dds_test.py -u USER -p PASS -c RCMImageProducts --aoi aoi.geojson
    
    \b
    # Search with limit
    python stac_dds_test.py -u USER -p PASS -c RCMImageProducts -l 50
    
    \b
    # Download specific image by UUID (skips search)
    python stac_dds_test.py -u USER -p PASS -c RCMImageProducts --uuid 12345678-1234-1234-1234-123456789abc
    
    \b
    # Specify download directory
    python stac_dds_test.py -u USER -p PASS -c RCMImageProducts -dl ./downloads

    \b
    # Specify product type filter along with output results
    python stac_dds_test.py -u USER -p PASS -c RCMImageProducts -d "2026-01-01/2026-05-05" -f "product:type = 'MLC'" --output results.geojson
    """
    
    # Parse bbox string to list of floats
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
    )

if __name__ == '__main__':
    cli()