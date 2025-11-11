# config.py
import os
from datetime import timedelta


def _coerce_bool(value, default=False):
    """Convert environment-style truthy/falsey values to bool."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    value_str = str(value).strip().lower()
    if value_str in {"1", "true", "yes", "on"}:
        return True
    if value_str in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_adapter_list(value):
    """
    Parse a comma-separated adapter list while keeping order and removing duplicates.

    Returns:
        tuple[str, ...]: Normalized adapter identifiers.
    """
    if not value:
        return ()

    seen = set()
    adapters = []
    for raw_item in value.split(","):
        item = raw_item.strip().lower()
        if not item or item in seen:
            continue
        seen.add(item)
        adapters.append(item)
    return tuple(adapters)


def _parse_int_list(value, *, minimum=1, maximum=100):
    """
    Parse a comma-separated list of integers with optional bounds.
    """

    if not value:
        return []

    parsed: list[int] = []
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        try:
            number = int(item)
        except ValueError:
            continue
        if number < minimum or number > maximum:
            continue
        if number not in parsed:
            parsed.append(number)
    return parsed


class Config:
    # SECRET_KEY must be set via environment variable for security
    # Generate with: python -c "import secrets; print(secrets.token_hex(32))"
    # For development, we allow a default but warn about it
    # For production, it must be set via environment variable
    _flask_env = os.environ.get("FLASK_ENV", "development")
    _is_testing = _flask_env == "testing"
    _is_production = _flask_env == "production"

    SECRET_KEY = os.environ.get("SECRET_KEY")

    # Only require SECRET_KEY in production mode
    if not SECRET_KEY and _is_production:
        raise ValueError(
            "SECRET_KEY environment variable is required in production. "
            'Generate with: python -c "import secrets; print(secrets.token_hex(32))"'
        )

    # For development, use a default but it's not secure
    if not SECRET_KEY and not _is_testing:
        import warnings

        warnings.warn(
            "SECRET_KEY not set. Using default for development only. "
            "This is insecure and should not be used in production. "
            "Set SECRET_KEY environment variable or generate with: "
            'python -c "import secrets; print(secrets.token_hex(32))"',
            UserWarning,
        )
        SECRET_KEY = "dev-secret-key-change-in-production"

    # Set a default for testing (will be overridden by TestingConfig)
    if not SECRET_KEY:
        SECRET_KEY = "test-secret-key-placeholder"

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {}

    # Importer configuration
    _raw_importer_enabled = os.environ.get("IMPORTER_ENABLED")
    IMPORTER_ENABLED = _coerce_bool(_raw_importer_enabled, default=False)
    IMPORTER_ADAPTERS = _parse_adapter_list(os.environ.get("IMPORTER_ADAPTERS", ""))

    if IMPORTER_ENABLED and not IMPORTER_ADAPTERS:
        raise ValueError(
            "IMPORTER_ENABLED is true but IMPORTER_ADAPTERS is empty. " "Provide at least one adapter name."
        )

    _raw_worker_enabled = os.environ.get("IMPORTER_WORKER_ENABLED")
    IMPORTER_WORKER_ENABLED = _coerce_bool(_raw_worker_enabled, default=False)
    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL")
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND")
    CELERY_SQLITE_PATH = os.environ.get("CELERY_SQLITE_PATH")
    CELERY_CONFIG = os.environ.get("CELERY_CONFIG")
    IMPORTER_UPLOAD_DIR = os.environ.get("IMPORTER_UPLOAD_DIR")
    IMPORTER_ARTIFACT_DIR = os.environ.get("IMPORTER_ARTIFACT_DIR")
    IMPORTER_METRICS_ENV = os.environ.get("IMPORTER_METRICS_ENV", "sandbox")
    IMPORTER_METRICS_SANDBOX_ENABLED = _coerce_bool(
        os.environ.get("IMPORTER_METRICS_SANDBOX_ENABLED"),
        default=True,
    )
    try:
        IMPORTER_MAX_UPLOAD_MB = int(os.environ.get("IMPORTER_MAX_UPLOAD_MB", "25"))
    except ValueError:
        IMPORTER_MAX_UPLOAD_MB = 25
    IMPORTER_SHOW_RECENT_RUNS = _coerce_bool(os.environ.get("IMPORTER_SHOW_RECENT_RUNS"), default=True)
    _raw_runs_page_sizes = os.environ.get("IMPORTER_RUNS_PAGE_SIZES", "25,50,100")
    _parsed_page_sizes = _parse_int_list(_raw_runs_page_sizes, minimum=5, maximum=500)
    if not _parsed_page_sizes:
        _parsed_page_sizes = [25, 50, 100]
    _raw_default_page_size = os.environ.get("IMPORTER_RUNS_PAGE_SIZE_DEFAULT")
    if _raw_default_page_size is not None:
        try:
            IMPORTER_RUNS_PAGE_SIZE_DEFAULT = int(_raw_default_page_size)
        except ValueError:
            IMPORTER_RUNS_PAGE_SIZE_DEFAULT = _parsed_page_sizes[0]
    else:
        IMPORTER_RUNS_PAGE_SIZE_DEFAULT = _parsed_page_sizes[0]

    IMPORTER_CSV_DOC_URL = os.environ.get(
        "IMPORTER_CSV_DOC_URL",
        "https://docs.polaris.example/importer/csv",
    )
    IMPORTER_SALESFORCE_DOC_URL = os.environ.get(
        "IMPORTER_SALESFORCE_DOC_URL",
        "https://docs.polaris.example/importer/salesforce",
    )
    IMPORTER_SALESFORCE_MAPPING_PATH = os.environ.get(
        "IMPORTER_SALESFORCE_MAPPING_PATH",
        os.path.join(os.path.dirname(__file__), "mappings", "salesforce_contact_v1.yaml"),
    )
    _raw_sf_objects = os.environ.get("IMPORTER_SALESFORCE_OBJECTS", "contacts")
    IMPORTER_SALESFORCE_OBJECTS = tuple(
        obj.strip().lower() for obj in _raw_sf_objects.split(",") if obj.strip()
    ) or ("contacts",)
    try:
        IMPORTER_SALESFORCE_BATCH_SIZE = max(
            1000, int(os.environ.get("IMPORTER_SALESFORCE_BATCH_SIZE", "5000"))
        )
    except ValueError:
        IMPORTER_SALESFORCE_BATCH_SIZE = 5000
    if IMPORTER_RUNS_PAGE_SIZE_DEFAULT not in _parsed_page_sizes:
        _parsed_page_sizes.insert(0, IMPORTER_RUNS_PAGE_SIZE_DEFAULT)
    IMPORTER_RUNS_PAGE_SIZES = tuple(sorted(set(_parsed_page_sizes)))
    try:
        IMPORTER_RUNS_AUTO_REFRESH_SECONDS = max(0, int(os.environ.get("IMPORTER_RUNS_AUTO_REFRESH_SECONDS", "30")))
    except ValueError:
        IMPORTER_RUNS_AUTO_REFRESH_SECONDS = 30

    # Session configuration
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)  # Reduced from 31 days for better security
    SESSION_COOKIE_SECURE = False  # Set to True in production with HTTPS
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # CSRF protection
    WTF_CSRF_ENABLED = True


class DevelopmentConfig(Config):
    DEBUG = True
    # Use instance folder for database to avoid conflicts
    # Get the project root directory (parent of config directory)
    _config_dir = os.path.dirname(os.path.abspath(__file__))
    _project_root = os.path.dirname(_config_dir)
    instance_path = os.path.join(_project_root, "instance")

    # Ensure instance folder exists
    if not os.path.exists(instance_path):
        os.makedirs(instance_path, exist_ok=True)

    # Use absolute path for SQLite - Windows needs forward slashes in URI
    db_path = os.path.join(instance_path, "polaris_dev.db")
    # Convert Windows backslashes to forward slashes for SQLite URI
    db_path_normalized = db_path.replace("\\", "/")
    # SQLite URI format: sqlite:///absolute/path (3 slashes for absolute path)
    db_uri = f"sqlite:///{db_path_normalized}"

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", db_uri)
    SQLALCHEMY_ECHO = True  # Enable SQL query logging in development
    if SQLALCHEMY_DATABASE_URI.startswith("sqlite"):
        SQLALCHEMY_ENGINE_OPTIONS = {
            "connect_args": {
                "check_same_thread": False,
                "timeout": 5,
            }
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {}


class TestingConfig(Config):
    TESTING = True
    # Override SECRET_KEY for testing - tests will set their own
    SECRET_KEY = os.environ.get("SECRET_KEY", "test-secret-key-for-testing-only")
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"  # In-memory database for testing
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_ECHO = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {
            "check_same_thread": False,
            "timeout": 5,
        }
    }


class ProductionConfig(Config):
    DEBUG = False
    uri = os.environ.get("DATABASE_URL")  # Get the Heroku DATABASE_URL
    if uri and uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = uri
    SQLALCHEMY_ECHO = False
    SESSION_COOKIE_SECURE = True  # Secure cookies in production
