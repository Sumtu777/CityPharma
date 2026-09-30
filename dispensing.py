# ============================================
# dispensing.py - Dispensing & Payment Routes
# Blueprint for dispensing medicines and payments
# Accessible by Pharmacy Staff 
# ============================================

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import datetime
import uuid

dispensing_bp = Blueprint('dispensing', __name__)

def get_db():
    from app import get_db_connection
    return get_db_connection()

def audit(user_id, action_type, table_name, record_id, details):
    from app import log_audit
    log_audit(user_id, action_type, table_name, record_id, details)


def generate_receipt_reference():
    """
    Generates a unique receipt reference number.
    Format: RCP-YYYYMMDD-XXXX (e.g., RCP-20260420-A3F2)
    part of a UUID for the random portion to ensure uniqueness.
    """
    date_part = datetime.now().strftime('%Y%m%d')
    unique_part = uuid.uuid4().hex[:4].upper()
    return f"RCP-{date_part}-{unique_part}"


def get_available_batches(cursor, medicine_id):
    """
    Gets all non-expired batches for a medicine, ordered by expiry date (FEFO).
    FEFO = First Expiry, First Out
    This ensures we always dispense from the batch closest to expiring first,
    which is standard pharmacy practice to minimise waste.
    """
    cursor.execute(
        """SELECT batch_id, batch_number, expiry_date, quantity
           FROM batches
           WHERE medicine_id = %s
             AND expiry_date >= CURDATE()
             AND quantity > 0
           ORDER BY expiry_date ASC""",
        (medicine_id,)
    )
    return cursor.fetchall()


def allocate_stock(cursor, medicine_id, quantity_needed):
    """
    Allocates stock from batches using FEFO (First Expiry, First Out).

    How it works:
    1. Get all valid (non-expired, in-stock) batches sorted by expiry date
    2. Take as much as needed from the first batch
    3. If that batch doesn't have enough, move to the next batch
    4. Continue until we've allocated the full quantity

    Returns:
        list of dicts: [{batch_id, batch_number, quantity_to_take}, ...]
        or None if insufficient stock
    """
    batches = get_available_batches(cursor, medicine_id)

    total_available = sum(b['quantity'] for b in batches)
    if total_available < quantity_needed:
        return None  # Not enough stock

    allocations = []
    remaining = quantity_needed

    for batch in batches:
        if remaining <= 0:
            break

        # Take what we can from this batch
        take = min(batch['quantity'], remaining)
        allocations.append({
            'batch_id': batch['batch_id'],
            'batch_number': batch['batch_number'],
            'expiry_date': batch['expiry_date'],
            'quantity_to_take': take
        })
        remaining -= take

    return allocations


# ============================================
# DISPENSE PRESCRIPTION
# URL: /dispensing/dispense/<prescription_id>
# This is the main dispensing workflow:
# 1. Show confirmation page with stock allocation preview
# 2. Process dispensing on POST
# ============================================
@dispensing_bp.route('/dispensing/dispense/<int:prescription_id>', methods=['GET', 'POST'])
def dispense_prescription(prescription_id):
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

        if prescription['status'] != 'created':
            flash('This prescription has already been processed.', 'warning')
            cursor.close()
            conn.close()
            return redirect(url_for('prescriptions.view_prescription',
                                   prescription_id=prescription_id))

        # Get prescription items
        cursor.execute(
            """SELECT pi.*, m.name AS medicine_name, m.strength, m.dosage_form, m.medicine_id
               FROM prescription_items pi
               JOIN medicines m ON pi.medicine_id = m.medicine_id
               WHERE pi.prescription_id = %s""",
            (prescription_id,)
        )
        items = cursor.fetchall()

        if not items:
            flash('Cannot dispense an empty prescription.', 'warning')
            cursor.close()
            conn.close()
            return redirect(url_for('prescriptions.view_prescription',
                                   prescription_id=prescription_id))

        # --- Preview stock allocations for each item ---
        all_allocations = []
        can_dispense = True
        total_cost = 0

        for item in items:
            allocations = allocate_stock(cursor, item['medicine_id'], item['quantity'])

            if allocations is None:
                can_dispense = False
                all_allocations.append({
                    'item': item,
                    'allocations': [],
                    'error': f"Insufficient non-expired stock for {item['medicine_name']}"
                })
            else:
                all_allocations.append({
                    'item': item,
                    'allocations': allocations,
                    'error': None
                })

            # Get selling price from the medicines table
            cursor.execute(
                """SELECT selling_price FROM medicines
                   WHERE medicine_id = %s""",
                (item['medicine_id'],)
            )
            price_result = cursor.fetchone()
            item_cost = float(price_result['selling_price'] or 0) * item['quantity']
            total_cost += item_cost

        # If total cost is 0, set a default (NHS prescriptions have a flat fee)
        if total_cost == 0:
            total_cost = 9.90 * len(items)  # Default NHS prescription charge per item

        if request.method == 'POST':
            if not can_dispense:
                flash('Cannot dispense - insufficient stock for one or more items.', 'danger')
                cursor.close()
                conn.close()
                return redirect(url_for('dispensing.dispense_prescription',
                                       prescription_id=prescription_id))

            payment_method = request.form.get('payment_method', '').strip()
            payment_amount = request.form.get('payment_amount', '0').strip()

            # --- Validation ---
            if payment_method not in ['cash', 'card', 'contactless']:
                flash('Please select a valid payment method.', 'danger')
                cursor.close()
                conn.close()
                return render_template('dispensing/dispense.html',
                                     prescription=prescription,
                                     items=items,
                                     all_allocations=all_allocations,
                                     can_dispense=can_dispense,
                                     total_cost=total_cost)

            try:
                payment_amount = float(payment_amount)
                if payment_amount < 0:
                    flash('Payment amount cannot be negative.', 'danger')
                    cursor.close()
                    conn.close()
                    return render_template('dispensing/dispense.html',
                                         prescription=prescription,
                                         items=items,
                                         all_allocations=all_allocations,
                                         can_dispense=can_dispense,
                                         total_cost=total_cost)
            except ValueError:
                flash('Invalid payment amount.', 'danger')
                cursor.close()
                conn.close()
                return render_template('dispensing/dispense.html',
                                     prescription=prescription,
                                     items=items,
                                     all_allocations=all_allocations,
                                     can_dispense=can_dispense,
                                     total_cost=total_cost)

            # ============================================
            # PROCESS THE DISPENSING
            # This is a critical transaction - all steps must succeed
            # ============================================

            # 1. Create dispensing record
            cursor.execute(
                """INSERT INTO dispensing_records (prescription_id, dispensed_by)
                   VALUES (%s, %s)""",
                (prescription_id, session['user_id'])
            )
            dispensing_id = cursor.lastrowid

            # 2. Process each item - allocate stock and create dispensing items
            for alloc_data in all_allocations:
                item = alloc_data['item']
                allocations = alloc_data['allocations']

                for alloc in allocations:
                    # Create dispensing item record
                    cursor.execute(
                        """INSERT INTO dispensing_items
                           (dispensing_id, prescription_item_id, batch_id, quantity_dispensed)
                           VALUES (%s, %s, %s, %s)""",
                        (dispensing_id, item['item_id'],
                         alloc['batch_id'], alloc['quantity_to_take'])
                    )

                    # Reduce batch quantity
                    cursor.execute(
                        """UPDATE batches
                           SET quantity = quantity - %s
                           WHERE batch_id = %s""",
                        (alloc['quantity_to_take'], alloc['batch_id'])
                    )

                    # Audit trail for each stock reduction
                    audit(session['user_id'], 'STOCK_OUT', 'batches', alloc['batch_id'],
                          f"Dispensed {alloc['quantity_to_take']} units of {item['medicine_name']} "
                          f"(Batch: {alloc['batch_number']}) for prescription RX-{prescription_id:05d}")

            # 3. Create payment record
            receipt_ref = generate_receipt_reference()

            cursor.execute(
                """INSERT INTO payments
                   (dispensing_id, amount, payment_method, receipt_reference, processed_by)
                   VALUES (%s, %s, %s, %s, %s)""",
                (dispensing_id, payment_amount, payment_method,
                 receipt_ref, session['user_id'])
            )

            # 4. Update prescription status to 'dispensed'
            cursor.execute(
                "UPDATE prescriptions SET status = 'dispensed' WHERE prescription_id = %s",
                (prescription_id,)
            )

            conn.commit()

            # 5. Audit trail for the dispensing
            audit(session['user_id'], 'DISPENSING', 'dispensing_records', dispensing_id,
                  f"Dispensed prescription RX-{prescription_id:05d} for {prescription['patient_name']}. "
                  f"Payment: £{payment_amount:.2f} ({payment_method}). Receipt: {receipt_ref}")

            cursor.close()
            conn.close()

            flash(f'Prescription dispensed successfully! Receipt: {receipt_ref}', 'success')
            return redirect(url_for('dispensing.view_dispensing', dispensing_id=dispensing_id))

        # GET - show confirmation page
        cursor.close()
        conn.close()

        return render_template('dispensing/dispense.html',
                             prescription=prescription,
                             items=items,
                             all_allocations=all_allocations,
                             can_dispense=can_dispense,
                             total_cost=total_cost)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('prescriptions.view_prescription',
                               prescription_id=prescription_id))


# ============================================
# VIEW DISPENSING RECORD (Receipt)
# URL: /dispensing/<id>
# Shows the completed dispensing with receipt info
# ============================================
@dispensing_bp.route('/dispensing/<int:dispensing_id>')
def view_dispensing(dispensing_id):
    if 'user_id' not in session or session.get('role') != 'staff':
        flash('Access denied. Staff privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Get dispensing record with related info
        cursor.execute(
            """SELECT dr.*,
                      p.patient_name, p.patient_dob, p.patient_address,
                      p.doctor_name, p.doctor_registration, p.prescription_id,
                      u.full_name AS dispensed_by_name,
                      pay.amount, pay.payment_method, pay.receipt_reference, pay.payment_date
               FROM dispensing_records dr
               JOIN prescriptions p ON dr.prescription_id = p.prescription_id
               JOIN users u ON dr.dispensed_by = u.user_id
               LEFT JOIN payments pay ON dr.dispensing_id = pay.dispensing_id
               WHERE dr.dispensing_id = %s""",
            (dispensing_id,)
        )
        record = cursor.fetchone()

        if not record:
            flash('Dispensing record not found.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('dispensing.dispensing_history'))

        # Get dispensed items with batch details
        cursor.execute(
            """SELECT di.*, pi.quantity AS prescribed_qty, pi.dosage_instructions,
                      m.name AS medicine_name, m.strength, m.dosage_form,
                      b.batch_number, b.expiry_date
               FROM dispensing_items di
               JOIN prescription_items pi ON di.prescription_item_id = pi.item_id
               JOIN medicines m ON pi.medicine_id = m.medicine_id
               JOIN batches b ON di.batch_id = b.batch_id
               WHERE di.dispensing_id = %s""",
            (dispensing_id,)
        )
        dispensed_items = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('dispensing/view.html',
                             record=record,
                             dispensed_items=dispensed_items)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('dispensing.dispensing_history'))


# ============================================
# DISPENSING HISTORY
# URL: /dispensing/history
# Shows all past dispensing records
# ============================================
@dispensing_bp.route('/dispensing/history')
def dispensing_history():
    if 'user_id' not in session or session.get('role') != 'staff':
        flash('Access denied. Staff privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        search = request.args.get('search', '').strip()

        query = """
            SELECT dr.*,
                   p.patient_name, p.doctor_name, p.prescription_id,
                   u.full_name AS dispensed_by_name,
                   pay.amount, pay.payment_method, pay.receipt_reference
            FROM dispensing_records dr
            JOIN prescriptions p ON dr.prescription_id = p.prescription_id
            JOIN users u ON dr.dispensed_by = u.user_id
            LEFT JOIN payments pay ON dr.dispensing_id = pay.dispensing_id
            WHERE 1=1
        """
        params = []

        if search:
            query += """ AND (p.patient_name LIKE %s
                        OR pay.receipt_reference LIKE %s
                        OR p.doctor_name LIKE %s)"""
            search_param = f'%{search}%'
            params.extend([search_param, search_param, search_param])

        query += " ORDER BY dr.dispensing_date DESC"

        cursor.execute(query, params)
        records = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('dispensing/history.html',
                             records=records,
                             search=search)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))