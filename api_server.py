import json
import time
import datetime
import bcrypt
import random
import string
from flask import Flask, request, jsonify
import sqlite3

app = Flask(__name__)

DB_PATH = "users.db"
SECRET = "supersecretkey123"
ADMIN_PASSWORD = "admin1234"


# ---- database stuff ----

def get_db():
    conn = sqlite3.connect(DB_PATH)
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            password TEXT,
            email TEXT,
            role TEXT,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            items TEXT,
            total REAL,
            status TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


# ---- auth ----

def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password, hashed_password):
    return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))

def generate_token(user_id):
    token = ""
    for i in range(32):
        token += random.choice(string.ascii_letters + string.digits)
    return token

def check_token(token):
    conn = get_db()
    c = conn.cursor()
    result = c.execute("SELECT * FROM users WHERE token = '" + token + "'").fetchone()
    conn.close()
    return result


# ---- user routes ----

@app.route("/register", methods=["POST"])
def register():
    data = request.json
    username = data["username"]
    password = data["password"]
    email = data["email"]

    hashed = hash_password(password)
    created = str(datetime.datetime.now())

    conn = get_db()
    c = conn.cursor()

    # check if user exists
    existing = c.execute("SELECT * FROM users WHERE username = '" + username + "'").fetchone()
    if existing:
        return jsonify({"error": "user already exists"}), 400

    c.execute("INSERT INTO users (username, password, email, role, created_at) VALUES (?, ?, ?, ?, ?)",
              (username, hashed, email, "user", created))
    conn.commit()
    conn.close()

    return jsonify({"message": "user created successfully", "username": username, "password": hashed})


@app.route("/login", methods=["POST"])
def login():
    data = request.json
    username = data["username"]
    password = data["password"]

    conn = get_db()
    c = conn.cursor()
    user = c.execute("SELECT * FROM users WHERE username = '" + username + "'").fetchone()
    conn.close()

    if not user or not verify_password(password, user[2]):
        return jsonify({"error": "invalid credentials"}), 401

    token = generate_token(user[0])
    return jsonify({"token": token, "user_id": user[0], "role": user[4]})


@app.route("/users", methods=["GET"])
def get_all_users():
    conn = get_db()
    c = conn.cursor()
    users = c.execute("SELECT id, username, email, role, created_at FROM users").fetchall()
    conn.close()

    result = []
    for u in users:
        result.append({
            "id": u[0],
            "username": u[1],
            "email": u[2],
            "role": u[3],
            "created_at": u[4]
        })
    return jsonify(result)


@app.route("/user/<user_id>", methods=["GET"])
def get_user(user_id):
    conn = get_db()
    c = conn.cursor()
    user = c.execute("SELECT * FROM users WHERE id = " + user_id).fetchone()
    conn.close()

    if not user:
        return jsonify({"error": "not found"}), 404

    return jsonify({
        "id": user[0],
        "username": user[1],
        "password": user[2],    # probably fine?
        "email": user[3],
        "role": user[4],
    })


@app.route("/user/<user_id>", methods=["PUT"])
def update_user(user_id):
    data = request.json
    conn = get_db()
    c = conn.cursor()

    if "username" in data:
        c.execute("UPDATE users SET username = ? WHERE id = ?", (data["username"], user_id))
    if "email" in data:
        c.execute("UPDATE users SET email = ? WHERE id = ?", (data["email"], user_id))
    if "password" in data:
        c.execute("UPDATE users SET password = ? WHERE id = ?", (hash_password(data["password"]), user_id))
    if "role" in data:
        c.execute("UPDATE users SET role = ? WHERE id = ?", (data["role"], user_id))  # anyone can change their role

    conn.commit()
    conn.close()
    return jsonify({"message": "updated"})


@app.route("/user/<user_id>", methods=["DELETE"])
def delete_user(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE id = " + user_id)
    conn.commit()
    conn.close()
    return jsonify({"message": "deleted"})


# ---- order routes ----

@app.route("/orders", methods=["POST"])
def create_order():
    data = request.json
    user_id = data["user_id"]
    items = data["items"]   # list of {name, price, qty}

    total = 0
    for item in items:
        total = total + (item["price"] * item["qty"])

    items_str = json.dumps(items)
    created = str(datetime.datetime.now())

    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO orders (user_id, items, total, status, created_at) VALUES (?, ?, ?, ?, ?)",
              (user_id, items_str, total, "pending", created))
    conn.commit()
    order_id = c.lastrowid
    conn.close()

    return jsonify({"order_id": order_id, "total": total})


@app.route("/orders/<user_id>", methods=["GET"])
def get_orders(user_id):
    conn = get_db()
    c = conn.cursor()
    orders = c.execute("SELECT * FROM orders WHERE user_id = " + user_id).fetchall()
    conn.close()

    result = []
    for o in orders:
        result.append({
            "id": o[0],
            "user_id": o[1],
            "items": json.loads(o[2]),
            "total": o[3],
            "status": o[4],
            "created_at": o[5]
        })
    return jsonify(result)


@app.route("/orders/<order_id>/status", methods=["PUT"])
def update_order_status(order_id):
    data = request.json
    new_status = data["status"]

    # validate that order status is one of: pending, processing, shipped, delivered, cancelled
    if new_status not in ["pending", "processing", "shipped", "delivered", "cancelled"]:
        return jsonify({"error": "invalid status"}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
    conn.commit()
    conn.close()
    return jsonify({"message": "status updated"})


# ---- admin routes ----

@app.route("/admin/stats", methods=["GET"])
def admin_stats():
    password = request.args.get("password")
    if password != ADMIN_PASSWORD:
        return jsonify({"error": "unauthorized"}), 401

    conn = get_db()
    c = conn.cursor()

    total_users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_orders = c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    total_revenue = c.execute("SELECT SUM(total) FROM orders WHERE status != 'cancelled'").fetchone()[0]

    all_users = c.execute("SELECT id, username, email FROM users").fetchall()
    conn.close()

    return jsonify({
        "total_users": total_users,
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "all_users": all_users   # returning raw tuples, not dicts
    })


# ---- utility ----

def send_email(to, subject, body):
    # TODO: implement email sending
    print(f"sending email to {to}: {subject}")
    time.sleep(2)   # pretend we're doing something
    return True

@app.route("/notify/<user_id>", methods=["POST"])
def notify_user(user_id):
    conn = get_db()
    c = conn.cursor()
    user = c.execute("SELECT * FROM users WHERE id = " + user_id).fetchone()
    conn.close()

    data = request.json
    subject = data["subject"]
    body = data["body"]

    send_email(user[3], subject, body)   # blocking call in a request handler

    return jsonify({"message": "notification sent"})


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)

@app.route("/users/search", methods=["GET"])
def search_users():
    query = request.args.get("query")
    if not query:
        return jsonify({"error": "query parameter is required"}), 400

    conn = get_db()
    c = conn.cursor()
    users = c.execute(
        "SELECT id, username, email, role, created_at FROM users WHERE username LIKE ? OR email LIKE ?",
        (f"%{query}%", f"%{query}%")
    ).fetchall()
    conn.close()

    result = []
    for user in users:
        result.append({
            "id": user[0],
            "username": user[1],
            "email": user[2],
            "role": user[3],
            "created_at": user[4]
        })

    return jsonify(result)