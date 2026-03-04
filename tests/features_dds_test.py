import sys
from pathlib import Path
# Add parent directory to path to allow imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from eodms_dds import dds, aaa, config
import requests
from typing import List, Dict, Any, Optional
import os
import click
import json
from datetime import datetime as dt

class OGCFeature:
    def __init__(self, feature_dict):
        self.id = feature_dict.get('id')
        self.type = feature_dict.get('type')
        self.geometry = feature_dict.get('geometry')
        self.properties = feature_dict.get('properties', {})
        self.raw = feature_dict
    def __repr__(self):
        return f"OGCFeature(id={self.id}, type={self.type})"
    def to_dict(self):
        return self.raw
    def print_feature(self):
        print(f"Feature ID: {self.id}")
        print(f"Type: {self.type}")
        print(f"Geometry: {self.geometry}")
        print("Properties:")
        for key, value in self.properties.items():
            print(f"  {key}: {value}")

class OGCFeatureCollection:
    def __init__(self, collection_dict):
        self.type = collection_dict.get('type')
        self.features = [OGCFeature(f) for f in collection_dict.get('features', [])]
        self.raw = collection_dict
    def __repr__(self):
        return f"OGCFeatureCollection(type={self.type}, features={len(self.features)})"
    def to_dict(self):
        return self.raw

class OGCFeaturesClient:
    def __init__(self, base_url, access_token=None, verify_ssl=True):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.headers = {}
        if access_token:
            self.headers['Authorization'] = f'Bearer {access_token}'

    def get_collections(self):
        url = f"{self.base_url}/collections"
        resp = self.session.get(url, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def get_features(self, collection_id, bbox=None, datetime=None, limit=None, intersects=None):
        url = f"{self.base_url}/collections/{collection_id}/items"
        params = {}
        if bbox:
            params['bbox'] = ','.join(str(x) for x in bbox)
        if intersects:
            params['intersects'] = intersects
        if datetime:
            params['datetime'] = datetime
        if limit is not None:
            params['limit'] = limit
        
        all_features = []
        next_page = None
        page_count = 0
        
        while limit is None or len(all_features) < limit:
            if next_page:
                params['page_token'] = next_page
            page_count += 1
            #print(f"Fetching {url} with params: {params}")
            resp = self.session.get(url, headers=self.headers, params=params)
            resp.raise_for_status()
            data = resp.json()
           
            features = data.get('features', [])
            all_features.extend(features)
            
            # Check for next page token in links or directly in response
            next_page = None
            links = data.get('links', [])
            for link in links:
                if link.get('rel') == 'next':
                    # Extract page_token from next link if present
                    next_url = link.get('href', '')
                    if 'page_token=' in next_url:
                        next_page = next_url.split('page_token=')[1].split('&')[0]
                        print(f"Fetched page {page_count} (features: {len(all_features)} next_page: {next_page})")
                    break
            
            if not next_page:
                break
        
        # Construct final collection with all features
        final_data = data.copy()
        final_data['features'] = all_features
        return OGCFeatureCollection(final_data)

    def get_feature(self, collection_id, feature_id):
        url = f"{self.base_url}/collections/{collection_id}/items/{feature_id}"
        resp = self.session.get(url, headers=self.headers)
        resp.raise_for_status()
        return OGCFeature(resp.json())

# OGC Features: /collections

def get_collections(aaa_api=None, environment='prod') -> List[Dict[str, Any]]:
    domain_config = config.get_domain_config(environment)
    domain = domain_config['domain']
    search_endpoint = f"{domain}/search"
    verify_ssl = domain_config.get('verify_ssl', True)
    access_token = None
    if aaa_api:
        access_token = aaa_api.get_access_token()
    client = OGCFeaturesClient(search_endpoint, access_token, verify_ssl)
    return client.get_collections()

# OGC Features: /collections/{collectionId}/items

def get_features(
    collection_id: str,
    aaa_api=None,
    environment='prod',
    bbox: Optional[List[float]] = None,
    datetime: Optional[str] = None,
    limit: Optional[int] = None
) -> Dict[str, Any]:
    domain_config = config.get_domain_config(environment)
    domain = domain_config['domain']
    search_endpoint = f"{domain}/search"
    verify_ssl = domain_config.get('verify_ssl', True)
    access_token = None
    if aaa_api:
        access_token = aaa_api.get_access_token()
    client = OGCFeaturesClient(search_endpoint, access_token, verify_ssl)
    return client.get_features(collection_id, bbox, datetime, limit)

# OGC Features: /collections/{collectionId}/items/{featureId}

def get_feature(
    collection_id: str,
    feature_id: str,
    aaa_api=None,
    environment='prod'
) -> Dict[str, Any]:
    domain_config = config.get_domain_config(environment)
    domain = domain_config['domain']
    search_endpoint = f"{domain}/search"
    verify_ssl = domain_config.get('verify_ssl', True)
    access_token = None
    if aaa_api:
        access_token = aaa_api.get_access_token()
    client = OGCFeaturesClient(search_endpoint, access_token, verify_ssl)
    return client.get_feature(collection_id, feature_id)

def download(dds_api, collection, item_uuid, out_folder):

    item_info = dds_api.get_item(collection, item_uuid)

    if item_info is None:
        return None

    if 'download_url' not in item_info.keys():
        return None

    dds_api.download_item(os.path.abspath(out_folder))

    return item_info

def run(username, password, collection, feature_id, env, bbox, datetime, limit, output, geojson=None, print_feature=False):
    domain_config = config.get_domain_config(env)
    base_url = f"{domain_config['domain']}/search"
    verify_ssl = domain_config.get('verify_ssl', True)
    access_token = None
    if username and password:
        aaa_api = aaa.AAA_API(username, password, env)
        access_token = aaa_api.get_access_token()
    client = OGCFeaturesClient(base_url, access_token, verify_ssl)

    if not collection and not feature_id:
        result = client.get_collections()
        collections = result.get('collections', [])
        print(f"OGC Features collections: {len(collections)}")
        for coll in collections:
            print(f"  - {coll.get('id')}")
        return

    if feature_id:
        feature = client.get_feature(collection, feature_id)
        
        if print_feature:
            feature.print_feature()
        else:
            aaa_api = aaa.AAA_API(username, password, env) if username and password else None
            dds_api = dds.DDS_API(aaa_api, env)
            download(dds_api, collection, feature.id, '.')
            
        return

    if collection:
        # If GeoJSON file is provided, extract point geometries and search for features that contain them
        if geojson:
            try:
                with open(geojson, 'r') as f:
                    geojson_data = json.load(f)
                features = geojson_data.get('features', [])
                all_geojson_features = []
                
                for idx, feature in enumerate(features):
                    geom = feature.get('geometry', {})
                    if geom.get('type') == 'Point':
                        coords = geom.get('coordinates', [])
                        if len(coords) >= 2:
                            lon, lat = coords[0], coords[1]
                            # Use point geometry for spatial intersection to find features containing this point
                            point_geom = json.dumps({'type': 'Point', 'coordinates': [lon, lat]})
                            print(f"Searching point {idx + 1}/{len(features)}: lon={lon}, lat={lat}")
                            point_result = client.get_features(collection, intersects=point_geom, datetime=datetime, limit=limit)
                            # Avoid adding duplicate features
                            existing_ids = {f.id for f in all_geojson_features}
                            for f in point_result.features:
                                if f.id not in existing_ids:
                                    all_geojson_features.append(f)
                                    existing_ids.add(f.id)
                            print(f"  Found {len(point_result.features)} features for point {idx + 1}")
                
                # Create combined result
                result = OGCFeatureCollection({
                    'type': 'FeatureCollection',
                    'features': [f.to_dict() for f in all_geojson_features]
                })
                print(f"Total features from GeoJSON points: {len(all_geojson_features)}")
            except (json.JSONDecodeError, IOError, KeyError) as e:
                click.echo(f"Error processing GeoJSON file: {e}", err=True)
                return
        #result = client.get_features(collection, bbox, datetime, limit)
        # Handle multi-year datetime ranges by splitting into yearly chunks
        elif datetime and '/' in datetime:
            try:
                start_str, end_str = datetime.split('/')
                start_dt = dt.fromisoformat(start_str.replace('Z', '+00:00'))
                end_dt = dt.fromisoformat(end_str.replace('Z', '+00:00'))
                
                # Check if spans multiple years
                if end_dt.year > start_dt.year:
                    print(f"Date range spans multiple years ({start_dt.year} to {end_dt.year}), splitting into yearly queries...")
                    all_features = []
                    current_year = start_dt.year
                    
                    while current_year <= end_dt.year:
                        # Determine start of year period
                        if current_year == start_dt.year:
                            year_start = start_dt
                        else:
                            year_start = dt(current_year, 1, 1)
                        
                        # Determine end of year period
                        if current_year == end_dt.year:
                            year_end = end_dt
                        else:
                            year_end = dt(current_year, 12, 31, 23, 59, 59)
                        
                        # Format datetime with proper Z suffix
                        year_start_str = year_start.strftime('%Y-%m-%dT%H:%M:%SZ')
                        year_end_str = year_end.strftime('%Y-%m-%dT%H:%M:%SZ')
                        year_datetime = f"{year_start_str}/{year_end_str}"
                        print(f"Querying year {current_year}: {year_datetime}")
                        
                        year_result = client.get_features(collection, bbox, year_datetime, limit)
                        all_features.extend(year_result.features)
                        print(f"  Found {len(year_result.features)} features for {current_year}")
                        
                        current_year += 1
                        

                    # Create combined result
                    result = OGCFeatureCollection({
                    'type': 'FeatureCollection',
                    'features': [f.to_dict() for f in all_features]
                    })
                    print(f"Total features across all years: {len(all_features)}")
                else:
                    result = client.get_features(collection, bbox, datetime, limit)
            except (ValueError, AttributeError) as e:
                print(f"Error parsing datetime range: {e}, proceeding with original query")
                result = client.get_features(collection, bbox, datetime, limit)
        else:
            result = client.get_features(collection, bbox, datetime, limit)


        print(f"Found {len(result.features)} features in collection '{collection}':")
        # for feature in result.features:
        #     print(f"  - Feature ID: {feature.id}")
        
        if output and result:
            
            # Combine existing features with new ones
            all_feature_dicts = [f.to_dict() for f in result.features]
            
            # Create GeoJSON FeatureCollection
            geojson_output = {
                'type': 'FeatureCollection',
                'features': all_feature_dicts
            }
            
            # Write to file
            with open(output, 'w') as f:
                json.dump(geojson_output, f, indent=2)
            
            click.echo(f"Results saved to {output} ({len(all_feature_dicts)} total features)")

@click.command(context_settings={'help_option_names': ['-h', '--help']})
@click.option('--username', '-u', required=False, help='The EODMS username.')
@click.option('--password', '-p', required=False, help='The EODMS password.')
@click.option('--collection', '-c', required=False, help='The collection name.')
@click.option('--feature_id', '-f', required=False, help='The feature (item) ID.')
@click.option('--bbox', '-b', required=False, default=None,
              help='Bounding box as comma-separated values: west,south,east,north (e.g., "-100,45,-95,50").')
@click.option('--geojson', '-g', required=False, default=None, type=click.Path(exists=True),
              help='Path to a GeoJSON file containing point geometries for spatial search.')
@click.option('--datetime', '-d', required=False, default=None,
              help='Temporal filter as ISO 8601 string or range (e.g., "2020-10-31T00:00:00Z/2020-11-04T23:59:00Z").')
@click.option('--env', '-e', required=False, default='prod', help='Defaults to "prod". If "staging", define `EODMS_STAGING_DOMAIN` env variable.')
@click.option('--limit', '-l', required=False, default=None, type=int, help='Maximum number of features to return.')
@click.option('--output', '-o', required=False, help='Output file path to save the results (JSON format).')
@click.option('--print', '-pr', 'print_feature', is_flag=True, help='Print the feature when --feature_id is provided instead of downloading.')
def main(username, password, collection, feature_id, bbox, geojson, datetime, env, limit, output, print_feature):
    """
    OGC Features CLI for EODMS Search API.
    
    Examples:
    
    \b
    # List all guest collections
    python features_dds_test.py
    
    \b
    # List all collections with authentication
    python features_dds_test.py -u USER -p PASS

    \b
    # List features in a collection
    python features_dds_test.py -u USER -p PASS -c RCMImageProducts -l 5
    
    \b
    # Get a single feature by ID
    python features_dds_test.py -u USER -p PASS -c RCMImageProducts -f some-feature-id
    
    \b
    # Filter by bbox and datetime
    python features_dds_test.py -u USER -p PASS -c RCMImageProducts -b "-100,45,-95,50" -d "2020-10-31T00:00:00Z/2020-11-04T23:59:00Z"
    
    \b
    # Filter by GeoJSON file containing point geometries
    python features_dds_test.py -u USER -p PASS -c RCMImageProducts -g points.geojson
    
    \b
    # Save results to file
    python features_dds_test.py -u USER -p PASS -c RCMImageProducts -l 5 -o results.json
    """
    bbox_list = None
    if bbox:
        try:
            bbox_list = [float(x.strip()) for x in bbox.split(',')]
            if len(bbox_list) != 4:
                raise ValueError("Bounding box must have exactly 4 values")
        except ValueError as e:
            click.echo(f"Error parsing bbox: {e}", err=True)
            return
    
    run(username, password, collection, feature_id, env, bbox_list, datetime, limit, output, geojson, print_feature)
    

if __name__ == '__main__':
    main()
