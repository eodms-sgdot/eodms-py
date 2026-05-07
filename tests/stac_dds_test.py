from eodms import dds, aaa, search
from typing import Optional, List, Dict, Any
import json
import os
import click

def download(dds_api, collection, item_uuid, out_folder):

    if item_info is None:
        print(f"Item not found: Collection={collection}, Feature ID={item_uuid}")
        return None

    if 'download_url' not in item_info.keys():
        print(f"No download URL found for item: Collection={collection}, Feature ID={item_uuid} item_info={item_info}")
        return None

    dds_api.download_item(os.path.abspath(out_folder))

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

def run(
    eodms_user,
    eodms_pwd,
    collection,
    env,
    out_folder,
    datetime_range=None,
    bbox=None,
    uuid=None,
    limit=100,
    output=None,
    filter_text=None,
    s_intersect=None,
):
    # Create shared AAA instance
    aaa_api = aaa.AAA_API(eodms_user, eodms_pwd, env) if eodms_user and eodms_pwd else None

    dds_api = dds.DDS_API(aaa_api, env)

    # If UUID is provided, skip search and download directly
    if uuid:
        print(f"Downloading image with UUID: {uuid}")
        download(dds_api, collection, uuid, out_folder)
        return

    parsed_filter = search.compose_filter(filter_text=filter_text, geometry_wkt=s_intersect)

    # Search using pystac_client with shared AAA instance
    search_api = search.Search_API(aaa_api, env)
    items = search_api.stac_search(
        collections=[collection] if collection else None,
        datetime=datetime_range,
        bbox=bbox,
        limit=limit,
        filter=parsed_filter,
        filter_lang='cql2-text' if parsed_filter else None,
    )

    if items is not None and output:
        save_items_geojson(items, output)
    else:
        print(f"not outputiong items to geojson because output is {output}")
        
    
    if items and len(items) > 0 and eodms_user and eodms_pwd:
        uuid = items[0].get('id')
        print(f"Downloading the first image (UUID: {uuid}) from the list")
        download(dds_api, collection, uuid, out_folder)
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
              help="CQL2 text filter expression (e.g., roll_number = 'KA3').")
@click.option('--s-intersect', 's_intersect', required=False, default=None,
              help='WKT geometry used with S_INTERSECTS on geometry (e.g., "POLYGON((-100.0 45.0, -99.2 45.6, -98.3 45.4, -97.4 46.0, -96.6 45.7, -96.1 46.5, -96.8 47.2, -97.9 47.5, -99.1 47.0, -100.0 46.1, -100.0 45.0))").')
@click.option('--output', required=False, default=None,
              help='Output GeoJSON filename (e.g., results.geojson).')
@click.option('--env', '-e', required=False, default='prod', help='Defaults to "prod". If "staging", define `EODMS_STAGING_DOMAIN` env variable.')
@click.option('--out_folder', '-o', required=False, default='.',
              help='The output folder.')
def cli(username, password, collection, uuid, datetime, bbox, limit, filter_text, s_intersect, output, env, out_folder):
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
    # Search with limit
    python stac_dds_test.py -u USER -p PASS -c RCMImageProducts -l 50
    
    \b
    # Download specific image by UUID (skips search)
    python stac_dds_test.py -u USER -p PASS -c RCMImageProducts --uuid 12345678-1234-1234-1234-123456789abc
    
    \b
    # Specify output folder
    python stac_dds_test.py -u USER -p PASS -c RCMImageProducts -o ./downloads

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
        out_folder,
        datetime,
        bbox_list,
        uuid,
        limit,
        output,
        filter_text,
        s_intersect,
    )

if __name__ == '__main__':
    cli()