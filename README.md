eodms-py EODMS Client Package
================

The EODMS API Client was designed using Python 3.10.

## Pip Installation

```bash
pip install git+https://github.com/eodms-sgdot/eodms-py.git
```

## Usage

### Get and Download Image

> **_NOTE:_** Before using the DDS API, you'll need a valid item UUID for the target collection. You can discover UUIDs with [stac_dds_test.py](./tests/stac_dds_test.py) and then download via DDS.

```python
from eodms import aaa, dds

# First, create the AAA_API with your EODMS username and password.
aaa_api = aaa.AAA_API('myeodmsusername', 'myeodmspassword')

# Next, create the client DDS API using the AAA obj
dds_api = dds.DDS_API(aaa_api)

# Set the Collection Id and the UUID
collection = 'RCMImageProducts'
item_uuid = '01d0c4e2-853b-5d05-b48f-7d768bb249c5'

# Once the DDS_API has been initialized, you can now get an item with a UUID and the Collection Id.
item_info = dds_api.get_item(collection, item_uuid)

# NOTE: item_info is also stored as self.item_info in the DDS_API object.

# Download the image to a specific location (the download link will be taken from the self.item_info)
out_folder = "/home/myuser"
dds_api.download_item(out_folder)
```

### Search STAC Catalog

The `Search_API` class provides helpers for searching the EODMS STAC catalog using [pystac-client](https://pystac-client.readthedocs.io/).

```python
from eodms import aaa, search

aaa_api = aaa.AAA_API('myeodmsusername', 'myeodmspassword')

# Build an authenticated Search_API
search_api = search.Search_API(aaa_api=aaa_api, environment='prod')

# List available collections and their queryable fields
search_api.stac_search(collections=None)
```

For a full search-and-download example see [stac_dds_test.py](./tests/stac_dds_test.py) and [features_dds_test.py](./tests/features_dds_test.py).

### For External CLI Integrators

The package and wrapper responsibilities are intentionally separated:

- Package (`eodms`): emits logs on `eodms.*` loggers and raises typed exceptions.
- Wrapper CLI: configures handlers/format/level, catches exceptions, and decides exit codes/user-facing messages.

By default, the package uses a `NullHandler`, so importing it will not force log output. External CLIs can either configure Python logging globally or call `api_logger.configure_logging(...)` explicitly.

```python
import logging
import os
import sys

from eodms import AAA_API, DDSError, Search_API, SearchError, CatalogError


def main() -> int:
  # Wrapper-owned logging policy.
  logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
  )

  try:
    aaa_api = AAA_API(os.environ["EODMS_USERNAME"], os.environ["EODMS_PASSWORD"])
    search_api = Search_API(aaa_api=aaa_api, environment="prod")

    items = search_api.stac_search(collections=["RCMImageProducts"], limit=5)
    print(f"Found {len(items)} items")
    return 0
  except CatalogError as exc:
    logging.getLogger("cli").error("Catalog initialization failed: %s", exc)
    return 2
  except SearchError as exc:
    logging.getLogger("cli").error("Search failed: %s", exc)
    return 3
  except DDSError as exc:
    logging.getLogger("cli").error("DDS failed: %s", exc)
    return 4


if __name__ == "__main__":
  raise SystemExit(main())
```

### Run OGC Processes Jobs (RADARSAT-1 L1)

The `Processes_API` class provides helpers for the EODMS OGC Processes workflow used in [radarsat1_l1_processing.ipynb](https://github.com/eodms-sgdot/radarsat-notebooks/blob/main/examples/radarsat1_l1_processing.ipynb):

- list processes
- print process input schema
- submit a process job
- poll job status
- download output files from job results

```python
import os
from eodms import aaa, Processes_API

aaa_api = aaa.AAA_API(os.environ['EODMS_USERNAME'], os.environ['EODMS_PASSWORD'])
proc_api = Processes_API(aaa_api=aaa_api, environment='prod')

# List all available processes
processes = proc_api.list_processes()

# Print expected input structure for a process
proc_api.print_process_inputs('Radarsat1GAMMAL1SLC')

# Submit RADARSAT-1 L1 processing job
order = proc_api.submit_r1_process(
  segment_id='your-fred-segment-uuid',
  process_id='Radarsat1GAMMAL1SLC',
  start_time='2007-06-21T10:18:22Z',
  stop_time='2007-06-21T10:18:28Z',
)
job_id = order['jobID']

# Wait for terminal job status
status = proc_api.poll_job_status(job_id, interval=60, timeout=3600)

# Download all output files referenced by /jobs/{jobID}/results
downloaded = proc_api.download_job_results(job_id, out_dir=f'./data/{job_id}')
print(downloaded)
```

### Environment and TLS Behavior

The `--env` flag controls TLS verification behavior in the client, so you can keep proxy and CA environment variables set all the time without shell toggling.

- `prod`
  - Ignores CA-bundle environment variables (`REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`, `CURL_CA_BUNDLE`).
  - Uses standard certificate verification (`verify=True`).
- `staging`
  - Requires `EODMS_STAGING_DOMAIN`.
  - Uses `REQUESTS_CA_BUNDLE`, then `SSL_CERT_FILE`, then `CURL_CA_BUNDLE` when set.
  - Falls back to insecure mode (`verify=False`) if no CA-bundle variable is set.

Proxy environment variables (`HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY`) are respected in both environments.

This keeps EODMS credentials managed by the client while avoiding accidental auth side effects from ambient `.netrc` settings.

## Testing

### Clone Repository

```bash
git clone https://github.com/eodms-sgdot/eodms-py.git
```

### Package Installation

Install the package in editable mode so that changes to the source are reflected immediately:

```bash
cd eodms-py
pip install -e .
```

### Run stac_dds_test.py

Searches the EODMS STAC catalog using the OGC Features items endpoint (paginated) and downloads the first result via DDS. Use `--queryables` to list available collections and queryable fields.

```
Usage: stac_dds_test.py [OPTIONS]

  Search and Download images from EODMS STAC catalog and DDS.

Options:
  -u, --username TEXT      The EODMS username.
  -p, --password TEXT      The EODMS password.
  -c, --collection TEXT    The collection name.
      --uuid TEXT          UUID of the image to download (skips search).
      --queryables         List available STAC collections and queryable
                 fields, then exit.
  -d, --datetime TEXT      Temporal filter as ISO 8601 string or range
                           (e.g., "2023-01-01/2023-12-31").
  -b, --bbox TEXT          Bounding box: west,south,east,north
                           (e.g., "-100,45,-95,50").
  -l, --limit INTEGER      Maximum number of items to fetch (default: 1000).
  -f, --filter TEXT        CQL2 text filter expression
                           (e.g., "roll_number = 'KA3'").
      --s-intersect TEXT   WKT geometry for S_INTERSECTS spatial filter.
      --aoi PATH           GeoJSON file with 1-5 polygon(s) for spatial filter.
  -o, --output TEXT        Output GeoJSON filename (e.g., results.geojson).
  -e, --env TEXT           Environment: "prod" (default) or "staging".
  -dl, --download_dir TEXT Download directory (default: current folder).
  -h, --help               Show this message and exit.
```

```bash
# List all collections and queryable fields
python stac_dds_test.py --queryables

# Search and download first RCM image
python stac_dds_test.py -u eodms_user -p eodms_pwd -c RCMImageProducts

# Search with datetime and bbox filters
python stac_dds_test.py -u eodms_user -p eodms_pwd -c RCMImageProducts -d "2023-01-01/2023-12-31" -b "-100,45,-95,50"

# Apply a CQL2 filter and save results as GeoJSON
python stac_dds_test.py -u eodms_user -p eodms_pwd -c RCMImageProducts -f "roll_number = 'KA3'" --output results.geojson

# Search with an AOI from a GeoJSON file (1-5 polygons)
python stac_dds_test.py -u eodms_user -p eodms_pwd -c RCMImageProducts --aoi tests/aoi.geojson --output results.geojson

# Specify a download directory
python stac_dds_test.py -u eodms_user -p eodms_pwd -c RCMImageProducts -dl ./downloads
```

### Run pystac_client_test.py (Vanilla pystac-client Demo)

Demonstrates direct pystac-client usage without the Search_API wrapper. This test supports two paging/search paths:

- `itemsearch`: Uses `ItemSearch` against `/collections/{id}/items`.
- `catalog-search`: Uses `catalog.search(...)` directly.

See implementation in [tests/pystac_client_test.py](./tests/pystac_client_test.py).

```
Usage: pystac_client_test.py [OPTIONS]

  Pure pystac-client search/fetch test with CLI parity to stac_dds_test.py.

Options:
  -u, --username TEXT      The EODMS username.
  -p, --password TEXT      The EODMS password.
  -c, --collection TEXT    The collection name.
      --uuid TEXT          UUID of the item to fetch (skips search).
  -d, --datetime TEXT      Temporal filter as ISO 8601 string or range.
  -b, --bbox TEXT          Bounding box: west,south,east,north.
  -l, --limit INTEGER      Maximum number of items to fetch (default: 1000).
  -f, --filter TEXT        CQL2 text filter expression.
      --s-intersect TEXT   WKT geometry for S_INTERSECTS spatial filter.
      --aoi PATH           GeoJSON file with 1-5 polygon(s) for spatial filter.
  -o, --output TEXT        Output GeoJSON filename.
      --search-method      Search backend: itemsearch or catalog-search.
  -e, --env TEXT           Environment: prod (default) or staging.
  -dl, --download_dir TEXT Accepted for CLI parity; not used in this script.
  -h, --help               Show this message and exit.
```

```bash
# ItemSearch path (collection items endpoint)
python tests/pystac_client_test.py --search-method itemsearch -c rcm-ard -l 1000 -d "2025-01-01/2026-05-01"

# catalog.search path
python tests/pystac_client_test.py --search-method catalog-search -c rcm-ard -l 1000 -d "2025-01-01/2026-05-01"

# Match reported URL parameters (limit + datetime)
python tests/pystac_client_test.py --search-method itemsearch -c rcm-ard -l 100 -d "2025-01-01T00:00:00Z/2025-05-01T23:59:59Z"
```

### Run features_dds_test.py

Browses the EODMS OGC Features API directly (without pystac-client) with page-token pagination, and downloads a specific feature via DDS.

```
Usage: features_dds_test.py [OPTIONS]

  OGC Features CLI for EODMS STAC

Options:
  -u, --username TEXT      The EODMS username.
  -p, --password TEXT      The EODMS password.
  -c, --collection TEXT    The collection name.
  -f, --feature_id TEXT    The feature (item) ID.
  -b, --bbox TEXT          Bounding box: west,south,east,north
                           (e.g., "-100,45,-95,50").
  -d, --datetime TEXT      Temporal filter as ISO 8601 string or range.
  -e, --env TEXT           Environment: "prod" (default) or "staging".
  -l, --limit INTEGER      Maximum number of features to return (default: 10).
  -h, --help               Show this message and exit.
```

```bash
# List all collections
python features_dds_test.py

# List features in a collection
python features_dds_test.py -u eodms_user -p eodms_pwd -c RCMImageProducts -l 5

# Download a specific feature by ID
python features_dds_test.py -u eodms_user -p eodms_pwd -c RCMImageProducts -f some-feature-uuid
```

### Run processes_test.py

Runs OGC Processes operations used by the RADARSAT-1 L1 workflow: list processes, inspect process inputs, submit jobs, monitor status, fetch results, and download outputs.

```
Usage: processes_test.py [OPTIONS]

  OGC Processes CLI for EODMS processing workflows.

Options:
  -u, --username TEXT              The EODMS username.
  -p, --password TEXT              The EODMS password.
  -e, --env TEXT                   Defaults to "prod". If "staging", define
                                   EODMS_STAGING_DOMAIN env variable.
  -pi, --process_id TEXT           Processing service ID
                                   (e.g., Radarsat1GAMMAL1SLC).
  --list_processes / --no-list_processes
                                   List available processes (default behavior).
  --input-structure                Print process input structure and sample
                                   payload from
                                   /processing/processes/{processID}.
  --submit                         Submit a processing job (requires auth).
  --inputs_json TEXT               JSON string or path to JSON file for submit
                                   inputs.
  --outputs_json TEXT              JSON string or path to JSON file for submit
                                   outputs.
  --mode TEXT                      Execution mode for generic submit (default:
                                   async).
  -j, --job_id TEXT                Existing job ID to check/poll/results/
                                   download.
  --wait                           Poll job status until terminal state.
  --interval INTEGER               Polling interval seconds for --wait (default:
                                   30).
  --timeout INTEGER                Polling timeout seconds for --wait (default:
                                   600).
  --show_results                   Print /jobs/{jobID}/results JSON.
  -dl, --download_dir TEXT         Download all job result files to this
                                   folder.
  --skip_existing / --no-skip_existing
                                   Skip existing local files when downloading
                                   results (default: enabled).
  -o, --output TEXT                Write JSON response (process details or
                                   submit response) to file.
  -h, --help                       Show this message and exit.
```

```bash
# List available processes
python tests/processes_test.py

# Show input schema and sample execution payload for a process
python tests/processes_test.py --input-structure --process_id Radarsat1CEOSL1SLC

# Submit generic process payload from JSON file (inputs-only object)
python tests/processes_test.py -u eodms_user -p eodms_pwd --submit --process_id Radarsat1CEOSL1SLC --inputs_json ./inputs.json

# Submit full execution payload JSON (inputs + outputs + mode)
python tests/processes_test.py -u eodms_user -p eodms_pwd --submit --process_id Radarsat1CEOSL1SLC --inputs_json ./radarsat1_input.json

# Poll existing job until completion
python tests/processes_test.py -u eodms_user -p eodms_pwd --job_id your-job-id --wait --interval 60 --timeout 3600

# Download all files from job results
python tests/processes_test.py -u eodms_user -p eodms_pwd --job_id your-job-id --download_dir ./data/your-job-id
```

### Run test_search_queryables.py

Unit and integration tests for the STAC search and CQL2 filter helpers.

The unit tests run offline with no credentials required. The integration tests call the live EODMS STAC catalog and are marked with `@pytest.mark.integration`.

```bash
# Run all unit tests (no network access required)
pytest tests/test_search_queryables.py

# Run a specific test by name
pytest tests/test_search_queryables.py::test_compose_filter_combines_attribute_and_geometry_filters

# Run integration tests (requires network access, no credentials needed)
pytest tests/test_search_queryables.py -m integration

# Run all tests including integration
pytest tests/test_search_queryables.py -m "integration or not integration"

# Run with verbose output
pytest tests/test_search_queryables.py -v
```

## Documentation

Official Swagger documentation can be found here, https://eodms-sgdot.nrcan-rncan.gc.ca/dds/v1/swagger-ui/#/
