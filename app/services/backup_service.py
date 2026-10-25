"""Database-consistent SQLite Backup, Integrity Verification, Retention Pruning, and Safe Restore Service."""

from __future__ import annotations

from datetime import datetime
import glob
import hashlib
import os
import shutil
import sqlite3
import tempfile
from typing import Any

from app.db.database import DatabaseManager
from app.services.auth_service import AuthService


class BackupIntegrityError(RuntimeError):
    """Raised when a backup file fails SQLite PRAGMA integrity_check or schema validation."""


REQUIRED_TABLES = {
    "schema_migrations",
    "app_settings",
    "users",
    "audit_logs",
    "suppliers",
    "customers",
    "products",
    "product_barcodes",
    "batches",
    "stock_movements",
    "purchases",
    "purchase_lines",
    "sales",
    "sale_lines",
    "payments",
    "sales_returns",
    "purchase_returns",
    "stock_adjustments",
    "expenses",
}


class BackupService:
    """Manages online SQLite backups, SHA-256 checksums, retention pruning, and staged safe restoration."""

    def __init__(self, db: DatabaseManager, auth: AuthService, backup_dir: str) -> None:
        self.db = db
        self.auth = auth
        self.backup_dir = os.path.abspath(backup_dir)
        os.makedirs(self.backup_dir, exist_ok=True)

    @staticmethod
    def compute_sha256(file_path: str) -> str:
        """Compute SHA-256 hex digest of a file."""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def verify_backup_file(self, backup_file_path: str) -> dict[str, Any]:
        """Validate a candidate SQLite backup file in an isolated temporary copy before accepting it.

        Checks:
        1. File exists and is non-empty.
        2. SQLite `PRAGMA integrity_check` returns `'ok'`.
        3. All core pharmacy tables exist in `sqlite_master`.
        """
        if not os.path.isfile(backup_file_path) or os.path.getsize(backup_file_path) == 0:
            raise BackupIntegrityError(f"Backup file '{backup_file_path}' is missing or empty.")

        with tempfile.TemporaryDirectory(prefix="pakpharma_verify_") as tmp_dir:
            staged_path = os.path.join(tmp_dir, "staged_verify.db")
            shutil.copy2(backup_file_path, staged_path)
            try:
                conn = sqlite3.connect(staged_path)
                conn.row_factory = sqlite3.Row
                integrity_row = conn.execute("PRAGMA integrity_check;").fetchone()
                if not integrity_row or str(integrity_row[0]).lower() != "ok":
                    conn.close()
                    raise BackupIntegrityError(
                        f"SQLite integrity check failed: {integrity_row[0] if integrity_row else 'unknown'}"
                    )

                tables = {
                    r["name"]
                    for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                }
                missing = REQUIRED_TABLES - tables
                if missing:
                    conn.close()
                    raise BackupIntegrityError(
                        f"Backup file is missing required PakPharma tables: {', '.join(sorted(missing))}"
                    )

                product_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
                sale_count = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
                conn.close()
            except sqlite3.DatabaseError as e:
                raise BackupIntegrityError(f"Corrupted SQLite database file: {e}") from e

        checksum = self.compute_sha256(backup_file_path)
        return {
            "valid": True,
            "file_path": os.path.abspath(backup_file_path),
            "file_size_bytes": os.path.getsize(backup_file_path),
            "sha256_checksum": checksum,
            "product_count": int(product_count),
            "sale_count": int(sale_count),
        }

    def create_backup(
        self,
        user_id: int | None = None,
        target_dir: str | None = None,
        backup_type: str = "MANUAL",
        notes: str = "",
    ) -> dict[str, Any]:
        """Perform an online, database-consistent backup using SQLite's native `backup()` API."""
        if user_id is not None and backup_type == "MANUAL":
            self.auth.require_permission(user_id, "CREATE_BACKUP")

        dest_folder = os.path.abspath(target_dir) if target_dir else self.backup_dir
        os.makedirs(dest_folder, exist_ok=True)

        now = datetime.now()
        now_iso = now.isoformat(timespec="seconds")
        stamp = now.strftime("%Y%m%d_%H%M%S_%f")
        filename = f"pakpharma_backup_{backup_type.lower()}_{stamp}.sqlite3"
        dest_path = os.path.join(dest_folder, filename)

        # Perform consistent online SQLite backup
        src_conn = self.db.get_connection()
        dst_conn = sqlite3.connect(dest_path)
        try:
            with dst_conn:
                src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()

        # Verify the newly created backup immediately
        verification = self.verify_backup_file(dest_path)

        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO backup_logs (
                    timestamp, backup_path, file_size_bytes, sha256_checksum,
                    backup_type, status, triggered_by, notes
                ) VALUES (?, ?, ?, ?, ?, 'SUCCESS', ?, ?)
                """,
                (
                    now_iso,
                    dest_path,
                    verification["file_size_bytes"],
                    verification["sha256_checksum"],
                    backup_type,
                    user_id,
                    notes.strip(),
                ),
            )
            if user_id is not None:
                u = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
                uname = u["username"] if u else "system"
                self.auth._log_in_tx(
                    conn,
                    user_id=user_id,
                    username=uname,
                    action=f"BACKUP_{backup_type}",
                    entity_type="backup_logs",
                    entity_id=filename,
                    reason=notes or f"Created {backup_type} database backup",
                    details={"sha256": verification["sha256_checksum"], "size": verification["file_size_bytes"]},
                )

        # Apply retention pruning if backing up to default backup_dir
        if os.path.abspath(dest_folder) == self.backup_dir:
            self._prune_old_backups()

        return {
            "backup_path": dest_path,
            "file_size_bytes": verification["file_size_bytes"],
            "sha256_checksum": verification["sha256_checksum"],
            "timestamp": now_iso,
            "backup_type": backup_type,
            "product_count": verification["product_count"],
            "sale_count": verification["sale_count"],
        }

    def restore_backup(
        self,
        admin_user_id: int,
        backup_file_path: str,
        confirmed: bool = False,
        reason: str = "Database restore",
    ) -> dict[str, Any]:
        """Safely restore a verified backup file.

        Safety Protocol:
        1. Requires `RESTORE_BACKUP` permission (Admin only) and `confirmed=True`.
        2. Validates the backup in a separate temporary database first (`verify_backup_file`).
        3. Creates an automatic `PRE_RESTORE` safety backup of the current live database before overwriting.
        4. Copies the verified backup into the live database via SQLite's online `backup()` API and runs migrations.
        """
        admin = self.auth.require_permission(admin_user_id, "RESTORE_BACKUP")
        if not confirmed:
            raise ValueError("Database restoration requires explicit confirmation (confirmed=True).")

        # Step 1: Validate target backup in isolated staging DB
        verification = self.verify_backup_file(backup_file_path)

        # Step 2: Create a PRE_RESTORE safety snapshot of current live DB
        pre_restore_info = self.create_backup(
            user_id=admin_user_id,
            backup_type="PRE_RESTORE",
            notes=f"Automatic safety snapshot before restoring {os.path.basename(backup_file_path)}",
        )

        # Step 3: Copy validated backup contents into live database using SQLite backup API
        src_conn = sqlite3.connect(backup_file_path)
        dst_conn = sqlite3.connect(self.db.db_path)
        try:
            with dst_conn:
                src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()

        # Step 4: Run any newer schema migrations on the restored database
        self.db.initialize_and_migrate()

        # Step 5: Record audit log in restored database
        self.auth.log_action(
            user_id=admin["id"],
            action="RESTORE_BACKUP",
            entity_type="database",
            entity_id=os.path.basename(backup_file_path),
            reason=reason,
            details={
                "restored_from": backup_file_path,
                "sha256": verification["sha256_checksum"],
                "pre_restore_snapshot": pre_restore_info["backup_path"],
            },
        )

        return {
            "restored": True,
            "restored_from": os.path.abspath(backup_file_path),
            "pre_restore_backup_path": pre_restore_info["backup_path"],
            "sha256_checksum": verification["sha256_checksum"],
            "product_count": verification["product_count"],
            "sale_count": verification["sale_count"],
        }

    def _prune_old_backups(self) -> list[str]:
        """Retain the most recent N automatic backups according to `backup_retention_count`."""
        retention = max(3, int(self.db.get_setting("backup_retention_count", "14")))
        pattern = os.path.join(self.backup_dir, "pakpharma_backup_scheduled_*.sqlite3")
        files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        removed: list[str] = []
        for old_path in files[retention:]:
            try:
                os.remove(old_path)
                removed.append(old_path)
            except OSError:
                pass
        return removed

    def get_backup_status(self) -> dict[str, Any]:
        """Return backup history and latest backup status for the UI."""
        with self.db.read_only() as conn:
            logs = [
                dict(r)
                for r in conn.execute("SELECT * FROM backup_logs ORDER BY id DESC LIMIT 50").fetchall()
            ]
        latest = logs[0] if logs else None
        return {
            "backup_dir": self.backup_dir,
            "latest_backup": latest,
            "history": logs,
            "disclaimer": (
                "IMPORTANT SECURITY NOTICE: Local backups protect against accidental deletion or database "
                "corruption, but a local-only system cannot guarantee protection against physical computer "
                "theft, fire, full hard-drive failure, or ransomware unless you regularly copy backups to an "
                "external USB flash drive or off-site storage."
            ),
        }
