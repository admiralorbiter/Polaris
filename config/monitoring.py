# config/monitoring.py

import os


class MonitoringConfig:
    """Monitoring and alerting configuration"""
    
    # Monitoring Configuration
    MONITORING_ENABLED = os.environ.get('MONITORING_ENABLED', 'false').lower() == 'true'
    METRICS_ENDPOINT = os.environ.get('METRICS_ENDPOINT', '/metrics')
    HEALTH_CHECK_ENDPOINT = os.environ.get('HEALTH_CHECK_ENDPOINT', '/health')
    
    # Error Alerting Configuration
    ERROR_ALERTING_ENABLED = os.environ.get('ERROR_ALERTING_ENABLED', 'false').lower() == 'true'
    ERROR_EMAIL_RECIPIENTS = os.environ.get('ERROR_EMAIL_RECIPIENTS', '').split(',') if os.environ.get('ERROR_EMAIL_RECIPIENTS') else []
    
    # Logging Configuration
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    LOG_FORMAT = os.environ.get('LOG_FORMAT', 'json')  # 'json' or 'text'
    LOG_DIR = os.environ.get('LOG_DIR', 'logs')
    LOG_FILE_MAX_BYTES = int(os.environ.get('LOG_FILE_MAX_BYTES', 10485760))  # 10MB
    LOG_FILE_BACKUP_COUNT = int(os.environ.get('LOG_FILE_BACKUP_COUNT', 10))
    
    # Console and File Logging
    ENABLE_FILE_LOGGING = os.environ.get('ENABLE_FILE_LOGGING', 'true').lower() == 'true'
    ENABLE_CONSOLE_LOGGING = os.environ.get('ENABLE_CONSOLE_LOGGING', 'true').lower() == 'true'
    
    # Email Alerting
    ENABLE_EMAIL_ALERTS = os.environ.get('ENABLE_EMAIL_ALERTS', 'false').lower() == 'true'
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_FROM = os.environ.get('MAIL_FROM', 'noreply@example.com')
    ADMIN_EMAILS = os.environ.get('ADMIN_EMAILS', '').split(',') if os.environ.get('ADMIN_EMAILS') else []
    
    # Rate Limiting for Alerts
    EMAIL_ALERT_RATE_LIMIT = int(os.environ.get('EMAIL_ALERT_RATE_LIMIT', 5))
    SLACK_ALERT_RATE_LIMIT = int(os.environ.get('SLACK_ALERT_RATE_LIMIT', 10))
    WEBHOOK_ALERT_RATE_LIMIT = int(os.environ.get('WEBHOOK_ALERT_RATE_LIMIT', 20))
    
    # Slack Integration
    ENABLE_SLACK_ALERTS = os.environ.get('ENABLE_SLACK_ALERTS', 'false').lower() == 'true'
    SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')
    
    # Webhook Integration
    ENABLE_WEBHOOK_ALERTS = os.environ.get('ENABLE_WEBHOOK_ALERTS', 'false').lower() == 'true'
    WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
    WEBHOOK_HEADERS = {}
    
    # Sentry Integration (optional)
    ENABLE_SENTRY = os.environ.get('ENABLE_SENTRY', 'false').lower() == 'true'
    SENTRY_DSN = os.environ.get('SENTRY_DSN')
    
    # Application Info
    APP_NAME = os.environ.get('APP_NAME', 'Flask Application')
    APP_VERSION = os.environ.get('APP_VERSION', '1.0.0')


class DevelopmentMonitoringConfig(MonitoringConfig):
    """Development-specific monitoring configuration"""
    
    LOG_LEVEL = 'DEBUG'
    LOG_FORMAT = 'text'  # More readable in development
    ENABLE_FILE_LOGGING = True
    ENABLE_CONSOLE_LOGGING = True
    ENABLE_EMAIL_ALERTS = False  # Don't spam emails in development
    ENABLE_SLACK_ALERTS = False
    ENABLE_WEBHOOK_ALERTS = False


class ProductionMonitoringConfig(MonitoringConfig):
    """Production-specific monitoring configuration"""
    
    LOG_LEVEL = 'INFO'
    LOG_FORMAT = 'json'  # Structured logging for production
    ENABLE_FILE_LOGGING = True
    ENABLE_CONSOLE_LOGGING = False  # Usually handled by container orchestration
    ENABLE_EMAIL_ALERTS = True
    ENABLE_SLACK_ALERTS = True
    ENABLE_WEBHOOK_ALERTS = True
    
    # More aggressive rate limiting in production
    EMAIL_ALERT_RATE_LIMIT = 3
    SLACK_ALERT_RATE_LIMIT = 5
    WEBHOOK_ALERT_RATE_LIMIT = 10


class TestingMonitoringConfig(MonitoringConfig):
    """Testing-specific monitoring configuration"""
    
    MONITORING_ENABLED = False
    ERROR_ALERTING_ENABLED = False
    LOG_LEVEL = 'WARNING'
    LOG_FORMAT = 'text'
    ENABLE_FILE_LOGGING = False
    ENABLE_CONSOLE_LOGGING = False
    ENABLE_EMAIL_ALERTS = False
    ENABLE_SLACK_ALERTS = False
    ENABLE_WEBHOOK_ALERTS = False
