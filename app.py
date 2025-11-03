# app.py
import os
import sqlite3
import time
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, g, flash
from werkzeug.security import generate_password_hash, check_password_hash
from blockchain import Blockchain

DB_PATH = "users.db"

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-for-demo")

# initialize blockchain with default admins (these will be synced with DB on startup)
bc = Blockchain(admins=["alice", "bob", "carol"], garages=[])

# --- DB helpers ---
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

def get_user_by_username(username):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (username,))
    return cur.fetchone()

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

def create_user(username, password, role="user", display_name=None):
    db = get_db()
    cur = db.cursor()
    ph = generate_password_hash(password)
    try:
        cur.execute("INSERT INTO users (username, password_hash, role, display_name) VALUES (?, ?, ?, ?)",
                    (username, ph, role, display_name or username))
        db.commit()
        # If new admin, add to bc.admins
        if role == "admin" and username not in bc.admins:
            bc.admins.append(username)
            bc.save_to_file()
            print(f"[Network Update] New admin '{username}' added to blockchain network.")
        # If new garage, add to bc.garages
        if role == "garage" and username not in bc.garages:
            bc.garages.append(username)
            bc.save_to_file()
            print(f"[Network Update] New garage '{username}' added to garage network.")
        return True
    except sqlite3.IntegrityError:
        return False

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

# --- Auth helpers ---
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

# --- App startup & demo users ---
with app.app_context():
    init_db()
    # create demo users if missing
    for u, role in [("alice", "admin"), ("bob", "admin"), ("carol", "admin"), ("owner1", "user")]:
        if not get_user_by_username(u):
            create_user(u, "password", role=role, display_name=u.capitalize())
    # Sync admins and garages from DB into blockchain
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT username FROM users WHERE role='admin'")
    for (admin_name,) in cur.fetchall():
        if admin_name not in bc.admins:
            bc.admins.append(admin_name)
    cur.execute("SELECT username FROM users WHERE role='garage'")
    for (garage_name,) in cur.fetchall():
        if garage_name not in bc.garages:
            bc.garages.append(garage_name)
    bc.save_to_file()

# --- Routes ---
@app.route("/")
def index():
    pending_count = len(bc.pending_transactions)
    user = current_user()
    return render_template("index.html", pending_count=pending_count, user=user)

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username").strip()
        password = request.form.get("password")
        role = request.form.get("role", "user")
        display_name = request.form.get("display_name") or username
        
        # If role is garage, create a proposal transaction instead
        if role == "garage":
            payload = {
                "username": username,
                "password": password,  # Store for later user creation
                "display_name": display_name,
                "action": "propose_garage",
                "proposed_by": "signup"
            }
            tx = {
                "type": "propose_garage",
                "payload": payload,
                "requested_by": "signup",
                "time": time.time()
            }
            tx_id = bc.new_transaction(tx)
            flash(f"Garage registration submitted for admin approval. Transaction ID: {tx_id}", "info")
            return redirect(url_for("login"))
        else:
            # Regular user or admin creation
            success = create_user(username, password, role, display_name)
            if success:
                flash("Account created. You can now log in.", "success")
                return redirect(url_for("login"))
            else:
                flash("Username already taken.", "danger")
    return render_template("signup.html")

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

    users = get_all_users()
    return render_template("login.html", users=users)

@app.route("/logout")
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for("index"))

@app.route("/switch/<username>")
def quick_switch(username):
    row = get_user_by_username(username)
    if not row:
        flash("User not found.", "danger")
        return redirect(url_for("index"))
    login_user(row)
    flash(f"Switched to {row['display_name']}.", "info")
    return redirect(url_for("index"))

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user()
    if request.method == "POST":
        display_name = request.form.get("display_name") or user["username"]
        password = request.form.get("password") or None
        update_profile(user["username"], display_name, password if password else None)
        session["display_name"] = display_name
        flash("Profile updated.", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", user=user)

# --- Register vehicle (users only) ---
@app.route("/add-vehicle", methods=["GET", "POST"])
@login_required
def add_vehicle():
    user = current_user()
    if user["role"] != "user":
        flash("Only regular users can register new vehicles.", "warning")
        return redirect(url_for("index"))
    if request.method == "POST":
        vin = request.form.get("vin").strip().upper()
        owner = user["username"]
        payload = {"vin": vin, "owner": owner, "action": "register_vehicle", "meta": {"submitted_by": owner}}
        tx = {"type": "register_vehicle", "payload": payload, "requested_by": owner, "time": time.time()}
        tx_id = bc.new_transaction(tx)
        flash(f"Vehicle registration submitted. Transaction ID: {tx_id}", "info")
        return redirect(url_for("index"))
    return render_template("add_vehicle.html", user=user)

# --- Propose garage (admins) ---
@app.route("/add-garage", methods=["GET", "POST"])
@login_required
def add_garage():
    user = current_user()
    if user["role"] != "admin":
        flash("Only admins can propose a new garage.", "warning")
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username").strip()
        display_name = request.form.get("display_name").strip() or username
        password = request.form.get("password", "password")
        payload = {
            "username": username,
            "password": password,
            "display_name": display_name,
            "action": "propose_garage",
            "proposed_by": user["username"]
        }
        tx = {"type": "propose_garage", "payload": payload, "requested_by": user["username"], "time": time.time()}
        tx_id = bc.new_transaction(tx)
        flash(f"Garage proposal submitted as transaction: {tx_id}", "info")
        return redirect(url_for("admin_panel"))
    return render_template("add_garage.html", user=user)

# --- Garage submits service record (garages only) ---
@app.route("/garage/add-service", methods=["GET", "POST"])
@login_required
def garage_add_service():
    user = current_user()
    if user["role"] != "garage":
        flash("Only garages can submit service records.", "warning")
        return redirect(url_for("index"))
    if request.method == "POST":
        vin = request.form.get("vin").strip().upper()
        description = request.form.get("description").strip()
        payload = {
            "vin": vin,
            "garage": user["username"],
            "description": description,
            "action": "add_service",
            "submitted_by": user["username"]
        }
        tx = {
            "type": "add_service",
            "payload": payload,
            "requested_by": user["username"],
            "time": time.time()
        }
        tx_id = bc.new_transaction(tx)
        flash(f"Service record submitted for garage consensus. Transaction ID: {tx_id}", "info")
        return redirect(url_for("garage_panel"))
    return render_template("garage_add_service.html", user=user)

# --- Garage panel (shows pending service txs) ---
@app.route("/garage")
@login_required
def garage_panel():
    user = current_user()
    if user["role"] != "garage":
        flash("Only garages can access this panel.", "warning")
        return redirect(url_for("index"))
    
    # Filter pending transactions for service records only
    pending = [tx for tx in bc.pending_transactions if tx["tx"]["type"] == "add_service"]
    garages = bc.garages
    votes = bc.votes
    return render_template("garage_panel.html", pending=pending, garages=garages, votes=votes, user=user)

# --- Admin panel (shows pending txs) ---
@app.route("/admin")
@login_required
def admin_panel():
    user = current_user()
    # Filter pending transactions for admin-relevant types
    pending = [tx for tx in bc.pending_transactions if tx["tx"]["type"] in ("register_vehicle", "propose_garage")]
    admins = bc.admins
    votes = bc.votes
    users = get_all_users()
    return render_template("admin_panel.html", pending=pending, admins=admins, votes=votes, user=user, users=users)

# --- Vote endpoint ---
@app.route("/vote", methods=["POST"])
@login_required
def vote():
    user = current_user()
    tx_id = request.json.get("tx_id")
    vote_val = request.json.get("vote")

    # find tx type to decide who can vote
    tx_record = next((t for t in bc.pending_transactions if t["tx_id"] == tx_id), None)
    tx_type = tx_record["tx"]["type"] if tx_record else None

    # permission checks
    if tx_type in ("register_vehicle", "propose_garage"):
        if user["role"] != "admin":
            return jsonify({"error": "not-authorized"}), 403
        voter = user["username"]
    elif tx_type == "add_service":
        if user["role"] != "garage":
            return jsonify({"error": "not-authorized"}), 403
        voter = user["username"]
    else:
        if user["role"] != "admin":
            return jsonify({"error": "not-authorized"}), 403
        voter = user["username"]

    # cast vote
    result = bc.cast_vote(tx_id, voter, vote_val)

    # If a garage proposal was accepted -> create garage user
    if result.get("finalized") == "accepted":
        tx_info = result.get("tx")
        if not tx_info:
            # fallback: search in global chain for the tx record
            for block in bc.chain[::-1]:
                for rec in block.transactions:
                    if rec.get("tx_id") == tx_id:
                        tx_info = rec
                        break
                if tx_info:
                    break

        if tx_info:
            ttype = tx_info["tx"].get("type")
            if ttype == "propose_garage":
                payload = tx_info["tx"].get("payload", {})
                new_username = payload.get("username")
                display_name = payload.get("display_name") or new_username
                password = payload.get("password", "password")
                if not get_user_by_username(new_username):
                    created = create_user(new_username, password, role="garage", display_name=display_name)
                    if created:
                        result["garage_created_message"] = f"Garage '{new_username}' created successfully."
                    else:
                        result["garage_created_message"] = f"Garage '{new_username}' could not be created (exists?)."

            # if a service record was accepted, write it to vehicle-specific chain
            if ttype == "add_service":
                payload = tx_info["tx"].get("payload", {})
                vin = payload.get("vin")
                # add block to vehicle chain
                block = bc.add_service_block_to_vehicle(vin, tx_info)
                result["vehicle_block"] = block
                result["vehicle"] = vin

    return jsonify(result)

# --- Explorer & vehicle history ---
# --- Explorer & vehicle history ---
@app.route("/explorer")
def explorer():
    chain = bc.get_chain()
    user = current_user()
    return render_template("explorer.html", chain=chain, user=user)

#
# --- ADD THIS NEW ROUTE ---
#
@app.route("/search-vehicle", methods=["POST"])
def search_vehicle():
    """
    Handle VIN search form submission.
    Redirects to the specific vehicle history page.
    """
    # Get the VIN from the form, clean it up
    vin = request.form.get("vin", "").strip().upper()
    
    if not vin:
        flash("Please enter a VIN to search.", "warning")
        return redirect(url_for("explorer"))
    
    # Redirect to the existing page that displays vehicle history
    return redirect(url_for("vehicle_history", vin=vin))
#
# --- END OF NEW ROUTE ---
#

@app.route("/vehicle/<vin>")
def vehicle_history(vin):
    vin = vin.strip().upper()
    data = bc.get_vehicle_history(vin)
    user = current_user()
    return render_template("vehicle_history.html", vin=vin, data=data, user=user)

@app.route("/api/chain")
def api_chain():
    return jsonify(bc.get_chain())

@app.route("/api/pending")
def api_pending():
    return jsonify(bc.pending_transactions)

if __name__ == "__main__":
    app.run(debug=True, port=5001)


# UPDATED TEMPLATES NEEDED:
# 1. templates/signup.html - Add garage option
# 2. templates/add_garage.html - Add password field
# 3. templates/garage_add_service.html - Fix to be service form, not history
# 4. templates/garage_panel.html - NEW: Voting panel for garages
# 5. templates/base.html - Add garage panel link