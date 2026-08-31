class IgnisDomainException(Exception):
    """Lỗi cơ sở cho Domain layer."""
    pass


class InvalidSignalDataException(IgnisDomainException):
    """Dữ liệu signal không hợp lệ."""
    pass


class RepositoryException(IgnisDomainException):
    """Lỗi thao tác trên tầng lưu trữ Database / TimescaleDB."""
    pass


class ConnectorExecutionException(IgnisDomainException):
    """Lỗi khi thực thi Connector plugin."""
    pass


class ConnectorQuotaExceededException(ConnectorExecutionException):
    """Lỗi cạn hạn ngạch API của nhà cung cấp dịch vụ."""
    pass


class CircuitBreakerOpenException(ConnectorExecutionException):
    """Lỗi khi cố gắng gọi plugin đang trong trạng thái ngắt mạch (Circuit Breaker OPEN)."""
    pass
