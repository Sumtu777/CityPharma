# ============================================
# suppliers.py - Supplier Management Routes
# Blueprint for all supplier-related functionality
# Only accessible by Pharmacy Manager 
# ============================================

from flask import Blueprint, render_template, request, redirect, url_for, flash, session

suppliers_bp = Blueprint('suppliers', __name__)

def get_db():
    from app import get_db_connection
    return get_db_connection()

def audit(user_id, action_type, table_name, record_id, details):
    from app import log_audit
    log_audit(user_id, action_type, table_name, record_id, details)


# ============================================
# LIST ALL SUPPLIERS
# URL: /suppliers
# ============================================
@suppliers_bp.route('/suppliers')
def list_suppliers():
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        search = request.args.get('search', '').strip()

        # --- Query suppliers with a count of linked medicines ---
        # The LEFT JOIN + COUNT tells us how many medicines each supplier provides
        query = """
            SELECT s.*,
                   COUNT(DISTINCT ms.medicine_id) AS medicine_count
            FROM suppliers s
            LEFT JOIN medicine_suppliers ms ON s.supplier_id = ms.supplier_id
            WHERE s.is_active = 1
        """
        params = []

        if search:
            query += " AND (s.name LIKE %s OR s.contact_person LIKE %s OR s.email LIKE %s)"
            search_param = f'%{search}%'
            params.extend([search_param, search_param, search_param])

        query += " GROUP BY s.supplier_id ORDER BY s.name"

        cursor.execute(query, params)
        suppliers = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('suppliers/list.html', suppliers=suppliers, search=search)

    except Exception as e:
        flash(f'Error loading suppliers: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))


# ============================================
# ADD NEW SUPPLIER
# URL: /suppliers/add
# ============================================
@suppliers_bp.route('/suppliers/add', methods=['GET', 'POST'])
def add_supplier():
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        contact_person = request.form.get('contact_person', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()

        # --- Validation ---
        errors = []
        if not name:
            errors.append('Supplier name is required.')
        if email and '@' not in email:
            errors.append('Please enter a valid email address.')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('suppliers/add.html')

        try:
            conn = get_db()
            cursor = conn.cursor(dictionary=True)

            # --- Check for duplicate supplier name ---
            cursor.execute(
                "SELECT supplier_id FROM suppliers WHERE name = %s AND is_active = 1",
                (name,)
            )
            if cursor.fetchone():
                flash(f'A supplier named "{name}" already exists.', 'warning')
                cursor.close()
                conn.close()
                return render_template('suppliers/add.html')

            # --- Insert supplier ---
            cursor.execute(
                """INSERT INTO suppliers (name, contact_person, email, phone, address)
                   VALUES (%s, %s, %s, %s, %s)""",
                (name, contact_person or None, email or None, phone or None, address or None)
            )
            conn.commit()
            supplier_id = cursor.lastrowid

            audit(session['user_id'], 'SUPPLIER_ADDED', 'suppliers', supplier_id,
                  f"Added supplier: {name}")

            cursor.close()
            conn.close()

            flash(f'Supplier "{name}" added successfully!', 'success')
            return redirect(url_for('suppliers.list_suppliers'))

        except Exception as e:
            flash(f'Error adding supplier: {str(e)}', 'danger')
            return render_template('suppliers/add.html')

    return render_template('suppliers/add.html')


# ============================================
# EDIT SUPPLIER
# URL: /suppliers/edit/<id>
# ============================================
@suppliers_bp.route('/suppliers/edit/<int:supplier_id>', methods=['GET', 'POST'])
def edit_supplier(supplier_id):
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            contact_person = request.form.get('contact_person', '').strip()
            email = request.form.get('email', '').strip()
            phone = request.form.get('phone', '').strip()
            address = request.form.get('address', '').strip()

            errors = []
            if not name:
                errors.append('Supplier name is required.')
            if email and '@' not in email:
                errors.append('Please enter a valid email address.')

            if errors:
                for error in errors:
                    flash(error, 'danger')
                cursor.execute("SELECT * FROM suppliers WHERE supplier_id = %s", (supplier_id,))
                supplier = cursor.fetchone()
                cursor.close()
                conn.close()
                return render_template('suppliers/edit.html', supplier=supplier)

            # --- Check for duplicate (excluding current) ---
            cursor.execute(
                "SELECT supplier_id FROM suppliers WHERE name = %s AND is_active = 1 AND supplier_id != %s",
                (name, supplier_id)
            )
            if cursor.fetchone():
                flash(f'Another supplier named "{name}" already exists.', 'warning')
                cursor.execute("SELECT * FROM suppliers WHERE supplier_id = %s", (supplier_id,))
                supplier = cursor.fetchone()
                cursor.close()
                conn.close()
                return render_template('suppliers/edit.html', supplier=supplier)

            cursor.execute(
                """UPDATE suppliers
                   SET name = %s, contact_person = %s, email = %s, phone = %s, address = %s
                   WHERE supplier_id = %s""",
                (name, contact_person or None, email or None, phone or None, address or None, supplier_id)
            )
            conn.commit()

            audit(session['user_id'], 'SUPPLIER_UPDATED', 'suppliers', supplier_id,
                  f"Updated supplier: {name}")

            cursor.close()
            conn.close()

            flash(f'Supplier "{name}" updated successfully!', 'success')
            return redirect(url_for('suppliers.list_suppliers'))

        # --- GET request ---
        cursor.execute("SELECT * FROM suppliers WHERE supplier_id = %s AND is_active = 1", (supplier_id,))
        supplier = cursor.fetchone()

        if not supplier:
            flash('Supplier not found.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('suppliers.list_suppliers'))

        cursor.close()
        conn.close()
        return render_template('suppliers/edit.html', supplier=supplier)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('suppliers.list_suppliers'))


# ============================================
# DELETE SUPPLIER (Soft Delete)
# ============================================
@suppliers_bp.route('/suppliers/delete/<int:supplier_id>', methods=['POST'])
def delete_supplier(supplier_id):
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT name FROM suppliers WHERE supplier_id = %s", (supplier_id,))
        supplier = cursor.fetchone()

        if supplier:
            cursor.execute("UPDATE suppliers SET is_active = 0 WHERE supplier_id = %s", (supplier_id,))
            conn.commit()

            audit(session['user_id'], 'SUPPLIER_DELETED', 'suppliers', supplier_id,
                  f"Deactivated supplier: {supplier['name']}")

            flash(f'Supplier "{supplier["name"]}" has been removed.', 'success')
        else:
            flash('Supplier not found.', 'danger')

        cursor.close()
        conn.close()

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')

    return redirect(url_for('suppliers.list_suppliers'))


# ============================================
# VIEW SUPPLIER DETAILS
# Shows supplier info and all linked medicines
# ============================================
@suppliers_bp.route('/suppliers/<int:supplier_id>')
def view_supplier(supplier_id):
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Get supplier details
        cursor.execute("SELECT * FROM suppliers WHERE supplier_id = %s AND is_active = 1", (supplier_id,))
        supplier = cursor.fetchone()

        if not supplier:
            flash('Supplier not found.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('suppliers.list_suppliers'))

        # Get linked medicines with stock info
        cursor.execute(
            """SELECT m.*, ms.unit_cost, ms.medicine_supplier_id,
                      COALESCE(SUM(b.quantity), 0) AS total_stock
               FROM medicine_suppliers ms
               JOIN medicines m ON ms.medicine_id = m.medicine_id
               LEFT JOIN batches b ON m.medicine_id = b.medicine_id AND b.expiry_date >= CURDATE()
               WHERE ms.supplier_id = %s AND m.is_active = 1
               GROUP BY m.medicine_id, ms.unit_cost, ms.medicine_supplier_id""",
            (supplier_id,)
        )
        linked_medicines = cursor.fetchall()

        # Get medicines NOT linked to this supplier (for the "Link Medicine" dropdown)
        cursor.execute(
            """SELECT m.medicine_id, m.name, m.strength, m.dosage_form
               FROM medicines m
               WHERE m.is_active = 1
               AND m.medicine_id NOT IN (
                   SELECT medicine_id FROM medicine_suppliers WHERE supplier_id = %s
               )
               ORDER BY m.name""",
            (supplier_id,)
        )
        available_medicines = cursor.fetchall()

        # Get purchase order history for this supplier
        cursor.execute(
            """SELECT po.*, u.full_name AS ordered_by_name,
                      COUNT(poi.item_id) AS item_count
               FROM purchase_orders po
               JOIN users u ON po.ordered_by = u.user_id
               LEFT JOIN purchase_order_items poi ON po.order_id = poi.order_id
               WHERE po.supplier_id = %s
               GROUP BY po.order_id
               ORDER BY po.order_date DESC
               LIMIT 10""",
            (supplier_id,)
        )
        recent_orders = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('suppliers/view.html',
                             supplier=supplier,
                             linked_medicines=linked_medicines,
                             available_medicines=available_medicines,
                             recent_orders=recent_orders)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('suppliers.list_suppliers'))


# ============================================
# LINK MEDICINE TO SUPPLIER
# This creates a record in the medicine_suppliers junction table
# ============================================
@suppliers_bp.route('/suppliers/<int:supplier_id>/link-medicine', methods=['POST'])
def link_medicine(supplier_id):
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    medicine_id = request.form.get('medicine_id')
    unit_cost = request.form.get('unit_cost', '0').strip()

    if not medicine_id:
        flash('Please select a medicine.', 'danger')
        return redirect(url_for('suppliers.view_supplier', supplier_id=supplier_id))

    try:
        unit_cost = float(unit_cost) if unit_cost else 0.00
        if unit_cost < 0:
            flash('Unit cost cannot be negative.', 'danger')
            return redirect(url_for('suppliers.view_supplier', supplier_id=supplier_id))
    except ValueError:
        flash('Please enter a valid unit cost.', 'danger')
        return redirect(url_for('suppliers.view_supplier', supplier_id=supplier_id))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Check if already linked
        cursor.execute(
            "SELECT * FROM medicine_suppliers WHERE medicine_id = %s AND supplier_id = %s",
            (medicine_id, supplier_id)
        )
        if cursor.fetchone():
            flash('This medicine is already linked to this supplier.', 'warning')
            cursor.close()
            conn.close()
            return redirect(url_for('suppliers.view_supplier', supplier_id=supplier_id))

        # Insert the link
        cursor.execute(
            """INSERT INTO medicine_suppliers (medicine_id, supplier_id, unit_cost)
               VALUES (%s, %s, %s)""",
            (medicine_id, supplier_id, unit_cost)
        )
        conn.commit()

        # Get names for audit log
        cursor.execute("SELECT name FROM medicines WHERE medicine_id = %s", (medicine_id,))
        med = cursor.fetchone()
        cursor.execute("SELECT name FROM suppliers WHERE supplier_id = %s", (supplier_id,))
        sup = cursor.fetchone()

        audit(session['user_id'], 'SUPPLIER_LINKED', 'medicine_suppliers', cursor.lastrowid,
              f"Linked {med['name']} to supplier {sup['name']} at £{unit_cost:.2f}")

        cursor.close()
        conn.close()

        flash('Medicine linked to supplier successfully!', 'success')

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')

    return redirect(url_for('suppliers.view_supplier', supplier_id=supplier_id))


# ============================================
# UNLINK MEDICINE FROM SUPPLIER
# Removes the record from the junction table
# ============================================
@suppliers_bp.route('/suppliers/unlink-medicine/<int:medicine_supplier_id>', methods=['POST'])
def unlink_medicine(medicine_supplier_id):
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Get details before deleting (for audit and redirect)
        cursor.execute(
            """SELECT ms.*, m.name AS medicine_name, s.name AS supplier_name, s.supplier_id
               FROM medicine_suppliers ms
               JOIN medicines m ON ms.medicine_id = m.medicine_id
               JOIN suppliers s ON ms.supplier_id = s.supplier_id
               WHERE ms.medicine_supplier_id = %s""",
            (medicine_supplier_id,)
        )
        link = cursor.fetchone()

        if link:
            cursor.execute(
                "DELETE FROM medicine_suppliers WHERE medicine_supplier_id = %s",
                (medicine_supplier_id,)
            )
            conn.commit()

            audit(session['user_id'], 'SUPPLIER_UNLINKED', 'medicine_suppliers', medicine_supplier_id,
                  f"Unlinked {link['medicine_name']} from supplier {link['supplier_name']}")

            flash(f'Medicine "{link["medicine_name"]}" unlinked from supplier.', 'success')
            supplier_id = link['supplier_id']
        else:
            flash('Link not found.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('suppliers.list_suppliers'))

        cursor.close()
        conn.close()
        return redirect(url_for('suppliers.view_supplier', supplier_id=supplier_id))

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('suppliers.list_suppliers'))