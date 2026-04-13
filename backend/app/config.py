from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge"
    DATABASE_URL_SYNC: str = "postgresql+psycopg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge"
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 hours
    PRIVATE_DATA_KEY: str = ""             # AES-256 key for private invoice encryption
    COMPANY_NAME: str = "Stone Crusher Enterprises"

    # Serial port defaults
    SERIAL_PORT: str = "COM1"
    SERIAL_BAUD_RATE: int = 9600
    SERIAL_DATA_BITS: int = 8
    SERIAL_STOP_BITS: int = 1
    SERIAL_PARITY: str = "N"
    SERIAL_PROTOCOL: str = "generic"

    # Tally integration
    TALLY_HOST: str = "localhost"
    TALLY_PORT: int = 9000

    # Multi-tenant
    MULTI_TENANT: bool = False
    MASTER_DATABASE_URL: str = "postgresql+asyncpg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge_master"
    MASTER_DATABASE_URL_SYNC: str = "postgresql+psycopg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge_master"
    TENANT_DB_PREFIX: str = "wb_"
    TENANT_POOL_SIZE: int = 3          # Per-tenant connection pool size
    TENANT_MAX_OVERFLOW: int = 5       # Per-tenant max overflow connections
    SUPER_ADMIN_SECRET: str = ""       # Secret for tenant management API auth
    PLATFORM_ADMIN_USER: str = "platform_admin"     # Default platform admin username
    PLATFORM_ADMIN_PASSWORD: str = "Admin@123"      # Default platform admin password

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
