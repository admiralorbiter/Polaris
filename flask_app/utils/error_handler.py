# flask_app/utils/error_handler.py

import os
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app, request, render_template_string
from datetime import datetime, timedelta, timezone
import json
from typing import Dict, List, Optional
import logging


class ErrorAlertingSystem:
    """Configurable error alerting system"""
    
    def __init__(self, app=None):
        self.app = app
        self.alert_methods = []
        self.error_counts = {}
        self.rate_limits = {}
        
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize the alerting system with app configuration"""
        self.app = app
        
        # Load alert methods from config
        if app.config.get('ENABLE_EMAIL_ALERTS'):
            self.alert_methods.append(self._send_email_alert)
        
        if app.config.get('ENABLE_SLACK_ALERTS'):
            self.alert_methods.append(self._send_slack_alert)
        
        if app.config.get('ENABLE_WEBHOOK_ALERTS'):
            self.alert_methods.append(self._send_webhook_alert)
        
        # Set up error rate limiting
        self.rate_limits = {
            'email': app.config.get('EMAIL_ALERT_RATE_LIMIT', 5),  # Max 5 emails per hour
            'slack': app.config.get('SLACK_ALERT_RATE_LIMIT', 10),  # Max 10 Slack messages per hour
            'webhook': app.config.get('WEBHOOK_ALERT_RATE_LIMIT', 20)  # Max 20 webhooks per hour
        }
    
    def should_send_alert(self, alert_type: str, error_key: str) -> bool:
        """Check if we should send an alert based on rate limiting"""
        now = datetime.now(timezone.utc)
        hour_ago = now - timedelta(hours=1)
        
        # Initialize error tracking
        if error_key not in self.error_counts:
            self.error_counts[error_key] = []
        
        # Clean old entries
        self.error_counts[error_key] = [
            timestamp for timestamp in self.error_counts[error_key]
            if timestamp > hour_ago
        ]
        
        # Check rate limit
        rate_limit = self.rate_limits.get(alert_type, 10)
        if len(self.error_counts[error_key]) >= rate_limit:
            return False
        
        # Record this error
        self.error_counts[error_key].append(now)
        return True
    
    def send_error_alert(self, error: Exception, context: Dict = None, severity: str = 'medium'):
        """Send error alert through configured channels"""
        context = context or {}
        
        # Create error key for rate limiting
        error_key = f"{type(error).__name__}_{context.get('endpoint', 'unknown')}"
        
        alert_data = {
            'error_type': type(error).__name__,
            'error_message': str(error),
            'severity': severity,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'context': context,
            'environment': self.app.config.get('FLASK_ENV', 'development'),
            'app_name': self.app.config.get('APP_NAME', 'Flask App')
        }
        
        # Send alerts through configured methods
        for method in self.alert_methods:
            try:
                method(alert_data, error_key)
            except Exception as e:
                # Don't let alerting failures crash the app
                current_app.logger.error(f"Failed to send alert: {e}")
    
    def _send_email_alert(self, alert_data: Dict, error_key: str):
        """Send email alert"""
        if not self.should_send_alert('email', error_key):
            return
        
        try:
            # Get email configuration
            smtp_server = self.app.config.get('MAIL_SERVER')
            smtp_port = self.app.config.get('MAIL_PORT', 587)
            smtp_username = self.app.config.get('MAIL_USERNAME')
            smtp_password = self.app.config.get('MAIL_PASSWORD')
            from_email = self.app.config.get('MAIL_FROM', 'noreply@example.com')
            admin_emails = self.app.config.get('ADMIN_EMAILS', [])
            
            if not all([smtp_server, smtp_username, smtp_password, admin_emails]):
                current_app.logger.warning("Email alerting configured but missing required settings")
                return
            
            # Create email content
            subject = f"[{alert_data['severity'].upper()}] {alert_data['app_name']} Error: {alert_data['error_type']}"
            
            # Email template
            email_template = """
            <html>
            <body>
                <h2>Application Error Alert</h2>
                <table border="1" cellpadding="5" cellspacing="0">
                    <tr><td><strong>Application</strong></td><td>{app_name}</td></tr>
                    <tr><td><strong>Environment</strong></td><td>{environment}</td></tr>
                    <tr><td><strong>Severity</strong></td><td>{severity}</td></tr>
                    <tr><td><strong>Error Type</strong></td><td>{error_type}</td></tr>
                    <tr><td><strong>Error Message</strong></td><td>{error_message}</td></tr>
                    <tr><td><strong>Timestamp</strong></td><td>{timestamp}</td></tr>
                    <tr><td><strong>Endpoint</strong></td><td>{endpoint}</td></tr>
                    <tr><td><strong>User ID</strong></td><td>{user_id}</td></tr>
                    <tr><td><strong>IP Address</strong></td><td>{ip_address}</td></tr>
                </table>
                
                <h3>Context</h3>
                <pre>{context_json}</pre>
                
                <h3>Stack Trace</h3>
                <pre>{stack_trace}</pre>
            </body>
            </html>
            """
            
            context = alert_data['context']
            body = email_template.format(
                app_name=alert_data['app_name'],
                environment=alert_data['environment'],
                severity=alert_data['severity'],
                error_type=alert_data['error_type'],
                error_message=alert_data['error_message'],
                timestamp=alert_data['timestamp'],
                endpoint=context.get('endpoint', 'N/A'),
                user_id=context.get('user_id', 'N/A'),
                ip_address=context.get('ip_address', 'N/A'),
                context_json=json.dumps(context, indent=2),
                stack_trace=context.get('stack_trace', 'N/A')
            )
            
            # Send email
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = from_email
            msg['To'] = ', '.join(admin_emails)
            
            msg.attach(MIMEText(body, 'html'))
            
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
            server.quit()
            
            current_app.logger.info(f"Email alert sent for {error_key}")
            
        except Exception as e:
            current_app.logger.error(f"Failed to send email alert: {e}")
    
    def _send_slack_alert(self, alert_data: Dict, error_key: str):
        """Send Slack alert"""
        if not self.should_send_alert('slack', error_key):
            return
        
        try:
            webhook_url = self.app.config.get('SLACK_WEBHOOK_URL')
            if not webhook_url:
                return
            
            # Create Slack message
            context = alert_data['context']
            severity_emoji = {
                'low': '🟡',
                'medium': '🟠', 
                'high': '🔴',
                'critical': '🚨'
            }.get(alert_data['severity'], '⚪')
            
            message = {
                "text": f"{severity_emoji} *{alert_data['app_name']} Error Alert*",
                "attachments": [
                    {
                        "color": "danger" if alert_data['severity'] in ['high', 'critical'] else "warning",
                        "fields": [
                            {"title": "Environment", "value": alert_data['environment'], "short": True},
                            {"title": "Severity", "value": alert_data['severity'], "short": True},
                            {"title": "Error Type", "value": alert_data['error_type'], "short": True},
                            {"title": "Endpoint", "value": context.get('endpoint', 'N/A'), "short": True},
                            {"title": "User ID", "value": str(context.get('user_id', 'N/A')), "short": True},
                            {"title": "IP Address", "value": context.get('ip_address', 'N/A'), "short": True},
                            {"title": "Error Message", "value": alert_data['error_message'], "short": False},
                            {"title": "Timestamp", "value": alert_data['timestamp'], "short": True}
                        ]
                    }
                ]
            }
            
            response = requests.post(webhook_url, json=message, timeout=10)
            response.raise_for_status()
            
            current_app.logger.info(f"Slack alert sent for {error_key}")
            
        except Exception as e:
            current_app.logger.error(f"Failed to send Slack alert: {e}")
    
    def _send_webhook_alert(self, alert_data: Dict, error_key: str):
        """Send webhook alert"""
        if not self.should_send_alert('webhook', error_key):
            return
        
        try:
            webhook_url = self.app.config.get('WEBHOOK_URL')
            if not webhook_url:
                return
            
            # Send webhook
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': f"{alert_data['app_name']}/1.0"
            }
            
            # Add custom headers if configured
            custom_headers = self.app.config.get('WEBHOOK_HEADERS', {})
            headers.update(custom_headers)
            
            response = requests.post(
                webhook_url,
                json=alert_data,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            
            current_app.logger.info(f"Webhook alert sent for {error_key}")
            
        except Exception as e:
            current_app.logger.error(f"Failed to send webhook alert: {e}")


# Global error alerting instance
error_alerter = ErrorAlertingSystem()


def init_error_alerting(app):
    """Initialize error alerting system"""
    error_alerter.init_app(app)


def send_error_alert(error: Exception, context: Dict = None, severity: str = 'medium'):
    """Send error alert through the configured alerting system"""
    error_alerter.send_error_alert(error, context, severity)
