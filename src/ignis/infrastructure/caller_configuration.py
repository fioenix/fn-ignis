"""Literal, caller-owned settings; no process environment mutation or source permission."""
from io import StringIO
from pathlib import Path
from urllib.parse import urlsplit
from dotenv.parser import parse_stream
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class CallerConfiguration(BaseModel):
    """Only settings whose scoped composition consumers are explicitly wired."""
    model_config = ConfigDict(extra='forbid')
    DATABASE_URL: SecretStr
    DB_MIN_POOL_SIZE: int = Field(default=1, ge=1, le=32)
    DB_MAX_POOL_SIZE: int = Field(default=3, ge=1, le=32)
    YOUTUBE_API_KEY: SecretStr = SecretStr('')
    YOUTUBE_SEARCH_DAILY_LIMIT: int = Field(default=100, ge=1)
    YOUTUBE_OTHER_DAILY_UNIT_LIMIT: int = Field(default=10_000, ge=1)

    @model_validator(mode='after')
    def valid_pool(self):
        if self.DB_MIN_POOL_SIZE > self.DB_MAX_POOL_SIZE:
            raise ValueError('Invalid pool bounds')
        return self


def load_caller_configuration(text: str, root: Path, default_database: Path):
    """Parse literal dotenv syntax and validate without echoing any submitted value."""
    try:
        values = {}
        for binding in parse_stream(StringIO(text)):
            if binding.error:
                raise ValueError('Invalid configuration syntax')
            if binding.key is None:
                continue
            if binding.key in values or binding.value is None or '${' in binding.value:
                raise ValueError('Invalid literal setting')
            values[binding.key] = binding.value
        if not values.get('DATABASE_URL'):
            values['DATABASE_URL'] = 'sqlite:///' + str(default_database)
        config = CallerConfiguration.model_validate(values)
        dsn = config.DATABASE_URL.get_secret_value()
        if any(character in dsn for character in ('\n','\r','\0')):
            raise ValueError('Invalid connection')
        database = None
        if dsn.startswith('sqlite:///'):
            database = Path(dsn.removeprefix('sqlite:///'))
            if not database.is_absolute() or '..' in database.parts or root not in database.parents:
                raise ToolError('ROOT_SCOPE_REQUIRED')
            if '?' in dsn or '#' in dsn or database == root:
                raise ValueError('Unsupported SQLite connection')
        else:
            uri = urlsplit(dsn)
            if uri.scheme not in ('postgres','postgresql') or not uri.hostname or not uri.path.strip('/'):
                raise ValueError('Unsupported connection')
            _ = uri.port
        return config, database
    except ToolError:
        raise
    except Exception:
        raise ToolError('CALLER_CONFIG_REFUSED') from None
