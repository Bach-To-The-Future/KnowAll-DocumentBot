"""Domain exception hierarchy.

Every layer raises these instead of bare RuntimeError/ValueError; the API
layer maps them to standardized JSON responses via `http_status` (see
api/errors.py). Keep integrations' library exceptions wrapped at the boundary
so services and routers never depend on qdrant/boto3/requests error types.
"""


class RAGSystemError(Exception):
    """Base class for all domain errors."""

    http_status: int = 500

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class ConfigurationError(RAGSystemError):
    """Invalid or missing configuration."""


class InvalidRequestError(RAGSystemError):
    """Client-supplied input failed validation (e.g. path traversal)."""

    http_status = 400


class PayloadTooLargeError(RAGSystemError):
    """Upload exceeded the configured byte ceiling."""

    http_status = 413


class RateLimitedError(RAGSystemError):
    """Per-user request budget exhausted."""

    http_status = 429

    def __init__(self, message: str, *, detail: str | None = None,
                 retry_after: int = 60) -> None:
        super().__init__(message, detail=detail)
        self.retry_after = retry_after


class ServiceOverloadedError(RAGSystemError):
    """Admission control rejected the request: no free capacity."""

    http_status = 503

    def __init__(self, message: str, *, detail: str | None = None,
                 retry_after: int = 5) -> None:
        super().__init__(message, detail=detail)
        self.retry_after = retry_after


class AuthenticationError(RAGSystemError):
    http_status = 401


class AuthorizationError(RAGSystemError):
    """Valid key, insufficient scope."""

    http_status = 403


class ObjectStorageError(RAGSystemError):
    """MinIO/S3 failure."""

    http_status = 502


class ObjectNotFoundError(ObjectStorageError):
    http_status = 404


class ExtractionError(RAGSystemError):
    """Document parsing/OCR produced no usable content."""

    http_status = 422


class UnsupportedFormatError(ExtractionError):
    http_status = 415


class EmbeddingError(RAGSystemError):
    """Embedding backend failure or a text<->vector alignment violation."""

    http_status = 502


class VectorStoreError(RAGSystemError):
    """Qdrant failure."""

    http_status = 502


class SchemaMigrationError(VectorStoreError):
    """Collection exists with an incompatible schema; refusing to write."""

    http_status = 409


class RetrievalError(RAGSystemError):
    """Search/rerank pipeline failure."""


class GenerationError(RAGSystemError):
    """LLM backend failure."""

    http_status = 502


class JobNotFoundError(RAGSystemError):
    http_status = 404
