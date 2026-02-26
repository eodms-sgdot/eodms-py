from . import config
import requests
from typing import List, Dict, Any, Optional

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

    def get_features(self, collection_id, bbox=None, datetime=None, limit=10):
        url = f"{self.base_url}/collections/{collection_id}/items"
        params = {}
        if bbox:
            params['bbox'] = ','.join(str(x) for x in bbox)
        if datetime:
            params['datetime'] = datetime
        params['limit'] = limit
        
        all_features = []
        page_token = None
        page_count = 0
        
        while len(all_features) < limit:
            if page_token:
                print(f"Fetching page {page_count + 1} (features: {len(all_features)} token: {page_token})")
                params['page_token'] = page_token
            page_count += 1
            resp = self.session.get(url, headers=self.headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            
            features = data.get('features', [])
            all_features.extend(features)
            
            # Check for next page token in links or directly in response
            page_token = None
            links = data.get('links', [])
            for link in links:
                if link.get('rel') == 'next':
                    # Extract page_token from next link if present
                    next_url = link.get('href', '')
                    if 'page_token=' in next_url:
                        page_token = next_url.split('page_token=')[1].split('&')[0]
                    break
            
            # Alternative: check if page_token is directly in response
            if not page_token:
                page_token = data.get('page_token')
            
            if not page_token:
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

class Search_API:

    def __init__(self, aaa_api=None):
        self.aaa_api = aaa_api

    def get_collections(self, environment='prod') -> List[Dict[str, Any]]:
        domain_config = config.get_domain_config(environment)
        domain = domain_config['domain']
        search_endpoint = f"{domain}/search"
        verify_ssl = domain_config.get('verify_ssl', True)
        access_token = None
        if self.aaa_api:
            access_token = self.aaa_api.get_access_token()
        client = OGCFeaturesClient(search_endpoint, access_token, verify_ssl)
        return client.get_collections()

    # OGC Features: /collections/{collectionId}/items

    def get_features(self, 
        collection_id: str,
        environment='prod',
        bbox: Optional[List[float]] = None,
        datetime: Optional[str] = None,
        limit: int = 10
    ) -> Dict[str, Any]:
        domain_config = config.get_domain_config(environment)
        domain = domain_config['domain']
        search_endpoint = f"{domain}/search"
        verify_ssl = domain_config.get('verify_ssl', True)
        access_token = None
        if self.aaa_api:
            access_token = self.aaa_api.get_access_token()
        client = OGCFeaturesClient(search_endpoint, access_token, verify_ssl)
        return client.get_features(collection_id, bbox, datetime, limit)

    # OGC Features: /collections/{collectionId}/items/{featureId}

    def get_feature(self, 
        collection_id: str,
        feature_id: str,
        environment='prod'
    ) -> Dict[str, Any]:
        domain_config = config.get_domain_config(environment)
        domain = domain_config['domain']
        search_endpoint = f"{domain}/search"
        verify_ssl = domain_config.get('verify_ssl', True)
        access_token = None
        if self.aaa_api:
            access_token = self.aaa_api.get_access_token()
        client = OGCFeaturesClient(search_endpoint, access_token, verify_ssl)
        return client.get_feature(collection_id, feature_id)