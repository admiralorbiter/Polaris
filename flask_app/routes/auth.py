# app/routes/auth.py

from flask import flash, redirect, render_template, url_for, request, current_app
from flask_login import login_required, login_user, logout_user, current_user
from werkzeug.security import check_password_hash
from flask_app.forms import LoginForm
from flask_app.models import User

def register_auth_routes(app):
    """Register authentication routes"""
    
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        form = LoginForm()
        
        try:
            if form.validate_on_submit():
                username = form.username.data.strip()
                password = form.password.data
                
                current_app.logger.info(f"Login attempt for username: {username} from {request.remote_addr}")
                
                # Query user with error handling
                user = User.find_by_username(username)
                if user is None and not isinstance(user, User):
                    # This means there was a database error
                    flash('A database error occurred. Please try again.', 'danger')
                    return render_template('login.html', form=form)
                
                # Validate user and password
                if user and check_password_hash(user.password_hash, password):
                    try:
                        login_user(user)
                        
                        # Update last login timestamp
                        user.update_last_login()
                        
                        current_app.logger.info(f"Successful login for user: {username}")
                        flash('Logged in successfully.', 'success')
                        
                        # Redirect to next page if provided, otherwise go to index
                        next_page = request.args.get('next')
                        if next_page and next_page.startswith('/'):
                            return redirect(next_page)
                        return redirect(url_for('index'))
                    except Exception as e:
                        current_app.logger.error(f"Error during login process: {str(e)}")
                        flash('An error occurred during login. Please try again.', 'danger')
                else:
                    current_app.logger.warning(f"Failed login attempt for username: {username}")
                    flash('Invalid username or password.', 'danger')
            
            return render_template('login.html', form=form)
            
        except Exception as e:
            current_app.logger.error(f"Unexpected error in login route: {str(e)}")
            flash('An unexpected error occurred. Please try again.', 'danger')
            return render_template('login.html', form=form), 500
    
    @app.route('/logout')
    def logout():
        try:
            # Check if user is authenticated before trying to access current_user
            if current_user.is_authenticated:
                username = current_user.username
                logout_user()
                current_app.logger.info(f"User {username} logged out")
                flash('You have been logged out.', 'info')
            else:
                # User was not authenticated, just redirect
                current_app.logger.info("Logout requested for unauthenticated user")
                flash('You were not logged in.', 'info')
            
            return redirect(url_for('index'))
        except Exception as e:
            current_app.logger.error(f"Error during logout: {str(e)}")
            # Force logout even if there's an error
            try:
                logout_user()
            except:
                pass
            flash('You have been logged out.', 'info')
            return redirect(url_for('index'))
