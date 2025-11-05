# app.py

from flask import Flask, current_app
from flask_login import LoginManager
from dotenv import load_dotenv
import os
import logging
from logging.handlers import RotatingFileHandler

# Import from modular structure
from flask_app.models import db, User
from flask_app.routes import init_routes
from flask_app.utils.logging_config import setup_logging
from flask_app.utils.error_handler import init_error_alerting
from flask_app.utils.monitoring import init_monitoring
from config import DevelopmentConfig, ProductionConfig, TestingConfig
from config.monitoring import DevelopmentMonitoringConfig, ProductionMonitoringConfig, TestingMonitoringConfig

app = Flask(__name__)
# Load configuration based on the environment
if os.environ.get('FLASK_ENV') == 'production':
    app.config.from_object(ProductionConfig)
    app.config.from_object(ProductionMonitoringConfig)
elif os.environ.get('FLASK_ENV') == 'testing':
    app.config.from_object(TestingConfig)
    app.config.from_object(TestingMonitoringConfig)
else:
    app.config.from_object(DevelopmentConfig)
    app.config.from_object(DevelopmentMonitoringConfig)

# Initialize extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # Redirect to 'login' view if unauthorized
login_manager.login_message_category = 'info'

# Register login manager in app extensions for testing
app.extensions['login_manager'] = login_manager

# Initialize monitoring and logging systems
setup_logging(app)
init_error_alerting(app)
init_monitoring(app)

# Create the database tables
with app.app_context():
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
    return {'error': 'Not found'}, 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return {'error': 'Internal server error'}, 500

# Load environment variables from .env file
load_dotenv()

if __name__ == '__main__':
    # Use production-ready server configuration
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)