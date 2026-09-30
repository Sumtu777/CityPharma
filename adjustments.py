# ============================================
# adjustments.py - Stock Adjustments & Audit Trail Routes
# Blueprint for stock adjustments and activity history
# ============================================

from flask import Blueprint, render_template, request, redirect, url_for, flash, session

adjustments_bp = Blueprint('adjustments', __name__)

def get_db():
    from app import get_db_connection
    return get_db_connection()

def audit(user_id, action_type, table_name, record_id, details):
    from app import log_audit
    log_audit(user_id, action_type, table_name, record_id, details)


# ============================================
# STOCK ADJUSTMENTS PAGE
# URL: /adjustments
# Shows form to make adjustments and history of past adjustments
# Accessible by both Manager and Staff
# ============================================

@adjustments_bp.route('/adjustments')
def list_adjustments():
    if 'user_id' not in session:
        flash('Please log in to access this page.', 'warning')
        return redirect(url_for('login'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Get past adjustments
        query = """
            SELECT sa.*,
                   b.batch_number, b.expiry_date,
                   m.name AS medicine_name, m.strength, m.dosage_form,
                   u.full_name AS adjusted_by_name
            FROM stock_adjustments sa
            JOIN batches b ON sa.batch_id = b.batch_id
            JOIN medicines m ON b.medicine_id = m.medicine_id
            JOIN users u ON sa.adjusted_by = u.user_id
            ORDER BY sa.adjustment_date DESC
            LIMIT 50
        """
        cursor.execute(query)
        adjustments = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('adjustments/list.html', adjustments=adjustments)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))


# ============================================
# CREATE NEW STOCK ADJUSTMENT
# URL: /adjustments/new
# Step 1: Select medicine, then batch
# Step 2: Enter adjustment details
# ============================================

@adjustments_bp.route('/adjustments/new', methods=['GET', 'POST'])
def new_adjustment():
    if 'user_id' not in session:
        flash('Please log in to access this page.', 'warning')
        return redirect(url_for('login'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            batch_id = request.form.get('batch_id')
            adjustment_type = request.form.get('adjustment_type', '').strip()
            quantity = request.form.get('quantity', '0').strip()
            reason = request.form.get('reason', '').strip()

            # --- Validation ---
            errors = []
            if not batch_id:
                errors.append('Please select a batch.')
            if adjustment_type not in ['increase', 'decrease']:
                errors.append('Please select a valid adjustment type.')
            if not reason:
                errors.append('A reason is required for every stock adjustment.')

            try:
                quantity = int(quantity)
                if quantity <= 0:
                    errors.append('Quantity must be a positive number.')
            except ValueError:
                errors.append('Quantity must be a valid number.')

            if errors:
                for error in errors:
                    flash(error, 'danger')
                # Reload page with medicines
                cursor.execute(
                    """SELECT m.medicine_id, m.name, m.strength, m.dosage_form
                       FROM medicines m WHERE m.is_active = 1 ORDER BY m.name"""
                )
                medicines = cursor.fetchall()
                cursor.close()
                conn.close()
                return render_template('adjustments/new.html', medicines=medicines)

            # Get batch details
            cursor.execute(
                """SELECT b.*, m.name AS medicine_name, m.strength, m.dosage_form
                   FROM batches b
                   JOIN medicines m ON b.medicine_id = m.medicine_id
                   WHERE b.batch_id = %s""",
                (batch_id,)
            )
            batch = cursor.fetchone()

            if not batch:
                flash('Batch not found.', 'danger')
                cursor.close()
                conn.close()
                return redirect(url_for('adjustments.new_adjustment'))

            # Check if decrease would make stock negative
            if adjustment_type == 'decrease' and quantity > batch['quantity']:
                flash(f'Cannot decrease by {quantity}. Current batch stock is only {batch["quantity"]}.', 'danger')
                cursor.execute(
                    """SELECT m.medicine_id, m.name, m.strength, m.dosage_form
                       FROM medicines m WHERE m.is_active = 1 ORDER BY m.name"""
                )
                medicines = cursor.fetchall()
                cursor.close()
                conn.close()
                return render_template('adjustments/new.html', medicines=medicines)

            # --- Perform the adjustment ---
            if adjustment_type == 'increase':
                new_quantity = batch['quantity'] + quantity
            else:
                new_quantity = batch['quantity'] - quantity

            # Update batch quantity
            cursor.execute(
                "UPDATE batches SET quantity = %s WHERE batch_id = %s",
                (new_quantity, batch_id)
            )

            # Record the adjustment
            cursor.execute(
                """INSERT INTO stock_adjustments
                   (batch_id, adjusted_by, adjustment_type, quantity, reason)
                   VALUES (%s, %s, %s, %s, %s)""",
                (batch_id, session['user_id'], adjustment_type, quantity, reason)
            )
            adjustment_id = cursor.lastrowid

            conn.commit()

            # Audit trail
            audit(session['user_id'], 'ADJUSTMENT', 'batches', int(batch_id),
                  f"Stock adjustment ({adjustment_type}) for {batch['medicine_name']} "
                  f"Batch {batch['batch_number']}: {batch['quantity']} → {new_quantity}. "
                  f"Reason: {reason}")

            cursor.close()
            conn.close()

            flash(f'Stock adjustment recorded successfully! '
                  f'{batch["medicine_name"]} Batch {batch["batch_number"]}: '
                  f'{batch["quantity"]} → {new_quantity}', 'success')
            return redirect(url_for('adjustments.list_adjustments'))

        # --- GET request - show form ---
        cursor.execute(
            """SELECT m.medicine_id, m.name, m.strength, m.dosage_form
               FROM medicines m WHERE m.is_active = 1 ORDER BY m.name"""
        )
        medicines = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('adjustments/new.html', medicines=medicines)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('adjustments.list_adjustments'))


# ============================================
# GET BATCHES FOR A MEDICINE (AJAX endpoint)
# URL: /adjustments/get-batches/<medicine_id>
# Called by JavaScript when user selects a medicine
# Returns batch data as HTML options
# ============================================
@adjustments_bp.route('/adjustments/get-batches/<int:medicine_id>')
def get_batches(medicine_id):
    if 'user_id' not in session:
        return '', 403

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """SELECT batch_id, batch_number, quantity, expiry_date,
                      CASE
                          WHEN expiry_date < CURDATE() THEN 'EXPIRED'
                          WHEN expiry_date <= DATE_ADD(CURDATE(), INTERVAL 30 DAY) THEN 'EXPIRING SOON'
                          ELSE 'Valid'
                      END AS status
               FROM batches
               WHERE medicine_id = %s
               ORDER BY expiry_date ASC""",
            (medicine_id,)
        )
        batches = cursor.fetchall()

        cursor.close()
        conn.close()

        # Build HTML options to return
        html = '<option value="">Select batch...</option>'
        for batch in batches:
            exp_date = batch['expiry_date'].strftime('%d/%m/%Y')
            label = (f"Batch {batch['batch_number']} | "
                    f"Qty: {batch['quantity']} | "
                    f"Exp: {exp_date} | "
                    f"{batch['status']}")
            html += f'<option value="{batch["batch_id"]}">{label}</option>'

        return html

    except Exception as e:
        return f'<option value="">Error loading batches: {str(e)}</option>'


# ============================================
# MY ACTIVITY HISTORY
# URL: /activity
# Staff can view their own activity from audit trail
# Manager can see all activity
# ============================================
@adjustments_bp.route('/activity')
def activity_history():
    if 'user_id' not in session:
        flash('Please log in to access this page.', 'warning')
        return redirect(url_for('login'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Get filter parameters
        action_filter = request.args.get('action', 'all')
        search = request.args.get('search', '').strip()
        view_mode = request.args.get('view', 'mine')

        # Base query
        query = """
            SELECT at.*,
                   u.full_name AS user_name, u.role AS user_role
            FROM audit_trail at
            LEFT JOIN users u ON at.user_id = u.user_id
            WHERE 1=1
        """
        params = []

        # Staff can only see their own activity
        # Manager can toggle between 'mine' and 'all'
        if session.get('role') == 'staff' or view_mode == 'mine':
            query += " AND at.user_id = %s"
            params.append(session['user_id'])

        # Action type filter
        if action_filter != 'all':
            query += " AND at.action_type = %s"
            params.append(action_filter)

        # Search filter
        if search:
            query += " AND (at.details LIKE %s OR at.action_type LIKE %s OR at.table_name LIKE %s)"
            search_param = f'%{search}%'
            params.extend([search_param, search_param, search_param])

        query += " ORDER BY at.action_date DESC LIMIT 100"

        cursor.execute(query, params)
        activities = cursor.fetchall()

        # Get distinct action types for the filter dropdown
        if session.get('role') == 'staff':
            cursor.execute(
                "SELECT DISTINCT action_type FROM audit_trail WHERE user_id = %s ORDER BY action_type",
                (session['user_id'],)
            )
        else:
            cursor.execute("SELECT DISTINCT action_type FROM audit_trail ORDER BY action_type")

        action_types = [row['action_type'] for row in cursor.fetchall()]

        cursor.close()
        conn.close()

        return render_template('adjustments/activity.html',
                             activities=activities,
                             action_types=action_types,
                             current_action=action_filter,
                             search=search,
                             view_mode=view_mode)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))

# ============================================
# RECORD PHARMACEUTICAL WASTE
# URL: /adjustments/waste
# Additional feature: Record medicines that must be destroyed
# e.g., expired, contaminated, damaged beyond use
# ============================================
@adjustments_bp.route('/adjustments/waste', methods=['GET', 'POST'])
def record_waste():
    if 'user_id' not in session:
        flash('Please log in.', 'warning')
        return redirect(url_for('login'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            batch_id = request.form.get('batch_id')
            quantity = request.form.get('quantity', '0').strip()
            reason = request.form.get('reason', '').strip()

            errors = []
            if not batch_id:
                errors.append('Please select a batch.')
            if not reason:
                errors.append('A reason is required for waste recording.')

            try:
                quantity = int(quantity)
                if quantity <= 0:
                    errors.append('Quantity must be a positive number.')
            except ValueError:
                errors.append('Quantity must be a valid number.')

            if errors:
                for error in errors:
                    flash(error, 'danger')
                cursor.execute(
                    "SELECT m.medicine_id, m.name, m.strength, m.dosage_form FROM medicines m WHERE m.is_active = 1 ORDER BY m.name"
                )
                medicines = cursor.fetchall()
                cursor.close()
                conn.close()
                return render_template('adjustments/waste.html', medicines=medicines)

            # Get batch info
            cursor.execute(
                """SELECT b.*, m.name AS medicine_name
                   FROM batches b JOIN medicines m ON b.medicine_id = m.medicine_id
                   WHERE b.batch_id = %s""",
                (batch_id,)
            )
            batch = cursor.fetchone()

            if not batch:
                flash('Batch not found.', 'danger')
                cursor.close()
                conn.close()
                return redirect(url_for('adjustments.record_waste'))

            if quantity > batch['quantity']:
                flash(f'Cannot waste {quantity} units. Only {batch["quantity"]} in stock.', 'danger')
                cursor.execute(
                    "SELECT m.medicine_id, m.name, m.strength, m.dosage_form FROM medicines m WHERE m.is_active = 1 ORDER BY m.name"
                )
                medicines = cursor.fetchall()
                cursor.close()
                conn.close()
                return render_template('adjustments/waste.html', medicines=medicines)

            # Reduce stock
            cursor.execute(
                "UPDATE batches SET quantity = quantity - %s WHERE batch_id = %s",
                (quantity, batch_id)
            )

            # Record as a decrease adjustment with waste reason
            cursor.execute(
                """INSERT INTO stock_adjustments
                   (batch_id, adjusted_by, adjustment_type, quantity, reason)
                   VALUES (%s, %s, 'decrease', %s, %s)""",
                (batch_id, session['user_id'], quantity, f"WASTE: {reason}")
            )

            conn.commit()

            audit(session['user_id'], 'WASTE_RECORDED', 'batches', int(batch_id),
                  f"Recorded waste: {quantity} units of {batch['medicine_name']} "
                  f"(Batch: {batch['batch_number']}). Reason: {reason}")

            cursor.close()
            conn.close()

            flash(f'Waste recorded: {quantity} units of {batch["medicine_name"]} removed from stock.', 'success')
            return redirect(url_for('adjustments.list_adjustments'))

        # GET - show form
        cursor.execute(
            "SELECT m.medicine_id, m.name, m.strength, m.dosage_form FROM medicines m WHERE m.is_active = 1 ORDER BY m.name"
        )
        medicines = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('adjustments/waste.html', medicines=medicines)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('adjustments.list_adjustments'))