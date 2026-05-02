from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from pystac_client import Client, ItemSearch
from pystac_client.stac_api_io import StacApiIO

from . import config


class Search_API:
	"""STAC search client for the EODMS catalog."""

	def __init__(self, aaa_api=None, environment='prod'):
		domain_config = config.get_domain_config(environment)
		domain = domain_config['domain']
		self.search_endpoint = f"{domain}/search"
		verify_ssl = domain_config.get('verify_ssl', True)

		stac_api_io = StacApiIO()
		stac_api_io.session.verify = verify_ssl

		if aaa_api:
			access_token = aaa_api.get_access_token()
			if not access_token:
				raise RuntimeError("Authentication failed - no access token available")
			stac_api_io.session.headers.update({"Authorization": f"Bearer {access_token}"})
			print(f"Using authenticated catalog: {self.search_endpoint}")
		else:
			print(f"Using unauthenticated catalog: {self.search_endpoint}")

		self.client = Client.open(self.search_endpoint, stac_io=stac_api_io)
		self.client.add_conforms_to("FILTER")
		self.client.add_conforms_to("QUERY")

	@staticmethod
	def parse_filter_text(filter_text: Optional[str]):
		"""Normalize a CQL2 text filter string."""
		if not filter_text:
			return None

		filter_text = filter_text.strip()
		if not filter_text:
			return None

		return filter_text

	@staticmethod
	def build_cql2_example(field_name: str, field_schema: Any) -> str:
		"""Build a simple CQL2 text example expression for a queryable field."""
		field_type = None
		field_format = None
		if isinstance(field_schema, dict):
			field_type = field_schema.get("type")
			field_format = field_schema.get("format")

		if field_type in ("number", "integer"):
			return f"{field_name} = 1"
		if field_type == "boolean":
			return f"{field_name} = true"
		if field_format == "date-time":
			return f"{field_name} >= '2020-01-01T00:00:00Z'"
		if field_type == "geometry-any":
			return f"S_INTERSECTS({field_name}, POLYGON((-100 45, -95 45, -95 50, -100 50, -100 45)))"
		return f"{field_name} = 'example'"

	def stac_search(
		self,
		collections: Optional[List[str]] = None,
		bbox: Optional[List[float]] = None,
		datetime: Optional[str] = None,
		limit: int = 100,
		**kwargs
	) -> List[Dict[str, Any]]:
		"""Search the EODMS STAC catalog using the OGC Features items endpoint.

		:param collections: List of collection IDs to search
		:param bbox: Bounding box as [west, south, east, north]
		:param datetime: Temporal filter as ISO 8601 string or range
		:param limit: Maximum number of items to return
		:param kwargs: Additional search parameters (e.g. filter, filter_lang)
		:return: List of item dictionaries
		"""
		available_collections = list(self.client.get_collections())

		if collections is None:
			print("Available collections and queryables:")
			for collection in available_collections:
				print(f"  - {collection.id}")
				try:
					queryables = collection.get_queryables()
					properties = queryables.get("properties", {}) if isinstance(queryables, dict) else {}
					if properties:
						for field_name, field_schema in properties.items():
							field_type = "unknown"
							if isinstance(field_schema, dict):
								field_type = field_schema.get("type", "unknown")
							example_expr = Search_API.build_cql2_example(field_name, field_schema)
							print(f"      * {field_name} ({field_type}) e.g. {example_expr}")
					else:
						print("      * No queryable properties returned")
				except Exception as e:
					print(f"      * Queryables not available: {e}")
			return []

		search_params: Dict[str, Any] = {'limit': limit}
		if bbox:
			search_params['bbox'] = bbox
		if datetime:
			search_params['datetime'] = datetime
		search_params.update(kwargs)

		try:
			items: List[Dict[str, Any]] = []
			print(f"Searching for up to {limit} items...")

			for collection_id in collections:
				if len(items) >= limit:
					break

				collection = self.client.get_collection(collection_id)
				if collection is None:
					print(f"Collection not found: {collection_id}")
					continue

				remaining = limit - len(items)
				item_search = ItemSearch(
					url=collection.get_single_link('items').href,
					method='GET',
					client=self.client,
					max_items=remaining,
					**search_params,
				)

				print(unquote(item_search.url_with_parameters()))

				for item in item_search.items_as_dicts():
					items.append(item)
					if len(items) >= limit:
						break

			print(f"Found {len(items)} items (limited to {limit})")
		except Exception as e:
			print(f"Search error: {e}")
			return []

		return items


# Backward-compatible module-level helpers.
def parse_filter_text(filter_text: Optional[str]):
	return Search_API.parse_filter_text(filter_text)


def build_cql2_example(field_name: str, field_schema: Any) -> str:
	return Search_API.build_cql2_example(field_name, field_schema)
