import hashlib
import hmac
import logging
import os
import sqlite3
import stat
import time
import uuid
from contextlib import closing

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

logger = logging.getLogger(__name__)

DEFAULT_COMPLIANCE_DB_PATH = "/var/lib/yantra/consent_ledger.db"
DEFAULT_COMPLIANCE_KEY_PATH = "/var/lib/yantra/.compliance_key.pem"
COMPLIANCE_DB_PATH = os.environ.get(
    "YANTRA_COMPLIANCE_DB_PATH", DEFAULT_COMPLIANCE_DB_PATH
)
COMPLIANCE_KEY_PATH = os.environ.get(
    "YANTRA_COMPLIANCE_KEY_PATH", DEFAULT_COMPLIANCE_KEY_PATH
)

_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_PRIVATE_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
_PRIVATE_WRITE_FLAGS = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
_MAX_KEY_BYTES = 65536
_MAX_TELEMETRY_BYTES = 65_536
_CONSENT_INTENTS = frozenset({"CONSENT_GRANTED", "CONSENT_REVOKED"})


def _split_state_path(path: str | os.PathLike[str], label: str) -> tuple[str, str]:
    path = os.fspath(path)
    if not os.path.isabs(path) or os.path.normpath(path) != path:
        raise ValueError(f"{label} path must be absolute and normalized: {path!r}")
    directory, filename = os.path.split(path)
    if not filename:
        raise ValueError(f"{label} path must name a file")
    return directory, filename


def _validate_directory(info: os.stat_result, *, created: bool, label: str) -> None:
    mode = stat.S_IMODE(info.st_mode)
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"{label} parent is not a directory")
    if created:
        if info.st_uid != os.geteuid() or mode != 0o700:
            raise PermissionError(
                f"New {label} directories must be owned by the service with mode 0700"
            )
        return
    if os.geteuid() != 0 and info.st_uid not in (os.geteuid(), 0):
        raise PermissionError(f"{label} parent has an untrusted owner")
    if mode not in (0o700, 0o750):
        raise PermissionError(
            f"Existing {label} parent must have mode 0700 or 0750"
        )


def _open_secure_parent(
    path: str | os.PathLike[str], label: str
) -> tuple[int, str]:
    directory, filename = _split_state_path(path, label)
    current_fd = os.open("/", _DIRECTORY_FLAGS)
    try:
        parts = [part for part in directory.split(os.sep) if part]
        for index, part in enumerate(parts):
            created = False
            try:
                next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=current_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(part, 0o700, dir_fd=current_fd)
                    os.fsync(current_fd)
                    created = True
                except FileExistsError:
                    pass
                next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=current_fd)

            os.close(current_fd)
            current_fd = next_fd
            if created:
                os.fchmod(current_fd, 0o700)
                os.fsync(current_fd)
            if index == len(parts) - 1:
                _validate_directory(
                    os.fstat(current_fd), created=created, label=label
                )

        if not parts:
            _validate_directory(
                os.fstat(current_fd), created=False, label=label
            )
        return current_fd, filename
    except Exception:
        os.close(current_fd)
        raise


def _validate_private_file(info: os.stat_result, label: str) -> None:
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"{label} is not a regular file")
    if info.st_uid != os.geteuid():
        raise PermissionError(f"{label} is not owned by the service")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise PermissionError(f"{label} must have mode 0600")


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("Short state-file write")
        view = view[written:]


def _read_private_file(path: str, label: str) -> bytes:
    parent_fd, filename = _open_secure_parent(path, label)
    try:
        before = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
        _validate_private_file(before, label)
        fd = os.open(filename, _PRIVATE_READ_FLAGS, dir_fd=parent_fd)
        try:
            after = os.fstat(fd)
            _validate_private_file(after, label)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise RuntimeError(f"{label} changed while being opened")
            data = bytearray()
            while len(data) <= _MAX_KEY_BYTES:
                chunk = os.read(fd, min(8192, _MAX_KEY_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            if len(data) > _MAX_KEY_BYTES:
                raise ValueError(f"{label} is unexpectedly large")
            return bytes(data)
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def _publish_private_file(path: str, data: bytes, label: str) -> bool:
    """Publish complete private data without ever exposing a partial final file."""
    parent_fd, filename = _open_secure_parent(path, label)
    temporary = f".yantra-key-{uuid.uuid4().hex}.tmp"
    temporary_exists = False
    fd: int | None = None
    try:
        fd = os.open(
            temporary,
            _PRIVATE_WRITE_FLAGS | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=parent_fd,
        )
        temporary_exists = True
        os.fchmod(fd, 0o600)
        _validate_private_file(os.fstat(fd), label)
        _write_all(fd, data)
        os.fsync(fd)
        os.close(fd)
        fd = None

        try:
            os.link(
                temporary,
                filename,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
            published = True
        except FileExistsError:
            published = False

        os.unlink(temporary, dir_fd=parent_fd)
        temporary_exists = False
        os.fsync(parent_fd)
        return published
    finally:
        if fd is not None:
            os.close(fd)
        if temporary_exists:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
                os.fsync(parent_fd)
            except FileNotFoundError:
                pass
        os.close(parent_fd)


class ComplianceExecutor:
    """
    Sovereign Data Assertion Layer for YantraOS.
    Implements a simulated TPM 2.0 PCR register for cryptographic consent tracking
    and enforces data mortality (automated telemetry TTL) in compliance with DPDPA.
    """

    def __init__(
        self,
        db_path: str | os.PathLike[str] | None = None,
        chroma_client=None,
        key_path: str | os.PathLike[str] | None = None,
    ):
        configured_db_path = os.environ.get(
            "YANTRA_COMPLIANCE_DB_PATH", COMPLIANCE_DB_PATH
        )
        configured_key_path = os.environ.get(
            "YANTRA_COMPLIANCE_KEY_PATH", COMPLIANCE_KEY_PATH
        )
        self.db_path = os.fspath(
            db_path if db_path is not None else configured_db_path
        )
        self.key_path = os.fspath(
            key_path if key_path is not None else configured_key_path
        )
        _split_state_path(self.db_path, "Compliance database")
        _split_state_path(self.key_path, "Compliance key")
        self.chroma_client = chroma_client
        self._init_keys()
        self._init_db()
        self._verify_ledger()

    def _load_private_key(self) -> ed25519.Ed25519PrivateKey:
        encoded = _read_private_file(self.key_path, "Compliance key")
        private_key = serialization.load_pem_private_key(encoded, password=None)
        if not isinstance(private_key, ed25519.Ed25519PrivateKey):
            raise ValueError("Compliance key must be an Ed25519 private key")
        return private_key

    def _init_keys(self) -> None:
        """Load a validated Ed25519 key or atomically publish a new one."""
        try:
            self.private_key = self._load_private_key()
            return
        except FileNotFoundError:
            pass

        private_key = ed25519.Ed25519PrivateKey.generate()
        encoded = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        if _publish_private_file(self.key_path, encoded, "Compliance key"):
            self.private_key = private_key
        else:
            self.private_key = self._load_private_key()

    def _ensure_db_file(self) -> None:
        parent_fd, filename = _open_secure_parent(
            self.db_path, "Compliance database"
        )
        created = False
        try:
            try:
                fd = os.open(
                    filename,
                    _PRIVATE_WRITE_FLAGS | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=parent_fd,
                )
                created = True
                before = None
            except FileExistsError:
                before = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
                _validate_private_file(before, "Compliance database")
                fd = os.open(filename, _PRIVATE_WRITE_FLAGS, dir_fd=parent_fd)

            try:
                if created:
                    os.fchmod(fd, 0o600)
                after = os.fstat(fd)
                _validate_private_file(after, "Compliance database")
                if before is not None and (
                    before.st_dev,
                    before.st_ino,
                ) != (after.st_dev, after.st_ino):
                    raise RuntimeError(
                        "Compliance database changed while being opened"
                    )
                if created:
                    os.fsync(fd)
                    os.fsync(parent_fd)
            finally:
                os.close(fd)
        finally:
            os.close(parent_fd)

    def _connect(self) -> sqlite3.Connection:
        self._ensure_db_file()
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("PRAGMA synchronous=FULL")
            return connection
        except Exception:
            connection.close()
            raise

    def _init_db(self):
        with closing(self._connect()) as conn:
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
        with closing(self._connect()) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT pcr_value FROM consent_ledger ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                return row[0]
            # Initial PCR value (all zeros)
            return "0" * 64

    def _verify_ledger(self) -> None:
        """Fail closed if the PCR chain or an Ed25519 signature was altered."""
        previous = "0" * 64
        public_key = self.private_key.public_key()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT timestamp, intent, pcr_value, signature "
                "FROM consent_ledger ORDER BY id"
            ).fetchall()
        for timestamp, intent, pcr_value, signature in rows:
            if intent not in _CONSENT_INTENTS or not isinstance(signature, bytes):
                raise RuntimeError("Consent ledger contains invalid data")
            expected = hashlib.sha256(
                previous.encode("utf-8") + f"{intent}:{timestamp}".encode("utf-8")
            ).hexdigest()
            if not isinstance(pcr_value, str) or not hmac.compare_digest(expected, pcr_value):
                raise RuntimeError("Consent ledger PCR chain verification failed")
            try:
                public_key.verify(signature, pcr_value.encode("utf-8"))
            except Exception as exc:
                raise RuntimeError("Consent ledger signature verification failed") from exc
            previous = pcr_value

    def consent_granted(self) -> bool:
        """Return the persisted latest consent state; absence defaults to denied."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT intent FROM consent_ledger ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return bool(row and row[0] == "CONSENT_GRANTED")

    def record_consent(self, intent: str):
        """
        Record a consent state change into the simulated PCR register.
        intent: 'CONSENT_GRANTED' or 'CONSENT_REVOKED'
        """
        if intent not in _CONSENT_INTENTS:
            raise ValueError("Unknown consent state")
        timestamp = time.time()
        last_pcr = self._get_last_pcr()

        # PCR_n = SHA-256(PCR_{n-1} || measurement)
        measurement = f"{intent}:{timestamp}".encode("utf-8")
        pcr_input = last_pcr.encode("utf-8") + measurement
        new_pcr = hashlib.sha256(pcr_input).hexdigest()

        # Sign the new PCR value
        signature = self.private_key.sign(new_pcr.encode("utf-8"))

        with closing(self._connect()) as conn:
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
        if not isinstance(data, str) or len(data.encode("utf-8")) > _MAX_TELEMETRY_BYTES:
            raise ValueError("Telemetry must be a bounded string")
        timestamp = time.time()
        telemetry_id = str(uuid.uuid4())
        with closing(self._connect()) as conn:
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
        with closing(self._connect()) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM telemetry_store")
            deleted = cursor.rowcount
            conn.commit()

        if self.chroma_client:
            try:
                for collection_name in ["skill_index", "execution_logs"]:
                    try:
                        self.chroma_client.delete_collection(collection_name)
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
        if isinstance(ttl_hours, bool) or not isinstance(ttl_hours, (int, float)):
            raise ValueError("Telemetry TTL must be numeric")
        if not 1 <= ttl_hours <= 24 * 365:
            raise ValueError("Telemetry TTL is outside the supported range")
        expiration_time = time.time() - (ttl_hours * 3600)
        with closing(self._connect()) as conn:
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
