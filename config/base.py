# config.py
import os
from datetime import timedelta


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


class TestingConfig(Config):
    TESTING = True
    # Override SECRET_KEY for testing - tests will set their own
    SECRET_KEY = os.environ.get("SECRET_KEY", "test-secret-key-for-testing-only")
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"  # In-memory database for testing
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_ECHO = False


class ProductionConfig(Config):
    DEBUG = False
    uri = os.environ.get("DATABASE_URL")  # Get the Heroku DATABASE_URL
    if uri and uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = uri
    SQLALCHEMY_ECHO = False
    SESSION_COOKIE_SECURE = True  # Secure cookies in production
