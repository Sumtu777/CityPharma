# ============================================
# setup_passwords.py
# Run this ONCE to set proper hashed passwords for default users
# After running, you can delete this file
# ============================================

from werkzeug.security import generate_password_hash
import mysql.connector

conn = mysql.connector.connect(
    host='localhost',
    user='root',
    password='',
    database='citypharma_db'
)
cursor = conn.cursor()

# Generate hashed passwords
# 'pbkdf2:sha256' is a strong hashing algorithm
# Even if someone steals the database, they can't read the passwords
manager_hash = generate_password_hash('password123', method='pbkdf2:sha256')
staff_hash = generate_password_hash('password123', method='pbkdf2:sha256')

# Update the users table
cursor.execute("UPDATE users SET password_hash = %s WHERE username = 'manager1'", (manager_hash,))
cursor.execute("UPDATE users SET password_hash = %s WHERE username = 'staff1'", (staff_hash,))

conn.commit()
print("Passwords updated successfully!")
print(f"Manager hash: {manager_hash[:50]}...")
print(f"Staff hash: {staff_hash[:50]}...")

cursor.close()
conn.close()