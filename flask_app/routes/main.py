# app/routes/main.py

from flask import flash, render_template, request, current_app

def register_main_routes(app):
    """Register main application routes"""
    
    @app.route('/')
    def index():
        try:
            current_app.logger.info(f"Index page accessed by {request.remote_addr}")
            return render_template('index.html')
        except Exception as e:
            current_app.logger.error(f"Error in index route: {str(e)}")
            flash('An error occurred while loading the page.', 'danger')
            return render_template('index.html'), 500
