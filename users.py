# ============================================
# users.py - User Management Routes
# Additional feature: Manager can manage user accounts
# Also handles password changes for all users
# ============================================

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash

users_bp = Blueprint('users', __name__)

def get_db():
    from app import get_db_connection
    return get_db_connection()

def audit(user_id, action_type, table_name, record_id, details):
    from app import log_audit
    log_audit(user_id, action_type, table_name, record_id, details)


# ============================================
# LIST USERS (Manager only)
# ============================================
@users_bp.route('/users')
def list_users():
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT u.*,
                   (SELECT COUNT(*) FROM audit_trail at WHERE at.user_id = u.user_id) AS action_count,
                   (SELECT MAX(at.action_date) FROM audit_trail at WHERE at.user_id = u.user_id) AS last_activity
            FROM users u
            ORDER BY u.role, u.full_name
        """)
        users = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('users/list.html', users=users)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))


# ============================================
# ADD NEW USER (Manager only)
# ============================================
@users_bp.route('/users/add', methods=['GET', 'POST'])
def add_user():
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        role = request.form.get('role', '').strip()

        # Validation
        errors = []
        if not full_name:
            errors.append('Full name is required.')
        if not username:
            errors.append('Username is required.')
        if len(username) < 3:
            errors.append('Username must be at least 3 characters.')
        if not email or '@' not in email:
            errors.append('A valid email is required.')
        if not password:
            errors.append('Password is required.')
        if len(password) < 6:
            errors.append('Password must be at least 6 characters.')
        if password != confirm_password:
            errors.append('Passwords do not match.')
        if role not in ['manager', 'staff']:
            errors.append('Please select a valid role.')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('users/add.html')

        try:
            conn = get_db()
            cursor = conn.cursor(dictionary=True)

            # Check for duplicate username
            cursor.execute("SELECT user_id FROM users WHERE username = %s", (username,))
            if cursor.fetchone():
                flash('Username already exists.', 'warning')
                cursor.close()
                conn.close()
                return render_template('users/add.html')

            # Check for duplicate email
            cursor.execute("SELECT user_id FROM users WHERE email = %s", (email,))
            if cursor.fetchone():
                flash('Email already exists.', 'warning')
                cursor.close()
                conn.close()
                return render_template('users/add.html')

            # Hash password and insert
            password_hash = generate_password_hash(password, method='pbkdf2:sha256')

            cursor.execute(
                """INSERT INTO users (full_name, username, email, password_hash, role)
                   VALUES (%s, %s, %s, %s, %s)""",
                (full_name, username, email, password_hash, role)
            )
            conn.commit()
            new_user_id = cursor.lastrowid

            audit(session['user_id'], 'USER_CREATED', 'users', new_user_id,
                  f"Created user account: {username} ({role})")

            cursor.close()
            conn.close()

            flash(f'User "{full_name}" created successfully!', 'success')
            return redirect(url_for('users.list_users'))

        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
            return render_template('users/add.html')

    return render_template('users/add.html')


# ============================================
# TOGGLE USER ACTIVE STATUS (Manager only)
# ============================================
@users_bp.route('/users/toggle/<int:user_id>', methods=['POST'])
def toggle_user(user_id):
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    # Prevent manager from deactivating themselves
    if user_id == session['user_id']:
        flash('You cannot deactivate your own account.', 'warning')
        return redirect(url_for('users.list_users'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()

        if user:
            new_status = 0 if user['is_active'] else 1
            cursor.execute(
                "UPDATE users SET is_active = %s WHERE user_id = %s",
                (new_status, user_id)
            )
            conn.commit()

            status_text = 'activated' if new_status else 'deactivated'
            audit(session['user_id'], 'USER_UPDATED', 'users', user_id,
                  f"User {user['username']} {status_text}")

            flash(f'User "{user["full_name"]}" has been {status_text}.', 'success')

        cursor.close()
        conn.close()

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')

    return redirect(url_for('users.list_users'))


# ============================================
# CHANGE OWN PASSWORD (All users)
# ============================================
@users_bp.route('/change-password', methods=['GET', 'POST'])
def change_password():
    if 'user_id' not in session:
        flash('Please log in.', 'warning')
        return redirect(url_for('login'))

    if request.method == 'POST':
        current_password = request.form.get('current_password', '').strip()
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        errors = []
        if not current_password:
            errors.append('Current password is required.')
        if not new_password:
            errors.append('New password is required.')
        if len(new_password) < 6:
            errors.append('New password must be at least 6 characters.')
        if new_password != confirm_password:
            errors.append('New passwords do not match.')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('users/change_password.html')

        try:
            conn = get_db()
            cursor = conn.cursor(dictionary=True)

            cursor.execute(
                "SELECT password_hash FROM users WHERE user_id = %s",
                (session['user_id'],)
            )
            user = cursor.fetchone()

            if not check_password_hash(user['password_hash'], current_password):
                flash('Current password is incorrect.', 'danger')
                cursor.close()
                conn.close()
                return render_template('users/change_password.html')

            new_hash = generate_password_hash(new_password, method='pbkdf2:sha256')
            cursor.execute(
                "UPDATE users SET password_hash = %s WHERE user_id = %s",
                (new_hash, session['user_id'])
            )
            conn.commit()

            audit(session['user_id'], 'PASSWORD_CHANGED', 'users', session['user_id'],
                  f"User {session['username']} changed their password")

            cursor.close()
            conn.close()

            flash('Password changed successfully!', 'success')
            return redirect(url_for('dashboard'))

        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')

    return render_template('users/change_password.html')