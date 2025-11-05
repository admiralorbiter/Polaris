import pytest
import os
import logging
from unittest.mock import patch, MagicMock, mock_open
from flask import Flask
from flask_app.utils.error_handler import (
    ErrorAlertingSystem, 
    init_error_alerting, 
    send_error_alert, 
    error_alerter
)


class TestErrorAlertingSystem:
    """Comprehensive tests for ErrorAlertingSystem class"""
    
    def test_init_without_app(self):
        """Test initialization without app"""
        alerter = ErrorAlertingSystem()
        assert alerter.app is None
        assert alerter.alert_methods == []
        assert alerter.error_counts == {}
        assert alerter.rate_limits == {}
    
    def test_init_with_app(self, app):
        """Test initialization with app"""
        alerter = ErrorAlertingSystem(app)
        assert alerter.app == app
    
    def test_init_app_email_alerts_enabled(self, app):
        """Test app initialization with email alerts enabled"""
        app.config.update({
            'ENABLE_EMAIL_ALERTS': True,
            'ENABLE_SLACK_ALERTS': False,
            'ENABLE_WEBHOOK_ALERTS': False,
            'EMAIL_ALERT_RATE_LIMIT': 3,
            'SLACK_ALERT_RATE_LIMIT': 5,
            'WEBHOOK_ALERT_RATE_LIMIT': 10
        })
        
        alerter = ErrorAlertingSystem()
        alerter.init_app(app)
        
        assert len(alerter.alert_methods) == 1
        assert alerter.rate_limits['email'] == 3
        assert alerter.rate_limits['slack'] == 5
        assert alerter.rate_limits['webhook'] == 10
    
    def test_init_app_all_alerts_enabled(self, app):
        """Test app initialization with all alerts enabled"""
        app.config.update({
            'ENABLE_EMAIL_ALERTS': True,
            'ENABLE_SLACK_ALERTS': True,
            'ENABLE_WEBHOOK_ALERTS': True
        })
        
        alerter = ErrorAlertingSystem()
        alerter.init_app(app)
        
        assert len(alerter.alert_methods) == 3
    
    def test_should_send_alert_rate_limiting(self, app):
        """Test rate limiting functionality"""
        alerter = ErrorAlertingSystem(app)
        alerter.rate_limits = {'email': 2}
        
        error_key = 'test_error'
        
        # First two alerts should be allowed
        assert alerter.should_send_alert('email', error_key) == True
        assert alerter.should_send_alert('email', error_key) == True
        
        # Third alert should be rate limited
        assert alerter.should_send_alert('email', error_key) == False
        
        # Different error key should still be allowed
        assert alerter.should_send_alert('email', 'different_error') == True
    
    def test_should_send_alert_cleanup_old_entries(self, app):
        """Test that old error entries are cleaned up"""
        from datetime import datetime, timedelta, timezone
        
        alerter = ErrorAlertingSystem(app)
        alerter.rate_limits = {'email': 1}
        
        error_key = 'test_error'
        
        # Mock datetime to simulate old entries
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        alerter.error_counts[error_key] = [old_time, old_time]
        
        # Should clean up old entries and allow new alert
        with patch('flask_app.utils.error_handler.datetime') as mock_datetime:
            current_time = datetime.now(timezone.utc)
            mock_datetime.now.return_value = current_time
            mock_datetime.timedelta = timedelta
            
            result = alerter.should_send_alert('email', error_key)
            assert result == True
            assert len(alerter.error_counts[error_key]) == 1
    
    def test_send_error_alert_basic(self, app):
        """Test basic error alert sending"""
        alerter = ErrorAlertingSystem(app)
        alerter.alert_methods = [MagicMock()]
        
        error = ValueError("Test error")
        context = {'endpoint': '/test', 'user_id': 1}
        
        alerter.send_error_alert(error, context, 'high')
        
        # Check that alert method was called
        assert alerter.alert_methods[0].called
        call_args = alerter.alert_methods[0].call_args[0]
        alert_data = call_args[0]
        error_key = call_args[1]
        
        assert alert_data['error_type'] == 'ValueError'
        assert alert_data['error_message'] == 'Test error'
        assert alert_data['severity'] == 'high'
        assert alert_data['context'] == context
        assert error_key == 'ValueError_/test'
    
    def test_send_error_alert_without_context(self, app):
        """Test error alert sending without context"""
        alerter = ErrorAlertingSystem(app)
        alerter.alert_methods = [MagicMock()]
        
        error = RuntimeError("Test runtime error")
        
        alerter.send_error_alert(error)
        
        # Check that alert method was called
        assert alerter.alert_methods[0].called
        call_args = alerter.alert_methods[0].call_args[0]
        alert_data = call_args[0]
        
        assert alert_data['error_type'] == 'RuntimeError'
        assert alert_data['context'] == {}
        assert alert_data['severity'] == 'medium'  # Default severity
    
    def test_send_error_alert_method_failure(self, app):
        """Test error alert when alert method fails"""
        alerter = ErrorAlertingSystem(app)
        failing_method = MagicMock(side_effect=Exception("Alert failed"))
        alerter.alert_methods = [failing_method]
        
        error = ValueError("Test error")
        
        # Should not raise exception, just log error
        with patch('flask_app.utils.error_handler.current_app') as mock_app:
            alerter.send_error_alert(error)
            mock_app.logger.error.assert_called()
    
    def test_send_email_alert_missing_config(self, app):
        """Test email alert with missing configuration"""
        alerter = ErrorAlertingSystem(app)
        alerter.app = app
        
        # Test with missing SMTP configuration
        app.config.update({
            'ENABLE_EMAIL_ALERTS': True,
            'MAIL_SERVER': None,
            'MAIL_USERNAME': None
        })
        
        with patch('flask_app.utils.error_handler.current_app') as mock_app:
            alerter._send_email_alert({'test': 'data'}, 'test_key')
            mock_app.logger.warning.assert_called()
    
    def test_send_email_alert_success(self, app):
        """Test successful email alert sending"""
        alerter = ErrorAlertingSystem(app)
        alerter.app = app
        
        app.config.update({
            'ENABLE_EMAIL_ALERTS': True,
            'MAIL_SERVER': 'smtp.example.com',
            'MAIL_PORT': 587,
            'MAIL_USERNAME': 'test@example.com',
            'MAIL_PASSWORD': 'password',
            'MAIL_FROM': 'noreply@example.com',
            'ADMIN_EMAILS': ['admin@example.com'],
            'APP_NAME': 'Test App',
            'FLASK_ENV': 'test'
        })
        
        alert_data = {
            'error_type': 'ValueError',
            'error_message': 'Test error',
            'severity': 'high',
            'timestamp': '2023-01-01T00:00:00',
            'context': {'endpoint': '/test', 'user_id': 1, 'ip_address': '127.0.0.1'},
            'environment': 'test',
            'app_name': 'Test App'
        }
        
        with patch('flask_app.utils.error_handler.smtplib.SMTP') as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value = mock_server
            
            with patch('flask_app.utils.error_handler.current_app') as mock_app:
                alerter._send_email_alert(alert_data, 'test_key')
                
                # Verify SMTP was called correctly
                mock_smtp.assert_called_once_with('smtp.example.com', 587)
                mock_server.starttls.assert_called_once()
                mock_server.login.assert_called_once_with('test@example.com', 'password')
                mock_server.send_message.assert_called_once()
                mock_server.quit.assert_called_once()
    
    def test_send_slack_alert_missing_webhook(self, app):
        """Test Slack alert with missing webhook URL"""
        alerter = ErrorAlertingSystem(app)
        alerter.app = app
        
        app.config.update({
            'ENABLE_SLACK_ALERTS': True,
            'SLACK_WEBHOOK_URL': None
        })
        
        # Should return early without error
        alerter._send_slack_alert({'test': 'data'}, 'test_key')
    
    def test_send_slack_alert_success(self, app):
        """Test successful Slack alert sending"""
        alerter = ErrorAlertingSystem(app)
        alerter.app = app
        
        app.config.update({
            'ENABLE_SLACK_ALERTS': True,
            'SLACK_WEBHOOK_URL': 'https://hooks.slack.com/test'
        })
        
        alert_data = {
            'error_type': 'ValueError',
            'error_message': 'Test error',
            'severity': 'high',
            'timestamp': '2023-01-01T00:00:00',
            'context': {'endpoint': '/test', 'user_id': 1, 'ip_address': '127.0.0.1'},
            'environment': 'test',
            'app_name': 'Test App'
        }
        
        with patch('flask_app.utils.error_handler.requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.raise_for_status.return_value = None
            mock_post.return_value = mock_response
            
            with patch('flask_app.utils.error_handler.current_app') as mock_app:
                alerter._send_slack_alert(alert_data, 'test_key')
                
                # Verify request was made correctly
                mock_post.assert_called_once()
                call_args = mock_post.call_args
                assert call_args[0][0] == 'https://hooks.slack.com/test'
                assert 'json' in call_args[1]
                assert 'timeout' in call_args[1]
    
    def test_send_webhook_alert_missing_url(self, app):
        """Test webhook alert with missing URL"""
        alerter = ErrorAlertingSystem(app)
        alerter.app = app
        
        app.config.update({
            'ENABLE_WEBHOOK_ALERTS': True,
            'WEBHOOK_URL': None
        })
        
        # Should return early without error
        alerter._send_webhook_alert({'test': 'data'}, 'test_key')
    
    def test_send_webhook_alert_success(self, app):
        """Test successful webhook alert sending"""
        alerter = ErrorAlertingSystem(app)
        alerter.app = app
        
        app.config.update({
            'ENABLE_WEBHOOK_ALERTS': True,
            'WEBHOOK_URL': 'https://webhook.example.com/test',
            'WEBHOOK_HEADERS': {'X-Custom': 'value'}
        })
        
        alert_data = {
            'error_type': 'ValueError',
            'error_message': 'Test error',
            'severity': 'high',
            'timestamp': '2023-01-01T00:00:00',
            'context': {'endpoint': '/test'},
            'environment': 'test',
            'app_name': 'Test App'
        }
        
        with patch('flask_app.utils.error_handler.requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.raise_for_status.return_value = None
            mock_post.return_value = mock_response
            
            with patch('flask_app.utils.error_handler.current_app') as mock_app:
                alerter._send_webhook_alert(alert_data, 'test_key')
                
                # Verify request was made correctly
                mock_post.assert_called_once()
                call_args = mock_post.call_args
                assert call_args[0][0] == 'https://webhook.example.com/test'
                assert call_args[1]['json'] == alert_data
                assert call_args[1]['headers']['X-Custom'] == 'value'
                assert call_args[1]['timeout'] == 10


class TestGlobalErrorHandler:
    """Test global error handler functions"""
    
    def test_global_error_alerter(self, app):
        """Test global error alerter instance"""
        # Test that global instance exists
        assert error_alerter is not None
        assert hasattr(error_alerter, 'send_error_alert')
        
        # Test global send_error_alert function
        with patch.object(error_alerter, 'send_error_alert') as mock_send:
            error = ValueError("Test")
            send_error_alert(error, {'test': 'context'}, 'high')
            mock_send.assert_called_once_with(error, {'test': 'context'}, 'high')
    
    def test_init_error_alerting_function(self, app):
        """Test init_error_alerting function"""
        # Test that function initializes the global alerter
        init_error_alerting(app)
        assert error_alerter.app == app
