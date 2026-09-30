# ============================================
# app.py - Main Application File for CityPharma
# ============================================

from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import mysql.connector

# --- Create Flask App ---
app = Flask(__name__)
app.secret_key = 'citypharma_secret_key_2026'

# ============================================
# DATABASE CONNECTION
# ============================================
def get_db_connection():
    connection = mysql.connector.connect(
        host='localhost',
        user='root',
        password='',
        database='citypharma_db'
    )
    return connection

# ============================================
# ROLE-BASED ACCESS CONTROL DECORATORS
# ============================================
# Decorators are functions that wrap other functions.
# use them to check if a user is logged in and has the right role
# BEFORE the page loads. This is how we enforce access control.

def login_required(f):

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def manager_required(f):

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        if session.get('role') != 'manager':
            flash('Access denied. Manager privileges required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def staff_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        if session.get('role') != 'staff':
            flash('Access denied. Staff privileges required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# ============================================
# AUDIT TRAIL HELPER FUNCTION
# ============================================
def log_audit(user_id, action_type, table_name, record_id, details):

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO audit_trail (user_id, action_type, table_name, record_id, details)
               VALUES (%s, %s, %s, %s, %s)""",
            (user_id, action_type, table_name, record_id, details)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Audit trail error: {e}")

# ============================================
# AUTHENTICATION ROUTES
# ============================================

@app.route('/')
def home():

    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    Login page.
    GET request = show the login form
    POST request = process the form (check username and password)

    How it works:
    1. User submits username and password
    2. look up the username in the database
    3. check the password hash matches (using check_password_hash)
    4. If valid, store user info in the session
    5. redirect to the appropriate dashboard based on role
    """
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        # --- Validation ---
        if not username or not password:
            flash('Please enter both username and password.', 'danger')
            return render_template('login.html')

        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)

            # Look up the user by username
            cursor.execute("SELECT * FROM users WHERE username = %s AND is_active = 1", (username,))
            user = cursor.fetchone()

            cursor.close()
            conn.close()

            if user and check_password_hash(user['password_hash'], password):
                # --- Password is correct - create session ---
                # Session data is stored on the server and linked to the browser via a cookie
                session['user_id'] = user['user_id']
                session['username'] = user['username']
                session['full_name'] = user['full_name']
                session['role'] = user['role']

                # Log the login in audit trail
                log_audit(user['user_id'], 'LOGIN', 'users', user['user_id'],
                         f"User {user['username']} logged in")

                flash(f'Welcome back, {user["full_name"]}!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid username or password.', 'danger')

        except Exception as e:
            flash(f'An error occurred: {str(e)}', 'danger')

    return render_template('login.html')

@app.route('/logout')
def logout():
    """
    Logs the user out by clearing the session.
    """
    if 'user_id' in session:
        log_audit(session['user_id'], 'LOGOUT', 'users', session['user_id'],
                 f"User {session['username']} logged out")
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))
@app.route('/dashboard')
@login_required
def dashboard():
    """
    Dashboard - shows different content based on user role.
    Now includes live statistics from the database.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if session.get('role') == 'manager':
            # Manager stats
            cursor.execute("SELECT COUNT(*) AS c FROM medicines WHERE is_active = 1")
            total_medicines = cursor.fetchone()['c']

            cursor.execute("SELECT COUNT(*) AS c FROM suppliers WHERE is_active = 1")
            total_suppliers = cursor.fetchone()['c']

            cursor.execute("""
                SELECT COUNT(*) AS c FROM purchase_orders WHERE status = 'pending'
            """)
            pending_orders = cursor.fetchone()['c']

            cursor.execute("""
                SELECT COUNT(*) AS c FROM (
                    SELECT m.medicine_id
                    FROM medicines m
                    LEFT JOIN batches b ON m.medicine_id = b.medicine_id AND b.expiry_date >= CURDATE()
                    WHERE m.is_active = 1
                    GROUP BY m.medicine_id, m.low_stock_threshold
                    HAVING COALESCE(SUM(b.quantity), 0) <= m.low_stock_threshold
                ) AS low
            """)
            low_stock = cursor.fetchone()['c']

            # --- Report snapshot data ---

            # This month's revenue
            cursor.execute("""
                SELECT COALESCE(SUM(p.amount), 0) AS total
                FROM payments p
                WHERE MONTH(p.payment_date) = MONTH(CURDATE())
                  AND YEAR(p.payment_date) = YEAR(CURDATE())
            """)
            monthly_revenue = cursor.fetchone()['total']

            # This month's spending
            cursor.execute("""
                SELECT COALESCE(SUM(po.total_cost), 0) AS total
                FROM purchase_orders po
                WHERE po.status = 'received'
                  AND MONTH(po.received_date) = MONTH(CURDATE())
                  AND YEAR(po.received_date) = YEAR(CURDATE())
            """)
            monthly_spending = cursor.fetchone()['total']

            # Total dispensed prescriptions
            cursor.execute("SELECT COUNT(*) AS c FROM prescriptions WHERE status = 'dispensed'")
            total_dispensed = cursor.fetchone()['c']

            # Expiring within 30 days
            cursor.execute("""
                SELECT COUNT(DISTINCT b.batch_id) AS c
                FROM batches b
                JOIN medicines m ON b.medicine_id = m.medicine_id
                WHERE m.is_active = 1 AND b.quantity > 0
                  AND b.expiry_date >= CURDATE()
                  AND b.expiry_date <= DATE_ADD(CURDATE(), INTERVAL 30 DAY)
            """)
            expiring_soon = cursor.fetchone()['c']

            # Out of stock count
            cursor.execute("""
                SELECT COUNT(*) AS c FROM (
                    SELECT m.medicine_id
                    FROM medicines m
                    LEFT JOIN batches b ON m.medicine_id = b.medicine_id AND b.expiry_date >= CURDATE()
                    WHERE m.is_active = 1
                    GROUP BY m.medicine_id
                    HAVING COALESCE(SUM(b.quantity), 0) = 0
                ) AS oos
            """)
            out_of_stock = cursor.fetchone()['c']

            # Recent 5 transactions
            cursor.execute("""
                SELECT p.receipt_reference, p.amount, p.payment_method, p.payment_date,
                       pr.patient_name
                FROM payments p
                JOIN dispensing_records dr ON p.dispensing_id = dr.dispensing_id
                JOIN prescriptions pr ON dr.prescription_id = pr.prescription_id
                ORDER BY p.payment_date DESC
                LIMIT 5
            """)
            recent_transactions = cursor.fetchall()

            # Top 5 low stock medicines
            cursor.execute("""
                SELECT m.name, m.strength, m.dosage_form,
                       COALESCE(SUM(CASE WHEN b.expiry_date >= CURDATE() THEN b.quantity ELSE 0 END), 0) AS stock,
                       m.low_stock_threshold
                FROM medicines m
                LEFT JOIN batches b ON m.medicine_id = b.medicine_id
                WHERE m.is_active = 1
                GROUP BY m.medicine_id, m.low_stock_threshold
                HAVING stock <= m.low_stock_threshold
                ORDER BY stock ASC
                LIMIT 5
            """)
            low_stock_medicines = cursor.fetchall()

            cursor.close()
            conn.close()

            return render_template('manager_dashboard.html',
                                 total_medicines=total_medicines,
                                 total_suppliers=total_suppliers,
                                 pending_orders=pending_orders,
                                 low_stock=low_stock,
                                 monthly_revenue=monthly_revenue,
                                 monthly_spending=monthly_spending,
                                 total_dispensed=total_dispensed,
                                 expiring_soon=expiring_soon,
                                 out_of_stock=out_of_stock,
                                 recent_transactions=recent_transactions,
                                 low_stock_medicines=low_stock_medicines)
        
        else:
            # Staff stats
            cursor.execute("""
                SELECT COUNT(*) AS c FROM prescriptions
                WHERE status = 'created'
            """)
            pending_prescriptions = cursor.fetchone()['c']

            cursor.execute("""
                SELECT COUNT(*) AS c FROM dispensing_records
                WHERE dispensed_by = %s
            """, (session['user_id'],))
            my_dispensed = cursor.fetchone()['c']

            cursor.execute("""
                SELECT COUNT(*) AS c FROM audit_trail
                WHERE user_id = %s
            """, (session['user_id'],))
            my_actions = cursor.fetchone()['c']

            cursor.close()
            conn.close()

            return render_template('staff_dashboard.html',
                                 pending_prescriptions=pending_prescriptions,
                                 my_dispensed=my_dispensed,
                                 my_actions=my_actions)

    except Exception as e:
        return render_template('manager_dashboard.html' if session.get('role') == 'manager'
                             else 'staff_dashboard.html')
    

# --- Register Blueprints ---
from medicines import medicines_bp
from suppliers import suppliers_bp
from orders import orders_bp
from prescriptions import prescriptions_bp
from dispensing import dispensing_bp
from adjustments import adjustments_bp
from reports import reports_bp
from users import users_bp
app.register_blueprint(medicines_bp)
app.register_blueprint(suppliers_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(prescriptions_bp)
app.register_blueprint(dispensing_bp)
app.register_blueprint(adjustments_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(users_bp)


# ============================================
# RUN THE APPLICATION
# ============================================

if __name__ == '__main__':
    app.run(debug=True)