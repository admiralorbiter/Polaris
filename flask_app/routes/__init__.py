# app/routes/__init__.py
"""
Application routes package
"""

from .admin import register_admin_routes
from .api import register_api_routes
from .auth import register_auth_routes
from .main import register_main_routes
from .organization import register_organization_routes


def init_routes(app):
    """Initialize all application routes"""
    register_main_routes(app)
    register_auth_routes(app)
    register_admin_routes(app)
    register_organization_routes(app)
    register_api_routes(app)
