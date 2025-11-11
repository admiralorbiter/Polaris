# app.py

import logging
import os

from dotenv import load_dotenv
from flask import Flask, current_app, render_template
from flask_login import LoginManager
from sqlalchemy import event

# Load environment variables from .env file first
load_dotenv()

# Module imports after load_dotenv() - E402 is intentional
from config import DevelopmentConfig, ProductionConfig, TestingConfig  # noqa: E402
from config.monitoring import (  # noqa: E402
    DevelopmentMonitoringConfig,
    ProductionMonitoringConfig,
    TestingMonitoringConfig,
)
from config.validation import validate_and_exit  # noqa: E402
from flask_app.middleware.org_context import init_org_context_middleware  # noqa: E402

# Import from modular structure
from flask_app.models import User, db  # noqa: E402
from flask_app.routes import init_routes  # noqa: E402
from flask_app.utils.error_handler import init_error_alerting  # noqa: E402
from flask_app.utils.logging_config import setup_logging  # noqa: E402
from flask_app.utils.monitoring import init_monitoring  # noqa: E402

logger = logging.getLogger(__name__)

app = Flask(__name__)

# Validate environment variables (only in production)
flask_env = os.environ.get("FLASK_ENV", "development")
if flask_env == "production":
    validate_and_exit(flask_env)

# Load configuration based on the environment
if flask_env == "production":
    app.config.from_object(ProductionConfig)
    app.config.from_object(ProductionMonitoringConfig)
elif os.environ.get("FLASK_ENV") == "testing":
    app.config.from_object(TestingConfig)
    app.config.from_object(TestingMonitoringConfig)
else:
    app.config.from_object(DevelopmentConfig)
    app.config.from_object(DevelopmentMonitoringConfig)

# Initialize extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"  # Redirect to 'login' view if unauthorized
login_manager.login_message_category = "info"

# Register login manager in app extensions for testing
app.extensions["login_manager"] = login_manager

# Initialize monitoring and logging systems
setup_logging(app)
init_error_alerting(app)
init_monitoring(app)

# Initialize organization context middleware
init_org_context_middleware(app)

def _configure_sqlite_connection_factory(*, enable_foreign_keys: bool):
    """Return a connection hook applying concurrency-friendly pragmas."""

    def _configure_sqlite_connection(dbapi_connection, connection_record):  # pragma: no cover - instrumentation
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            if enable_foreign_keys:
                cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        except Exception as exc:
            logger.warning("Failed to apply SQLite PRAGMAs: %s", exc)

    return _configure_sqlite_connection


with app.app_context():
    engine = db.engine
    if engine.url.drivername.startswith("sqlite"):
        if not getattr(engine, "_sqlite_pragmas_configured", False):
            pragma_hook = _configure_sqlite_connection_factory(
                enable_foreign_keys=not app.config.get("TESTING", False)
            )
            event.listen(engine, "connect", pragma_hook)
            engine._sqlite_pragmas_configured = True  # type: ignore[attr-defined]
    # Create the database tables only if not in testing mode
    if not app.config.get("TESTING", False):
        db.create_all()


# User loader callback for Flask-Login
@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (ValueError, TypeError):
        # Invalid user_id format
        return None
    except Exception as e:
        # Handle any other database errors gracefully
        current_app.logger.error(f"Error loading user {user_id}: {str(e)}")
        return None


# Initialize routes
init_routes(app)


# Register error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template("errors/404.html"), 404


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template("errors/500.html"), 500


if __name__ == "__main__":
    # Use production-ready server configuration
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
