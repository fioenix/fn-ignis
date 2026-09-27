class IgnisDomainException(Exception):
    """Base exception class for Domain layer."""
    pass


class InvalidSignalDataException(IgnisDomainException):
    """Signal payload failed schema or validation check."""
    pass


class RepositoryException(IgnisDomainException):
    """Persistence or database storage layer operation failed."""
    pass


class ConnectorExecutionException(IgnisDomainException):
    """Connector plugin encountered an execution error."""
    pass


class ConnectorQuotaExceededException(ConnectorExecutionException):
    """Upstream connector platform API quota exhausted."""
    pass


class CircuitBreakerOpenException(ConnectorExecutionException):
    """Execution rejected because Circuit Breaker is in OPEN state."""
    pass


class ConnectorAuthenticationException(ConnectorExecutionException):
    """Upstream connector rejected the request due to invalid, expired, or revoked credentials."""
    pass


class VocabularySynchronizationError(IgnisDomainException):
    """The persisted vocabulary a mission depends on could not be loaded into its engines.

    Raised before any connector is called, so no result is ever produced under a partial
    configuration -- the TikTok grid, for one, rejects every card until its UI-noise vocabulary
    is registered, and an empty platform would otherwise read as an absent market.
    """
    pass


class EncryptionKeyMissingException(IgnisDomainException):
    """A persistent IGNIS_ENCRYPTION_KEY is required for this operation but is not configured."""
    pass
