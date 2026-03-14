import os
import mysql.connector
from mysql.connector import pooling
from contextlib import contextmanager

# ================= DATABASE CONNECTION =================



dbconfig = {
    "host": os.environ.get("MYSQLHOST"),
    "port": int(os.environ.get("MYSQLPORT", 3306)),
    "user": os.environ.get("MYSQLUSER"),
    "password": os.environ.get("MYSQLPASSWORD"),
    "database": os.environ.get("MYSQLDATABASE"),
}

missing = [k for k, v in dbconfig.items() if v is None]
if missing:
    raise RuntimeError(f"MySQL ENV vars missing: {missing}")

pool = pooling.MySQLConnectionPool(
    pool_name="retech_pool",
    pool_size=10,
    **dbconfig
)


def get_db():
    return pool.get_connection()


@contextmanager
def db_cursor(dictionary=False):
    db = get_db()
    cur = db.cursor(dictionary=dictionary)
    try:
        yield cur
        db.commit()
    finally:
        cur.close()
        db.close()

# ================= CREATE TABLES =================

def init_tables():
    db = get_db()
    cur = db.cursor()

    # USERS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(100),
        phone VARCHAR(15),
        gender VARCHAR(10),
        age INT,
        email VARCHAR(100) UNIQUE,
        password VARCHAR(255),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # PRODUCTS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INT AUTO_INCREMENT PRIMARY KEY,
        product_name VARCHAR(255) NOT NULL,
        category VARCHAR(150),
        material VARCHAR(150),
        stone_type VARCHAR(150),
        weight VARCHAR(50),
        occasion VARCHAR(150),
        sku VARCHAR(100),
        price DECIMAL(10,2) NOT NULL,
        stock INT NOT NULL DEFAULT 0,
        is_active BOOLEAN DEFAULT TRUE,
        image_url VARCHAR(255),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
    )
    """)

    # ADDRESSES
    cur.execute("""
    CREATE TABLE IF NOT EXISTS addresses (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        full_name VARCHAR(100) NOT NULL,
        phone VARCHAR(20) NOT NULL,
        address_line TEXT NOT NULL,
        city VARCHAR(50) NOT NULL,
        state VARCHAR(50) NOT NULL,
        pincode VARCHAR(10) NOT NULL,
        is_default TINYINT DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # CART
    cur.execute("""
    CREATE TABLE IF NOT EXISTS cart (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        product_id INT NOT NULL,
        quantity INT DEFAULT 1,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
    )
    """)

    # ORDERS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        address_id INT NOT NULL,
        total_amount DECIMAL(10,2),
        status VARCHAR(30) DEFAULT 'Placed',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (address_id) REFERENCES addresses(id)
    )
    """)

    # ORDER ITEMS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS order_items (
        id INT AUTO_INCREMENT PRIMARY KEY,
        order_id INT NOT NULL,
        product_id INT NOT NULL,
        quantity INT NOT NULL,
        price DECIMAL(10,2) NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
        FOREIGN KEY (product_id) REFERENCES products(id)
    )
    """)

    # ADMINS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        id INT AUTO_INCREMENT PRIMARY KEY,
        admin_id VARCHAR(100) UNIQUE,
        password VARCHAR(255)
    )
    """)

    # ORDER STATUS HISTORY
    cur.execute("""
    CREATE TABLE IF NOT EXISTS order_status_history (
        id INT AUTO_INCREMENT PRIMARY KEY,
        order_id INT NOT NULL,
        status VARCHAR(30) NOT NULL,
        changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
    )
    """)

    # PAYMENTS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id INT AUTO_INCREMENT PRIMARY KEY,
        order_id INT NOT NULL,
        payment_method VARCHAR(30),
        payment_status VARCHAR(30),
        transaction_id VARCHAR(100),
        amount DECIMAL(10,2),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
    )
    """)

    # ADMIN LOGS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS admin_logs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        admin_id INT,
        action VARCHAR(255),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (admin_id) REFERENCES admins(id)
    )
    """)

    # ORDER CANCELLATIONS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS order_cancellations (
        id INT AUTO_INCREMENT PRIMARY KEY,
        order_id INT NOT NULL,
        user_id INT NOT NULL,
        reason VARCHAR(255) NOT NULL,
        cancelled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # DEFAULT ADMIN
    cur.execute("""
    INSERT IGNORE INTO admins (admin_id, password)
    VALUES ('admin@kundal', 'Krishna@9582')
    """)

    db.commit()
    cur.close()
    db.close()