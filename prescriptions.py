# ============================================
# prescriptions.py - Prescription Management Routes
# Blueprint for all prescription functionality
# Accessible by Pharmacy Staff 
# ============================================

from flask import Blueprint, render_template, request, redirect, url_for, flash, session

prescriptions_bp = Blueprint('prescriptions', __name__)

def get_db():
    from app import get_db_connection
    return get_db_connection()

def audit(user_id, action_type, table_name, record_id, details):
    from app import log_audit
    log_audit(user_id, action_type, table_name, record_id, details)


# ============================================
# LIST ALL PRESCRIPTIONS
# URL: /prescriptions
# Staff see all prescriptions (they need to dispense any of them)
# ============================================
@prescriptions_bp.route('/prescriptions')
def list_prescriptions():
    if 'user_id' not in session or session.get('role') != 'staff':
        flash('Access denied. Staff privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Get filters
        status_filter = request.args.get('status', 'all')
        search = request.args.get('search', '').strip()

        query = """
            SELECT p.*,
                   u.full_name AS created_by_name,
                   COUNT(pi.item_id) AS item_count
            FROM prescriptions p
            JOIN users u ON p.created_by = u.user_id
            LEFT JOIN prescription_items pi ON p.prescription_id = pi.prescription_id
            WHERE 1=1
        """
        params = []

        if status_filter != 'all':
            query += " AND p.status = %s"
            params.append(status_filter)

        if search:
            query += " AND (p.patient_name LIKE %s OR p.doctor_name LIKE %s)"
            search_param = f'%{search}%'
            params.extend([search_param, search_param])

        query += " GROUP BY p.prescription_id ORDER BY p.prescription_date DESC"

        cursor.execute(query, params)
        prescriptions = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('prescriptions/list.html',
                             prescriptions=prescriptions,
                             current_status=status_filter,
                             search=search)

    except Exception as e:
        flash(f'Error loading prescriptions: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))


# ============================================
# CREATE NEW PRESCRIPTION
# URL: /prescriptions/create
# Step 1: Enter patient and doctor details
# ============================================
@prescriptions_bp.route('/prescriptions/create', methods=['GET', 'POST'])
def create_prescription():
    if 'user_id' not in session or session.get('role') != 'staff':
        flash('Access denied. Staff privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        patient_name = request.form.get('patient_name', '').strip()
        patient_dob = request.form.get('patient_dob', '').strip()
        patient_address = request.form.get('patient_address', '').strip()
        doctor_name = request.form.get('doctor_name', '').strip()
        doctor_registration = request.form.get('doctor_registration', '').strip()
        notes = request.form.get('notes', '').strip()

        # --- Validation ---
        errors = []
        if not patient_name:
            errors.append('Patient name is required.')
        if not doctor_name:
            errors.append('Doctor name is required.')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('prescriptions/create.html')

        try:
            conn = get_db()
            cursor = conn.cursor()

            cursor.execute(
                """INSERT INTO prescriptions
                   (patient_name, patient_dob, patient_address, doctor_name,
                    doctor_registration, created_by, notes)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (patient_name,
                 patient_dob or None,
                 patient_address or None,
                 doctor_name,
                 doctor_registration or None,
                 session['user_id'],
                 notes or None)
            )
            conn.commit()
            prescription_id = cursor.lastrowid

            audit(session['user_id'], 'PRESCRIPTION_CREATED', 'prescriptions', prescription_id,
                  f"Created prescription for patient {patient_name} by Dr. {doctor_name}")

            cursor.close()
            conn.close()

            flash(f'Prescription created! Now add medicines to it.', 'success')
            return redirect(url_for('prescriptions.view_prescription', prescription_id=prescription_id))

        except Exception as e:
            flash(f'Error creating prescription: {str(e)}', 'danger')
            return render_template('prescriptions/create.html')

    return render_template('prescriptions/create.html')


# ============================================
# VIEW PRESCRIPTION DETAILS
# URL: /prescriptions/<id>
# Shows patient info, doctor info, and all items
# ============================================
@prescriptions_bp.route('/prescriptions/<int:prescription_id>')
def view_prescription(prescription_id):
    if 'user_id' not in session or session.get('role') != 'staff':
        flash('Access denied. Staff privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Get prescription details
        cursor.execute(
            """SELECT p.*, u.full_name AS created_by_name
               FROM prescriptions p
               JOIN users u ON p.created_by = u.user_id
               WHERE p.prescription_id = %s""",
            (prescription_id,)
        )
        prescription = cursor.fetchone()

        if not prescription:
            flash('Prescription not found.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('prescriptions.list_prescriptions'))

        # Get prescription items with medicine details and available stock
        cursor.execute(
            """SELECT pi.*, m.name AS medicine_name, m.strength, m.dosage_form,
                      m.selling_price,
                      COALESCE(SUM(
                          CASE WHEN b.expiry_date >= CURDATE() THEN b.quantity ELSE 0 END
                      ), 0) AS available_stock
               FROM prescription_items pi
               JOIN medicines m ON pi.medicine_id = m.medicine_id
               LEFT JOIN batches b ON m.medicine_id = b.medicine_id
               WHERE pi.prescription_id = %s
               GROUP BY pi.item_id""",
            (prescription_id,)
        )
        items = cursor.fetchall()

        # Get available medicines for adding items (only if prescription is 'created')
        available_medicines = []
        if prescription['status'] == 'created':
            existing_medicine_ids = [item['medicine_id'] for item in items]

            query = "SELECT * FROM medicines WHERE is_active = 1"
            if existing_medicine_ids:
                placeholders = ','.join(['%s'] * len(existing_medicine_ids))
                query += f" AND medicine_id NOT IN ({placeholders})"
            query += " ORDER BY name"

            cursor.execute(query, existing_medicine_ids if existing_medicine_ids else ())
            available_medicines = cursor.fetchall()

        # Check if prescription can be dispensed
        # All items must have sufficient non-expired stock
        can_dispense = (prescription['status'] == 'created' and len(items) > 0)
        dispense_warnings = []

        for item in items:
            if item['available_stock'] < item['quantity']:
                can_dispense = False
                dispense_warnings.append(
                    f"{item['medicine_name']}: Need {item['quantity']}, only {item['available_stock']} available"
                )

        cursor.close()
        conn.close()

        return render_template('prescriptions/view.html',
                             prescription=prescription,
                             items=items,
                             available_medicines=available_medicines,
                             can_dispense=can_dispense,
                             dispense_warnings=dispense_warnings)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('prescriptions.list_prescriptions'))


# ============================================
# ADD ITEM TO PRESCRIPTION
# URL: /prescriptions/<id>/add-item
# ============================================
@prescriptions_bp.route('/prescriptions/<int:prescription_id>/add-item', methods=['POST'])
def add_prescription_item(prescription_id):
    if 'user_id' not in session or session.get('role') != 'staff':
        flash('Access denied. Staff privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    medicine_id = request.form.get('medicine_id')
    quantity = request.form.get('quantity', '0').strip()
    dosage_instructions = request.form.get('dosage_instructions', '').strip()

    # --- Validation ---
    errors = []
    if not medicine_id:
        errors.append('Please select a medicine.')

    try:
        quantity = int(quantity)
        if quantity <= 0:
            errors.append('Quantity must be a positive number.')
    except ValueError:
        errors.append('Quantity must be a valid number.')

    if errors:
        for error in errors:
            flash(error, 'danger')
        return redirect(url_for('prescriptions.view_prescription', prescription_id=prescription_id))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Verify prescription exists and is in 'created' status
        cursor.execute(
            "SELECT status FROM prescriptions WHERE prescription_id = %s",
            (prescription_id,)
        )
        prescription = cursor.fetchone()

        if not prescription or prescription['status'] != 'created':
            flash('Cannot modify this prescription.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('prescriptions.view_prescription', prescription_id=prescription_id))

        # Check medicine isn't already in this prescription
        cursor.execute(
            """SELECT item_id FROM prescription_items
               WHERE prescription_id = %s AND medicine_id = %s""",
            (prescription_id, medicine_id)
        )
        if cursor.fetchone():
            flash('This medicine is already in the prescription.', 'warning')
            cursor.close()
            conn.close()
            return redirect(url_for('prescriptions.view_prescription', prescription_id=prescription_id))

        # Add the item
        cursor.execute(
            """INSERT INTO prescription_items (prescription_id, medicine_id, quantity, dosage_instructions)
               VALUES (%s, %s, %s, %s)""",
            (prescription_id, medicine_id, quantity, dosage_instructions or None)
        )
        conn.commit()

        # Get medicine name for message
        cursor.execute("SELECT name FROM medicines WHERE medicine_id = %s", (medicine_id,))
        med = cursor.fetchone()

        audit(session['user_id'], 'PRESCRIPTION_ITEM_ADDED', 'prescription_items', cursor.lastrowid,
              f"Added {med['name']} (qty: {quantity}) to prescription #{prescription_id}")

        cursor.close()
        conn.close()

        flash(f'{med["name"]} added to prescription!', 'success')

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')

    return redirect(url_for('prescriptions.view_prescription', prescription_id=prescription_id))


# ============================================
# REMOVE ITEM FROM PRESCRIPTION
# ============================================
@prescriptions_bp.route('/prescriptions/remove-item/<int:item_id>', methods=['POST'])
def remove_prescription_item(item_id):
    if 'user_id' not in session or session.get('role') != 'staff':
        flash('Access denied. Staff privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Get item details
        cursor.execute(
            """SELECT pi.*, p.status, p.prescription_id, m.name AS medicine_name
               FROM prescription_items pi
               JOIN prescriptions p ON pi.prescription_id = p.prescription_id
               JOIN medicines m ON pi.medicine_id = m.medicine_id
               WHERE pi.item_id = %s""",
            (item_id,)
        )
        item = cursor.fetchone()

        if not item:
            flash('Item not found.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('prescriptions.list_prescriptions'))

        if item['status'] != 'created':
            flash('Cannot modify a dispensed or cancelled prescription.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('prescriptions.view_prescription',
                                   prescription_id=item['prescription_id']))

        prescription_id = item['prescription_id']

        cursor.execute("DELETE FROM prescription_items WHERE item_id = %s", (item_id,))
        conn.commit()

        audit(session['user_id'], 'PRESCRIPTION_ITEM_REMOVED', 'prescription_items', item_id,
              f"Removed {item['medicine_name']} from prescription #{prescription_id}")

        cursor.close()
        conn.close()

        flash(f'{item["medicine_name"]} removed from prescription.', 'success')
        return redirect(url_for('prescriptions.view_prescription', prescription_id=prescription_id))

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('prescriptions.list_prescriptions'))


# ============================================
# CANCEL PRESCRIPTION
# ============================================
@prescriptions_bp.route('/prescriptions/<int:prescription_id>/cancel', methods=['POST'])
def cancel_prescription(prescription_id):
    if 'user_id' not in session or session.get('role') != 'staff':
        flash('Access denied. Staff privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT status, patient_name FROM prescriptions WHERE prescription_id = %s",
            (prescription_id,)
        )
        prescription = cursor.fetchone()

        if not prescription:
            flash('Prescription not found.', 'danger')
        elif prescription['status'] != 'created':
            flash('Only prescriptions with "created" status can be cancelled.', 'warning')
        else:
            cursor.execute(
                "UPDATE prescriptions SET status = 'cancelled' WHERE prescription_id = %s",
                (prescription_id,)
            )
            conn.commit()

            audit(session['user_id'], 'PRESCRIPTION_CANCELLED', 'prescriptions', prescription_id,
                  f"Cancelled prescription for {prescription['patient_name']}")

            flash('Prescription has been cancelled.', 'success')

        cursor.close()
        conn.close()

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')

    return redirect(url_for('prescriptions.view_prescription', prescription_id=prescription_id))