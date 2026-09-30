# ============================================
# reports.py - Reporting Routes
# Blueprint for all reporting functionality
# Only accessible by Pharmacy Manager 
# ============================================

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import datetime

reports_bp = Blueprint('reports', __name__)

def get_db():
    from app import get_db_connection
    return get_db_connection()


# ============================================
# REPORTS DASHBOARD
# URL: /reports
# Central hub linking to all reports
# ============================================
@reports_bp.route('/reports')
def reports_dashboard():
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Quick summary stats for the dashboard cards

        # Total medicines
        cursor.execute("SELECT COUNT(*) AS count FROM medicines WHERE is_active = 1")
        total_medicines = cursor.fetchone()['count']

# Low stock count
        cursor.execute("""
            SELECT COUNT(*) AS count FROM (
                SELECT m.medicine_id, m.low_stock_threshold AS threshold
                FROM medicines m
                LEFT JOIN batches b ON m.medicine_id = b.medicine_id AND b.expiry_date >= CURDATE()
                WHERE m.is_active = 1
                GROUP BY m.medicine_id, m.low_stock_threshold
                HAVING COALESCE(SUM(b.quantity), 0) <= threshold
                   AND COALESCE(SUM(b.quantity), 0) > 0
            ) AS low_stock
        """)
        low_stock_count = cursor.fetchone()['count']

        # Out of stock count
        cursor.execute("""
            SELECT COUNT(*) AS count FROM (
                SELECT m.medicine_id
                FROM medicines m
                LEFT JOIN batches b ON m.medicine_id = b.medicine_id AND b.expiry_date >= CURDATE()
                WHERE m.is_active = 1
                GROUP BY m.medicine_id
                HAVING COALESCE(SUM(b.quantity), 0) = 0
            ) AS out_of_stock
        """)
        out_of_stock_count = cursor.fetchone()['count']

        # Expiring within 30 days
        cursor.execute("""
            SELECT COUNT(DISTINCT b.batch_id) AS count
            FROM batches b
            JOIN medicines m ON b.medicine_id = m.medicine_id
            WHERE m.is_active = 1
              AND b.quantity > 0
              AND b.expiry_date >= CURDATE()
              AND b.expiry_date <= DATE_ADD(CURDATE(), INTERVAL 30 DAY)
        """)
        expiring_count = cursor.fetchone()['count']

        # This month's revenue
        cursor.execute("""
            SELECT COALESCE(SUM(p.amount), 0) AS total
            FROM payments p
            WHERE MONTH(p.payment_date) = MONTH(CURDATE())
              AND YEAR(p.payment_date) = YEAR(CURDATE())
        """)
        monthly_revenue = cursor.fetchone()['total']

        # This month's supplier spending
        cursor.execute("""
            SELECT COALESCE(SUM(po.total_cost), 0) AS total
            FROM purchase_orders po
            WHERE po.status = 'received'
              AND MONTH(po.received_date) = MONTH(CURDATE())
              AND YEAR(po.received_date) = YEAR(CURDATE())
        """)
        monthly_spending = cursor.fetchone()['total']

        # Total prescriptions dispensed
        cursor.execute("""
            SELECT COUNT(*) AS count FROM prescriptions WHERE status = 'dispensed'
        """)
        total_dispensed = cursor.fetchone()['count']

        # Total suppliers
        cursor.execute("SELECT COUNT(*) AS count FROM suppliers WHERE is_active = 1")
        total_suppliers = cursor.fetchone()['count']

        cursor.close()
        conn.close()

        return render_template('reports/dashboard.html',
                             total_medicines=total_medicines,
                             low_stock_count=low_stock_count,
                             out_of_stock_count=out_of_stock_count,
                             expiring_count=expiring_count,
                             monthly_revenue=monthly_revenue,
                             monthly_spending=monthly_spending,
                             total_dispensed=total_dispensed,
                             total_suppliers=total_suppliers)

    except Exception as e:
        flash(f'Error loading reports: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))


# ============================================
# MONTHLY REVENUE REPORT
# URL: /reports/revenue
# Shows prescription revenue grouped by month
# ============================================
@reports_bp.route('/reports/revenue')
def revenue_report():
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Get selected year (default current year)
        selected_year = request.args.get('year', datetime.now().year, type=int)

        # Monthly revenue breakdown
        cursor.execute("""
            SELECT
                MONTH(p.payment_date) AS month_num,
                MONTHNAME(p.payment_date) AS month_name,
                COUNT(p.payment_id) AS transaction_count,
                SUM(p.amount) AS total_revenue,
                AVG(p.amount) AS avg_transaction,
                SUM(CASE WHEN p.payment_method = 'cash' THEN p.amount ELSE 0 END) AS cash_total,
                SUM(CASE WHEN p.payment_method = 'card' THEN p.amount ELSE 0 END) AS card_total,
                SUM(CASE WHEN p.payment_method = 'contactless' THEN p.amount ELSE 0 END) AS contactless_total
            FROM payments p
            WHERE YEAR(p.payment_date) = %s
            GROUP BY MONTH(p.payment_date), MONTHNAME(p.payment_date)
            ORDER BY MONTH(p.payment_date)
        """, (selected_year,))
        monthly_data = cursor.fetchall()

        # Yearly totals
        cursor.execute("""
            SELECT
                COALESCE(SUM(p.amount), 0) AS yearly_total,
                COUNT(p.payment_id) AS yearly_transactions
            FROM payments p
            WHERE YEAR(p.payment_date) = %s
        """, (selected_year,))
        yearly_totals = cursor.fetchone()

        # Get available years for the dropdown
        cursor.execute("""
            SELECT DISTINCT YEAR(payment_date) AS yr
            FROM payments
            ORDER BY yr DESC
        """)
        available_years = [row['yr'] for row in cursor.fetchall()]
        if selected_year not in available_years:
            available_years.append(selected_year)
            available_years.sort(reverse=True)

        # Recent transactions
        cursor.execute("""
            SELECT p.*, pr.patient_name, pr.prescription_id,
                   u.full_name AS processed_by_name
            FROM payments p
            JOIN dispensing_records dr ON p.dispensing_id = dr.dispensing_id
            JOIN prescriptions pr ON dr.prescription_id = pr.prescription_id
            JOIN users u ON p.processed_by = u.user_id
            WHERE YEAR(p.payment_date) = %s
            ORDER BY p.payment_date DESC
            LIMIT 20
        """, (selected_year,))
        recent_transactions = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('reports/revenue.html',
                             monthly_data=monthly_data,
                             yearly_totals=yearly_totals,
                             selected_year=selected_year,
                             available_years=available_years,
                             recent_transactions=recent_transactions)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('reports.reports_dashboard'))


# ============================================
# MONTHLY SUPPLIER SPENDING REPORT
# URL: /reports/spending
# Shows purchase order spending grouped by month and supplier
# ============================================
@reports_bp.route('/reports/spending')
def spending_report():
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        selected_year = request.args.get('year', datetime.now().year, type=int)

        # Monthly spending breakdown
        cursor.execute("""
            SELECT
                MONTH(po.received_date) AS month_num,
                MONTHNAME(po.received_date) AS month_name,
                COUNT(po.order_id) AS order_count,
                SUM(po.total_cost) AS total_spending
            FROM purchase_orders po
            WHERE po.status = 'received'
              AND YEAR(po.received_date) = %s
            GROUP BY MONTH(po.received_date), MONTHNAME(po.received_date)
            ORDER BY MONTH(po.received_date)
        """, (selected_year,))
        monthly_data = cursor.fetchall()

        # Spending by supplier
        cursor.execute("""
            SELECT
                s.name AS supplier_name,
                COUNT(po.order_id) AS order_count,
                SUM(po.total_cost) AS total_spent
            FROM purchase_orders po
            JOIN suppliers s ON po.supplier_id = s.supplier_id
            WHERE po.status = 'received'
              AND YEAR(po.received_date) = %s
            GROUP BY s.supplier_id, s.name
            ORDER BY total_spent DESC
        """, (selected_year,))
        supplier_spending = cursor.fetchall()

        # Yearly totals
        cursor.execute("""
            SELECT
                COALESCE(SUM(po.total_cost), 0) AS yearly_total,
                COUNT(po.order_id) AS yearly_orders
            FROM purchase_orders po
            WHERE po.status = 'received'
              AND YEAR(po.received_date) = %s
        """, (selected_year,))
        yearly_totals = cursor.fetchone()

        # Available years
        cursor.execute("""
            SELECT DISTINCT YEAR(received_date) AS yr
            FROM purchase_orders
            WHERE status = 'received' AND received_date IS NOT NULL
            ORDER BY yr DESC
        """)
        available_years = [row['yr'] for row in cursor.fetchall()]
        if selected_year not in available_years:
            available_years.append(selected_year)
            available_years.sort(reverse=True)

        cursor.close()
        conn.close()

        return render_template('reports/spending.html',
                             monthly_data=monthly_data,
                             supplier_spending=supplier_spending,
                             yearly_totals=yearly_totals,
                             selected_year=selected_year,
                             available_years=available_years)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('reports.reports_dashboard'))


# ============================================
# LOW STOCK REPORT
# URL: /reports/low-stock
# ============================================
@reports_bp.route('/reports/low-stock')
def low_stock_report():
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT m.*,
                   COALESCE(SUM(CASE WHEN b.expiry_date >= CURDATE() THEN b.quantity ELSE 0 END), 0) AS available_stock,
                   GROUP_CONCAT(DISTINCT s.name SEPARATOR ', ') AS supplier_names
            FROM medicines m
            LEFT JOIN batches b ON m.medicine_id = b.medicine_id
            LEFT JOIN medicine_suppliers ms ON m.medicine_id = ms.medicine_id
            LEFT JOIN suppliers s ON ms.supplier_id = s.supplier_id AND s.is_active = 1
            WHERE m.is_active = 1
            GROUP BY m.medicine_id
            HAVING available_stock <= m.low_stock_threshold
            ORDER BY available_stock ASC, m.name ASC
        """)
        medicines = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('reports/low_stock.html', medicines=medicines)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('reports.reports_dashboard'))


# ============================================
# EXPIRING MEDICINES REPORT
# URL: /reports/expiring
# ============================================
@reports_bp.route('/reports/expiring')
def expiring_report():
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        days = request.args.get('days', 30, type=int)

        # Get batches expiring within the selected period
        cursor.execute("""
            SELECT b.*, m.name AS medicine_name, m.strength, m.dosage_form,
                   DATEDIFF(b.expiry_date, CURDATE()) AS days_until_expiry
            FROM batches b
            JOIN medicines m ON b.medicine_id = m.medicine_id
            WHERE m.is_active = 1
              AND b.quantity > 0
              AND b.expiry_date >= CURDATE()
              AND b.expiry_date <= DATE_ADD(CURDATE(), INTERVAL %s DAY)
            ORDER BY b.expiry_date ASC
        """, (days,))
        expiring_batches = cursor.fetchall()

        # Also get already expired batches with remaining stock
        cursor.execute("""
            SELECT b.*, m.name AS medicine_name, m.strength, m.dosage_form,
                   DATEDIFF(CURDATE(), b.expiry_date) AS days_since_expiry
            FROM batches b
            JOIN medicines m ON b.medicine_id = m.medicine_id
            WHERE m.is_active = 1
              AND b.quantity > 0
              AND b.expiry_date < CURDATE()
            ORDER BY b.expiry_date DESC
        """)
        expired_batches = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('reports/expiring.html',
                             expiring_batches=expiring_batches,
                             expired_batches=expired_batches,
                             selected_days=days)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('reports.reports_dashboard'))