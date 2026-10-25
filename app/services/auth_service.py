"""User authentication, role-based access control (RBAC), and audit logging service."""

from __future__ import annotations

from datetime import datetime
import json
import sqlite3
from typing import Any

from app.db.database import DatabaseManager, hash_password, verify_password


class AuthorizationError(PermissionError):
    """Raised when a user lacks permission for a restricted operation."""


class AuthenticationError(ValueError):
    """Raised when login credentials are invalid or account is inactive."""


ROLE_PERMISSIONS: dict[str, set[str]] = {
    "ADMIN": {
        "CHANGE_PRICES",
        "HIGH_DISCOUNT",
        "VOID_INVOICE",
        "STOCK_ADJUSTMENT",
        "EXPIRED_OVERRIDE",
        "VIEW_FINANCIAL_REPORTS",
        "RESTORE_BACKUP",
        "CREATE_BACKUP",
        "MANAGE_USERS",
        "MANAGE_SETTINGS",
        "DEACTIVATE_PRODUCT",
        "POS_BILLING",
        "PURCHASE_STOCK",
        "PROCESS_RETURNS",
        "RECORD_EXPENSES",
    },
    "MANAGER": {
        "CHANGE_PRICES",
        "HIGH_DISCOUNT",
        "VOID_INVOICE",
        "STOCK_ADJUSTMENT",
        "EXPIRED_OVERRIDE",
        "VIEW_FINANCIAL_REPORTS",
        "CREATE_BACKUP",
        "DEACTIVATE_PRODUCT",
        "POS_BILLING",
        "PURCHASE_STOCK",
        "PROCESS_RETURNS",
        "RECORD_EXPENSES",
    },
    "CASHIER": {
        "POS_BILLING",
        "PROCESS_RETURNS",
    },
}


class AuthService:
    """Manages local user accounts, PBKDF2 authentication, permissions, and audit trails."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def authenticate(self, username: str, password: str) -> dict[str, Any]:
        """Authenticate a user and record login in the audit log."""
        clean_user = (username or "").strip()
        if not clean_user or not password:
            raise AuthenticationError("Username and password are required.")

        now_iso = datetime.now().isoformat(timespec="seconds")
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                (clean_user,),
            ).fetchone()
            if not row:
                self._log_in_tx(
                    conn,
                    user_id=None,
                    username=clean_user,
                    action="LOGIN_FAILED",
                    entity_type="users",
                    entity_id=clean_user,
                    reason="Unknown username",
                )
                raise AuthenticationError("Invalid username or password.")

            if not row["is_active"]:
                self._log_in_tx(
                    conn,
                    user_id=row["id"],
                    username=row["username"],
                    action="LOGIN_BLOCKED",
                    entity_type="users",
                    entity_id=str(row["id"]),
                    reason="Account deactivated",
                )
                raise AuthenticationError("User account is deactivated. Contact Administrator.")

            if not verify_password(password, row["password_hash"], row["password_salt"]):
                self._log_in_tx(
                    conn,
                    user_id=row["id"],
                    username=row["username"],
                    action="LOGIN_FAILED",
                    entity_type="users",
                    entity_id=str(row["id"]),
                    reason="Incorrect password",
                )
                raise AuthenticationError("Invalid username or password.")

            conn.execute(
                "UPDATE users SET last_login_at = ? WHERE id = ?",
                (now_iso, row["id"]),
            )
            self._log_in_tx(
                conn,
                user_id=row["id"],
                username=row["username"],
                action="LOGIN_SUCCESS",
                entity_type="users",
                entity_id=str(row["id"]),
                reason="User authenticated",
            )
            return {
                "id": row["id"],
                "username": row["username"],
                "full_name": row["full_name"],
                "role": row["role"],
                "is_active": bool(row["is_active"]),
            }

    def get_user(self, user_id: int) -> dict[str, Any]:
        """Fetch user profile by ID and verify active status."""
        with self.db.read_only() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                raise AuthorizationError(f"User ID {user_id} does not exist.")
            if not row["is_active"]:
                raise AuthorizationError(f"User '{row['username']}' is deactivated.")
            return {
                "id": row["id"],
                "username": row["username"],
                "full_name": row["full_name"],
                "role": row["role"],
                "is_active": bool(row["is_active"]),
            }

    def has_permission(self, user_id: int, permission: str) -> bool:
        """Return True if the active user has the specified permission."""
        try:
            user = self.get_user(user_id)
        except AuthorizationError:
            return False
        allowed = ROLE_PERMISSIONS.get(user["role"], set())
        return permission in allowed

    def require_permission(self, user_id: int, permission: str, reason: str = "") -> dict[str, Any]:
        """Verify that user_id has permission; otherwise log denial and raise AuthorizationError."""
        user = self.get_user(user_id)
        allowed = ROLE_PERMISSIONS.get(user["role"], set())
        if permission not in allowed:
            self.log_action(
                user_id=user["id"],
                action=f"PERMISSION_DENIED:{permission}",
                entity_type="security",
                entity_id=permission,
                reason=reason or f"Role {user['role']} attempted restricted operation {permission}",
            )
            raise AuthorizationError(
                f"Access Denied: Role '{user['role']}' is not authorized for '{permission}'."
            )
        return user

    def check_discount_limit(self, user_id: int, subtotal_paisa: int, discount_paisa: int) -> None:
        """Enforce role-based discount ceilings based on configured basis points."""
        if discount_paisa <= 0 or subtotal_paisa <= 0:
            return
        user = self.get_user(user_id)
        role = user["role"]
        if role == "ADMIN":
            return
        discount_bps = (discount_paisa * 10_000) // subtotal_paisa
        if role == "CASHIER":
            max_bps = int(self.db.get_setting("cashier_max_discount_bps", "500"))
            if discount_bps > max_bps:
                self.log_action(
                    user_id=user_id,
                    action="DISCOUNT_LIMIT_EXCEEDED",
                    entity_type="sales",
                    entity_id="discount_check",
                    reason=f"Cashier attempted {discount_bps/100:.2f}% discount (limit {max_bps/100:.2f}%)",
                )
                raise AuthorizationError(
                    f"Cashier discount limit is {max_bps/100:.2f}%. "
                    f"Requested discount ({discount_bps/100:.2f}%) requires Manager or Admin authorization."
                )
        elif role == "MANAGER":
            max_bps = int(self.db.get_setting("manager_max_discount_bps", "2000"))
            if discount_bps > max_bps:
                raise AuthorizationError(
                    f"Manager discount limit is {max_bps/100:.2f}%. "
                    f"Requested discount ({discount_bps/100:.2f}%) requires Administrator authorization."
                )

    def create_user(
        self,
        admin_user_id: int,
        username: str,
        full_name: str,
        role: str,
        password: str,
    ) -> int:
        """Create a new user account (Admin only)."""
        admin = self.require_permission(admin_user_id, "MANAGE_USERS")
        clean_username = username.strip()
        if not clean_username or not full_name.strip():
            raise ValueError("Username and full name are required.")
        if role not in ("ADMIN", "MANAGER", "CASHIER"):
            raise ValueError("Invalid role. Must be ADMIN, MANAGER, or CASHIER.")
        phash, psalt = hash_password(password)
        now_iso = datetime.now().isoformat(timespec="seconds")
        with self.db.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (username, full_name, role, password_hash, password_salt, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (clean_username, full_name.strip(), role, phash, psalt, now_iso),
            )
            new_id = int(cur.lastrowid)
            self._log_in_tx(
                conn,
                user_id=admin["id"],
                username=admin["username"],
                action="CREATE_USER",
                entity_type="users",
                entity_id=str(new_id),
                reason=f"Created user '{clean_username}' with role {role}",
            )
            return new_id

    def change_user_password(
        self,
        actor_user_id: int,
        target_user_id: int,
        new_password: str,
        reason: str = "Password update",
    ) -> None:
        """Change password (users can change their own; Admin can reset any user's password)."""
        actor = self.get_user(actor_user_id)
        if actor_user_id != target_user_id:
            self.require_permission(actor_user_id, "MANAGE_USERS")
        phash, psalt = hash_password(new_password)
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, password_salt = ? WHERE id = ?",
                (phash, psalt, target_user_id),
            )
            self._log_in_tx(
                conn,
                user_id=actor["id"],
                username=actor["username"],
                action="CHANGE_PASSWORD",
                entity_type="users",
                entity_id=str(target_user_id),
                reason=reason,
            )

    def set_user_active(self, admin_user_id: int, target_user_id: int, is_active: bool, reason: str) -> None:
        """Activate or deactivate a user account (Admin only)."""
        admin = self.require_permission(admin_user_id, "MANAGE_USERS")
        if admin_user_id == target_user_id and not is_active:
            raise ValueError("Administrator cannot deactivate their own active account.")
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE users SET is_active = ? WHERE id = ?",
                (1 if is_active else 0, target_user_id),
            )
            self._log_in_tx(
                conn,
                user_id=admin["id"],
                username=admin["username"],
                action="SET_USER_ACTIVE",
                entity_type="users",
                entity_id=str(target_user_id),
                reason=reason,
                details={"is_active": is_active},
            )

    def list_users(self) -> list[dict[str, Any]]:
        """Return all users without exposing password hashes or salts."""
        with self.db.read_only() as conn:
            rows = conn.execute(
                "SELECT id, username, full_name, role, is_active, created_at, last_login_at FROM users ORDER BY id"
            ).fetchall()
            return [dict(r) for r in rows]

    def log_action(
        self,
        user_id: int | None,
        action: str,
        entity_type: str,
        entity_id: str,
        reason: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record a standalone audit log entry."""
        with self.db.transaction() as conn:
            username = "system"
            if user_id is not None:
                u_row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
                if u_row:
                    username = u_row["username"]
            self._log_in_tx(conn, user_id, username, action, entity_type, entity_id, reason, details)

    @staticmethod
    def _log_in_tx(
        conn: sqlite3.Connection,
        user_id: int | None,
        username: str,
        action: str,
        entity_type: str,
        entity_id: str,
        reason: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Insert an audit log record within an existing database transaction."""
        now_iso = datetime.now().isoformat(timespec="seconds")
        details_json = json.dumps(details, ensure_ascii=False) if details else None
        conn.execute(
            """
            INSERT INTO audit_logs (timestamp, user_id, username, action, entity_type, entity_id, reason, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (now_iso, user_id, username, action, entity_type, str(entity_id), reason, details_json),
        )

    def get_audit_logs(self, limit: int = 200, action_filter: str = "") -> list[dict[str, Any]]:
        """Query recent audit logs."""
        with self.db.read_only() as conn:
            if action_filter:
                rows = conn.execute(
                    """
                    SELECT * FROM audit_logs
                    WHERE action LIKE ? OR entity_type LIKE ? OR username LIKE ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (f"%{action_filter}%", f"%{action_filter}%", f"%{action_filter}%", limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
