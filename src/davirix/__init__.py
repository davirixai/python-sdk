"""Davirix — agent platformasi uchun rasmiy Python SDK.

    from davirix import Davirix

    dx = Davirix(tenant_id="acme", actor="service:billing")   # kalit env'dan
    n = dx.run(agent_id="support", input={"text": "Mijozga SMS yubor"})

    n.status      # "completed"  ← MODEL javob berdi
    n.verified    # False        ← AMAL tasdiqlanmagan bo'lishi mumkin
    n.verdict     # Verdict.UNKNOWN

⚠ `completed` HECH QACHON «bajarildi» degani emas. Amalning taqdiri
`operations[]` da; `verified` — fail-closed xulosa. Batafsil: `result.py`.
"""

from davirix._canonical import canonical, digest
from davirix.client import DEFAULT_BASE_URL, Davirix, derive_idempotency_key
from davirix.errors import (
    APIError,
    AuthError,
    ConfigurationError,
    ConflictError,
    DavirixError,
    ExecutionTimeout,
    InvalidRequestError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
    TransportError,
    UnverifiedError,
    UpstreamError,
    ValidationError,
    is_retryable,
)
from davirix.result import (
    TERMINAL_STATUSES,
    Execution,
    ExecutionError,
    ExecutionStatus,
    Operation,
    OperationsCoverage,
    OperationStatus,
    Verdict,
    WaitingFor,
    set_unverified_warning,
)

__version__ = "0.1.0"

__all__ = [
    "APIError",
    "AuthError",
    "ConfigurationError",
    "ConflictError",
    "DEFAULT_BASE_URL",
    "Davirix",
    "DavirixError",
    "Execution",
    "ExecutionError",
    "ExecutionStatus",
    "ExecutionTimeout",
    "InvalidRequestError",
    "NotFoundError",
    "Operation",
    "OperationStatus",
    "OperationsCoverage",
    "RateLimitError",
    "ServerError",
    "ServiceUnavailableError",
    "TERMINAL_STATUSES",
    "TransportError",
    "UnverifiedError",
    "UpstreamError",
    "ValidationError",
    "Verdict",
    "WaitingFor",
    "__version__",
    "canonical",
    "derive_idempotency_key",
    "digest",
    "is_retryable",
    "set_unverified_warning",
]
