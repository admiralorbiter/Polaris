"""Robustness tests for error handler - alerting failures, rate limiting, and configuration errors"""

from unittest.mock import MagicMock, patch

import pytest
import requests
import smtplib

from flask_app.utils.error_handler import ErrorAlertingSystem, error_alerter, init_error_alerting


class TestErrorAlertingRobustness:
    """Test error alerting system error handling"""

    def test_send_email_alert_missing_smtp_config(self, app):
        """Test email alert with missing SMTP configuration"""
        with app.app_context():
            app.config["ENABLE_EMAIL_ALERTS"] = True
            app.config["MAIL_SERVER"] = None  # Missing config
            app.config["MAIL_USERNAME"] = None
            app.config["MAIL_PASSWORD"] = None
            app.config["ADMIN_EMAILS"] = []

            alerter = ErrorAlertingSystem(app)
            error = Exception("Test error")
            
            # Should not raise, should log warning
            try:
                alerter.send_error_alert(error, {"endpoint": "/test"})
                # Should not crash
            except Exception:
                pytest.fail("Should handle missing config gracefully")

    def test_send_email_alert_smtp_connection_error(self, app):
        """Test email alert with SMTP connection error"""
        with app.app_context():
            app.config["ENABLE_EMAIL_ALERTS"] = True
            app.config["MAIL_SERVER"] = "smtp.example.com"
            app.config["MAIL_PORT"] = 587
            app.config["MAIL_USERNAME"] = "user"
            app.config["MAIL_PASSWORD"] = "pass"
            app.config["ADMIN_EMAILS"] = ["admin@example.com"]

            alerter = ErrorAlertingSystem(app)
            error = Exception("Test error")

            # Mock SMTP to raise connection error
            with patch("flask_app.utils.error_handler.smtplib.SMTP") as mock_smtp:
                mock_smtp.side_effect = smtplib.SMTPException("Connection refused")
                
                # Should not raise, should log error
                try:
                    alerter.send_error_alert(error, {"endpoint": "/test"})
                except Exception:
                    pytest.fail("Should handle SMTP error gracefully")

    def test_send_email_alert_smtp_login_error(self, app):
        """Test email alert with SMTP login error"""
        with app.app_context():
            app.config["ENABLE_EMAIL_ALERTS"] = True
            app.config["MAIL_SERVER"] = "smtp.example.com"
            app.config["MAIL_PORT"] = 587
            app.config["MAIL_USERNAME"] = "user"
            app.config["MAIL_PASSWORD"] = "wrongpass"
            app.config["ADMIN_EMAILS"] = ["admin@example.com"]

            alerter = ErrorAlertingSystem(app)
            error = Exception("Test error")

            # Mock SMTP server to raise login error
            with patch("flask_app.utils.error_handler.smtplib.SMTP") as mock_smtp_class:
                mock_server = MagicMock()
                mock_smtp_class.return_value = mock_server
                mock_server.starttls.side_effect = smtplib.SMTPAuthenticationError(535, "Authentication failed")
                
                try:
                    alerter.send_error_alert(error, {"endpoint": "/test"})
                except Exception:
                    pytest.fail("Should handle login error gracefully")

    def test_send_slack_alert_missing_webhook_url(self, app):
        """Test Slack alert with missing webhook URL"""
        with app.app_context():
            app.config["ENABLE_SLACK_ALERTS"] = True
            app.config["SLACK_WEBHOOK_URL"] = None  # Missing

            alerter = ErrorAlertingSystem(app)
            error = Exception("Test error")
            
            # Should not raise
            try:
                alerter.send_error_alert(error, {"endpoint": "/test"})
            except Exception:
                pytest.fail("Should handle missing webhook URL gracefully")

    def test_send_slack_alert_webhook_error(self, app):
        """Test Slack alert with webhook request error"""
        with app.app_context():
            app.config["ENABLE_SLACK_ALERTS"] = True
            app.config["SLACK_WEBHOOK_URL"] = "https://hooks.slack.com/test"

            alerter = ErrorAlertingSystem(app)
            error = Exception("Test error")

            # Mock requests.post to raise error
            with patch("flask_app.utils.error_handler.requests.post") as mock_post:
                mock_post.side_effect = requests.RequestException("Connection error")
                
                try:
                    alerter.send_error_alert(error, {"endpoint": "/test"})
                except Exception:
                    pytest.fail("Should handle webhook error gracefully")

    def test_send_slack_alert_http_error(self, app):
        """Test Slack alert with HTTP error response"""
        with app.app_context():
            app.config["ENABLE_SLACK_ALERTS"] = True
            app.config["SLACK_WEBHOOK_URL"] = "https://hooks.slack.com/test"

            alerter = ErrorAlertingSystem(app)
            error = Exception("Test error")

            # Mock requests.post to return error status
            with patch("flask_app.utils.error_handler.requests.post") as mock_post:
                mock_response = MagicMock()
                mock_response.raise_for_status.side_effect = requests.HTTPError("400 Bad Request")
                mock_post.return_value = mock_response
                
                try:
                    alerter.send_error_alert(error, {"endpoint": "/test"})
                except Exception:
                    pytest.fail("Should handle HTTP error gracefully")

    def test_send_webhook_alert_missing_url(self, app):
        """Test webhook alert with missing URL"""
        with app.app_context():
            app.config["ENABLE_WEBHOOK_ALERTS"] = True
            app.config["WEBHOOK_URL"] = None  # Missing

            alerter = ErrorAlertingSystem(app)
            error = Exception("Test error")
            
            try:
                alerter.send_error_alert(error, {"endpoint": "/test"})
            except Exception:
                pytest.fail("Should handle missing webhook URL gracefully")

    def test_send_webhook_alert_request_error(self, app):
        """Test webhook alert with request error"""
        with app.app_context():
            app.config["ENABLE_WEBHOOK_ALERTS"] = True
            app.config["WEBHOOK_URL"] = "https://webhook.example.com/alert"

            alerter = ErrorAlertingSystem(app)
            error = Exception("Test error")

            # Mock requests.post to raise error
            with patch("flask_app.utils.error_handler.requests.post") as mock_post:
                mock_post.side_effect = requests.Timeout("Request timeout")
                
                try:
                    alerter.send_error_alert(error, {"endpoint": "/test"})
                except Exception:
                    pytest.fail("Should handle timeout gracefully")

    def test_send_error_alert_all_methods_fail(self, app):
        """Test error alert when all alert methods fail"""
        with app.app_context():
            app.config["ENABLE_EMAIL_ALERTS"] = True
            app.config["ENABLE_SLACK_ALERTS"] = True
            app.config["ENABLE_WEBHOOK_ALERTS"] = True
            app.config["MAIL_SERVER"] = "smtp.example.com"
            app.config["MAIL_USERNAME"] = "user"
            app.config["MAIL_PASSWORD"] = "pass"
            app.config["ADMIN_EMAILS"] = ["admin@example.com"]
            app.config["SLACK_WEBHOOK_URL"] = "https://hooks.slack.com/test"
            app.config["WEBHOOK_URL"] = "https://webhook.example.com/alert"

            alerter = ErrorAlertingSystem(app)
            error = Exception("Test error")

            # Mock all methods to fail
            with patch("flask_app.utils.error_handler.smtplib.SMTP") as mock_smtp:
                mock_smtp.side_effect = smtplib.SMTPException("SMTP error")
                
                with patch("flask_app.utils.error_handler.requests.post") as mock_post:
                    mock_post.side_effect = requests.RequestException("Request error")
                    
                    # Should not raise, should log all errors
                    try:
                        alerter.send_error_alert(error, {"endpoint": "/test"})
                    except Exception:
                        pytest.fail("Should handle all failures gracefully")


class TestRateLimitingRobustness:
    """Test rate limiting edge cases"""

    def test_should_send_alert_rate_limit_exceeded(self, app):
        """Test rate limiting when limit is exceeded"""
        with app.app_context():
            app.config["EMAIL_ALERT_RATE_LIMIT"] = 2  # Low limit for testing
            alerter = ErrorAlertingSystem(app)
            error = Exception("Test error")
            error_key = "TestError_/test"

            # Send alerts up to limit
            for i in range(2):
                result = alerter.should_send_alert("email", error_key)
                assert result is True

            # Next one should be rate limited
            result = alerter.should_send_alert("email", error_key)
            assert result is False

    def test_should_send_alert_different_error_keys(self, app):
        """Test rate limiting with different error keys"""
        with app.app_context():
            app.config["EMAIL_ALERT_RATE_LIMIT"] = 1
            alerter = ErrorAlertingSystem(app)

            # Different error keys should have separate limits
            result1 = alerter.should_send_alert("email", "Error1_/endpoint1")
            result2 = alerter.should_send_alert("email", "Error2_/endpoint2")
            
            assert result1 is True
            assert result2 is True

    def test_should_send_alert_old_entries_cleaned(self, app):
        """Test that old entries are cleaned from rate limiting"""
        from datetime import datetime, timedelta, timezone

        with app.app_context():
            app.config["EMAIL_ALERT_RATE_LIMIT"] = 2
            alerter = ErrorAlertingSystem(app)
            error_key = "TestError_/test"

            # Add old entries (more than 1 hour ago)
            old_time = datetime.now(timezone.utc) - timedelta(hours=2)
            alerter.error_counts[error_key] = [old_time, old_time]

            # Should allow new alert (old entries cleaned)
            result = alerter.should_send_alert("email", error_key)
            assert result is True

    def test_should_send_alert_invalid_alert_type(self, app):
        """Test should_send_alert with invalid alert type"""
        with app.app_context():
            alerter = ErrorAlertingSystem(app)
            error_key = "TestError_/test"

            # Invalid alert type should use default limit
            result = alerter.should_send_alert("invalid_type", error_key)
            # Should still work with default limit
            assert isinstance(result, bool)


class TestErrorAlertingInitialization:
    """Test error alerting system initialization"""

    def test_init_error_alerting_no_config(self, app):
        """Test initialization with no alert methods configured"""
        with app.app_context():
            app.config["ENABLE_EMAIL_ALERTS"] = False
            app.config["ENABLE_SLACK_ALERTS"] = False
            app.config["ENABLE_WEBHOOK_ALERTS"] = False

            alerter = ErrorAlertingSystem(app)
            assert len(alerter.alert_methods) == 0

    def test_init_error_alerting_all_methods(self, app):
        """Test initialization with all alert methods"""
        with app.app_context():
            app.config["ENABLE_EMAIL_ALERTS"] = True
            app.config["ENABLE_SLACK_ALERTS"] = True
            app.config["ENABLE_WEBHOOK_ALERTS"] = True

            alerter = ErrorAlertingSystem(app)
            assert len(alerter.alert_methods) == 3

    def test_init_error_alerting_custom_rate_limits(self, app):
        """Test initialization with custom rate limits"""
        with app.app_context():
            app.config["EMAIL_ALERT_RATE_LIMIT"] = 10
            app.config["SLACK_ALERT_RATE_LIMIT"] = 20
            app.config["WEBHOOK_ALERT_RATE_LIMIT"] = 30

            alerter = ErrorAlertingSystem(app)
            assert alerter.rate_limits["email"] == 10
            assert alerter.rate_limits["slack"] == 20
            assert alerter.rate_limits["webhook"] == 30

    def test_send_error_alert_none_context(self, app):
        """Test send_error_alert with None context"""
        with app.app_context():
            alerter = ErrorAlertingSystem(app)
            error = Exception("Test error")
            
            # Should handle None context
            try:
                alerter.send_error_alert(error, None)
            except Exception:
                pytest.fail("Should handle None context gracefully")

    def test_send_error_alert_empty_context(self, app):
        """Test send_error_alert with empty context"""
        with app.app_context():
            alerter = ErrorAlertingSystem(app)
            error = Exception("Test error")
            
            # Should handle empty context
            try:
                alerter.send_error_alert(error, {})
            except Exception:
                pytest.fail("Should handle empty context gracefully")

    def test_error_key_generation_edge_cases(self, app):
        """Test error key generation with edge cases"""
        with app.app_context():
            alerter = ErrorAlertingSystem(app)
            error = Exception("Test error")

            # Test with missing endpoint
            alerter.send_error_alert(error, {})
            # Should use "unknown" as endpoint

            # Test with None endpoint
            alerter.send_error_alert(error, {"endpoint": None})
            # Should handle None endpoint

