from flask import Flask, request, jsonify, render_template, redirect, session, flash
from flask_cors import CORS
import bcrypt, random, time, os
from werkzeug.utils import secure_filename
import mysql.connector
import razorpay
from db import get_db, init_tables
from email_otp import send_otp
from flask import abort



app = Flask(__name__, template_folder="templates")
app.secret_key = "retech_secret_key"
CORS(app)

client = razorpay.Client(auth=(
    os.environ.get("RAZORPAY_KEY_ID"),
    os.environ.get("RAZORPAY_KEY_SECRET")
))

try:
    with app.app_context():
        init_tables()
except Exception as e:
    print("Database init error:", e)




# ================= ADMIN IP SECURITY =================

# Put YOUR real public IP here (example only)
ALLOWED_ADMIN_IPS = {
    ip.strip()
    for ip in os.environ.get("ADMIN_ALLOWED_IPS", "").split(",")
    if ip.strip()
}

@app.before_request
def hide_admin_from_unauthorized_ips():
    if request.path.startswith("/admin"):
        ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        if ip:
            ip = ip.split(",")[0].strip()

        if ip not in ALLOWED_ADMIN_IPS:
            abort(404)  # completely hide admin



@app.route("/smtp-debug")
def smtp_debug():
    return {
        "SMTP_HOST": os.environ.get("SMTP_HOST"),
        "SMTP_PORT": os.environ.get("SMTP_PORT"),
        "SMTP_EMAIL": os.environ.get("SMTP_EMAIL"),
        "FROM_EMAIL": os.environ.get("FROM_EMAIL"),
        "SMTP_PASSWORD_SET": bool(os.environ.get("SMTP_PASSWORD"))
    }

 
with app.app_context():
    init_tables()

    

# ================= ADMIN AUTH HELPER =================
from functools import wraps
from flask import session, redirect

def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "admin_id" not in session:
            return redirect("/admin/login")
        return func(*args, **kwargs)
    return wrapper



# ---------------- ROUTES ----------------


@app.route("/db-test")
def db_test():
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT DATABASE()")
        result = cur.fetchone()
        cur.close()
        db.close()

        return f"MySQL Connected ✅ Database: {result[0]}"

    except mysql.connector.Error as e:
        return f"MySQL Error ❌ {e}"

    except Exception as e:
        return f"App Error ❌ {e}"




# ---------------- CONFIG ----------------
OTP_EXPIRY = 120
UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ---------------- STORES ----------------
otp_store = {}
def clean_expired_otps(store):
    now = time.time()
    for key in list(store.keys()):
        if now - store[key]["time"] > OTP_EXPIRY:
            del store[key]


# ================== CHANGE PASSWORD WITH OTP ==================

from flask import Flask, render_template, request, session, redirect, jsonify
import random, time, bcrypt



OTP_EXPIRY = 120  # 5 minutes
change_pwd_otp_store = {}

# ---------------- SHOW PAGE ----------------
@app.route("/change-password")
def change_password():
    if "user_id" not in session:
        return redirect("/login")
    return render_template("change_password.html")


# ---------------- SEND OTP ----------------
@app.route("/send-change-otp", methods=["POST"])
def send_change_otp():
    if "user_id" not in session:
        return jsonify({"status": "unauthorized"}), 401

    data = request.json
    new_password = data.get("new_password")
    confirm_password = data.get("confirm_password")

    if not new_password or not confirm_password:
        return jsonify({"status": "error", "msg": "All fields required"})

    if new_password != confirm_password:
        return jsonify({"status": "error", "msg": "Passwords do not match"})

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT email FROM users WHERE id=%s", (session["user_id"],))
    user = cur.fetchone()

    email = user["email"]
    clean_expired_otps(change_pwd_otp_store)
    otp = random.randint(100000, 999999)

    change_pwd_otp_store[session["user_id"]] = {
        "otp": otp,
        "hashed": bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode(),
        "time": time.time()
    }

    send_otp(email, otp)
    print("CHANGE PASSWORD OTP:", otp)

    return jsonify({"status": "otp_sent"})


# ---------------- VERIFY OTP ----------------
@app.route("/verify-change-otp", methods=["POST"])
def verify_change_otp():
    if "user_id" not in session:
        return jsonify({"status": "unauthorized"}), 401

    otp = request.json.get("otp")
    record = change_pwd_otp_store.get(session["user_id"])

    if not record:
        return jsonify({"status": "error", "msg": "OTP expired"})

    if time.time() - record["time"] > OTP_EXPIRY:
        del change_pwd_otp_store[session["user_id"]]
        return jsonify({"status": "error", "msg": "OTP expired"})

    if str(record["otp"]) != str(otp):
        return jsonify({"status": "error", "msg": "Invalid OTP"})

    db = get_db()
    cur = db.cursor()
    cur.execute(
        "UPDATE users SET password=%s WHERE id=%s",
        (record["hashed"], session["user_id"])
    )
    db.commit()

    del change_pwd_otp_store[session["user_id"]]

    return jsonify({"status": "success"})


# ---------------- ADMIN CREDENTIALS ----------------
ADMIN_ID = "admin@retech"
ADMIN_PASSWORD = "Krishna@9582"

# ================== Home route ==================

@app.route("/")
def home():
    search = request.args.get("q")

    db = get_db()
    cur = db.cursor(dictionary=True)

    if search and search.strip():
        cur.execute("""
            SELECT * FROM products
            WHERE is_active=1 AND (
                product_name LIKE %s
                OR brand LIKE %s
                OR model_number LIKE %s
                OR ram LIKE %s
                OR rom LIKE %s
                OR operating_system LIKE %s
            )
            ORDER BY id DESC
        """, tuple(f"%{search}%" for _ in range(6)))
    else:
        cur.execute("""
            SELECT * FROM products
            WHERE is_active=1
            ORDER BY id DESC
        """)

    products = cur.fetchall()

    cur.close()
    db.close()

    return render_template(
        "first.html",
        products=products,
        user=session.get("user"),
        search=search
    )


# ================== DELETE ACCOUNT (OTP CONFIRM) ==================
delete_otp_store = {}
OTP_EXPIRY = 120  # 2 minutes


@app.route("/delete-account/send-otp", methods=["POST"])
def delete_account_otp():
    if "user" not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    user = session["user"]
    session["user_id"] = user["id"]
    clean_expired_otps(change_pwd_otp_store)

    otp = str(random.randint(100000, 999999))

    delete_otp_store[user["id"]] = {
        "otp": otp,
        "time": time.time()
    }

    send_otp(user["email"], otp)
    return jsonify({"success": True})


@app.route("/delete-account/confirm", methods=["POST"])
def confirm_delete_account():
    if "user_id" not in session:
        return jsonify(success=False, error="Not logged in")

    data = request.get_json()
    user_otp = data.get("otp")

    record = delete_otp_store.get(session["user_id"])
    if not record:
        return jsonify(success=False, error="OTP expired")

    if time.time() - record["time"] > OTP_EXPIRY:
        delete_otp_store.pop(session["user_id"], None)
        return jsonify(success=False, error="OTP expired")

    if record["otp"] != user_otp:
        return jsonify(success=False, error="Invalid OTP")

    db = get_db()
    cur = db.cursor(dictionary=True)

    # 🔴 CHECK ACTIVE ORDERS
    cur.execute("""
        SELECT COUNT(*) AS active_orders
        FROM orders
        WHERE user_id = %s
        AND status NOT IN ('Cancelled', 'Completed')
    """, (session["user_id"],))

    if cur.fetchone()["active_orders"] > 0:
        return jsonify(
            success=False,
            error="You have active orders. Please cancel them before deleting your account."
        )

    # ✅ DELETE CHILD → PARENT (FK SAFE)
    cur.execute("""
        DELETE FROM order_items
        WHERE order_id IN (
            SELECT id FROM orders WHERE user_id = %s
        )
    """, (session["user_id"],))

    cur.execute("DELETE FROM orders WHERE user_id = %s", (session["user_id"],))
    cur.execute("DELETE FROM users WHERE id = %s", (session["user_id"],))
    db.commit()

    uid = session["user_id"]
    session.clear()
    delete_otp_store.pop(uid, None)

    return jsonify(success=True)





# ================== LOGIN / REGISTER PAGES ==================

@app.route("/login")
def login_page():
    return render_template("login.html")


# ================== SIGNUP WITH OTP ==================

import random, time, bcrypt
from flask import request, jsonify, render_template, redirect

# store OTP temporarily (in-memory)
signup_otp_store = {}
OTP_EXPIRY = 300  # 5 minutes


# 🔹 REGISTER PAGE
@app.route("/register")
def register_page():
    return render_template("register.html")


# 🔹 SIGNUP (SEND OTP)
@app.route("/signup", methods=["POST"])
def signup():
    data = request.json

    name = data.get("name")
    phone = data.get("phone")
    gender = data.get("gender")
    age = data.get("age")
    email = data.get("email")
    password = data.get("password")
    confirm_password = data.get("confirm_password")

    # basic validation
    if not all([name, phone, gender, age, email, password, confirm_password]):
        return jsonify({"success": False, "message": "All fields are required"})

    if password != confirm_password:
        return jsonify({"success": False, "message": "Passwords do not match"})

    db = get_db()
    cur = db.cursor()

    # check existing user
    cur.execute("SELECT id FROM users WHERE email=%s", (email,))
    if cur.fetchone():
        return jsonify({"success": False, "message": "Email already registered"})

    clean_expired_otps(signup_otp_store)

    # generate OTP
    otp = str(random.randint(100000, 999999))

    signup_otp_store[email] = {
        "otp": otp,
        "data": data,
        "time": time.time()
    }

    # send OTP to email
    send_otp(email, otp)

    return jsonify({"success": True})


# 🔹 VERIFY OTP PAGE (YOU ALREADY HAVE verify_otp.html)
@app.route("/verify")
def verify_page():
    return render_template("verify_otp.html")


# 🔹 VERIFY OTP & CREATE USER
@app.route("/verify-otp", methods=["POST"])
def verify_otp():
    data = request.json
    email = data.get("email")
    user_otp = data.get("otp")

    record = signup_otp_store.get(email)

    if not record:
        return jsonify({"success": False, "message": "OTP expired or invalid"})

    # check expiry
    if time.time() - record["time"] > OTP_EXPIRY:
        signup_otp_store.pop(email, None)
        return jsonify({"success": False, "message": "OTP expired"})

    # check OTP
    if record["otp"] != user_otp:
        return jsonify({"success": False, "message": "Invalid OTP"})

    user = record["data"]

    # hash password
    hashed_password = bcrypt.hashpw(
        user["password"].encode("utf-8"),
        bcrypt.gensalt()
    )

    db = get_db()
    cur = db.cursor()

    # create user
    cur.execute("""
        INSERT INTO users (name, phone, gender, age, email, password)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        user["name"],
        user["phone"],
        user["gender"],
        user["age"],
        user["email"],
        hashed_password
    ))


    db.commit()

    cur.close()
    db.close()

    # clear OTP record
    signup_otp_store.pop(email, None)

    return jsonify({"success": True})



# ================== USER LOGIN API ==================

@app.route("/api/login", methods=["POST"])
def login_api():
    data = request.get_json()

    if not data:
        return jsonify(success=False, message="Invalid request")

    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify(success=False, message="Email and password required")

    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute(
        "SELECT id, name, email, password FROM users WHERE email=%s",
        (email,)
    )
    user = cur.fetchone()

    cur.close()
    db.close()

    if not user:
        return jsonify(success=False, message="User not found")

    if bcrypt.checkpw(password.encode(), user["password"].encode()):
        session["user"] = {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"]
        }
        return jsonify(success=True)

    return jsonify(success=False, message="Wrong password")


# ================== USER PROFILE ==================

@app.route("/profile", methods=["GET", "POST"])
def profile():
    if not session.get("user"):
        return redirect("/login")

    user_id = session["user"]["id"]
    db = get_db()
    cur = db.cursor(dictionary=True)

    # 🔹 UPDATE PROFILE
    if request.method == "POST":
        name = request.form.get("name")
        gender = request.form.get("gender")
        age = request.form.get("age")

        cur.execute("""
            UPDATE users
            SET name=%s, gender=%s, age=%s
            WHERE id=%s
        """, (name,gender, age, user_id))

        db.commit()

        cur.close()
        db.close()

        # 🔥 Update session name (important for navbar)
        session["user"]["name"] = name

        return redirect("/profile")

    # 🔹 FETCH PROFILE DATA
    cur.execute("""
        SELECT name, email, phone, gender, age
        FROM users
        WHERE id=%s
    """, (user_id,))

    user = cur.fetchone()

    cur.close()
    db.close()

    return render_template("profile.html", user=user)



# ================== USER ADDRESS ==================

@app.route("/address", methods=["GET", "POST"])
def address():
    if not session.get("user"):
        return redirect("/login")

    user_id = session["user"]["id"]
    db = get_db()
    cur = db.cursor(dictionary=True)

    if request.method == "POST" and "delete_address" in request.form:
        cur.execute(
            "DELETE FROM addresses WHERE id=%s AND user_id=%s",
            (request.form["address_id"], user_id)
        )
        db.commit()
        return redirect("/address")

    if request.method == "POST" and "select_address" in request.form:
        cur.execute("UPDATE addresses SET is_default=0 WHERE user_id=%s", (user_id,))
        cur.execute(
            "UPDATE addresses SET is_default=1 WHERE id=%s AND user_id=%s",
            (request.form["address_id"], user_id)
        )
        db.commit()
        return redirect("/address")

    if request.method == "POST" and "save_address" in request.form:
        address_line = f"{request.form['flat']}, {request.form['street']}, {request.form.get('landmark','')}"
        address_id = request.form.get("address_id")

        if address_id:
            cur.execute("""
                UPDATE addresses
                SET full_name=%s, phone=%s, address_line=%s,
                    city=%s, state=%s, pincode=%s
                WHERE id=%s AND user_id=%s
            """, (
                request.form["full_name"],
                request.form["phone"],
                address_line,
                request.form["city"],
                request.form["state"],
                request.form["pincode"],
                address_id,
                user_id
            ))
        else:
            cur.execute("""
                INSERT INTO addresses
                (user_id, full_name, phone, address_line, city, state, pincode)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (
                user_id,
                request.form["full_name"],
                request.form["phone"],
                address_line,
                request.form["city"],
                request.form["state"],
                request.form["pincode"]
            ))

        db.commit()
        return redirect("/address")

    cur.execute(
        "SELECT * FROM addresses WHERE user_id=%s ORDER BY is_default DESC",
        (user_id,)
    )
    addresses = cur.fetchall()

    edit_address = None
    edit_id = request.args.get("edit")
    if edit_id:
        cur.execute(
            "SELECT * FROM addresses WHERE id=%s AND user_id=%s",
            (edit_id, user_id)
        )
        edit_address = cur.fetchone()

    return render_template("address.html", addresses=addresses, edit_address=edit_address)

# ================== PRODUCT DETAIL PAGE ==================

@app.route("/product_detail/<int:product_id>")
def product_detail(product_id):
    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("SELECT * FROM products WHERE id=%s", (product_id,))
    product = cur.fetchone()

    cur.close()
    db.close()

    if not product:
        return "Product not found", 404

    # 🔥 IMPORTANT: render YOUR existing template
    return render_template("product_detail.html", product=product)



# ================== ADD TO CART ==================

@app.route("/cart/<int:product_id>")
def add_to_cart(product_id):
    if "user" not in session:
        return redirect("/login")
    
    user_id = session["user"]["id"]
    buy_now = request.args.get("buy")

    db = get_db()
    cur = db.cursor(dictionary=True)

    # 🔒 STOCK SAFETY CHECK (PASTE HERE)
    cur.execute(
        "SELECT stock FROM products WHERE id=%s AND is_active=1",
        (product_id,)
    )
    product = cur.fetchone()


    if not product or product["stock"] <= 0:
        return redirect("/")

    # 🔍 Check if already in cart
    cur.execute(
        "SELECT id, quantity FROM cart WHERE user_id=%s AND product_id=%s",
        (user_id, product_id)
    )
    row = cur.fetchone()

    # ⚡ BUY NOW FLOW
    if buy_now:
        cur.execute(
            "DELETE FROM cart WHERE user_id=%s AND product_id=%s",
            (user_id, product_id)
        )
        cur.execute(
            "INSERT INTO cart (user_id, product_id, quantity) VALUES (%s,%s,1)",
            (user_id, product_id)
        )
        db.commit()
        return redirect("/checkout")

    # 🛒 NORMAL ADD TO CART FLOW
    if row:
        cur.execute(
            "UPDATE cart SET quantity = quantity + 1 WHERE id=%s",
            (row["id"],)
        )
    else:
        cur.execute(
            "INSERT INTO cart (user_id, product_id, quantity) VALUES (%s,%s,1)",
            (user_id, product_id)
        )

    db.commit()
    return redirect("/cart")


    


# ================== CART ==================

@app.route("/cart")
def view_cart():
    if "user" not in session:
        return redirect("/login")

    user_id = session["user"]["id"]
    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("""
        SELECT c.id cart_id, c.quantity,
               p.id product_id, p.product_name, p.price, p.image_url
        FROM cart c
        JOIN products p ON c.product_id = p.id
        WHERE c.user_id=%s
    """, (user_id,))
    items = cur.fetchall()

    cur.close()
    db.close()

    return render_template("cart.html", cart_items=items)


@app.route("/delete-cart-item/<int:cart_id>")
def delete_cart_item(cart_id):
    if not session.get("user"):
        return redirect("/login")

    user_id = session["user"]["id"]
    db = get_db()
    cur = db.cursor()

    cur.execute(
        "DELETE FROM cart WHERE id=%s AND user_id=%s",
        (cart_id, user_id)
    )
    db.commit()
    return redirect("/cart")


# ================== add quantity ==================
@app.route("/cart/increase/<int:cart_id>")
def cart_increase(cart_id):
    if "user" not in session:
        return redirect("/login")

    user_id = session["user"]["id"]

    db = get_db()
    cur = db.cursor(dictionary=True)

    # get cart item
    cur.execute("""
        SELECT c.product_id, c.quantity, p.stock
        FROM cart c
        JOIN products p ON p.id = c.product_id
        WHERE c.id=%s AND c.user_id=%s
    """, (cart_id, user_id))
    item = cur.fetchone()

    if not item:
        return redirect("/cart")

    # prevent exceeding stock
    if item["quantity"] >= item["stock"]:
        flash("Cannot add more. Stock limit reached.")
        return redirect("/cart")

    cur.execute(
        "UPDATE cart SET quantity = quantity + 1 WHERE id=%s",
        (cart_id,)
    )
    db.commit()

    return redirect("/cart")


# ================== Dicresead quantity ==================

@app.route("/cart/decrease/<int:cart_id>")
def cart_decrease(cart_id):
    if "user" not in session:
        return redirect("/login")

    user_id = session["user"]["id"]

    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("""
        SELECT quantity
        FROM cart
        WHERE id=%s AND user_id=%s
    """, (cart_id, user_id))
    item = cur.fetchone()

    if not item:
        return redirect("/cart")

    if item["quantity"] <= 1:
        # remove item if quantity becomes 0
        cur.execute("DELETE FROM cart WHERE id=%s", (cart_id,))
    else:
        cur.execute(
            "UPDATE cart SET quantity = quantity - 1 WHERE id=%s",
            (cart_id,)
        )

    db.commit()
    return redirect("/cart")



# ================== CHAT SUPPORT ==================

ADMIN_SUPPORT_EMAIL = "vermaalka705@gmail.com"

@app.route("/chat-support")
def chat_support():
    if not session.get("user"):
        return redirect("/login")

    return render_template("chat_support.html", user=session.get("user"))


@app.route("/chat-answer", methods=["POST"])
def chat_answer():
    data = request.json
    question = data.get("question", "").lower()

    replies = {
        "order": "📦 Your order status can be checked in My Orders section.",
        "refund": "💰 Refunds are processed within 5–7 working days after approval.",
        "delivery": "🚚 Delivery usually takes 3–6 working days.",
        "warranty": "🛡️ All refurbished products come with 6 months warranty.",
        "login": "🔐 Please reset your password or contact support if issue persists."
    }

    for key in replies:
        if key in question:
            return jsonify(reply=replies[key])

    return jsonify(reply=None)  # trigger manual support


@app.route("/chat-send-mail", methods=["POST"])
def chat_send_mail():
    if not session.get("user"):
        return redirect("/login")

    message = request.form.get("message")
    user = session["user"]

    full_message = f"""
    User Name: {user['name']}
    User Email: {user['email']}

    Issue:
    {message}
    """

    # reuse your existing email sender
    send_otp(ADMIN_SUPPORT_EMAIL, full_message)

    return jsonify(success=True)




# ================== CHECKOUT ==================

@app.route("/checkout")
def checkout():
    if not session.get("user"):
        return redirect("/login")

    user_id = session["user"]["id"]
    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("""
        SELECT c.quantity, p.product_name, p.price
        FROM cart c
        JOIN products p ON c.product_id = p.id
        WHERE c.user_id=%s
    """, (user_id,))
    cart_items = cur.fetchall()

    if not cart_items:
        return redirect("/cart")

    total = sum(i["price"] * i["quantity"] for i in cart_items)

    cur.execute("""
        SELECT * FROM addresses
        WHERE user_id=%s AND is_default=1
    """, (user_id,))
    address = cur.fetchone()

    cur.close()
    db.close()

    return render_template(
        "checkout.html",
        cart_items=cart_items,
        total=total,
        address=address,
        razorpay_key=os.environ.get("RAZORPAY_KEY_ID")
    )


# ================== PLACE ORDER ==================

@app.route("/place-order", methods=["POST"])
def place_order():

    if not session.get("user"):
        return redirect("/login")

    user_id = session["user"]["id"]
    payment_method = request.form.get("payment_method", "cod")

    db = get_db()
    cur = db.cursor(dictionary=True)

    try:

        # 🔒 VERIFY CART STOCK
        cur.execute("""
            SELECT c.product_id, c.quantity, p.stock
            FROM cart c
            JOIN products p ON p.id = c.product_id
            WHERE c.user_id=%s
        """, (user_id,))
        cart_items = cur.fetchall()

        if not cart_items:
            flash("Your cart is empty")
            return redirect("/cart")

        for item in cart_items:
            if item["quantity"] > item["stock"]:
                flash("One or more items are out of stock")
                return redirect("/cart")

        # 📍 GET DEFAULT ADDRESS
        cur.execute("""
            SELECT id
            FROM addresses
            WHERE user_id=%s AND is_default=1
        """, (user_id,))
        address = cur.fetchone()

        if not address:
            return redirect("/address")

        # 📦 GET CART ITEMS WITH PRICE
        cur.execute("""
            SELECT c.product_id, c.quantity, p.price
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.user_id=%s
        """, (user_id,))
        items = cur.fetchall()

        if not items:
            return redirect("/cart")

        # 💰 CALCULATE TOTAL
        total = sum(i["price"] * i["quantity"] for i in items)

        # 📝 CREATE ORDER
        cur.execute("""
            INSERT INTO orders (user_id, address_id, total_amount, payment_method)
            VALUES (%s,%s,%s,%s)
        """, (user_id, address["id"], total, payment_method))

        order_id = cur.lastrowid

        # 📦 INSERT ORDER ITEMS
        for i in items:

            cur.execute("""
                INSERT INTO order_items (order_id, product_id, quantity, price)
                VALUES (%s,%s,%s,%s)
            """, (order_id, i["product_id"], i["quantity"], i["price"]))

            # 🔻 UPDATE STOCK
            cur.execute("""
                UPDATE products
                SET stock = stock - %s
                WHERE id=%s
            """, (i["quantity"], i["product_id"]))

        # 🛒 CLEAR CART
        cur.execute("DELETE FROM cart WHERE user_id=%s", (user_id,))

        db.commit()

    finally:
        cur.close()
        db.close()

    flash("Order placed successfully!")

    return redirect("/orders")

# ================== ORDERS ==================

@app.route("/orders")
def orders():
    if not session.get("user"):
        return redirect("/login")

    user_id = session["user"]["id"]
    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("""
        SELECT * FROM orders
        WHERE user_id=%s
        ORDER BY created_at DESC
    """, (user_id,))
    orders = cur.fetchall()

    cur.close()
    db.close()

    return render_template("orders.html", orders=orders)


@app.route("/orders/<int:order_id>")
def order_detail(order_id):
    if not session.get("user"):
        return redirect("/login")

    user_id = session["user"]["id"]
    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("""
        SELECT o.*, a.full_name, a.phone, a.address_line,
               a.city, a.state, a.pincode
        FROM orders o
        JOIN addresses a ON o.address_id = a.id
        WHERE o.id=%s AND o.user_id=%s
    """, (order_id, user_id))
    order = cur.fetchone()

    if not order:
        return "Order not found", 404

    cur.execute("""
        SELECT p.product_name, oi.quantity, oi.price
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id=%s
    """, (order_id,))
    items = cur.fetchall()

    cur.close()
    db.close()

    return render_template("order_detail.html", order=order, items=items)

# ================== LOGOUT ==================

@app.route("/logout")
def logout():
    session.clear()   # clears user + admin session
    return redirect("/")


# ================== CHANGE PASSWORD USING EMAIL + OTP ==================

from flask import request, jsonify, render_template
import random, time, bcrypt

change_pwd_otp_store = {}
OTP_EXPIRY = 120  # 2 minutes


# 🔹 OPEN CHANGE PASSWORD PAGE
@app.route("/change_password", methods=["GET"])
def change_password_page():
    return render_template("change_password.html")


# 🔹 SEND OTP
@app.route("/change_password/send_otp", methods=["POST"])
def send_change_password_otp():
    data = request.get_json()

    email = data.get("email")
    new_password = data.get("new_password")

    if not email or not new_password:
        return jsonify({"error": "Email and password required"}), 400

    clean_expired_otps(delete_otp_store)
    otp = random.randint(100000, 999999)

    # store OTP in memory
    change_pwd_otp_store[email] = {
        "otp": str(otp),
        "password": new_password,
        "time": time.time()
    }

    # 🔴 TEMP DEBUG (remove later)
    print("OTP for", email, "=", otp)

    # 👉 replace this with your real email function
    send_otp(email, otp)

    return jsonify({"success": True})


# 🔹 VERIFY OTP & CHANGE PASSWORD
@app.route("/change_password/verify", methods=["POST"])
def verify_change_password():
    data = request.get_json()

    email = data.get("email")
    otp = data.get("otp")

    if not email or not otp:
        return jsonify({"error": "Email and OTP required"}), 400

    record = change_pwd_otp_store.get(email)
    if not record:
        return jsonify({"error": "OTP expired"}), 400

    # expiry check
    if time.time() - record["time"] > OTP_EXPIRY:
        change_pwd_otp_store.pop(email, None)
        return jsonify({"error": "OTP expired"}), 400

    # otp check
    if record["otp"] != otp:
        return jsonify({"error": "Invalid OTP"}), 400

    # hash password
    hashed_password = bcrypt.hashpw(
        record["password"].encode("utf-8"),
        bcrypt.gensalt()
    )

    # update password in DB
    db = get_db()
    cur = db.cursor()
    cur.execute(
        "UPDATE users SET password=%s WHERE email=%s",
        (hashed_password, email)
    )
    db.commit()

    change_pwd_otp_store.pop(email, None)

    return jsonify({"success": True})



# ================= ADMIN AUTH =================

from flask import request, jsonify, session, render_template, redirect

@app.route("/admin/login", methods=["GET"])
def admin_login_page():
    return render_template("admin_login.html")


@app.route("/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json()
    admin_id = data.get("admin_id")
    password = data.get("password")

    if not admin_id or not password:
        return jsonify({"success": False, "message": "Missing credentials"})

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM admins WHERE admin_id=%s", (admin_id,))
    admin = cur.fetchone()

    if not admin or admin["password"] != password:
        return jsonify({"success": False, "message": "Invalid Admin ID or Password"})

    session.clear()
    session["admin_id"] = admin["id"]
    session["admin_name"] = admin["admin_id"]

    return jsonify({"success": True})


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect("/admin/login")



# ================== Dashboard(ADMIN) ==================

@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    db = get_db()
    cur = db.cursor(dictionary=True)

    # 1. Total users
    cur.execute("SELECT COUNT(*) AS total_users FROM users")
    total_users = cur.fetchone()["total_users"]

    # 2. Pending orders (anything not completed)
    cur.execute("""
        SELECT COUNT(*) AS pending_orders
        FROM orders
        WHERE status != 'Completed'
    """)
    pending_orders = cur.fetchone()["pending_orders"]

    # 3. Completed orders
    cur.execute("""
        SELECT COUNT(*) AS completed_orders
        FROM orders
        WHERE status = 'Completed'
    """)
    completed_orders = cur.fetchone()["completed_orders"]

    cur.execute("""
        SELECT id, product_name, category, price, stock, is_active
        FROM products
        ORDER BY id DESC
    """)
    products = cur.fetchall()



    # 4. Cart items (not ordered yet)
    cur.execute("SELECT COUNT(*) AS cart_items FROM cart")
    cart_items = cur.fetchone()["cart_items"]

    # Products list
    cur.execute("SELECT * FROM products ORDER BY id DESC")
    products = cur.fetchall()

    cur.close()
    db.close()

    return render_template(
        "admin_dashboard.html",
        total_users=total_users,
        pending_orders=pending_orders,
        completed_orders=completed_orders,
        cart_items=cart_items,
        products=products
    )


# ================== Pending Orders(Admin) ==================

@app.route("/admin/orders/pending")
@admin_required
def admin_pending_orders():
    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("""
        SELECT o.*, u.name, u.email
        FROM orders o
        JOIN users u ON o.user_id = u.id
        WHERE o.status != 'Completed'
        ORDER BY o.created_at DESC
    """)
    orders = cur.fetchall()

    cur.close()
    db.close()

    return render_template(
        "admin_orders.html",
        orders=orders,
        title="Pending Orders"
    )

# ================== Completed Orders(Admin) ==================

@app.route("/admin/orders/completed")
@admin_required
def admin_completed_orders():
    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("""
        SELECT o.*, u.name, u.email
        FROM orders o
        JOIN users u ON o.user_id = u.id
        WHERE o.status = 'Completed'
        ORDER BY o.created_at DESC
    """)
    orders = cur.fetchall()

    cur.close()
    db.close()

    return render_template(
        "admin_orders.html",
        orders=orders,
        title="Completed Orders"
    )

# ================== Admin_Orders(Admin) ==================

@app.route("/admin/orders/<int:order_id>", methods=["GET", "POST"])
@admin_required
def admin_order_detail(order_id):
    db = get_db()
    cur = db.cursor(dictionary=True)

    # Update status
    if request.method == "POST":
        new_status = request.form.get("status")

        cur.execute(
            "UPDATE orders SET status=%s WHERE id=%s",
            (new_status, order_id)
        )

        cur.execute(
            "INSERT INTO order_status_history (order_id, status) VALUES (%s, %s)",
            (order_id, new_status)
        )

        db.commit()

    # Order
    cur.execute("""
        SELECT o.*, u.name, u.email
        FROM orders o
        JOIN users u ON o.user_id = u.id
        WHERE o.id=%s
    """, (order_id,))
    order = cur.fetchone()

    # Address
    cur.execute("SELECT * FROM addresses WHERE id=%s", (order["address_id"],))
    address = cur.fetchone()

    # Items
    cur.execute("""
        SELECT oi.*, p.product_name
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id=%s
    """, (order_id,))
    items = cur.fetchall()

    # Status history
    cur.execute("""
        SELECT * FROM order_status_history
        WHERE order_id=%s
        ORDER BY changed_at DESC
    """, (order_id,))
    history = cur.fetchall()

    cur.close()
    db.close()

    return render_template(
        "admin_order_detail.html",
        order=order,
        address=address,
        items=items,
        history=history
    )


# ================== Admin_user detail==================

@app.route("/admin/users")
@admin_required
def admin_users():
    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("""
        SELECT id, name, email, phone, created_at
        FROM users
        ORDER BY created_at DESC
    """)
    users = cur.fetchall()

    cur.close()
    db.close()

    return render_template("admin_users.html", users=users)


# ================== Admin/cart==================

@app.route("/admin/cart")
@admin_required
def admin_cart():
    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("""
        SELECT c.id, u.name, u.email, p.product_name, c.quantity, c.added_at
        FROM cart c
        JOIN users u ON c.user_id = u.id
        JOIN products p ON c.product_id = p.id
        ORDER BY c.added_at DESC
    """)
    cart_items = cur.fetchall()

    cur.close()
    db.close()

    return render_template("admin_cart.html", cart_items=cart_items)

# ================== Add Product (Admin) ==================
import os
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = "static/uploads"

@app.route("/admin/add-product", methods=["GET", "POST"])
@admin_required
def admin_add_product():

    if request.method == "GET":
        return render_template("add_product.html", product=None)

    # -------- SAVE PRODUCT --------
    image = request.files.get("image")
    filename = None

    if image and image.filename:
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        filename = secure_filename(image.filename)
        image.save(os.path.join(UPLOAD_FOLDER, filename))

    db = get_db()
    cur = db.cursor()

    cur.execute("""
        INSERT INTO products (
            product_name,
            category,
            material,
            stone_type,
            weight,
            occasion,
            sku,
            price,
            stock,
            image_url
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        request.form["product_name"],
        request.form["category"],
        request.form["material"],
        request.form.get("stone_type"),
        request.form.get("weight"),
        request.form.get("occasion"),
        request.form.get("sku"),
        request.form["price"],
        request.form["stock"],
        filename
    ))
    db.commit()

    cur.close()
    db.close()

    return redirect("/admin/dashboard")


# ================== EDIT PRODUCT (ADMIN) ==================
@app.route("/admin/edit-product/<int:product_id>", methods=["GET", "POST"])
@admin_required
def admin_edit_product(product_id):

    db = get_db()
    cur = db.cursor(dictionary=True)

    # -------- GET PRODUCT --------
    cur.execute("SELECT * FROM products WHERE id=%s", (product_id,))
    product = cur.fetchone()

    if not product:
        return redirect("/admin/dashboard")

    # -------- SHOW FORM --------
    if request.method == "GET":
        return render_template("add_product.html", product=product)

    # -------- UPDATE PRODUCT --------
    image = request.files.get("image")
    filename = product["image_url"]

    if image and image.filename:
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        filename = secure_filename(image.filename)
        image.save(os.path.join(UPLOAD_FOLDER, filename))

    cur.execute("""
        UPDATE products SET
            product_name=%s,
            category=%s,
            material=%s,
            stone_type=%s,
            weight=%s,
            occasion=%s,
            sku=%s,
            price=%s,
            stock=%s,
            image_url=%s
        WHERE id=%s
    """, (
        request.form["product_name"],
        request.form["category"],
        request.form["material"],
        request.form.get("stone_type"),
        request.form.get("weight"),
        request.form.get("occasion"),
        request.form.get("sku"),
        request.form["price"],
        request.form["stock"],
        filename,
        product_id
    ))

    db.commit()

    cur.close()
    db.close()

    return redirect("/admin/dashboard")


# ================== Disable Product (Admin) ==================
@app.route("/admin/disable-product/<int:product_id>", methods=["POST"])
@admin_required
def admin_disable_product(product_id):

    db = get_db()
    cur = db.cursor()

    cur.execute(
        "UPDATE products SET is_active = 0 WHERE id = %s",
        (product_id,)
    )
    db.commit()

    return redirect("/admin/dashboard")


# ================== Enable Product (Admin) ==================
@app.route("/admin/enable-product/<int:product_id>", methods=["POST"])
@admin_required
def admin_enable_product(product_id):

    db = get_db()
    cur = db.cursor()

    cur.execute(
        "UPDATE products SET is_active = 1 WHERE id = %s",
        (product_id,)
    )
    db.commit()

    return redirect("/admin/dashboard")

# ================== Order_track ==================
@app.route("/order_track/<int:order_id>")
def order_track(order_id):

    # 🔐 Login check
    if "user" not in session:
        return redirect("/login")

    user_id = session["user"]["id"]

    db = get_db()
    cur = db.cursor(dictionary=True)

    # 🔎 Fetch order (security: must belong to user)
    cur.execute("""
        SELECT *
        FROM orders
        WHERE id=%s AND user_id=%s
    """, (order_id, user_id))

    order = cur.fetchone()

    if not order:
        return redirect("/orders")

    # 📦 Fetch order items
    cur.execute("""
        SELECT 
            p.product_name,
            oi.quantity,
            oi.price
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        WHERE oi.order_id=%s
    """, (order_id,))

    items = cur.fetchall()

    cur.close()
    db.close()

    return render_template(
        "order_track.html",
        order=order,
        items=items
    )

# ================== Cancle button ==================

@app.route("/order/cancel/<int:order_id>", methods=["POST"])
def cancel_order(order_id):
    if "user" not in session:
        return redirect("/login")

    user_id = session["user"]["id"]
    reason = request.form.get("reason")

    db = get_db()
    cur = db.cursor(dictionary=True)

    try:
        # 🔒 LOCK ORDER ROW FIRST
        cur.execute("""
            SELECT * FROM orders
            WHERE id=%s AND user_id=%s
            FOR UPDATE
        """, (order_id, user_id))
        order = cur.fetchone()

        if not order:
            return redirect("/orders")

        if order["status"] in ("Shipped", "Completed", "Cancelled"):
            flash("Order cannot be cancelled now")
            return redirect(f"/order_track/{order_id}")

        # 📦 LOCK ORDER ITEMS
        cur.execute("""
            SELECT product_id, quantity
            FROM order_items
            WHERE order_id=%s
            FOR UPDATE
        """, (order_id,))
        items = cur.fetchall()

        # ❌ UPDATE ORDER STATUS
        cur.execute(
            "UPDATE orders SET status='Cancelled' WHERE id=%s",
            (order_id,)
        )

        # 📝 SAVE CANCELLATION
        cur.execute("""
            INSERT INTO order_cancellations (order_id, user_id, reason)
            VALUES (%s,%s,%s)
        """, (order_id, user_id, reason))

        # 🔄 RESTORE STOCK
        for item in items:
            cur.execute("""
                UPDATE products
                SET stock = stock + %s
                WHERE id=%s
            """, (item["quantity"], item["product_id"]))

        db.commit()  # ✅ VERY IMPORTANT

        flash("Order cancelled successfully")
        return redirect(f"/order_track/{order_id}")

    except Exception as e:
        db.rollback()  # 🔥 RELEASE LOCKS
        print("CANCEL ERROR:", e)
        flash("Something went wrong. Try again.")
        return redirect(f"/order_track/{order_id}")





# ================== Invoice Page ==================

@app.route("/invoice/<int:order_id>")
def invoice(order_id):

    if "user" not in session:
        return redirect("/login")

    user_id = session["user"]["id"]

    db = get_db()
    cur = db.cursor(dictionary=True)

    # Fetch order
    cur.execute("""
        SELECT *
        FROM orders
        WHERE id=%s AND user_id=%s AND status='Completed'
    """, (order_id, user_id))
    order = cur.fetchone()

    if not order:
        return redirect("/orders")

    # Fetch address
    cur.execute("""
        SELECT *
        FROM addresses
        WHERE id=%s
    """, (order["address_id"],))
    address = cur.fetchone()

    # Fetch items
    cur.execute("""
        SELECT p.product_name, oi.quantity, oi.price
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        WHERE oi.order_id=%s
    """, (order_id,))
    items = cur.fetchall()

    cur.close()
    db.close()

    return render_template(
        "invoice.html",
        order=order,
        address=address,
        items=items
    )


# ==================PDF download ==================

@app.route("/invoice/<int:order_id>")
def invoice_page(order_id):

    if "user" not in session:
        return redirect("/login")

    user_id = session["user"]["id"]

    db = get_db()
    cur = db.cursor(dictionary=True)

    # ✅ Only completed orders
    cur.execute("""
        SELECT *
        FROM orders
        WHERE id=%s AND user_id=%s AND status='Completed'
    """, (order_id, user_id))
    order = cur.fetchone()

    if not order:
        return redirect("/orders")

    # Address
    cur.execute(
        "SELECT * FROM addresses WHERE id=%s",
        (order["address_id"],)
    )
    address = cur.fetchone()

    # Order items
    cur.execute("""
        SELECT 
            p.product_name,
            oi.quantity,
            oi.price,
            (oi.quantity * oi.price) AS total
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        WHERE oi.order_id=%s
    """, (order_id,))
    items = cur.fetchall()
    print("INVOICE ITEMS:", items)

    cur.close()
    db.close()

    return render_template(
        "invoice.html",
        order=order,
        address=address,
        items=items
    )

# ================== CREATE RAZORPAY ORDER ==================

@app.route("/create-razorpay-order", methods=["POST"])
def create_razorpay_order():

    if not session.get("user"):
        return jsonify({"error": "login_required"}), 401

    user_id = session["user"]["id"]

    db = get_db()
    cur = db.cursor(dictionary=True)

    # get cart items
    cur.execute("""
        SELECT c.quantity, p.price
        FROM cart c
        JOIN products p ON c.product_id = p.id
        WHERE c.user_id=%s
    """, (user_id,))
    items = cur.fetchall()

    if not items:
        cur.close()
        db.close()
        return jsonify({"error": "cart_empty"})

    total = sum(i["price"] * i["quantity"] for i in items)

    amount = int(total * 100)  # Razorpay uses paise

    order = client.order.create({
        "amount": amount,
        "currency": "INR",
        "payment_capture": 1
    })

    cur.close()
    db.close()

    return jsonify(order)




# ================== RUN ==================

if __name__ == "__main__":
    app.run(debug=True)
