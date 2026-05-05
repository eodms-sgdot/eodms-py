import re
import warnings
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
			if access_token:
				stac_api_io.session.headers.update({"Authorization": f"Bearer {access_token}"})
				print(f"Using authenticated catalog: {self.search_endpoint}")
			else:
				print("Authentication token unavailable; using unauthenticated catalog access.")
				print(f"Using unauthenticated catalog: {self.search_endpoint}")
		else:
			print(f"Using unauthenticated catalog: {self.search_endpoint}")

		self.client = Client.open(self.search_endpoint, stac_io=stac_api_io)
		self.client.add_conforms_to("FILTER")
		self.client.add_conforms_to("QUERY")

	@staticmethod
	def extract_filter_fields(filter_text: Optional[str]) -> List[str]:
		"""Extract likely property names from a CQL2 text expression."""
		if not filter_text:
			return []

		func_names = {
			"and", "or", "not", "in", "between", "like", "ilike", "is", "null", "true", "false",
			"s_intersects", "s_contains", "s_within", "s_overlaps", "s_touches", "s_crosses", "s_disjoint",
			"t_before", "t_after", "t_intersects", "a_contains", "a_overlaps",
			"date",
			"point", "linestring", "polygon", "multipoint", "multilinestring", "multipolygon", "geometrycollection",
		}

		# Strip quoted strings before token matching so string literals are not treated as fields.
		cleaned = re.sub(r"'[^']*'|\"[^\"]*\"", " ", filter_text)
		tokens = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_:.]*\b", cleaned)

		fields: List[str] = []
		seen = set()
		for token in tokens:
			lower_token = token.lower()
			if lower_token in func_names:
				continue
			if re.fullmatch(r"\d+(\.\d+)?", token):
				continue
			if token not in seen:
				seen.add(token)
				fields.append(token)

		return fields

	@staticmethod
	def validate_filter_fields(filter_text: Optional[str], queryables: Dict[str, Any]) -> List[str]:
		"""Return any filter fields that are not present in collection queryables."""
		if not filter_text:
			return []

		properties = queryables.get("properties", {}) if isinstance(queryables, dict) else {}
		allowed_fields = set(properties.keys())
		requested_fields = Search_API.extract_filter_fields(filter_text)

		return [field for field in requested_fields if field not in allowed_fields]

	@staticmethod
	def parse_filter_text(filter_text: Optional[str]):
		"""Normalize a CQL2 text filter string."""
		if not filter_text:
			return None

		filter_text = filter_text.strip()
		if not filter_text:
			return None

		# Normalize compact comparisons like "field=16" to "field = 16".
		filter_text = re.sub(r"\s*(<=|>=|<>|=|<|>)\s*", r" \1 ", filter_text)
		filter_text = re.sub(r"\s+", " ", filter_text).strip()

		return filter_text

	@staticmethod
	def _get_collection_example_datetime(collection: Any) -> str:
		"""Get a representative datetime within the collection temporal extent."""
		try:
			coll_dict = collection.to_dict() if hasattr(collection, "to_dict") else {}
			extent = coll_dict.get("extent", {})
			temporal = extent.get("temporal", {})
			intervals = temporal.get("interval", [])

			for interval in intervals:
				if not isinstance(interval, list) or len(interval) == 0:
					continue
				start = interval[0]
				end = interval[1] if len(interval) > 1 else None
				if start:
					return start
				if end:
					return end
		except Exception:
			pass

		return "2020-01-01T00:00:00Z"

	@staticmethod
	def build_cql2_example(field_name: str, field_schema: Any, collection: Any = None) -> str:
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
			example_dt = Search_API._get_collection_example_datetime(collection)
			example_date = str(example_dt).split("T")[0]
			return f"{field_name} >= DATE('{example_date}')"
		if field_type == "geometry-any":
			return f"S_INTERSECTS({field_name}, POLYGON((-100 45, -95 45, -95 50, -100 50, -100 45)))"
		return f"{field_name} = 'example'"

	def stac_search(
		self,
		collections: Optional[List[str]] = None,
		bbox: Optional[List[float]] = None,
		datetime: Optional[str] = None,
		limit: int = 100,
		sortby: Optional[Any] = None,
		**kwargs
	) -> List[Dict[str, Any]]:
		"""Search the EODMS STAC catalog using the OGC Features items endpoint.

		:param collections: List of collection IDs to search
		:param bbox: Bounding box as [west, south, east, north]
		:param datetime: Temporal filter as ISO 8601 string or range
		:param limit: Maximum number of items to return
		:param sortby: Ignored (server-side sortby is not supported by this deployment)
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
							example_expr = Search_API.build_cql2_example(field_name, field_schema, collection)
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

		# Server does not support STAC sort extension; ignore any sortby requests.
		if sortby is not None or 'sortby' in kwargs:
			print("sortby is not supported by this server and will be ignored.")
		kwargs.pop('sortby', None)

		search_params.update(kwargs)

		try:
			items: List[Dict[str, Any]] = []
			print(f"Searching for up to {limit} items...")
			filter_text = kwargs.get('filter')
			page_count = 0

			for collection_id in collections:
				if len(items) >= limit:
					break

				collection = self.client.get_collection(collection_id)
				if collection is None:
					print(f"Collection not found: {collection_id}")
					continue

				if filter_text:
					queryables = collection.get_queryables()
					invalid_fields = Search_API.validate_filter_fields(filter_text, queryables)
					if invalid_fields:
						properties = queryables.get("properties", {}) if isinstance(queryables, dict) else {}
						valid_fields = sorted(properties.keys())
						print(
							f"Invalid filter field(s) for collection '{collection_id}': {', '.join(invalid_fields)}"
						)
						if valid_fields:
							print(f"Available queryable fields: {', '.join(valid_fields)}")
						else:
							print("No queryable fields are available for this collection.")
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

				for page in item_search.pages_as_dicts():
					page_count += 1
					page_items = page.get('features', [])
					print(
						f"Fetched page {page_count} for {collection_id}: "
						f"{len(page_items)} items ({len(items)} collected so far)"
					)
					for item in page_items:
						items.append(item)
						if len(items) >= limit:
							break
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
