import os
import sqlite3
import hashlib
import time
import logging
import uuid
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

logger = logging.getLogger(__name__)

class ComplianceExecutor:
    """
    Sovereign Data Assertion Layer for YantraOS.
    Implements a simulated TPM 2.0 PCR register for cryptographic consent tracking
    and enforces data mortality (automated telemetry TTL) in compliance with DPDPA.
    """
    def __init__(self, db_path="/var/lib/yantra/consent_ledger.db", chroma_client=None):
        self.db_path = db_path
        self.chroma_client = chroma_client
        self._init_keys()
        self._init_db()

    def _init_keys(self):
        """Initialize or load Ed25519 keys for signing PCR measurements."""
        key_path = os.path.join(os.path.dirname(self.db_path), ".compliance_key.pem")
        if os.path.exists(key_path):
            with open(key_path, "rb") as f:
                self.private_key = serialization.load_pem_private_key(
                    f.read(),
                    password=None
                )
        else:
            self.private_key = ed25519.Ed25519PrivateKey.generate()
            with open(key_path, "wb") as f:
                f.write(self.private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption()
                ))

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Cryptographic Consent Ledger
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS consent_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    intent TEXT,
                    pcr_value TEXT,
                    signature BLOB
                )
            """)
            
            # Telemetry Store (simulated)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS telemetry_store (
                    id TEXT PRIMARY KEY,
                    timestamp REAL,
                    data TEXT
                )
            """)
            conn.commit()

    def _get_last_pcr(self) -> str:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT pcr_value FROM consent_ledger ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                return row[0]
            # Initial PCR value (all zeros)
            return "0" * 64

    def record_consent(self, intent: str):
        """
        Record a consent state change into the simulated PCR register.
        intent: 'CONSENT_GRANTED' or 'CONSENT_REVOKED'
        """
        timestamp = time.time()
        last_pcr = self._get_last_pcr()
        
        # PCR_n = SHA-256(PCR_{n-1} || measurement)
        measurement = f"{intent}:{timestamp}".encode('utf-8')
        pcr_input = last_pcr.encode('utf-8') + measurement
        new_pcr = hashlib.sha256(pcr_input).hexdigest()
        
        # Sign the new PCR value
        signature = self.private_key.sign(new_pcr.encode('utf-8'))
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO consent_ledger (timestamp, intent, pcr_value, signature) VALUES (?, ?, ?, ?)",
                (timestamp, intent, new_pcr, signature)
            )
            conn.commit()
        
        logger.info(f"Recorded consent state: {intent} (PCR updated)")
        
        if intent == "CONSENT_REVOKED":
            self.immediate_data_purge()

    def store_telemetry(self, data: str):
        """Stores a piece of telemetry data."""
        timestamp = time.time()
        telemetry_id = str(uuid.uuid4())
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO telemetry_store (id, timestamp, data) VALUES (?, ?, ?)",
                (telemetry_id, timestamp, data)
            )
            conn.commit()

    def immediate_data_purge(self):
        """
        Right to Erasure (DPDPA Section 12).
        Instantly truncates the SQLite telemetry cache and drops non-essential vector embeddings.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM telemetry_store")
            deleted = cursor.rowcount
            conn.commit()
            
        if self.chroma_client:
            try:
                for collection_name in ["skill_index", "execution_logs"]:
                    try:
                        col = self.chroma_client.get_collection(collection_name)
                        # Drop embeddings across vector space
                        col.delete(where={"timestamp": {"$gte": 0}})
                        logger.info(f"Purged vector collection {collection_name}")
                    except ValueError:
                        pass
            except Exception as e:
                logger.error(f"Failed to purge ChromaDB collections: {e}")
                
        logger.info(f"Immediate data purge executed. Dropped {deleted} SQLite records and cleared vectors.")

    def sweep_expired_telemetry(self, ttl_hours: float):
        """
        Automated Telemetry TTL (Data Mortality).
        Hard delete any telemetry records older than `ttl_hours`.
        """
        expiration_time = time.time() - (ttl_hours * 3600)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM telemetry_store WHERE timestamp < ?",
                (expiration_time,)
            )
            deleted = cursor.rowcount
            conn.commit()
            
        if self.chroma_client:
            try:
                for collection_name in ["skill_index", "execution_logs"]:
                    try:
                        col = self.chroma_client.get_collection(collection_name)
                        col.delete(where={"timestamp": {"$lt": expiration_time}})
                    except ValueError:
                        pass
            except Exception as e:
                logger.error(f"Failed to sweep ChromaDB collections: {e}")
            
        if deleted > 0:
            logger.info(f"Swept {deleted} expired telemetry records (TTL {ttl_hours} hours).")
