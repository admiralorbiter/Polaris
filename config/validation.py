# config/validation.py

"""
Environment variable validation for Polaris application.
Validates required environment variables at startup.
"""

import os
import sys
from typing import List, Tuple


def validate_environment(flask_env: str = None) -> Tuple[bool, List[str]]:
    """
    Validate required environment variables.

    Args:
        flask_env: Flask environment (development, production, testing)
                  If None, reads from FLASK_ENV environment variable

    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    if flask_env is None:
        flask_env = os.environ.get("FLASK_ENV", "development")

    errors = []

    # Only validate in production
    if flask_env != "production":
        return True, []

    # Production validations
    secret_key = os.environ.get("SECRET_KEY", "")
    if not secret_key or secret_key == "your-secret-key" or secret_key == "your_secret_key":
        errors.append(
            "SECRET_KEY is required in production and must not be the default value. "
            'Generate a secure key: python -c "import secrets; print(secrets.token_hex(32))"'
        )

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        errors.append(
            "DATABASE_URL is required in production. "
            "Set it to your PostgreSQL connection string."
        )

    # Validate conditional requirements
    if os.environ.get("ERROR_ALERTING_ENABLED", "false").lower() == "true":
        error_recipients = os.environ.get("ERROR_EMAIL_RECIPIENTS", "")
        if not error_recipients:
            errors.append("ERROR_EMAIL_RECIPIENTS is required when ERROR_ALERTING_ENABLED=true")

    if os.environ.get("ENABLE_EMAIL_ALERTS", "false").lower() == "true":
        mail_server = os.environ.get("MAIL_SERVER")
        mail_username = os.environ.get("MAIL_USERNAME")
        mail_password = os.environ.get("MAIL_PASSWORD")

        if not mail_server:
            errors.append("MAIL_SERVER is required when ENABLE_EMAIL_ALERTS=true")
        if not mail_username:
            errors.append("MAIL_USERNAME is required when ENABLE_EMAIL_ALERTS=true")
        if not mail_password:
            errors.append("MAIL_PASSWORD is required when ENABLE_EMAIL_ALERTS=true")

    if os.environ.get("ENABLE_SLACK_ALERTS", "false").lower() == "true":
        slack_webhook = os.environ.get("SLACK_WEBHOOK_URL")
        if not slack_webhook:
            errors.append("SLACK_WEBHOOK_URL is required when ENABLE_SLACK_ALERTS=true")

    if os.environ.get("ENABLE_WEBHOOK_ALERTS", "false").lower() == "true":
        webhook_url = os.environ.get("WEBHOOK_URL")
        if not webhook_url:
            errors.append("WEBHOOK_URL is required when ENABLE_WEBHOOK_ALERTS=true")

    if os.environ.get("ENABLE_SENTRY", "false").lower() == "true":
        sentry_dsn = os.environ.get("SENTRY_DSN")
        if not sentry_dsn:
            errors.append("SENTRY_DSN is required when ENABLE_SENTRY=true")

    is_valid = len(errors) == 0
    return is_valid, errors


def validate_and_exit(flask_env: str = None) -> None:
    """
    Validate environment variables and exit with error if validation fails.
    Intended to be called at application startup.

    Args:
        flask_env: Flask environment (development, production, testing)
    """
    is_valid, errors = validate_environment(flask_env)

    if not is_valid:
        print("=" * 80, file=sys.stderr)
        print("ENVIRONMENT VALIDATION FAILED", file=sys.stderr)
        print("=" * 80, file=sys.stderr)
        print("\nThe following environment variables are missing or invalid:\n", file=sys.stderr)

        for i, error in enumerate(errors, 1):
            print(f"{i}. {error}", file=sys.stderr)

        print("\n" + "=" * 80, file=sys.stderr)
        print("Please check your .env file or environment variables.", file=sys.stderr)
        print("See .env.example for required configuration.", file=sys.stderr)
        print("=" * 80, file=sys.stderr)

        sys.exit(1)
