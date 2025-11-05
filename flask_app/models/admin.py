# flask_app/models/admin.py

from datetime import datetime, timezone
from flask import current_app
from .base import db, BaseModel

class AdminLog(BaseModel):
    """Model for tracking admin actions"""
    __tablename__ = 'admin_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(100), nullable=False)  # CREATE_USER, UPDATE_USER, DELETE_USER, etc.
    target_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    details = db.Column(db.Text, nullable=True)  # JSON string with action details
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.Text, nullable=True)
    
    def __repr__(self):
        return f'<AdminLog {self.action} by user {self.admin_user_id}>'
    
    @staticmethod
    def log_action(admin_user_id, action, target_user_id=None, details=None, 
                   ip_address=None, user_agent=None):
        """Log an admin action"""
        try:
            log_entry = AdminLog(
                admin_user_id=admin_user_id,
                action=action,
                target_user_id=target_user_id,
                details=details,
                ip_address=ip_address,
                user_agent=user_agent
            )
            db.session.add(log_entry)
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error logging admin action: {str(e)}")
            return False

class SystemMetrics(BaseModel):
    """Model for storing system metrics"""
    __tablename__ = 'system_metrics'
    
    id = db.Column(db.Integer, primary_key=True)
    metric_name = db.Column(db.String(100), nullable=False, unique=True)
    metric_value = db.Column(db.Float, nullable=False)
    metric_data = db.Column(db.Text, nullable=True)  # JSON string for complex data
    
    def __repr__(self):
        return f'<SystemMetrics {self.metric_name}: {self.metric_value}>'
    
    @staticmethod
    def get_metric(metric_name, default_value=0):
        """Get a system metric value"""
        try:
            metric = SystemMetrics.query.filter_by(metric_name=metric_name).first()
            return metric.metric_value if metric else default_value
        except Exception as e:
            current_app.logger.error(f"Error getting metric {metric_name}: {str(e)}")
            return default_value
    
    @staticmethod
    def set_metric(metric_name, value, data=None):
        """Set a system metric value"""
        try:
            metric = SystemMetrics.query.filter_by(metric_name=metric_name).first()
            if metric:
                metric.metric_value = value
                metric.metric_data = data
            else:
                metric = SystemMetrics(
                    metric_name=metric_name,
                    metric_value=value,
                    metric_data=data
                )
                db.session.add(metric)
            db.session.commit()
            return True
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error setting metric {metric_name}: {str(e)}")
            return False
