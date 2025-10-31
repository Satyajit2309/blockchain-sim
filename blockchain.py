# blockchain.py
import time
import json
import hashlib
from typing import List, Dict, Any, Optional

STORAGE_FILE = "storage.json"

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
        self.garages = garages or []           # <-- new: garage network
        self.votes: Dict[str, Dict[str,str]] = {}  # tx_id -> {admin/garage: vote}
        self.load_from_file()

        if not self.chain:
            genesis = Block(index=0, timestamp=time.time(), transactions=[], previous_hash="0")
            self.chain.append(genesis)
            self.save_to_file()

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
        """
        voter = admin username (for admin-level votes) OR garage username (for garage-level votes)
        vote = 'approve' or 'reject'
        Logic same as before; returns result. If tx accepted, it finalizes into a block.
        """
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

        # determine which validator set applies:
        # if tx.tx.type == 'propose_garage' or 'register_vehicle' -> use admins
        # if tx.tx.type == 'add_service' -> use garages
        tx_record = next((t for t in self.pending_transactions if t["tx_id"] == tx_id), None)
        if not tx_record:
            # maybe already finalized; but allow vote recording earlier only
            # fallback to admins majority
            total_admins = len(self.admins)
            majority = total_admins // 2 + 1
        else:
            tx_type = tx_record["tx"].get("type")
            if tx_type in ("propose_garage", "register_vehicle"):
                total = len(self.admins)
            elif tx_type == "add_service":
                total = len(self.garages) if len(self.garages) > 0 else 1
            else:
                total = len(self.admins)
            majority = total // 2 + 1

        result = {"approve_count": approve_count, "reject_count": reject_count, "majority": majority}

        if approve_count >= majority:
            if tx_record:
                tx_record["status"] = "accepted"
                self._add_block([tx_record])
                # remove from pending
                self.pending_transactions = [t for t in self.pending_transactions if t["tx_id"] != tx_id]
                # cleanup votes
                if tx_id in self.votes:
                    del self.votes[tx_id]
                self.save_to_file()
                result["finalized"] = "accepted"
                result["tx"] = tx_record  # return tx for caller convenience
            else:
                result["error"] = "tx not in pending list"
        elif reject_count >= majority:
            if tx_record:
                tx_record["status"] = "rejected"
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
        # light mining
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

    def get_vehicle_history(self, vin: str) -> List[Dict[str,Any]]:
        history = []
        for block in self.chain:
            for tx_record in block.transactions:
                tx = tx_record.get("tx", {})
                payload = tx.get("payload", {})
                if payload.get("vin") == vin:
                    history.append({
                        "block_index": block.index,
                        "tx_id": tx_record.get("tx_id"),
                        "type": tx.get("type"),
                        "payload": payload,
                        "timestamp": block.timestamp
                    })
        return history

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
