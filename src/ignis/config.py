from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Cấu hình ứng dụng fn-ignis nạp từ biến môi trường."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Database TimescaleDB
    DATABASE_URL: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/ignis",
        description="Chuỗi kết nối PostgreSQL/TimescaleDB"
    )
    DB_MIN_POOL_SIZE: int = Field(default=2, description="Số kết nối tối thiểu trong pool")
    DB_MAX_POOL_SIZE: int = Field(default=10, description="Số kết nối tối đa trong pool")

    # Ingress Connectors
    YOUTUBE_API_KEY: str = Field(default="", description="YouTube Data API v3 Key")

    # Security & Encryption
    IGNIS_ENCRYPTION_KEY: str = Field(
        default="",
        description="Secret key (Fernet AES-256) dùng để mã hóa credentials lưu trên DB"
    )

    # Ingress Defaults
    DEFAULT_GEO: str = Field(default="VN", description="Mã vùng địa lý mặc định")
    INGRESS_BATCH_LIMIT: int = Field(default=50, description="Số lượng bản ghi tối đa mỗi lần fetch")


settings = Settings()

