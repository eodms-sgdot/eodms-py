import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from eodms_dds import dds, aaa, config
from pystac_client import Client
from typing import Optional, List, Dict, Any
# import json
import click
import os
import ssl
import requests
from requests.packages import urllib3
from urllib.parse import unquote
from urllib.parse import urlparse, parse_qs

def search(aaa_api=None, environment='prod', 
                collection = None,
                bbox: Optional[List[float]] = None,
                datetime: Optional[str] = None,
                limit = 100,
                **kwargs) -> List[Dict[str, Any]]:
    """
    Search the EODMS STAC catalog using pystac_client.
    
    :param aaa_api: Optional AAA_API instance for authentication
    :param environment: Environment to use ('prod' or 'staging')
    :param collection: Collection ID to search
    :param bbox: Bounding box as [west, south, east, north]
    :param datetime: Temporal filter as ISO 8601 string or range
    :param kwargs: Additional search parameters
    :return: List of item dictionaries
    """
    
    domain_config = config.get_domain_config(environment)
    domain = domain_config['domain']
    search_endpoint = f"{domain}/search"
    verify_ssl = domain_config.get('verify_ssl', True)
    
    # Create a custom session with verify setting
    session = requests.Session()
    session.verify = verify_ssl
    
    # Prepare headers with authentication if available
    headers = None
    if aaa_api:
        access_token = aaa_api.get_access_token()
        if not access_token:
            print("Authentication failed - no access token available")
            return []
        headers = {"Authorization": f"Bearer {access_token}"}
        catalog = Client.open(search_endpoint, headers=headers)
    else:
        catalog = Client.open(search_endpoint)
    
    # If no search parameters, just list collections
    if collection is None:
        try:
            print("STAC Collections:")
            collections_list = []
            for collection in catalog.get_collections():
                coll_dict = collection.to_dict()
                collections_list.append(coll_dict)
                print(f"  - {coll_dict.get('id')}")
            return collections_list
        except Exception as e:
            print(f"Error listing collections: {e}")
            return []
    
    # Execute search
    try:
        items = []

        search = catalog.search(
            collections=[collection],
            bbox=bbox,
            datetime=datetime,
            limit=100,
            method='GET'
        )
        search_results = search.item_collection()
        
        # Convert to list of dictionaries
        if search_results:
            items = [item.to_dict() for item in search_results if item is not None]
            print(f"{collection}: {len(items)} results")
        else:
            print(f"{collection}: No results found")

    except Exception as e:
        print(f"Search error: {e}")
        return []
    
    return items

def download(dds_api, collection, feature_id, out_folder):

    item_info = dds_api.get_item(collection, feature_id)

    if item_info is None:
        print(f"Item not found: Collection={collection}, Feature ID={feature_id}")
        return None

    if 'download_url' not in item_info.keys():
        print(f"No download URL found for item: Collection={collection}, Feature ID={feature_id} item_info={item_info}")
        return None

    dds_api.download_item(os.path.abspath(out_folder))

    return item_info

def run(eodms_user, eodms_pwd, collection, env, out_folder, datetime_range=None, bbox=None, feature_id=None, limit=100, test=False):

    # Create shared AAA instance
    aaa_api = aaa.AAA_API(eodms_user, eodms_pwd, env) if eodms_user and eodms_pwd else None

    dds_api = dds.DDS_API(aaa_api, env)

    # If test mode is enabled, cycle through all collections and download first feature from each
    if test:
        skipped_collections = []
        print("#### TEST MODE: Downloading first feature from specificied collections ####\n")

        if collection is not None:
            collections_list = [{'id': collection}]
        else:
            # Get all collections
            collections_list = search(aaa_api=aaa_api, environment=env, collection=None)
        
        for coll_dict in collections_list:
            coll_id = coll_dict.get('id')

            # Skip certain collection prefixes
            if coll_id.startswith(('aaa')):
                skipped_collections.append(coll_id)
                continue
            
            # Search for first feature in this collection
            items = search(
                aaa_api=aaa_api,
                environment=env,
                collection=coll_id,
                datetime=datetime_range,
                bbox=bbox,
                limit=1
            )
            
            if items and len(items) > 0:
                first_feature_id = None
                for item in items:
                    item_id = item.get('id')
                    if item_id:
                        first_feature_id = item_id
                        break
                
                if first_feature_id:         
                    download(dds_api, coll_id, first_feature_id, out_folder)
                else:
                    print(f"  No valid feature ID found in {coll_id}")
            else:
                print(f"  No features found in {coll_id}")
        
        print("\nTest mode completed.")
        print(f"Skipped collections: {', '.join(skipped_collections)}")
        return

    # If feature_id is provided, skip search and download directly
    if feature_id:
        print(f"Downloading image with feature ID: {feature_id}")
        download(dds_api, collection, feature_id, out_folder)
        return

    # Search using pystac_client with shared AAA instance
    items = search(
        aaa_api=aaa_api,
        environment=env,
        collection=collection,
        datetime=datetime_range,
        bbox=bbox,
        limit=limit
    )
    

@click.command(context_settings={'help_option_names': ['-h', '--help']})
@click.option('--username', '-u', required=False, help='The EODMS username.')
@click.option('--password', '-p', required=False, help='The EODMS password.')
@click.option('--collection', '-c', required=False, default=None, help='The collection name.')
@click.option('--feature_id', '-f', required=False, default=None, help='The feature (item) ID to download (skips search).')
@click.option('--datetime', '-d', required=False, default=None,
              help='Temporal filter as ISO 8601 string or range (e.g., "2023-01-01/2023-12-31").')
@click.option('--bbox', '-b', required=False, default=None,
              help='Bounding box as comma-separated values: west,south,east,north (e.g., "-100,45,-95,50").')
@click.option('--limit', '-l', required=False, default=None, type=int,
              help='Maximum number of items to fetch from search (default: 1000).')
@click.option('--env', '-e', required=False, default='prod', help='Defaults to "prod". If "staging", define `EODMS_STAGING_DOMAIN` env variable.')
@click.option('--out_folder', '-o', required=False, default='.',
              help='The output folder.')
@click.option('--test', is_flag=True, default=False,
              help='Test mode: cycle through all collections and download the first feature from each.')
def cli(username, password, collection, feature_id, datetime, bbox, limit, env, out_folder, test):
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
    # Search with limit
    python stac_dds_test.py -u USER -p PASS -c RCMImageProducts -l 50
    
    \b
    # Download specific image by UUID (skips search)
    python stac_dds_test.py -u USER -p PASS -c RCMImageProducts --uuid 12345678-1234-1234-1234-123456789abc
    
    \b
    # Specify output folder
    python stac_dds_test.py -u USER -p PASS -c RCMImageProducts -o ./downloads
    
    \b
    # Test mode: download first feature from all collections
    python stac_dds_test.py -u USER -p PASS --test
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

    run(username, password, collection, env, out_folder, datetime, bbox_list, feature_id, limit, test)

if __name__ == '__main__':
    cli()