# flask_app/routes/admin.py

from flask import flash, redirect, render_template, url_for, request, current_app, jsonify
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from sqlalchemy import func, desc
from flask_app.models import User, AdminLog, SystemMetrics, db
from flask_app.forms import CreateUserForm, UpdateUserForm, ChangePasswordForm, BulkUserActionForm
from datetime import datetime, timezone, timedelta

def admin_required(f):
    """Decorator to require admin privileges"""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin privileges required.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def register_admin_routes(app):
    """Register admin dashboard routes"""
    
    @app.route('/admin')
    @login_required
    @admin_required
    def admin_dashboard():
        """Admin dashboard main page"""
        try:
            # Get system statistics
            total_users = User.query.count()
            active_users = User.query.filter_by(is_active=True).count()
            admin_users = User.query.filter_by(is_admin=True).count()
            
            # Get recent users (last 30 days)
            thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
            recent_users = User.query.filter(User.created_at >= thirty_days_ago).count()
            
            # Get recent admin actions
            recent_actions = AdminLog.query.order_by(desc(AdminLog.created_at)).limit(10).all()
            
            # Update system metrics
            SystemMetrics.set_metric('total_users', total_users)
            SystemMetrics.set_metric('active_users', active_users)
            SystemMetrics.set_metric('admin_users', admin_users)
            
            stats = {
                'total_users': total_users,
                'active_users': active_users,
                'admin_users': admin_users,
                'recent_users': recent_users,
                'recent_actions': recent_actions
            }
            
            current_app.logger.info(f"Admin dashboard accessed by {current_user.username}")
            return render_template('admin/dashboard.html', stats=stats)
            
        except Exception as e:
            current_app.logger.error(f"Error in admin dashboard: {str(e)}")
            flash('An error occurred while loading the dashboard.', 'danger')
            return render_template('admin/dashboard.html', stats={})
    
    @app.route('/admin/users')
    @login_required
    @admin_required
    def admin_users():
        """Admin user management page"""
        try:
            page = request.args.get('page', 1, type=int)
            per_page = 20
            
            users = User.query.paginate(
                page=page, per_page=per_page, error_out=False
            )
            
            return render_template('admin/users.html', users=users)
            
        except Exception as e:
            current_app.logger.error(f"Error in admin users page: {str(e)}")
            flash('An error occurred while loading users.', 'danger')
            return redirect(url_for('admin_dashboard'))
    
    @app.route('/admin/users/create', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def admin_create_user():
        """Create new user"""
        form = CreateUserForm()
        
        try:
            if form.validate_on_submit():
                # Create new user
                new_user, error = User.safe_create(
                    username=form.username.data.strip(),
                    email=form.email.data.strip().lower(),
                    password_hash=generate_password_hash(form.password.data),
                    first_name=form.first_name.data.strip() if form.first_name.data else None,
                    last_name=form.last_name.data.strip() if form.last_name.data else None,
                    is_active=form.is_active.data,
                    is_admin=form.is_admin.data
                )
                
                if error:
                    flash(f'Error creating user: {error}', 'danger')
                else:
                    # Log admin action
                    AdminLog.log_action(
                        admin_user_id=current_user.id,
                        action='CREATE_USER',
                        target_user_id=new_user.id,
                        details=f'Created user: {new_user.username}',
                        ip_address=request.remote_addr,
                        user_agent=request.headers.get('User-Agent')
                    )
                    
                    flash(f'User {new_user.username} created successfully!', 'success')
                    return redirect(url_for('admin_users'))
            
            return render_template('admin/create_user.html', form=form)
            
        except Exception as e:
            current_app.logger.error(f"Error in admin create user: {str(e)}")
            flash('An error occurred while creating user.', 'danger')
            return render_template('admin/create_user.html', form=form)
    
    @app.route('/admin/users/<int:user_id>')
    @login_required
    @admin_required
    def admin_view_user(user_id):
        """View user details"""
        try:
            user = User.query.get_or_404(user_id)
            
            # Get admin actions for this user
            actions = AdminLog.query.filter_by(target_user_id=user_id).order_by(desc(AdminLog.created_at)).limit(10).all()
            
            return render_template('admin/view_user.html', user=user, actions=actions)
            
        except Exception as e:
            current_app.logger.error(f"Error viewing user {user_id}: {str(e)}")
            flash('User not found.', 'danger')
            return redirect(url_for('admin_users'))
    
    @app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def admin_edit_user(user_id):
        """Edit user information"""
        user = User.query.get_or_404(user_id)
        form = UpdateUserForm(user=user)
        
        try:
            if form.validate_on_submit():
                # Update user
                success, error = user.safe_update(
                    username=form.username.data.strip(),
                    email=form.email.data.strip().lower(),
                    first_name=form.first_name.data.strip() if form.first_name.data else None,
                    last_name=form.last_name.data.strip() if form.last_name.data else None,
                    is_active=form.is_active.data,
                    is_admin=form.is_admin.data
                )
                
                if error:
                    flash(f'Error updating user: {error}', 'danger')
                else:
                    # Log admin action
                    AdminLog.log_action(
                        admin_user_id=current_user.id,
                        action='UPDATE_USER',
                        target_user_id=user.id,
                        details=f'Updated user: {user.username}',
                        ip_address=request.remote_addr,
                        user_agent=request.headers.get('User-Agent')
                    )
                    
                    flash(f'User {user.username} updated successfully!', 'success')
                    return redirect(url_for('admin_view_user', user_id=user.id))
            
            elif request.method == 'GET':
                # Populate form with current user data
                form.username.data = user.username
                form.email.data = user.email
                form.first_name.data = user.first_name
                form.last_name.data = user.last_name
                form.is_active.data = user.is_active
                form.is_admin.data = user.is_admin
            
            return render_template('admin/edit_user.html', form=form, user=user)
            
        except Exception as e:
            current_app.logger.error(f"Error editing user {user_id}: {str(e)}")
            flash('An error occurred while updating user.', 'danger')
            return render_template('admin/edit_user.html', form=form, user=user)
    
    @app.route('/admin/users/<int:user_id>/change-password', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def admin_change_password(user_id):
        """Change user password"""
        user = User.query.get_or_404(user_id)
        form = ChangePasswordForm()
        
        try:
            if form.validate_on_submit():
                # Update password
                success, error = user.safe_update(
                    password_hash=generate_password_hash(form.new_password.data)
                )
                
                if error:
                    flash(f'Error changing password: {error}', 'danger')
                else:
                    # Log admin action
                    AdminLog.log_action(
                        admin_user_id=current_user.id,
                        action='CHANGE_PASSWORD',
                        target_user_id=user.id,
                        details=f'Password changed for user: {user.username}',
                        ip_address=request.remote_addr,
                        user_agent=request.headers.get('User-Agent')
                    )
                    
                    flash(f'Password changed successfully for {user.username}!', 'success')
                    return redirect(url_for('admin_view_user', user_id=user.id))
            
            return render_template('admin/change_password.html', form=form, user=user)
            
        except Exception as e:
            current_app.logger.error(f"Error changing password for user {user_id}: {str(e)}")
            flash('An error occurred while changing password.', 'danger')
            return render_template('admin/change_password.html', form=form, user=user)
    
    @app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
    @login_required
    @admin_required
    def admin_delete_user(user_id):
        """Delete user"""
        try:
            user = User.query.get_or_404(user_id)
            
            # Prevent deleting self
            if user.id == current_user.id:
                flash('You cannot delete your own account.', 'danger')
                return redirect(url_for('admin_view_user', user_id=user_id))
            
            username = user.username
            
            # Log admin action before deletion
            AdminLog.log_action(
                admin_user_id=current_user.id,
                action='DELETE_USER',
                target_user_id=user.id,
                details=f'Deleted user: {username}',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            
            # Delete user
            success, error = user.safe_delete()
            
            if error:
                flash(f'Error deleting user: {error}', 'danger')
            else:
                flash(f'User {username} deleted successfully!', 'success')
            
            return redirect(url_for('admin_users'))
            
        except Exception as e:
            current_app.logger.error(f"Error deleting user {user_id}: {str(e)}")
            flash('An error occurred while deleting user.', 'danger')
            return redirect(url_for('admin_users'))
    
    @app.route('/admin/logs')
    @login_required
    @admin_required
    def admin_logs():
        """View admin action logs"""
        try:
            page = request.args.get('page', 1, type=int)
            per_page = 50
            
            logs = AdminLog.query.order_by(desc(AdminLog.created_at)).paginate(
                page=page, per_page=per_page, error_out=False
            )
            
            return render_template('admin/logs.html', logs=logs)
            
        except Exception as e:
            current_app.logger.error(f"Error loading admin logs: {str(e)}")
            flash('An error occurred while loading logs.', 'danger')
            return redirect(url_for('admin_dashboard'))
    
    @app.route('/admin/stats')
    @login_required
    @admin_required
    def admin_stats():
        """Get system statistics as JSON"""
        try:
            stats = {
                'total_users': SystemMetrics.get_metric('total_users'),
                'active_users': SystemMetrics.get_metric('active_users'),
                'admin_users': SystemMetrics.get_metric('admin_users'),
                'recent_logins': User.query.filter(User.last_login >= datetime.now(timezone.utc) - timedelta(days=7)).count()
            }
            
            return jsonify(stats)
            
        except Exception as e:
            current_app.logger.error(f"Error getting stats: {str(e)}")
            return jsonify({'error': 'Failed to get statistics'}), 500
