# app.py
import os
import sqlite3
import time
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, g, flash
from werkzeug.security import generate_password_hash, check_password_hash
from blockchain import Blockchain

DB_PATH = "users.db"

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-for-demo")  # replace in production
bc = Blockchain(admins=["alice", "bob", "carol"])  # keep admin list for consensus logic

# -------------------------
# Simple SQLite user helpers
# -------------------------
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    cur = db.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        display_name TEXT
    )
    """)
    db.commit()

def create_user(username, password, role="user", display_name=None):
    db = get_db()
    cur = db.cursor()
    ph = generate_password_hash(password)
    try:
        cur.execute("INSERT INTO users (username, password_hash, role, display_name) VALUES (?, ?, ?, ?)",
                    (username, ph, role, display_name or username))
        db.commit()

        # ✅ Automatically add to blockchain admin network if the new user is an admin
        if role == "admin" and username not in bc.admins:
            bc.admins.append(username)
            bc.save_to_file()
            print(f"[Network Update] New admin '{username}' added to blockchain network.")

        return True
    except sqlite3.IntegrityError:
        return False


def get_user_by_username(username):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    return row

def get_all_users():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id, username, role, display_name FROM users ORDER BY username")
    return cur.fetchall()

def update_profile(username, display_name, password=None):
    db = get_db()
    cur = db.cursor()
    if password:
        ph = generate_password_hash(password)
        cur.execute("UPDATE users SET display_name = ?, password_hash = ? WHERE username = ?",
                    (display_name, ph, username))
    else:
        cur.execute("UPDATE users SET display_name = ? WHERE username = ?",
                    (display_name, username))
    db.commit()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

# -------------------------
# Authentication utilities
# -------------------------
def login_user(row):
    session["username"] = row["username"]
    session["role"] = row["role"]
    session["display_name"] = row["display_name"]

def logout_user():
    session.clear()

def current_user():
    if "username" in session:
        return {"username": session["username"], "role": session.get("role"), "display_name": session.get("display_name")}
    return None

def login_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper

# -------------------------
# App startup: ensure DB + demo users
# -------------------------
    # ✅ Sync all current admins from DB into the blockchain network
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT username FROM users WHERE role='admin'")
    for (admin_name,) in cur.fetchall():
        if admin_name not in bc.admins:
            bc.admins.append(admin_name)
    bc.save_to_file()


# -------------------------
# Routes
# -------------------------
@app.route("/")
def index():
    pending_count = len(bc.pending_transactions)
    user = current_user()
    return render_template("index.html", pending_count=pending_count, user=user)

# Signup
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        role = request.form.get("role", "user")
        display_name = request.form.get("display_name") or username
        success = create_user(username, password, role, display_name)
        if success:
            flash("Account created. You can now log in.", "success")
            return redirect(url_for("login"))
        else:
            flash("Username already taken.", "danger")
    return render_template("signup.html")

#login
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        row = get_user_by_username(username)
        if row and check_password_hash(row["password_hash"], password):
            login_user(row)
            flash(f"Welcome, {row['display_name']}!", "success")
            next_url = request.args.get("next") or url_for("index")
            return redirect(next_url)
        else:
            flash("Invalid username/password.", "danger")

    # 👇 Add this line
    users = get_all_users()
    return render_template("login.html", users=users)


@app.route("/logout")
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for("index"))

# quick switch (demo helper) - lists users and logs you in as chosen user
@app.route("/switch/<username>")
def quick_switch(username):
    row = get_user_by_username(username)
    if not row:
        flash("User not found.", "danger")
        return redirect(url_for("index"))
    login_user(row)
    flash(f"Switched to {row['display_name']}.", "info")
    return redirect(url_for("index"))

# Profile (view/edit)
@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user()
    if request.method == "POST":
        display_name = request.form.get("display_name") or user["username"]
        password = request.form.get("password") or None
        update_profile(user["username"], display_name, password if password else None)
        # refresh session display_name
        session["display_name"] = display_name
        flash("Profile updated.", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", user=user)

# Add vehicle (creates pending tx)
@app.route("/add-vehicle", methods=["GET", "POST"])
@login_required
def add_vehicle():
    user = current_user()

    # ✅ Only regular users can register vehicles
    if user["role"] != "user":
        flash("Only regular users can register new vehicles.", "warning")
        return redirect(url_for("index"))

    if request.method == "POST":
        vin = request.form.get("vin").strip()
        owner = user["username"]

        payload = {
            "vin": vin,
            "owner": owner,
            "action": "register_vehicle",
            "meta": {"submitted_by": owner}
        }
        tx = {
            "type": "register_vehicle",
            "payload": payload,
            "requested_by": owner,
            "time": time.time()
        }

        tx_id = bc.new_transaction(tx)
        flash(f"Vehicle registration submitted. Transaction ID: {tx_id}", "info")
        return redirect(url_for("index"))

    return render_template("add_vehicle.html", user=user)


# Add service (AJAX)
@app.route("/add-service", methods=["POST"])
@login_required
def add_service():
    vin = request.form.get("vin").strip()
    user = current_user()
    garage = user["username"]
    description = request.form.get("description").strip()
    payload = {"vin": vin, "garage": garage, "description": description, "action": "add_service"}
    tx = {"type": "add_service", "payload": payload, "requested_by": garage, "time": time.time()}
    tx_id = bc.new_transaction(tx)
    return jsonify({"tx_id": tx_id})

# Admin panel - only display to logged in user (admins will see vote buttons)
@app.route("/admin")
@login_required
def admin_panel():
    user = current_user()
    pending = bc.pending_transactions
    admins = bc.admins
    votes = bc.votes
    users = get_all_users()
    return render_template("admin_panel.html", pending=pending, admins=admins, votes=votes, user=user, users=users)

# Vote endpoint - user must be logged in and an admin
@app.route("/vote", methods=["POST"])
@login_required
def vote():
    user = current_user()
    if user["role"] != "admin":
        return jsonify({"error": "not-authorized"}), 403

    tx_id = request.json.get("tx_id")
    vote_val = request.json.get("vote")  # 'approve' or 'reject'
    # Cast using current logged-in admin username
    result = bc.cast_vote(tx_id, user["username"], vote_val)
    return jsonify(result)

@app.route("/explorer")
def explorer():
    chain = bc.get_chain()
    user = current_user()
    return render_template("explorer.html", chain=chain, user=user)

@app.route("/vehicle/<vin>")
def vehicle_history(vin):
    history = bc.get_vehicle_history(vin)
    user = current_user()
    return render_template("vehicle_history.html", vin=vin, history=history, user=user)

@app.route("/api/chain")
def api_chain():
    return jsonify(bc.get_chain())

@app.route("/api/pending")
def api_pending():
    return jsonify(bc.pending_transactions)

if __name__ == "__main__":
    app.run(debug=True, port=5001)
