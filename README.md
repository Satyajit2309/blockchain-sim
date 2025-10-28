# 🚗 Blockchain Simulation – Vehicle History Tracker

This project is a **Flask-based simulation** of a **Blockchain network** built for a *Vehicle History Tracker* application.  
It visually demonstrates how blockchain concepts like **consensus, immutability, decentralization, and transparency** work — without using a real blockchain.

---

## 🔍 Overview

- Users can **register vehicles** (simulated transactions).  
- Multiple **admins** act as validators and can **approve or reject** each transaction.  
- Once the **majority approves**, the transaction is added as a **block** to the simulated blockchain.  
- The **Blockchain Explorer** lets you view blocks, hashes, and full vehicle history.  
- The simulation mimics real blockchain behavior — but runs entirely locally using Flask and JSON storage.

---

## ⚙️ Installation & Setup

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/blockchain-simulation.git
cd blockchain-simulation

# 2. (Optional) Create a virtual environment
python -m venv venv
venv\Scripts\activate  # On Windows
source venv/bin/activate  # On mac/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the application
python app.py
