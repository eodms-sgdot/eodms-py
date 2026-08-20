from eodms.dds import DDS_API


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


class _FakeAAA:
    def get_access_token(self):
        return "token-abc"

    def prepare_request(self, url, headers=None):
        return _FakeResponse(
            200,
            {
                "status": "Available",
                "download_url": "https://example.test/files/item.zip?Signature=abc&Expires=1787241600",
            },
        )


def test_get_item_enriches_download_url_expires():
    dds_api = DDS_API(_FakeAAA())

    item_info = dds_api.get_item("RCMImageProducts", "item-uuid")

    assert item_info["download_expires"] == 1787241600
    assert item_info["download_expires_at"] == "2026-08-20T16:00:00Z"
    assert dds_api.img_info["download_expires"] == 1787241600