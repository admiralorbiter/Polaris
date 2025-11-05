# flask_app/utils/monitoring.py

import time
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
import os
from datetime import datetime, timezone
from flask import current_app, request, g, jsonify
from flask_app.models import db
from sqlalchemy import text
import logging


class HealthChecker:
    """Comprehensive health check system"""
    
    def __init__(self, app=None):
        self.app = app
        self.start_time = datetime.now(timezone.utc)
        
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize health checking"""
        self.app = app
        
        # Register health check endpoints
        @app.route('/health')
        def health_check():
            return self.basic_health_check()
        
        @app.route('/health/detailed')
        def detailed_health_check():
            return self.detailed_health_check()
        
        @app.route('/health/ready')
        def readiness_check():
            return self.readiness_check()
        
        @app.route('/health/live')
        def liveness_check():
            return self.liveness_check()
    
    def basic_health_check(self):
        """Basic health check for load balancers"""
        try:
            # Check database connectivity
            db.session.execute(text('SELECT 1'))
            
            return jsonify({
                'status': 'healthy',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'uptime': str(datetime.now(timezone.utc) - self.start_time),
                'version': current_app.config.get('APP_VERSION', '1.0.0')
            }), 200
            
        except Exception as e:
            current_app.logger.error(f"Health check failed: {e}")
            return jsonify({
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }), 503
    
    def detailed_health_check(self):
        """Detailed health check with system metrics"""
        health_data = {
            'status': 'healthy',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'uptime': str(datetime.now(timezone.utc) - self.start_time),
            'version': current_app.config.get('APP_VERSION', '1.0.0'),
            'environment': current_app.config.get('FLASK_ENV', 'development'),
            'checks': {}
        }
        
        overall_healthy = True
        
        # Database check
        try:
            start_time = time.time()
            db.session.execute(text('SELECT 1'))
            db_time = time.time() - start_time
            
            health_data['checks']['database'] = {
                'status': 'healthy',
                'response_time_ms': round(db_time * 1000, 2),
                'connection_pool_size': str(db.engine.pool.size()),
                'checked_in_connections': str(db.engine.pool.checkedin()),
                'checked_out_connections': str(db.engine.pool.checkedout())
            }
        except Exception as e:
            health_data['checks']['database'] = {
                'status': 'unhealthy',
                'error': str(e)
            }
            overall_healthy = False
        
        # System resource checks (only if psutil is available)
        if HAS_PSUTIL:
            # Disk space check
            try:
                disk_usage = psutil.disk_usage('/')
                health_data['checks']['disk_space'] = {
                    'status': 'healthy',
                    'total_gb': round(disk_usage.total / (1024**3), 2),
                    'free_gb': round(disk_usage.free / (1024**3), 2),
                    'used_percent': round((disk_usage.used / disk_usage.total) * 100, 2)
                }
                
                # Alert if disk usage > 90%
                if health_data['checks']['disk_space']['used_percent'] > 90:
                    health_data['checks']['disk_space']['status'] = 'warning'
                    overall_healthy = False
                    
            except Exception as e:
                health_data['checks']['disk_space'] = {
                    'status': 'unhealthy',
                    'error': str(e)
                }
                overall_healthy = False
            
            # Memory check
            try:
                memory = psutil.virtual_memory()
                health_data['checks']['memory'] = {
                    'status': 'healthy',
                    'total_gb': round(memory.total / (1024**3), 2),
                    'available_gb': round(memory.available / (1024**3), 2),
                    'used_percent': memory.percent
                }
                
                # Alert if memory usage > 90%
                if memory.percent > 90:
                    health_data['checks']['memory']['status'] = 'warning'
                    overall_healthy = False
                    
            except Exception as e:
                health_data['checks']['memory'] = {
                    'status': 'unhealthy',
                    'error': str(e)
                }
                overall_healthy = False
            
            # CPU check
            try:
                cpu_percent = psutil.cpu_percent(interval=1)
                health_data['checks']['cpu'] = {
                    'status': 'healthy',
                    'usage_percent': cpu_percent,
                    'core_count': psutil.cpu_count()
                }
                
                # Alert if CPU usage > 90%
                if cpu_percent > 90:
                    health_data['checks']['cpu']['status'] = 'warning'
                    overall_healthy = False
                    
            except Exception as e:
                health_data['checks']['cpu'] = {
                    'status': 'unhealthy',
                    'error': str(e)
                }
                overall_healthy = False
        else:
            # psutil not available, skip system checks
            health_data['checks']['system_resources'] = {
                'status': 'skipped',
                'message': 'psutil not available for system monitoring'
            }
        
        # Application-specific checks
        try:
            # Check if we can access application files
            app_dir = os.path.dirname(current_app.root_path)
            if os.path.exists(app_dir) and os.access(app_dir, os.R_OK):
                health_data['checks']['application'] = {
                    'status': 'healthy',
                    'app_directory': app_dir,
                    'config_loaded': bool(current_app.config)
                }
            else:
                health_data['checks']['application'] = {
                    'status': 'unhealthy',
                    'error': 'Application directory not accessible'
                }
                overall_healthy = False
                
        except Exception as e:
            health_data['checks']['application'] = {
                'status': 'unhealthy',
                'error': str(e)
            }
            overall_healthy = False
        
        # Update overall status
        health_data['status'] = 'healthy' if overall_healthy else 'degraded'
        
        status_code = 200 if overall_healthy else 503
        return jsonify(health_data), status_code
    
    def readiness_check(self):
        """Kubernetes readiness probe"""
        try:
            # Check if application is ready to serve traffic
            db.session.execute(text('SELECT 1'))
            
            # Check if all required services are available
            # Add custom readiness checks here
            
            return jsonify({
                'status': 'ready',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }), 200
            
        except Exception as e:
            current_app.logger.error(f"Readiness check failed: {e}")
            return jsonify({
                'status': 'not_ready',
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }), 503
    
    def liveness_check(self):
        """Kubernetes liveness probe"""
        try:
            # Simple check to see if application is alive
            # This should be very lightweight
            return jsonify({
                'status': 'alive',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'uptime': str(datetime.now(timezone.utc) - self.start_time)
            }), 200
            
        except Exception as e:
            current_app.logger.error(f"Liveness check failed: {e}")
            return jsonify({
                'status': 'dead',
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }), 503


class PerformanceMonitor:
    """Performance monitoring and metrics collection"""
    
    def __init__(self, app=None):
        self.app = app
        self.request_times = []
        self.error_counts = {}
        
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize performance monitoring"""
        self.app = app
        
        @app.before_request
        def before_request():
            g.start_time = time.time()
            g.request_id = f"req_{int(time.time() * 1000)}"
        
        @app.after_request
        def after_request(response):
            if hasattr(g, 'start_time'):
                duration = time.time() - g.start_time
                self.record_request(duration, response.status_code, request.endpoint)
            return response
        
        @app.teardown_request
        def teardown_request(exception):
            if exception:
                self.record_error(exception, request.endpoint)
    
    def record_request(self, duration, status_code, endpoint):
        """Record request metrics"""
        self.request_times.append({
            'duration': duration,
            'status_code': status_code,
            'endpoint': endpoint,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        
        # Keep only last 1000 requests
        if len(self.request_times) > 1000:
            self.request_times = self.request_times[-1000:]
        
        # Log slow requests
        if duration > 5.0:  # 5 seconds
            current_app.logger.warning(f"Slow request: {endpoint} took {duration:.2f}s")
    
    def record_error(self, exception, endpoint):
        """Record error metrics"""
        error_key = f"{type(exception).__name__}_{endpoint}"
        self.error_counts[error_key] = self.error_counts.get(error_key, 0) + 1
        
        current_app.logger.error(f"Request error: {error_key}", exc_info=True)
    
    def get_metrics(self):
        """Get performance metrics"""
        if not self.request_times:
            return {
                'total_requests': 0,
                'average_response_time': 0,
                'slow_requests': 0,
                'error_counts': self.error_counts
            }
        
        durations = [req['duration'] for req in self.request_times]
        
        return {
            'total_requests': len(self.request_times),
            'average_response_time': round(sum(durations) / len(durations), 3),
            'max_response_time': round(max(durations), 3),
            'min_response_time': round(min(durations), 3),
            'slow_requests': len([d for d in durations if d > 1.0]),
            'error_counts': self.error_counts,
            'last_updated': datetime.now(timezone.utc).isoformat()
        }


# Global instances
health_checker = HealthChecker()
performance_monitor = PerformanceMonitor()


def init_monitoring(app):
    """Initialize monitoring systems"""
    health_checker.init_app(app)
    performance_monitor.init_app(app)
