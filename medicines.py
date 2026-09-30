# ============================================
# medicines.py - Medicine & Batch Management Routes
# Blueprint for all medicine-related functionality
# Only accessible by Pharmacy Manager 
# ============================================

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import datetime, date

# --- Create the Blueprint ---

medicines_bp = Blueprint('medicines', __name__)


def get_db():
    """Get database connection - imported here to avoid circular imports"""
    from app import get_db_connection
    return get_db_connection()

def manager_check():
    """Quick check if current user is a manager"""
    from app import manager_required
    return manager_required

def audit(user_id, action_type, table_name, record_id, details):
    """Log to audit trail"""
    from app import log_audit
    log_audit(user_id, action_type, table_name, record_id, details)


# ============================================
# LIST ALL MEDICINES
# URL: /medicines
# Shows a table of all active medicines with stock info
# ============================================
@medicines_bp.route('/medicines')
def list_medicines():
    # --- Check access: must be logged in as manager ---
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # --- Get search/filter parameters from the URL query string ---
        # e.g., /medicines?search=paracetamol&type=Analgesic

        search = request.args.get('search', '').strip()
        med_type = request.args.get('type', '').strip()

        # --- Build the query ---
        # use a LEFT JOIN to get total stock from batches
        # SUM(b.quantity) adds up all batch quantities for each medicine
        # COALESCE returns 0 if there are no batches (instead of NULL)
        query = """
            SELECT m.*,
                   COALESCE(SUM(b.quantity), 0) AS total_stock,
                   MIN(CASE WHEN b.expiry_date >= CURDATE() THEN b.expiry_date END) AS nearest_expiry
            FROM medicines m
            LEFT JOIN batches b ON m.medicine_id = b.medicine_id
            WHERE m.is_active = 1
        """
        params = []

        # --- Apply search filter if provided ---
        if search:
            query += " AND (m.name LIKE %s OR m.type LIKE %s OR m.strength LIKE %s)"
            search_param = f'%{search}%'
            params.extend([search_param, search_param, search_param])

        # --- Apply type filter if provided ---
        if med_type:
            query += " AND m.type = %s"
            params.append(med_type)

        query += " GROUP BY m.medicine_id ORDER BY m.name"

        cursor.execute(query, params)
        medicines = cursor.fetchall()

        # --- Get distinct types for the filter dropdown ---
        cursor.execute("SELECT DISTINCT type FROM medicines WHERE is_active = 1 ORDER BY type")
        types = [row['type'] for row in cursor.fetchall()]

        cursor.close()
        conn.close()

        return render_template('medicines/list.html',
                             medicines=medicines,
                             types=types,
                             search=search,
                             selected_type=med_type)

    except Exception as e:
        flash(f'Error loading medicines: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))


# ============================================
# ADD NEW MEDICINE
# URL: /medicines/add
# GET = show the form, POST = process the form
# ============================================
@medicines_bp.route('/medicines/add', methods=['GET', 'POST'])
def add_medicine():
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        # --- Get form data ---
        name = request.form.get('name', '').strip()
        med_type = request.form.get('type', '').strip()
        strength = request.form.get('strength', '').strip()
        dosage_form = request.form.get('dosage_form', '').strip()
        low_stock_threshold = request.form.get('low_stock_threshold', '10').strip()
        selling_price = request.form.get('selling_price', '0').strip()
        description = request.form.get('description', '').strip()

        # --- Validation ---
        # We check each field and collect errors
        errors = []
        if not name:
            errors.append('Medicine name is required.')
        if not med_type:
            errors.append('Medicine type is required.')
        if not strength:
            errors.append('Strength is required.')
        if not dosage_form:
            errors.append('Dosage form is required.')
        try:
            low_stock_threshold = int(low_stock_threshold)
            if low_stock_threshold < 0:
                errors.append('Low stock threshold must be a positive number.')
        except ValueError:
            errors.append('Low stock threshold must be a valid number.')
        try:
                selling_price = float(selling_price)
                if selling_price < 0:
                    errors.append('Selling price cannot be negative.')

        except ValueError:
            errors.append('Selling price must be a valid number.')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('medicines/add.html')

        try:
            conn = get_db()
            cursor = conn.cursor()

            # --- Check for duplicate medicine ---
            # Same name + strength + dosage form = duplicate
            cursor.execute(
                """SELECT medicine_id FROM medicines
                   WHERE name = %s AND strength = %s AND dosage_form = %s AND is_active = 1""",
                (name, strength, dosage_form)
            )
            if cursor.fetchone():
                flash('A medicine with this name, strength, and dosage form already exists.', 'warning')
                cursor.close()
                conn.close()
                return render_template('medicines/add.html')

            # --- Insert the medicine ---
            cursor.execute(
                """INSERT INTO medicines (name, type, strength, dosage_form, low_stock_threshold, selling_price, description)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (name, med_type, strength, dosage_form, low_stock_threshold, selling_price, description)
            )
            conn.commit()
            medicine_id = cursor.lastrowid

            # --- Log to audit trail ---
            audit(session['user_id'], 'MEDICINE_ADDED', 'medicines', medicine_id,
                  f"Added medicine: {name} {strength} {dosage_form}")

            cursor.close()
            conn.close()

            flash(f'Medicine "{name}" added successfully!', 'success')
            return redirect(url_for('medicines.list_medicines'))

        except Exception as e:
            flash(f'Error adding medicine: {str(e)}', 'danger')
            return render_template('medicines/add.html')

    # GET request - show empty form
    return render_template('medicines/add.html')


# ============================================
# EDIT MEDICINE
# URL: /medicines/edit/<id>
# The <int:medicine_id> part captures the ID from the URL
# ============================================
@medicines_bp.route('/medicines/edit/<int:medicine_id>', methods=['GET', 'POST'])
def edit_medicine(medicine_id):
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            med_type = request.form.get('type', '').strip()
            strength = request.form.get('strength', '').strip()
            dosage_form = request.form.get('dosage_form', '').strip()
            low_stock_threshold = request.form.get('low_stock_threshold', '10').strip()
            selling_price = request.form.get('selling_price', '0').strip()
            description = request.form.get('description', '').strip()

            # --- Validation ---
            errors = []
            if not name:
                errors.append('Medicine name is required.')
            if not med_type:
                errors.append('Medicine type is required.')
            if not strength:
                errors.append('Strength is required.')
            if not dosage_form:
                errors.append('Dosage form is required.')
            try:
                low_stock_threshold = int(low_stock_threshold)
                if low_stock_threshold < 0:
                    errors.append('Low stock threshold must be a positive number.')
            except ValueError:
                errors.append('Low stock threshold must be a valid number.')
            try:
                selling_price = float(selling_price)
                if selling_price < 0:
                    errors.append('Selling price cannot be negative.')
            except ValueError:
                errors.append('Selling price must be a valid number.')

            if errors:
                for error in errors:
                    flash(error, 'danger')
                cursor.execute("SELECT * FROM medicines WHERE medicine_id = %s", (medicine_id,))
                medicine = cursor.fetchone()
                cursor.close()
                conn.close()
                return render_template('medicines/edit.html', medicine=medicine)

            # --- Check for duplicate (excluding current) ---
            cursor.execute(
                """SELECT medicine_id FROM medicines
                   WHERE name = %s AND strength = %s AND dosage_form = %s
                   AND is_active = 1 AND medicine_id != %s""",
                (name, strength, dosage_form, medicine_id)
            )
            duplicate = cursor.fetchone()

            if duplicate:
                flash('Another medicine with this name, strength, and dosage form already exists.', 'warning')
                cursor.execute("SELECT * FROM medicines WHERE medicine_id = %s", (medicine_id,))
                medicine = cursor.fetchone()
                cursor.close()
                conn.close()
                return render_template('medicines/edit.html', medicine=medicine)

            # --- Close old cursor, open fresh one for update ---
            cursor.close()
            cursor = conn.cursor(dictionary=True)

            cursor.execute(
                """UPDATE medicines
                   SET name = %s, type = %s, strength = %s, dosage_form = %s,
                       low_stock_threshold = %s, selling_price = %s, description = %s
                   WHERE medicine_id = %s""",
                (name, med_type, strength, dosage_form, low_stock_threshold, selling_price, description, medicine_id)
            )
            conn.commit()

            audit(session['user_id'], 'MEDICINE_UPDATED', 'medicines', medicine_id,
                  f"Updated medicine: {name} {strength} {dosage_form}")

            cursor.close()
            conn.close()

            flash(f'Medicine "{name}" updated successfully!', 'success')
            return redirect(url_for('medicines.list_medicines'))

        # --- GET request - load medicine data into form ---
        cursor.execute("SELECT * FROM medicines WHERE medicine_id = %s AND is_active = 1", (medicine_id,))
        medicine = cursor.fetchone()

        if not medicine:
            flash('Medicine not found.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('medicines.list_medicines'))

        cursor.close()
        conn.close()
        return render_template('medicines/edit.html', medicine=medicine)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('medicines.list_medicines'))
    
    
# ============================================
# DELETE MEDICINE (Soft Delete)
# We don't actually delete - we set is_active = 0
# This preserves data integrity for historical records
# ============================================
@medicines_bp.route('/medicines/delete/<int:medicine_id>', methods=['POST'])
def delete_medicine(medicine_id):
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Get medicine name for the audit log
        cursor.execute("SELECT name FROM medicines WHERE medicine_id = %s", (medicine_id,))
        medicine = cursor.fetchone()

        if medicine:
            cursor.execute("UPDATE medicines SET is_active = 0 WHERE medicine_id = %s", (medicine_id,))
            conn.commit()

            audit(session['user_id'], 'MEDICINE_DELETED', 'medicines', medicine_id,
                  f"Deactivated medicine: {medicine['name']}")

            flash(f'Medicine "{medicine["name"]}" has been removed.', 'success')
        else:
            flash('Medicine not found.', 'danger')

        cursor.close()
        conn.close()

    except Exception as e:
        flash(f'Error deleting medicine: {str(e)}', 'danger')

    return redirect(url_for('medicines.list_medicines'))


# ============================================
# VIEW MEDICINE DETAILS & BATCHES
# Shows full medicine info plus all its batches
# ============================================
@medicines_bp.route('/medicines/<int:medicine_id>')
def view_medicine(medicine_id):
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Get medicine details
        cursor.execute("SELECT * FROM medicines WHERE medicine_id = %s AND is_active = 1", (medicine_id,))
        medicine = cursor.fetchone()

        if not medicine:
            flash('Medicine not found.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('medicines.list_medicines'))

        # Get all batches for this medicine
        cursor.execute(
            """SELECT *,
                      CASE
                          WHEN expiry_date < CURDATE() THEN 'expired'
                          WHEN expiry_date <= DATE_ADD(CURDATE(), INTERVAL 30 DAY) THEN 'expiring_soon'
                          ELSE 'valid'
                      END AS expiry_status
               FROM batches
               WHERE medicine_id = %s
               ORDER BY expiry_date ASC""",
            (medicine_id,)
        )
        batches = cursor.fetchall()

        # Calculate total stock (only from non-expired batches)
        total_stock = sum(b['quantity'] for b in batches if b['expiry_status'] != 'expired')

        # Get linked suppliers
        cursor.execute(
            """SELECT s.*, ms.unit_cost
               FROM medicine_suppliers ms
               JOIN suppliers s ON ms.supplier_id = s.supplier_id
               WHERE ms.medicine_id = %s AND s.is_active = 1""",
            (medicine_id,)
        )
        suppliers = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('medicines/view.html',
                             medicine=medicine,
                             batches=batches,
                             total_stock=total_stock,
                             suppliers=suppliers)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('medicines.list_medicines'))


# ============================================
# ADD BATCH TO MEDICINE
# URL: /medicines/<id>/add-batch
# ============================================
@medicines_bp.route('/medicines/<int:medicine_id>/add-batch', methods=['GET', 'POST'])
def add_batch(medicine_id):
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Get the medicine
        cursor.execute("SELECT * FROM medicines WHERE medicine_id = %s AND is_active = 1", (medicine_id,))
        medicine = cursor.fetchone()

        if not medicine:
            flash('Medicine not found.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('medicines.list_medicines'))

        if request.method == 'POST':
            batch_number = request.form.get('batch_number', '').strip()
            expiry_date = request.form.get('expiry_date', '').strip()
            quantity = request.form.get('quantity', '0').strip()
            date_received = request.form.get('date_received', '').strip()

            # --- Validation ---
            errors = []
            if not batch_number:
                errors.append('Batch number is required.')
            if not expiry_date:
                errors.append('Expiry date is required.')
            if not date_received:
                errors.append('Date received is required.')

            try:
                quantity = int(quantity)
                if quantity <= 0:
                    errors.append('Quantity must be a positive number.')
            except ValueError:
                errors.append('Quantity must be a valid number.')

            # Check expiry date is in the future
            if expiry_date:
                try:
                    exp_date = datetime.strptime(expiry_date, '%Y-%m-%d').date()
                    if exp_date <= date.today():
                        errors.append('Expiry date must be in the future.')
                except ValueError:
                    errors.append('Invalid expiry date format.')

            if errors:
                for error in errors:
                    flash(error, 'danger')
                cursor.close()
                conn.close()
                return render_template('medicines/add_batch.html', medicine=medicine)

            # --- Check for duplicate batch number for this medicine ---
            cursor.execute(
                """SELECT batch_id FROM batches
                   WHERE medicine_id = %s AND batch_number = %s""",
                (medicine_id, batch_number)
            )
            if cursor.fetchone():
                flash(f'Batch number "{batch_number}" already exists for this medicine.', 'warning')
                cursor.close()
                conn.close()
                return render_template('medicines/add_batch.html', medicine=medicine)

            # --- Insert the batch ---
            cursor.execute(
                """INSERT INTO batches (medicine_id, batch_number, expiry_date, quantity, date_received)
                   VALUES (%s, %s, %s, %s, %s)""",
                (medicine_id, batch_number, expiry_date, quantity, date_received)
            )
            conn.commit()
            batch_id = cursor.lastrowid

            # --- Log to audit trail ---
            audit(session['user_id'], 'STOCK_IN', 'batches', batch_id,
                  f"Added batch {batch_number} for {medicine['name']}: qty {quantity}, expires {expiry_date}")

            cursor.close()
            conn.close()

            flash(f'Batch "{batch_number}" added successfully with {quantity} units!', 'success')
            return redirect(url_for('medicines.view_medicine', medicine_id=medicine_id))

        cursor.close()
        conn.close()
        return render_template('medicines/add_batch.html', medicine=medicine)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('medicines.view_medicine', medicine_id=medicine_id))


# ============================================
# STOCK OVERVIEW
# Shows all medicines with their total stock,
# flags low stock and expiring medicines
# ============================================
@medicines_bp.route('/medicines/stock')
def stock_overview():
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Get filter from URL
        stock_filter = request.args.get('filter', 'all')

        # --- Main stock query ---
        query = """
            SELECT m.*,
                   COALESCE(SUM(CASE WHEN b.expiry_date >= CURDATE() THEN b.quantity ELSE 0 END), 0) AS available_stock,
                   COALESCE(SUM(CASE WHEN b.expiry_date < CURDATE() THEN b.quantity ELSE 0 END), 0) AS expired_stock,
                   MIN(CASE WHEN b.expiry_date >= CURDATE() THEN b.expiry_date END) AS nearest_expiry
            FROM medicines m
            LEFT JOIN batches b ON m.medicine_id = b.medicine_id
            WHERE m.is_active = 1
            GROUP BY m.medicine_id
        """

        # --- Apply filters ---
        if stock_filter == 'low':
            query += " HAVING available_stock <= m.low_stock_threshold AND available_stock > 0"
        elif stock_filter == 'out':
            query += " HAVING available_stock = 0"
        elif stock_filter == 'expiring':
            query += " HAVING nearest_expiry <= DATE_ADD(CURDATE(), INTERVAL 30 DAY)"

        query += " ORDER BY m.name"

        cursor.execute(query)
        medicines = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('medicines/stock.html',
                             medicines=medicines,
                             current_filter=stock_filter)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))