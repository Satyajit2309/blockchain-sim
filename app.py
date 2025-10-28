# app.py
from flask import Flask, render_template, request, redirect, url_for, jsonify
from blockchain import Blockchain
import time

app = Flask(__name__)
bc = Blockchain(admins=["alice", "bob", "carol"])

@app.route("/")
def index():
    pending_count = len(bc.pending_transactions)
    return render_template("index.html", pending_count=pending_count)

@app.route("/add-vehicle", methods=["GET", "POST"])
def add_vehicle():
    if request.method == "POST":
        vin = request.form.get("vin").strip()
        owner = request.form.get("owner").strip()
        payload = {"vin": vin, "owner": owner, "action": "register_vehicle", "meta": {"submitted_by": owner}}
        tx = {"type": "register_vehicle", "payload": payload, "requested_by": owner, "time": time.time()}
        tx_id = bc.new_transaction(tx)
        return render_template("add_vehicle.html", message=f"Transaction submitted: {tx_id}", tx_id=tx_id)
    return render_template("add_vehicle.html")

@app.route("/add-service", methods=["POST"])
def add_service():
    vin = request.form.get("vin").strip()
    garage = request.form.get("garage").strip()
    description = request.form.get("description").strip()
    payload = {"vin": vin, "garage": garage, "description": description, "action": "add_service"}
    tx = {"type": "add_service", "payload": payload, "requested_by": garage, "time": time.time()}
    tx_id = bc.new_transaction(tx)
    return jsonify({"tx_id": tx_id})

@app.route("/admin")
def admin_panel():
    # show pending transactions and admins
    pending = bc.pending_transactions
    admins = bc.admins
    votes = bc.votes
    return render_template("admin_panel.html", pending=pending, admins=admins, votes=votes)

@app.route("/vote", methods=["POST"])
def vote():
    tx_id = request.json.get("tx_id")
    admin = request.json.get("admin")
    vote_val = request.json.get("vote")  # 'approve' or 'reject'
    result = bc.cast_vote(tx_id, admin, vote_val)
    return jsonify(result)

@app.route("/explorer")
def explorer():
    chain = bc.get_chain()
    return render_template("explorer.html", chain=chain)

@app.route("/vehicle/<vin>")
def vehicle_history(vin):
    history = bc.get_vehicle_history(vin)
    return render_template("vehicle_history.html", vin=vin, history=history)

@app.route("/api/chain")
def api_chain():
    return jsonify(bc.get_chain())

@app.route("/api/pending")
def api_pending():
    return jsonify(bc.pending_transactions)

if __name__ == "__main__":
    app.run(debug=True, port=5001)
