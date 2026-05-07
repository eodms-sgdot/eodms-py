eodms-py EODMS Client Package
================

The EODMS API Client was designed using Python 3.10.

## Pip Installation

```bash
pip install git+https://github.com/eodms-sgdot/eodms-py.git
```

## Usage

### Get and Download Image

> **_NOTE:_** Before using the DDS API, you'll need to get the UUID of an RCM image product. You can use the [py-eodms-rapi](https://github.com/eodms-sgdot/py-eodms-rapi) (see [rapi_dds_test.py](./tests/rapi_dds_test.py) for example code).

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
from eodms import aaa, dds, search

aaa_api = aaa.AAA_API('myeodmsusername', 'myeodmspassword')

# Build an authenticated pystac-client
client = search.build_stac_client(aaa_api=aaa_api, environment='prod')

# List available collections
for collection in client.get_collections():
    print(collection.id)
```

For a full search-and-download example see [stac_dds_test.py](./tests/stac_dds_test.py) and [features_dds_test.py](./tests/features_dds_test.py).

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

### Run rapi_dds_test.py

This test gets an image item from the EODMS RAPI, parses the metadata and uses the UUID to download the image using the EODMS DDS API.

For this test script, you will need to install the [py-eodms-rapi](https://github.com/eodms-sgdot/py-eodms-rapi) package:

```bash
pip install py-eodms-rapi -U
```

```
Usage: rapi_dds_test.py [OPTIONS]

  Used for CLI input.

Options:
  -u, --username TEXT    The EODMS username.  [required]
  -p, --password TEXT    The EODMS password.  [required]
  -c, --collection TEXT  The collection name.  [required]
  -e, --env TEXT         The AWS environment (default is "prod").
  -o, --out_folder TEXT  The output folder (default is the current folder).
  -h, --help             Show this message and exit.
```

```bash
python rapi_dds_test.py -u eodms_user -p eodms_pwd -c RCMImageProducts
```

### Run stac_dds_test.py

Searches the EODMS STAC catalog using the OGC Features items endpoint (paginated) and downloads the first result via DDS. Omitting `--collection` lists all available collections and their queryable fields.

```
Usage: stac_dds_test.py [OPTIONS]

  Search and Download images from EODMS STAC catalog and DDS.

Options:
  -u, --username TEXT      The EODMS username.
  -p, --password TEXT      The EODMS password.
  -c, --collection TEXT    The collection name.
      --uuid TEXT          UUID of the image to download (skips search).
  -d, --datetime TEXT      Temporal filter as ISO 8601 string or range
                           (e.g., "2023-01-01/2023-12-31").
  -b, --bbox TEXT          Bounding box: west,south,east,north
                           (e.g., "-100,45,-95,50").
  -l, --limit INTEGER      Maximum number of items to fetch (default: 1000).
  -f, --filter TEXT        CQL2 text filter expression
                           (e.g., "roll_number = 'KA3'").
      --output TEXT        Output GeoJSON filename (e.g., results.geojson).
  -e, --env TEXT           Environment: "prod" (default) or "staging".
  -o, --out_folder TEXT    Output folder (default: current folder).
  -h, --help               Show this message and exit.
```

```bash
# List all collections and queryable fields
python stac_dds_test.py

# Search and download first RCM image
python stac_dds_test.py -u eodms_user -p eodms_pwd -c RCMImageProducts

# Search with datetime and bbox filters
python stac_dds_test.py -u eodms_user -p eodms_pwd -c RCMImageProducts -d "2023-01-01/2023-12-31" -b "-100,45,-95,50"

# Apply a CQL2 filter and save results as GeoJSON
python stac_dds_test.py -u eodms_user -p eodms_pwd -c RCMImageProducts -f "roll_number = 'KA3'" --output results.geojson
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

## Documentation

Official Swagger documentation can be found here, https://eodms-sgdot.nrcan-rncan.gc.ca/dds/v1/swagger-ui/#/
