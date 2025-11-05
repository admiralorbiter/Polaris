# flask_app/utils/logging_config.py

import os
import logging
import logging.config
from logging.handlers import RotatingFileHandler, SMTPHandler
from flask import current_app, request, g
try:
    import structlog
    from pythonjsonlogger import jsonlogger
    HAS_STRUCTLOG = True
except ImportError:
    HAS_STRUCTLOG = False
    jsonlogger = None
from datetime import datetime, timezone
import json


class RequestContextFilter(logging.Filter):
    """Add request context to log records"""
    
    def filter(self, record):
        # Add request information if available
        if request:
            record.request_id = getattr(g, 'request_id', 'no-request')
            record.request_method = request.method
            record.request_path = request.path
            record.user_id = getattr(g, 'user_id', None)
            record.remote_addr = request.remote_addr
        else:
            record.request_id = 'no-request'
            record.request_method = 'N/A'
            record.request_path = 'N/A'
            record.user_id = None
            record.remote_addr = 'N/A'
        
        record.timestamp = datetime.now(timezone.utc).isoformat()
        return True


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging"""
    
    def format(self, record):
        # Create log record dictionary
        log_record = {
            'timestamp': getattr(record, 'timestamp', datetime.now(timezone.utc).isoformat()),
            'level': record.levelname,
            'logger': record.name,
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
            'message': record.getMessage()
        }
        
        # Add request context if available
        if hasattr(record, 'request_id'):
            log_record.update({
                'request_id': record.request_id,
                'request_method': record.request_method,
                'request_path': record.request_path,
                'user_id': record.user_id,
                'remote_addr': record.remote_addr
            })
        
        # Add exception info if present
        if record.exc_info:
            log_record['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_record)


def setup_logging(app):
    """Configure comprehensive logging system"""
    
    # Get configuration from app config
    log_level = app.config.get('LOG_LEVEL', 'INFO')
    log_format = app.config.get('LOG_FORMAT', 'json')  # 'json' or 'text'
    enable_file_logging = app.config.get('ENABLE_FILE_LOGGING', True)
    enable_console_logging = app.config.get('ENABLE_CONSOLE_LOGGING', True)
    enable_email_logging = app.config.get('ENABLE_EMAIL_LOGGING', False)
    
    # Create logs directory if needed
    if enable_file_logging:
        log_dir = app.config.get('LOG_DIR', 'logs')
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
    
    # Clear existing handlers
    app.logger.handlers.clear()
    
    # Configure formatters
    if log_format == 'json':
        formatter = JSONFormatter()
        text_formatter = logging.Formatter(
            '%(asctime)s %(levelname)s [%(name)s:%(lineno)d] %(message)s'
        )
    else:
        formatter = logging.Formatter(
            '%(asctime)s %(levelname)s [%(name)s:%(lineno)d] %(message)s '
            '[req:%(request_id)s %(request_method)s %(request_path)s]'
        )
        text_formatter = formatter
    
    # Add request context filter
    context_filter = RequestContextFilter()
    
    # File logging with rotation
    if enable_file_logging:
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, 'app.log'),
            maxBytes=app.config.get('LOG_FILE_MAX_BYTES', 10*1024*1024),  # 10MB
            backupCount=app.config.get('LOG_FILE_BACKUP_COUNT', 10)
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(context_filter)
        file_handler.setLevel(getattr(logging, log_level))
        app.logger.addHandler(file_handler)
        
        # Separate error log file
        error_handler = RotatingFileHandler(
            os.path.join(log_dir, 'errors.log'),
            maxBytes=app.config.get('LOG_FILE_MAX_BYTES', 10*1024*1024),
            backupCount=app.config.get('LOG_FILE_BACKUP_COUNT', 10)
        )
        error_handler.setFormatter(formatter)
        error_handler.addFilter(context_filter)
        error_handler.setLevel(logging.ERROR)
        app.logger.addHandler(error_handler)
    
    # Console logging
    if enable_console_logging:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(text_formatter)
        console_handler.addFilter(context_filter)
        console_handler.setLevel(getattr(logging, log_level))
        app.logger.addHandler(console_handler)
    
    # Email logging for critical errors
    if enable_email_logging and app.config.get('MAIL_SERVER'):
        mail_handler = SMTPHandler(
            mailhost=app.config.get('MAIL_SERVER'),
            fromaddr=app.config.get('MAIL_FROM', 'noreply@example.com'),
            toaddrs=app.config.get('ADMIN_EMAILS', []),
            subject='Application Error',
            credentials=(app.config.get('MAIL_USERNAME'), app.config.get('MAIL_PASSWORD'))
        )
        mail_handler.setFormatter(text_formatter)
        mail_handler.addFilter(context_filter)
        mail_handler.setLevel(logging.CRITICAL)
        app.logger.addHandler(mail_handler)
    
    # Set log level
    app.logger.setLevel(getattr(logging, log_level))
    
    # Configure structlog for structured logging if available
    if HAS_STRUCTLOG:
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.processors.JSONRenderer() if log_format == 'json' else structlog.dev.ConsoleRenderer()
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
    
    app.logger.info('Logging system initialized', extra={
        'log_level': log_level,
        'log_format': log_format,
        'file_logging': enable_file_logging,
        'console_logging': enable_console_logging,
        'email_logging': enable_email_logging
    })


def get_logger(name=None):
    """Get a structured logger instance"""
    if HAS_STRUCTLOG:
        if name:
            return structlog.get_logger(name)
        return structlog.get_logger()
    else:
        # Fallback to standard logging
        import logging
        return logging.getLogger(name or __name__)


def log_user_action(user_id, action, details=None, level='info'):
    """Log user actions with context"""
    logger = get_logger('user_actions')
    log_data = {
        'user_id': user_id,
        'action': action,
        'details': details,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }
    
    if level == 'error':
        logger.error('User action error', extra=log_data)
    elif level == 'warning':
        logger.warning('User action warning', extra=log_data)
    else:
        logger.info('User action', extra=log_data)


def log_security_event(event_type, details, severity='medium'):
    """Log security-related events"""
    logger = get_logger('security')
    log_data = {
        'event_type': event_type,
        'details': details,
        'severity': severity,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'ip_address': getattr(request, 'remote_addr', 'unknown') if request else 'unknown'
    }
    
    if severity == 'high':
        logger.error('Security event', extra=log_data)
    elif severity == 'medium':
        logger.warning('Security event', extra=log_data)
    else:
        logger.info('Security event', extra=log_data)
