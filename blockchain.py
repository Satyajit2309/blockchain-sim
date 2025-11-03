# blockchain.py
import time
import json
import hashlib
import os
from typing import List, Dict, Any, Optional

STORAGE_FILE = "storage.json"
VEHICLE_CHAINS_DIR = "vehicle_chains"

def sha256(data: str) -> str:
    return hashlib.sha256(data.encode('utf-8')).hexdigest()

class Block:
    def __init__(self, index: int, timestamp: float, transactions: List[Dict[str,Any]],
                 previous_hash: str, nonce: int = 0):
        self.index = index
        self.timestamp = timestamp
        self.transactions = transactions
        self.previous_hash = previous_hash
        self.nonce = nonce
        self.hash = self.compute_hash()

    def compute_hash(self) -> str:
        block_string = json.dumps({
            "index": self.index,
            "timestamp": self.timestamp,
            "transactions": self.transactions,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce
        }, sort_keys=True)
        return sha256(block_string)

    def to_dict(self):
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "transactions": self.transactions,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
            "hash": self.hash
        }

class Blockchain:
    def __init__(self, admins: Optional[List[str]] = None, garages: Optional[List[str]] = None):
        self.chain: List[Block] = []
        self.pending_transactions: List[Dict[str,Any]] = []
        self.admins = admins or ["admin1", "admin2", "admin3"]
        self.garages = garages or []
        self.votes: Dict[str, Dict[str,str]] = {}
        self.load_from_file()

        if not self.chain:
            genesis = Block(index=0, timestamp=time.time(), transactions=[], previous_hash="0")
            self.chain.append(genesis)
            self.save_to_file()

        # ensure vehicle chains dir exists
        os.makedirs(VEHICLE_CHAINS_DIR, exist_ok=True)

    # -------------------------
    # Global chain & pending tx
    # -------------------------
    def new_transaction(self, tx: Dict[str,Any]) -> str:
        tx_id = sha256(json.dumps(tx, sort_keys=True) + str(time.time()))
        tx_record = {
            "tx_id": tx_id,
            "tx": tx,
            "time_submitted": time.time(),
            "status": "pending"
        }
        self.pending_transactions.append(tx_record)
        self.votes[tx_id] = {}
        self.save_to_file()
        return tx_id

    def cast_vote(self, tx_id: str, voter: str, vote: str) -> Dict[str,Any]:
        if tx_id not in self.votes:
            return {"error": "transaction not found"}

        if vote not in ("approve", "reject"):
            return {"error": "invalid vote"}

        # record vote
        self.votes[tx_id][voter] = vote
        self.save_to_file()

        votes = self.votes[tx_id]
        approve_count = sum(1 for v in votes.values() if v == "approve")
        reject_count = sum(1 for v in votes.values() if v == "reject")

        tx_record = next((t for t in self.pending_transactions if t["tx_id"] == tx_id), None)
        if not tx_record:
            # fallback majority to admins
            total = len(self.admins)
        else:
            tx_type = tx_record["tx"].get("type")
            if tx_type in ("propose_garage", "register_vehicle", "transfer_ownership"):
                total = len(self.admins)
            elif tx_type == "add_service":
                total = len(self.garages) if len(self.garages) > 0 else 1
            else:
                total = len(self.admins)

        majority = (total // 2) + 1
        result = {"approve_count": approve_count, "reject_count": reject_count, "majority": majority}

        # If majority reached
        if approve_count >= majority:
            if tx_record:
                tx_record["status"] = "accepted"
                # Special-case: service records go to vehicle-specific chain instead of global chain.
                tx_type = tx_record["tx"].get("type")
                if tx_type == "add_service":
                    # mark accepted, remove pending, cleanup votes; actual vehicle-block write done externally (so caller can act)
                    self.pending_transactions = [t for t in self.pending_transactions if t["tx_id"] != tx_id]
                    if tx_id in self.votes:
                        del self.votes[tx_id]
                    self.save_to_file()
                    result["finalized"] = "accepted"
                    result["tx"] = tx_record
                else:
                    # default: add to global chain
                    self._add_block([tx_record])
                    self.pending_transactions = [t for t in self.pending_transactions if t["tx_id"] != tx_id]
                    if tx_id in self.votes:
                        del self.votes[tx_id]
                    self.save_to_file()
                    result["finalized"] = "accepted"
                    result["tx"] = tx_record
            else:
                result["error"] = "tx not in pending list"
        elif reject_count >= majority:
            if tx_record:
                tx_record["status"] = "rejected"
                # remove pending and votes
                self.pending_transactions = [t for t in self.pending_transactions if t["tx_id"] != tx_id]
                if tx_id in self.votes:
                    del self.votes[tx_id]
                self.save_to_file()
                result["finalized"] = "rejected"
                result["tx"] = tx_record
            else:
                result["error"] = "tx not in pending list"
        else:
            result["finalized"] = False

        return result

    def _add_block(self, transactions: List[Dict[str,Any]]):
        index = len(self.chain)
        previous_hash = self.chain[-1].hash
        new_block = Block(index=index, timestamp=time.time(), transactions=transactions, previous_hash=previous_hash)
        target_prefix = "00"
        while not new_block.hash.startswith(target_prefix):
            new_block.nonce += 1
            new_block.hash = new_block.compute_hash()
        self.chain.append(new_block)
        self.save_to_file()

    def get_chain(self) -> List[Dict[str,Any]]:
        return [b.to_dict() for b in self.chain]

    def get_block(self, index: int) -> Optional[Dict[str,Any]]:
        if 0 <= index < len(self.chain):
            return self.chain[index].to_dict()
        return None

    # -------------------------
    # Ownership tracking - NEW METHODS
    # -------------------------
    def get_current_owner(self, vin: str) -> Optional[str]:
        """Get the current owner of a vehicle by traversing the chain"""
        current_owner = None
        for block in self.chain:
            for tx_record in block.transactions:
                tx = tx_record.get("tx", {})
                payload = tx.get("payload", {})
                if payload.get("vin") == vin:
                    if tx.get("type") == "register_vehicle":
                        current_owner = payload.get("owner")
                    elif tx.get("type") == "transfer_ownership":
                        current_owner = payload.get("to_owner")
        return current_owner
    
    def get_vehicles_by_owner(self, owner: str) -> List[Dict[str,Any]]:
        """Get all vehicles currently owned by a user"""
        vehicles = {}  # vin -> ownership data
        
        for block in self.chain:
            for tx_record in block.transactions:
                tx = tx_record.get("tx", {})
                payload = tx.get("payload", {})
                vin = payload.get("vin")
                
                if not vin:
                    continue
                
                if tx.get("type") == "register_vehicle":
                    vehicles[vin] = {
                        "vin": vin,
                        "current_owner": payload.get("owner"),
                        "registered_at": block.timestamp,
                        "block_index": block.index
                    }
                elif tx.get("type") == "transfer_ownership":
                    if vin in vehicles:
                        vehicles[vin]["current_owner"] = payload.get("to_owner")
                        vehicles[vin]["last_transfer"] = block.timestamp
        
        # Filter only vehicles owned by the specified owner
        return [v for v in vehicles.values() if v["current_owner"] == owner]

    # -------------------------
    # Vehicle-specific chain ops
    # -------------------------
    def _vehicle_chain_path(self, vin: str) -> str:
        safe_vin = vin.replace("/", "_").upper()
        return os.path.join(VEHICLE_CHAINS_DIR, f"{safe_vin}.json")

    def ensure_vehicle_chain(self, vin: str):
        path = self._vehicle_chain_path(vin)
        if not os.path.exists(path):
            # create genesis block for vehicle
            genesis = {
                "vin": vin,
                "chain": [
                    {
                        "index": 0,
                        "timestamp": time.time(),
                        "transactions": [],
                        "previous_hash": "0",
                        "nonce": 0,
                        "hash": sha256(f"genesis-{vin}-{time.time()}")
                    }
                ]
            }
            with open(path, "w") as f:
                json.dump(genesis, f, indent=2)

    def get_vehicle_chain(self, vin: str) -> Dict[str,Any]:
        path = self._vehicle_chain_path(vin)
        if not os.path.exists(path):
            return {"vin": vin, "chain": []}
        with open(path, "r") as f:
            return json.load(f)

    def add_service_block_to_vehicle(self, vin: str, tx_record: Dict[str,Any]) -> Dict[str,Any]:
        """
        tx_record is the pending tx record that was accepted (status = 'accepted').
        This method appends a new block to the vehicle's chain containing that tx_record.
        """
        self.ensure_vehicle_chain(vin)
        path = self._vehicle_chain_path(vin)
        with open(path, "r") as f:
            data = json.load(f)

        chain = data.get("chain", [])
        index = len(chain)
        previous_hash = chain[-1]["hash"] if chain else "0"
        transactions = [tx_record]
        # build block dict & compute hash with PoW
        block = {
            "index": index,
            "timestamp": time.time(),
            "transactions": transactions,
            "previous_hash": previous_hash,
            "nonce": 0,
            "hash": ""
        }
        # compute hash until it starts with target prefix
        target_prefix = "00"
        while True:
            block["hash"] = sha256(json.dumps({
                "index": block["index"],
                "timestamp": block["timestamp"],
                "transactions": block["transactions"],
                "previous_hash": block["previous_hash"],
                "nonce": block["nonce"]
            }, sort_keys=True))
            if block["hash"].startswith(target_prefix):
                break
            block["nonce"] += 1

        chain.append(block)
        data["chain"] = chain
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        return block

    # -------------------------
    # vehicle-history search (global chain + vehicle chain)
    # -------------------------
    def get_vehicle_history(self, vin: str) -> Dict[str,Any]:
        """
        Return an object containing:
          - global_events: service/registration/transfer events found in global chain
          - vehicle_chain: per-vehicle chain file (if any)
        """
        global_events = []
        for block in self.chain:
            for tx_record in block.transactions:
                tx = tx_record.get("tx", {})
                payload = tx.get("payload", {})
                if payload.get("vin") == vin:
                    global_events.append({
                        "block_index": block.index,
                        "tx_id": tx_record.get("tx_id"),
                        "type": tx.get("type"),
                        "payload": payload,
                        "timestamp": block.timestamp
                    })
        vehicle_chain = self.get_vehicle_chain(vin)
        return {"global_events": global_events, "vehicle_chain": vehicle_chain}

    # -------------------------
    # persistence
    # -------------------------
    def save_to_file(self):
        data = {
            "chain": [b.to_dict() for b in self.chain],
            "pending_transactions": self.pending_transactions,
            "admins": self.admins,
            "garages": self.garages,
            "votes": self.votes
        }
        with open(STORAGE_FILE, "w") as f:
            json.dump(data, f, indent=2)

    def load_from_file(self):
        try:
            with open(STORAGE_FILE, "r") as f:
                data = json.load(f)
            self.chain = []
            for b in data.get("chain", []):
                block = Block(index=b["index"], timestamp=b["timestamp"],
                              transactions=b["transactions"], previous_hash=b["previous_hash"], nonce=b.get("nonce", 0))
                block.hash = b.get("hash", block.compute_hash())
                self.chain.append(block)
            self.pending_transactions = data.get("pending_transactions", [])
            self.admins = data.get("admins", self.admins)
            self.garages = data.get("garages", self.garages)
            self.votes = data.get("votes", {})
        except FileNotFoundError:
            self.chain = []
            self.pending_transactions = []
            self.votes = {}
        except Exception as e:
            print("Error loading storage:", e)
            self.chain = []
            self.pending_transactions = []
            self.votes = {}