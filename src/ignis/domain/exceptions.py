class IgnisDomainException(Exception):
    """Lỗi cơ sở cho Domain layer."""
    pass

class InvalidSignalDataException(IgnisDomainException):
    """Dữ liệu signal không hợp lệ."""
    pass

class ConnectorExecutionException(IgnisDomainException):
    """Lỗi khi thực thi Connector plugin."""
    pass
