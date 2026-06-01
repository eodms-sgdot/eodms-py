from typing import Optional


class EODMSError(Exception):
    """Base exception for the eodms package."""


class AAAError(EODMSError):
    """Authentication service is unavailable or returned an unusable response."""

    def __init__(self, message: str, *, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class CatalogError(EODMSError):
    """STAC catalog client could not be initialized."""


class SearchError(EODMSError):
    """STAC search request failed unexpectedly."""


class DDSError(EODMSError):
    """DDS request or download failed unexpectedly."""


class ProcessingError(EODMSError):
    """Processes API request failed unexpectedly."""