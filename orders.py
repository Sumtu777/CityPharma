# ============================================
# orders.py - Purchase Order & Stock Receiving Routes
# Blueprint for all purchase order functionality
# Only accessible by Pharmacy Manager 
# ============================================

from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import datetime

orders_bp = Blueprint('orders', __name__)

def get_db():
    from app import get_db_connection
    return get_db_connection()

def audit(user_id, action_type, table_name, record_id, details):
    from app import log_audit
    log_audit(user_id, action_type, table_name, record_id, details)


# ============================================
# LIST ALL PURCHASE ORDERS
# URL: /orders
# ============================================
@orders_bp.route('/orders')
def list_orders():
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Get status filter from URL
        status_filter = request.args.get('status', 'all')

        query = """
            SELECT po.*,
                   s.name AS supplier_name,
                   u.full_name AS ordered_by_name,
                   COUNT(poi.item_id) AS item_count,
                   COALESCE(SUM(poi.quantity_ordered * poi.unit_cost), 0) AS calculated_total
            FROM purchase_orders po
            JOIN suppliers s ON po.supplier_id = s.supplier_id
            JOIN users u ON po.ordered_by = u.user_id
            LEFT JOIN purchase_order_items poi ON po.order_id = poi.order_id
        """
        params = []

        if status_filter != 'all':
            query += " WHERE po.status = %s"
            params.append(status_filter)

        query += " GROUP BY po.order_id ORDER BY po.order_date DESC"

        cursor.execute(query, params)
        orders = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('orders/list.html',
                             orders=orders,
                             current_status=status_filter)

    except Exception as e:
        flash(f'Error loading orders: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))


# ============================================
# CREATE NEW PURCHASE ORDER
# URL: /orders/create
# Step 1: Select a supplier
# ============================================
@orders_bp.route('/orders/create', methods=['GET', 'POST'])
def create_order():
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        supplier_id = request.form.get('supplier_id')
        notes = request.form.get('notes', '').strip()

        if not supplier_id:
            flash('Please select a supplier.', 'danger')
            return redirect(url_for('orders.create_order'))

        try:
            conn = get_db()
            cursor = conn.cursor(dictionary=True)

            # Verify supplier exists
            cursor.execute(
                "SELECT name FROM suppliers WHERE supplier_id = %s AND is_active = 1",
                (supplier_id,)
            )
            supplier = cursor.fetchone()

            if not supplier:
                flash('Selected supplier not found.', 'danger')
                cursor.close()
                conn.close()
                return redirect(url_for('orders.create_order'))

            # Create the purchase order
            cursor.execute(
                """INSERT INTO purchase_orders (supplier_id, ordered_by, notes)
                   VALUES (%s, %s, %s)""",
                (supplier_id, session['user_id'], notes or None)
            )
            conn.commit()
            order_id = cursor.lastrowid

            audit(session['user_id'], 'ORDER_CREATED', 'purchase_orders', order_id,
                  f"Created purchase order PO-{order_id:04d} for supplier {supplier['name']}")

            cursor.close()
            conn.close()

            flash(f'Purchase order PO-{order_id:04d} created! Now add medicines to it.', 'success')
            return redirect(url_for('orders.view_order', order_id=order_id))

        except Exception as e:
            flash(f'Error creating order: {str(e)}', 'danger')
            return redirect(url_for('orders.create_order'))

    # GET - show create form with supplier list
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM suppliers WHERE is_active = 1 ORDER BY name")
        suppliers = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('orders/create.html', suppliers=suppliers)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('orders.list_orders'))


# ============================================
# VIEW PURCHASE ORDER DETAILS
# URL: /orders/<id>
# Shows order info, items, and action buttons
# ============================================
@orders_bp.route('/orders/<int:order_id>')
def view_order(order_id):
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Get order details
        cursor.execute(
            """SELECT po.*,
                      s.name AS supplier_name, s.email AS supplier_email,
                      s.phone AS supplier_phone,
                      u.full_name AS ordered_by_name
               FROM purchase_orders po
               JOIN suppliers s ON po.supplier_id = s.supplier_id
               JOIN users u ON po.ordered_by = u.user_id
               WHERE po.order_id = %s""",
            (order_id,)
        )
        order = cursor.fetchone()

        if not order:
            flash('Purchase order not found.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('orders.list_orders'))

        # Get order items
        cursor.execute(
            """SELECT poi.*, m.name AS medicine_name, m.strength, m.dosage_form
               FROM purchase_order_items poi
               JOIN medicines m ON poi.medicine_id = m.medicine_id
               WHERE poi.order_id = %s""",
            (order_id,)
        )
        items = cursor.fetchall()

        # Calculate total
        total_cost = sum(item['quantity_ordered'] * item['unit_cost'] for item in items)

        # Get medicines linked to this supplier (for adding items)
        # Only show if order is still pending
        available_medicines = []
        if order['status'] == 'pending':
            # Get medicines already in this order
            existing_medicine_ids = [item['medicine_id'] for item in items]

            # Get all active medicines (not just linked ones - manager might order from any supplier)
            query = "SELECT * FROM medicines WHERE is_active = 1"
            if existing_medicine_ids:
                placeholders = ','.join(['%s'] * len(existing_medicine_ids))
                query += f" AND medicine_id NOT IN ({placeholders})"

            query += " ORDER BY name"

            cursor.execute(query, existing_medicine_ids if existing_medicine_ids else ())
            available_medicines = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('orders/view.html',
                             order=order,
                             items=items,
                             total_cost=total_cost,
                             available_medicines=available_medicines)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('orders.list_orders'))


# ============================================
# ADD ITEM TO PURCHASE ORDER
# URL: /orders/<id>/add-item
# ============================================
@orders_bp.route('/orders/<int:order_id>/add-item', methods=['POST'])
def add_order_item(order_id):
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    medicine_id = request.form.get('medicine_id')
    quantity = request.form.get('quantity', '0').strip()
    unit_cost = request.form.get('unit_cost', '0').strip()

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

    try:
        unit_cost = float(unit_cost)
        if unit_cost < 0:
            errors.append('Unit cost cannot be negative.')
    except ValueError:
        errors.append('Unit cost must be a valid number.')

    if errors:
        for error in errors:
            flash(error, 'danger')
        return redirect(url_for('orders.view_order', order_id=order_id))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Verify order exists and is pending
        cursor.execute(
            "SELECT status FROM purchase_orders WHERE order_id = %s",
            (order_id,)
        )
        order = cursor.fetchone()

        if not order or order['status'] != 'pending':
            flash('Cannot add items. Order is not in pending status.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('orders.view_order', order_id=order_id))

        # Check medicine isn't already in this order
        cursor.execute(
            "SELECT item_id FROM purchase_order_items WHERE order_id = %s AND medicine_id = %s",
            (order_id, medicine_id)
        )
        if cursor.fetchone():
            flash('This medicine is already in the order.', 'warning')
            cursor.close()
            conn.close()
            return redirect(url_for('orders.view_order', order_id=order_id))

        # Add the item
        cursor.execute(
            """INSERT INTO purchase_order_items (order_id, medicine_id, quantity_ordered, unit_cost)
               VALUES (%s, %s, %s, %s)""",
            (order_id, medicine_id, quantity, unit_cost)
        )

        # Update the order total
        cursor.execute(
            """UPDATE purchase_orders
               SET total_cost = (
                   SELECT COALESCE(SUM(quantity_ordered * unit_cost), 0)
                   FROM purchase_order_items WHERE order_id = %s
               )
               WHERE order_id = %s""",
            (order_id, order_id)
        )

        conn.commit()

        # Get medicine name for flash message
        cursor.execute("SELECT name FROM medicines WHERE medicine_id = %s", (medicine_id,))
        med = cursor.fetchone()

        audit(session['user_id'], 'ORDER_ITEM_ADDED', 'purchase_order_items', cursor.lastrowid,
              f"Added {med['name']} (qty: {quantity}) to PO-{order_id:04d}")

        cursor.close()
        conn.close()

        flash(f'{med["name"]} added to order!', 'success')

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')

    return redirect(url_for('orders.view_order', order_id=order_id))


# ============================================
# REMOVE ITEM FROM PURCHASE ORDER
# ============================================
@orders_bp.route('/orders/remove-item/<int:item_id>', methods=['POST'])
def remove_order_item(item_id):
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Get item details for redirect and audit
        cursor.execute(
            """SELECT poi.*, po.status, po.order_id, m.name AS medicine_name
               FROM purchase_order_items poi
               JOIN purchase_orders po ON poi.order_id = po.order_id
               JOIN medicines m ON poi.medicine_id = m.medicine_id
               WHERE poi.item_id = %s""",
            (item_id,)
        )
        item = cursor.fetchone()

        if not item:
            flash('Item not found.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('orders.list_orders'))

        if item['status'] != 'pending':
            flash('Cannot remove items from a non-pending order.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('orders.view_order', order_id=item['order_id']))

        order_id = item['order_id']

        # Delete the item
        cursor.execute("DELETE FROM purchase_order_items WHERE item_id = %s", (item_id,))

        # Update order total
        cursor.execute(
            """UPDATE purchase_orders
               SET total_cost = (
                   SELECT COALESCE(SUM(quantity_ordered * unit_cost), 0)
                   FROM purchase_order_items WHERE order_id = %s
               )
               WHERE order_id = %s""",
            (order_id, order_id)
        )

        conn.commit()

        audit(session['user_id'], 'ORDER_ITEM_REMOVED', 'purchase_order_items', item_id,
              f"Removed {item['medicine_name']} from PO-{order_id:04d}")

        cursor.close()
        conn.close()

        flash(f'{item["medicine_name"]} removed from order.', 'success')
        return redirect(url_for('orders.view_order', order_id=order_id))

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('orders.list_orders'))


# ============================================
# RECEIVE PURCHASE ORDER
# This is the critical function - it:
# 1. Updates each item with batch number and expiry date
# 2. Creates new batch records in the batches table
# 3. Updates stock levels
# 4. Marks the order as received
# 5. Logs everything in the audit trail
# ============================================
@orders_bp.route('/orders/<int:order_id>/receive', methods=['GET', 'POST'])
def receive_order(order_id):
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # Get order details
        cursor.execute(
            """SELECT po.*, s.name AS supplier_name
               FROM purchase_orders po
               JOIN suppliers s ON po.supplier_id = s.supplier_id
               WHERE po.order_id = %s""",
            (order_id,)
        )
        order = cursor.fetchone()

        if not order:
            flash('Order not found.', 'danger')
            cursor.close()
            conn.close()
            return redirect(url_for('orders.list_orders'))

        if order['status'] != 'pending':
            flash('This order has already been processed.', 'warning')
            cursor.close()
            conn.close()
            return redirect(url_for('orders.view_order', order_id=order_id))

        # Get order items
        cursor.execute(
            """SELECT poi.*, m.name AS medicine_name, m.strength, m.dosage_form
               FROM purchase_order_items poi
               JOIN medicines m ON poi.medicine_id = m.medicine_id
               WHERE poi.order_id = %s""",
            (order_id,)
        )
        items = cursor.fetchall()

        if not items:
            flash('Cannot receive an empty order. Add medicines first.', 'warning')
            cursor.close()
            conn.close()
            return redirect(url_for('orders.view_order', order_id=order_id))

        if request.method == 'POST':
            # --- Process each item ---
            all_valid = True
            receive_data = []

            for item in items:
                item_id = item['item_id']
                batch_number = request.form.get(f'batch_number_{item_id}', '').strip()
                expiry_date = request.form.get(f'expiry_date_{item_id}', '').strip()
                qty_received = request.form.get(f'quantity_received_{item_id}', '0').strip()

                # Validate each item
                if not batch_number:
                    flash(f'Batch number required for {item["medicine_name"]}.', 'danger')
                    all_valid = False
                    continue

                if not expiry_date:
                    flash(f'Expiry date required for {item["medicine_name"]}.', 'danger')
                    all_valid = False
                    continue

                try:
                    qty_received = int(qty_received)
                    if qty_received <= 0:
                        flash(f'Quantity received must be positive for {item["medicine_name"]}.', 'danger')
                        all_valid = False
                        continue
                except ValueError:
                    flash(f'Invalid quantity for {item["medicine_name"]}.', 'danger')
                    all_valid = False
                    continue

                # Check expiry date is in the future
                try:
                    exp_date = datetime.strptime(expiry_date, '%Y-%m-%d').date()
                    if exp_date <= datetime.now().date():
                        flash(f'Expiry date must be in the future for {item["medicine_name"]}.', 'danger')
                        all_valid = False
                        continue
                except ValueError:
                    flash(f'Invalid expiry date for {item["medicine_name"]}.', 'danger')
                    all_valid = False
                    continue

                receive_data.append({
                    'item_id': item_id,
                    'medicine_id': item['medicine_id'],
                    'medicine_name': item['medicine_name'],
                    'batch_number': batch_number,
                    'expiry_date': expiry_date,
                    'quantity_received': qty_received
                })

            if not all_valid:
                cursor.close()
                conn.close()
                return render_template('orders/receive.html', order=order, items=items)

            # --- All valid - process the receiving ---
            today = datetime.now().date()

            for data in receive_data:
                # 1. Update the purchase order item
                cursor.execute(
                    """UPDATE purchase_order_items
                       SET quantity_received = %s, batch_number = %s, expiry_date = %s
                       WHERE item_id = %s""",
                    (data['quantity_received'], data['batch_number'],
                     data['expiry_date'], data['item_id'])
                )

                # 2. Check if batch already exists for this medicine
                cursor.execute(
                    """SELECT batch_id, quantity FROM batches
                       WHERE medicine_id = %s AND batch_number = %s""",
                    (data['medicine_id'], data['batch_number'])
                )
                existing_batch = cursor.fetchone()

                if existing_batch:
                    # Batch exists - add to existing quantity
                    new_qty = existing_batch['quantity'] + data['quantity_received']
                    cursor.execute(
                        "UPDATE batches SET quantity = %s WHERE batch_id = %s",
                        (new_qty, existing_batch['batch_id'])
                    )
                    batch_id = existing_batch['batch_id']
                else:
                    # 3. Create new batch record
                    cursor.execute(
                        """INSERT INTO batches (medicine_id, batch_number, expiry_date, quantity, date_received)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (data['medicine_id'], data['batch_number'],
                         data['expiry_date'], data['quantity_received'], today)
                    )
                    batch_id = cursor.lastrowid

                # 4. Log to audit trail
                audit(session['user_id'], 'STOCK_IN', 'batches', batch_id,
                      f"Received {data['quantity_received']} units of {data['medicine_name']} "
                      f"(Batch: {data['batch_number']}) from PO-{order_id:04d}")

            # 5. Mark order as received
            cursor.execute(
                """UPDATE purchase_orders
                   SET status = 'received', received_date = NOW()
                   WHERE order_id = %s""",
                (order_id,)
            )

            conn.commit()

            audit(session['user_id'], 'ORDER_RECEIVED', 'purchase_orders', order_id,
                  f"Marked PO-{order_id:04d} as received ({len(receive_data)} items)")

            cursor.close()
            conn.close()

            flash(f'Purchase order PO-{order_id:04d} received successfully! Stock has been updated.', 'success')
            return redirect(url_for('orders.view_order', order_id=order_id))

        # GET - show receive form
        cursor.close()
        conn.close()
        return render_template('orders/receive.html', order=order, items=items)

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('orders.view_order', order_id=order_id))


# ============================================
# CANCEL PURCHASE ORDER
# ============================================
@orders_bp.route('/orders/<int:order_id>/cancel', methods=['POST'])
def cancel_order(order_id):
    if 'user_id' not in session or session.get('role') != 'manager':
        flash('Access denied. Manager privileges required.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT status FROM purchase_orders WHERE order_id = %s",
            (order_id,)
        )
        order = cursor.fetchone()

        if not order:
            flash('Order not found.', 'danger')
        elif order['status'] != 'pending':
            flash('Only pending orders can be cancelled.', 'warning')
        else:
            cursor.execute(
                "UPDATE purchase_orders SET status = 'cancelled' WHERE order_id = %s",
                (order_id,)
            )
            conn.commit()

            audit(session['user_id'], 'ORDER_CANCELLED', 'purchase_orders', order_id,
                  f"Cancelled purchase order PO-{order_id:04d}")

            flash(f'Purchase order PO-{order_id:04d} has been cancelled.', 'success')

        cursor.close()
        conn.close()

    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')

    return redirect(url_for('orders.view_order', order_id=order_id))