import re
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse
from copy import deepcopy

import requests
from pystac_client import Client, ItemSearch
from pystac_client.exceptions import APIError
from pystac_client.stac_api_io import StacApiIO

from . import api_logger
from . import config
from .__version__ import __version__
from .errors import CatalogError, SearchError


class _EODMSStacApiIO(StacApiIO):
	"""StacApiIO variant that honors session.verify instead of forcing verify=True."""

	def request(
		self,
		href: str,
		method: str | None = None,
		headers: dict[str, str] | None = None,
		parameters: dict[str, Any] | None = None,
	) -> str:
		if method == "POST":
			request = requests.Request(method=method, url=href, headers=headers, json=parameters)
		else:
			params = deepcopy(parameters) or {}
			request = requests.Request(method="GET", url=href, headers=headers, params=params)

		try:
			modified = self._req_modifier(request) if self._req_modifier else None
			prepped = self.session.prepare_request(modified or request)
			send_kwargs = {
				"proxies": dict(self.session.proxies or {}),
				"verify": self.session.verify,
				"cert": None,
				"stream": False,
			}
			resp = self.session.send(prepped, timeout=self.timeout, **send_kwargs)
		except Exception as err:
			raise APIError(str(err)) from err

		if resp.status_code != 200:
			raise APIError.from_response(resp)

		try:
			return resp.content.decode("utf-8")
		except Exception as err:
			raise APIError(str(err)) from err


class Search_API:
	@staticmethod
	def _is_cert_verify_error(exc: Exception) -> bool:
		if isinstance(exc, requests.exceptions.SSLError):
			return True
		msg = str(exc).lower()
		return "certificate verify failed" in msg or "certificate_verify_failed" in msg

	@staticmethod
	def _default_user_agent() -> str:
		return f"{requests.utils.default_user_agent()} eodms-py/{__version__}"

	def search_multiple_geometries(
		self,
		s_intersect_list: List[Dict[str, Any]],
		collection: Optional[str] = None,
		datetime_range: Optional[str] = None,
		bbox: Optional[List[float]] = None,
		limit: int = 100,
		filter_text: Optional[str] = None,
	) -> List[Dict[str, Any]]:
		"""
		Perform multiple STAC searches for a list of geometries, deduplicating items by ID.
		Each geometry in s_intersect_list should be a dict with keys 'name' and 'wkt'.
		"""
		all_items = []
		seen_ids = set()
		for idx, geometry_entry in enumerate(s_intersect_list, start=1):
			geometry_name = geometry_entry.get('name')
			geometry_wkt = geometry_entry.get('wkt')
			if geometry_wkt:
				label = geometry_name if geometry_name else f"polygon {idx}"
				self.logger.info(f"Searching AOI geometry: {label}")
			parsed_filter = self.compose_filter(filter_text=filter_text, geometry_wkt=geometry_wkt)
			items = self.stac_search(
				collections=[collection] if collection else None,
				datetime=datetime_range,
				bbox=bbox,
				limit=limit,
				filter=parsed_filter,
				filter_lang='cql2-text' if parsed_filter else None,
			)
			if items:
				for item in items:
					item_id = item.get('id')
					if item_id not in seen_ids:
						all_items.append(item)
						seen_ids.add(item_id)
		return all_items

	def __init__(self, aaa_api=None, environment='prod'):
		domain_config = config.get_domain_config(environment)
		domain = domain_config['domain']
		self.search_endpoint = f"{domain}/search"
		verify_ssl = domain_config.get('verify_ssl', True)
		is_staging = environment == 'staging'
		self.logger = api_logger.EODMSLogger('eodms_search', api_logger.get_logger('search'))
		self._catalog_auth_label = 'unauthenticated'

		def _log_stac_request(req):
			method = getattr(req, 'method', 'GET')
			url = getattr(req, 'url', self.search_endpoint)
			self.logger.debug(f"Using {self._catalog_auth_label} catalog: {method} {url}")
			return req

		stac_api_io = _EODMSStacApiIO(request_modifier=_log_stac_request)
		stac_api_io.session.verify = verify_ssl
		stac_api_io.session.proxies.update(requests.utils.get_environ_proxies(self.search_endpoint))
		stac_api_io.session.trust_env = False
		stac_api_io.session.headers.update({"User-Agent": self._default_user_agent()})
		self.logger.debug(
			f"Outbound User-Agent: {stac_api_io.session.headers.get('User-Agent')}"
		)

		auth_enabled = False
		if aaa_api:
			access_token = aaa_api.get_access_token()
			if access_token:
				stac_api_io.session.headers.update(
					aaa_api.get_default_headers(stac_api_io.session.headers)
				)
				self.logger.debug(
					f"Outbound User-Agent: {stac_api_io.session.headers.get('User-Agent')}"
				)
				stac_api_io.session.headers.update({"Authorization": f"Bearer {access_token}"})
				auth_enabled = True
				self._catalog_auth_label = 'authenticated'
			else:
				if getattr(aaa_api, "last_error", None) is not None:
					self.logger.warning(f"Authentication unavailable; continuing unauthenticated. Details: {aaa_api.last_error}")
				self.logger.warning("Authentication token unavailable; using unauthenticated catalog access.")

		def _open_client():
			return Client.open(
				self.search_endpoint,
				stac_io=stac_api_io,
				request_modifier=_log_stac_request,
			)

		try:
			self.client = _open_client()
		except (APIError, Exception) as e:
			root_exc = e

			if is_staging and isinstance(verify_ssl, str) and self._is_cert_verify_error(e):
				self.logger.warning(
					"Staging catalog TLS verification failed using configured CA bundle; "
					"retrying with verify=False."
				)
				stac_api_io.session.verify = False
				try:
					self.client = _open_client()
					return
				except (APIError, Exception) as fallback_exc:
					root_exc = fallback_exc

			if auth_enabled:
				# Fallback when AAA is temporarily unhealthy or token is invalid/expired.
				self.logger.error(
					"Authenticated catalog initialization failed; "
					"retrying unauthenticated access. "
					f"Details: {root_exc}"
				)
				stac_api_io.session.headers.pop("Authorization", None)
				self._catalog_auth_label = 'unauthenticated'
				try:
					self.client = _open_client()
				except Exception as fallback_error:
					self.logger.error(f"Unauthenticated catalog initialization failed: {fallback_error}")
					raise CatalogError(
						f"Unable to initialize STAC catalog after authentication fallback: {fallback_error}"
					) from fallback_error
			else:
				self.logger.error(f"Catalog initialization failed: {root_exc}")
				raise CatalogError(f"Unable to initialize STAC catalog: {root_exc}") from root_exc
		self.client.add_conforms_to("FILTER")
		self.client.add_conforms_to("QUERY")

	@staticmethod
	def extract_filter_fields(filter_text: Optional[str]) -> List[str]:
		"""Extract likely property names from a CQL2 text expression."""
		if not filter_text:
			return []

		func_names = {
			"and", "or", "not", "in", "between", "like", "ilike", "is", "null", "true", "false",
			"s_intersect", "s_intersects", "s_contains", "s_within", "s_overlaps", "s_touches", "s_crosses", "s_disjoint",
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
		if not filter_text.strip():
			return None

		filter_text = re.sub(r"\s*(<=|>=|<>|=|<|>)\s*", r" \1 ", filter_text)
		filter_text = re.sub(r"\s+", " ", filter_text).strip()

		return filter_text

	@staticmethod
	def build_spatial_filter_expression(
		geometry_wkt: Optional[str],
		geometry_field: str = "geometry",
		spatial_op: str = "S_INTERSECTS",
	) -> Optional[str]:
		"""Build a CQL2 spatial predicate from WKT geometry."""
		if not geometry_wkt:
			return None

		geometry_wkt = geometry_wkt.strip()
		if not geometry_wkt:
			return None

		op = (spatial_op or "S_INTERSECTS").strip().upper()
		if op == "S_INTERSECT":
			op = "S_INTERSECTS"

		return f"{op}({geometry_field}, {geometry_wkt})"

	@staticmethod
	def compose_filter(
		filter_text: Optional[str] = None,
		geometry_wkt: Optional[str] = None,
		geometry_field: str = "geometry",
	) -> Optional[str]:
		"""Compose a normalized CQL2 filter, optionally adding a spatial predicate."""
		base_filter = Search_API.parse_filter_text(filter_text)
		spatial_filter = Search_API.build_spatial_filter_expression(
			geometry_wkt=geometry_wkt,
			geometry_field=geometry_field,
		)

		if base_filter and spatial_filter:
			return f"({base_filter}) AND {spatial_filter}"

		return base_filter or spatial_filter

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


	"""Build queryable field lines for a collection, including type and constraints."""
	def _build_queryables_lines(self, collection: Any) -> List[str]:
		lines: List[str] = []
		try:
			queryables = collection.get_queryables()
			properties = queryables.get("properties", {}) if isinstance(queryables, dict) else {}
			if properties:
				for field_name, field_schema in properties.items():
					field_type = "unknown"
					constraint_parts: List[str] = []
					if isinstance(field_schema, dict):
						field_type = field_schema.get("type", "unknown")

						enum_vals = field_schema.get("enum")
						if isinstance(enum_vals, list) and enum_vals:
							max_preview = 5
							enum_preview = ", ".join(str(v) for v in enum_vals[:max_preview])
							if len(enum_vals) > max_preview:
								enum_preview += ", ..."
							constraint_parts.append(f"enum=[{enum_preview}]")

						minimum = field_schema.get("minimum")
						maximum = field_schema.get("maximum")
						if minimum is not None or maximum is not None:
							constraint_parts.append(f"min={minimum} max={maximum}")

						pattern = field_schema.get("pattern")
						if isinstance(pattern, str) and pattern:
							constraint_parts.append(f"pattern={pattern}")
					example_expr = Search_API.build_cql2_example(field_name, field_schema, collection)
					constraints_text = f" | constraints: {'; '.join(constraint_parts)}" if constraint_parts else ""
					lines.append(f"      * {field_name} ({field_type}) e.g. {example_expr}{constraints_text}")
			else:
				lines.append("      * No queryable properties returned")
		except Exception as e:
			lines.append(f"      * Queryables not available: {e}")

		return lines

	"""Print queryable fields for a collection as a single log entry."""
	def print_queryables(self, collection: Any) -> None:
		collection_id = getattr(collection, "id", "unknown")
		lines = [f"Collection '{collection_id}' queryables:"]
		lines.extend(self._build_queryables_lines(collection))
		message = "\n".join(lines)
		self.logger.info("%s", message)

	"""Print all available collections and their queryable fields."""
	def print_collections(self) -> None:
		"""Print all available collections and their queryable fields."""
		available_collections = list(self.client.get_collections())
		lines = ["Available collections and queryables:"]
		for collection in available_collections:
			collection_id = getattr(collection, "id", "unknown")
			lines.append(f"  - Collection: {collection_id}")
			lines.extend(self._build_queryables_lines(collection))

		message = "\n".join(lines)
		self.logger.info("%s", message)
			

	@staticmethod
	def build_cql2_example(field_name: str, field_schema: Any, collection: Any = None) -> str:
		"""Build a simple CQL2 text example expression for a queryable field."""
		field_type = None
		field_format = None
		enum_vals = None
		if isinstance(field_schema, dict):
			field_type = field_schema.get("type")
			field_format = field_schema.get("format")
			enum_vals = field_schema.get("enum")

		if isinstance(enum_vals, list) and enum_vals:
			enum_value = enum_vals[0]
			if isinstance(enum_value, str):
				escaped = enum_value.replace("'", "''")
				return f"{field_name} = '{escaped}'"
			if isinstance(enum_value, bool):
				return f"{field_name} = {'true' if enum_value else 'false'}"
			if enum_value is None:
				return f"{field_name} IS NULL"
			return f"{field_name} = {enum_value}"

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
		if collections is None:
			self.print_collections()
			return []

		search_params: Dict[str, Any] = {'limit': limit}
		if bbox:
			search_params['bbox'] = bbox
		if datetime:
			search_params['datetime'] = datetime
		# Server does not support STAC sort extension; ignore any sortby requests.
		if sortby is not None or 'sortby' in kwargs:
			self.logger.warning("sortby is not supported by this server and will be ignored.")
		kwargs.pop('sortby', None)

		search_params.update(kwargs)

		try:
			items: List[Dict[str, Any]] = []
			seen_item_ids = set()
			seen_pages = set()
			self.logger.info(f"Searching up to limit of {limit}...")
			filter_text = kwargs.get('filter')
			page_count = 0

			for collection_id in collections:
				if len(items) >= limit:
					break

				collection = self.client.get_collection(collection_id)
				if collection is None:
					self.logger.warning(f"Collection not found: {collection_id}")
					continue

				if filter_text:
					queryables = collection.get_queryables()
					invalid_fields = Search_API.validate_filter_fields(filter_text, queryables)
					if invalid_fields:
						properties = queryables.get("properties", {}) if isinstance(queryables, dict) else {}
						valid_fields = sorted(properties.keys())
						self.logger.warning(
							f"Invalid filter field(s) for collection '{collection_id}': {', '.join(invalid_fields)}"
						)
						if valid_fields:
							self.logger.info(f"Available queryable fields: {', '.join(valid_fields)}")
						else:
							self.logger.info("No queryable fields are available for this collection.")
						continue

				remaining = limit - len(items)
				item_search = ItemSearch(
					url=collection.get_single_link('items').href,
					method='GET',
					client=self.client,
					max_items=remaining,
					**search_params,
				)

				self.logger.debug(unquote(item_search.url_with_parameters()))

				for page in item_search.pages_as_dicts():
					page_count += 1
					page_items = page.get('features', [])

					# Detect repeated pages to avoid looping forever if server pagination is unstable.
					page_item_ids = tuple(
						item.get('id')
						for item in page_items
						if isinstance(item, dict)
					)
					next_hrefs = tuple(
						link.get('href')
						for link in page.get('links', [])
						if isinstance(link, dict) and link.get('rel') == 'next'
					)
					page_token = None
					if next_hrefs:
						parsed_next = urlparse(next_hrefs[0])
						query = parse_qs(parsed_next.query)
						vals = query.get("page_token")
						if vals:
							page_token = vals[0]

					if page_token is not None and page_token in seen_pages:
						self.logger.warning(
							"Detected repeated page token during pagination; "
							"stopping to avoid an infinite loop."
						)
						break

					if page_token is not None:
						seen_pages.add(page_token)

					new_items = 0
					duplicate_items = 0

					for item in page_items:
						item_id = item.get('id') if isinstance(item, dict) else None
						if item_id is not None:
							item_key = (collection_id, item_id)
							if item_key in seen_item_ids:
								duplicate_items += 1
								continue
							seen_item_ids.add(item_key)

						items.append(item)
						new_items += 1
						if len(items) >= limit:
							break

					self.logger.info(
						f"Page {page_count} ({page_token}): ({len(items)} collected so far)"
					)
					if len(items) >= limit:
						break

			self.logger.info(f"Found {len(items)} items (limited to {limit})")
		except Exception as e:
			self.logger.error(f"Search error: {e}")
			raise SearchError(f"STAC search failed: {e}") from e

		return items

	def get_item(self, collection: str, item_uuid: str) -> Optional[Dict[str, Any]]:
		"""Get a single STAC item by collection ID and item UUID."""
		if not collection:
			self.logger.error("Collection is required.")
			return None
		if not item_uuid:
			self.logger.error("item_uuid is required.")
			return None

		try:
			collection_obj = self.client.get_collection(collection)
			if collection_obj is None:
				self.logger.warning(f"Collection not found: {collection}")
				return None

			item = collection_obj.get_item(item_uuid)
			if item is None:
				self.logger.warning(f"Item not found: {collection}/{item_uuid}")
				return None

			return item.to_dict() if hasattr(item, "to_dict") else item
		except Exception as e:
			self.logger.error(f"Get item error: {e}")
			return None


# Backward-compatible module-level helpers.
def parse_filter_text(filter_text: Optional[str]):
	return Search_API.parse_filter_text(filter_text)


def build_spatial_filter_expression(
	geometry_wkt: Optional[str],
	geometry_field: str = "geometry",
	spatial_op: str = "S_INTERSECTS",
) -> Optional[str]:
	return Search_API.build_spatial_filter_expression(geometry_wkt, geometry_field, spatial_op)


def compose_filter(
	filter_text: Optional[str] = None,
	geometry_wkt: Optional[str] = None,
	geometry_field: str = "geometry",
) -> Optional[str]:
	return Search_API.compose_filter(filter_text, geometry_wkt, geometry_field)


def build_cql2_example(field_name: str, field_schema: Any) -> str:
	return Search_API.build_cql2_example(field_name, field_schema)


def print_queryables(search_api: Search_API) -> None:
	search_api.print_queryables()


def get_item(search_api: Search_API, collection: str, item_uuid: str) -> Optional[Dict[str, Any]]:
	return search_api.get_item(collection, item_uuid)
