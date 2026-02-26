EODMS API Client
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

## Testing

### Clone Repository

```bash
git clone https://github.com/eodms-sgdot/eodms-py.git
```

### Package Installation

If the pip installation above did not work, you can install from the cloned repository:

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

## Documentation

Official Swagger documentation can be found here, https://eodms-sgdot.nrcan-rncan.gc.ca/dds/v1/swagger-ui/#/

## Cutover Plan

Here is the plan to meet the cutover target of Mar 31 2026:

1. Developers should import *both* `py-eodms-rapi` and `py-eodms-dds` into their code setup.
2. For `rapi.search(..)` calls... you **don't** need to change these.
3. For `rapi.order(..)` calls... you **do** need to change these and switch them over to `dds_api.get_item(..)` calls. See [rapi_dds_test.py](https://github.com/eodms-sgdot/py-eodms-dds/blob/main/tests/rapi_dds_test.py) an example.
4. A new version of eodms-cli will also be released to handle the switch to py-eodms-dds. See: https://github.com/eodms-sgdot/eodms-cli/issues/46.
5. Once all users are switched over, the https://www.eodms-sgdot.nrcan-rncan.gc.ca/wes/rapi/order endpoint will be blocked. Downloads will only be possible from the new endpoint, https://eodms-sgdot.nrcan-rncan.gc.ca/dds 

The main difference is that `rapi.order` uses a `sequence_id`, whereas `get_item` only accepts a `uuid`. Thankfully, `uuid` is already returned by `rapi.search(..)`.
