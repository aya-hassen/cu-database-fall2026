"""Baseline version: the same application without UUID, INET4 or RETURNING.

Run:  python app_baseline.py
Connection settings come from environment variables, never from the code:
    DB_HOST (default 127.0.0.1), DB_USER (default root),
    DB_PASSWORD (required), DB_NAME (default sql_features_project)

Differences from app_modern.py, on purpose:
  * ids are CHAR(36) text generated here in Python (no DEFAULT UUID() in the table)
  * IP addresses are plain VARCHAR(15) strings
  * there is no RETURNING, so values the SERVER produced (created_at,
    logged_in_at) need a second SELECT after each insert
"""
import hashlib
import os
import secrets
import time
import uuid

import mysql.connector

# Counts every statement sent to the server, same as in app_modern.py,
# so the two versions can be compared exactly.
QUERY_COUNT = 0


def get_connection():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ["DB_PASSWORD"],
        database=os.environ.get("DB_NAME", "sql_features_project"),
    )


def run(cursor, sql, params=None):
    """Execute one statement and count it (one round trip)."""
    global QUERY_COUNT
    QUERY_COUNT += 1
    cursor.execute(sql, params)


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return salt.hex() + "$" + digest.hex()


def signup(cursor, email, password):
    """Two statements. The id is generated here, so it is already known,
    but created_at is produced by the server, so it needs a read-back."""
    user_id = str(uuid.uuid4())
    run(
        cursor,
        "INSERT INTO users_baseline (id, email, password_hash) VALUES (%s, %s, %s)",
        (user_id, email, hash_password(password)),
    )
    run(cursor, "SELECT created_at FROM users_baseline WHERE id = %s", (user_id,))
    (created_at,) = cursor.fetchone()
    return user_id, created_at


def log_login(cursor, user_id, ip_address):
    """Two statements, for the same reason: logged_in_at comes from the server."""
    log_id = str(uuid.uuid4())
    run(
        cursor,
        "INSERT INTO login_log_baseline (id, user_id, ip_address) VALUES (%s, %s, %s)",
        (log_id, user_id, ip_address),
    )
    run(cursor, "SELECT logged_in_at FROM login_log_baseline WHERE id = %s", (log_id,))
    (logged_in_at,) = cursor.fetchone()
    return log_id, logged_in_at


def main():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        email = f"demo_{int(time.time())}@example.com"
        user_id, created_at = signup(cursor, email, "correct horse battery")
        print("Signed up:", email, user_id, created_at)

        for ip in ("192.168.1.10", "192.168.1.9", "10.0.0.2"):
            log_id, at = log_login(cursor, user_id, ip)
            print("Login logged:", ip, log_id, at)
        conn.commit()

        run(cursor, "SELECT ip_address FROM login_log_baseline "
                    "WHERE user_id = %s ORDER BY ip_address", (user_id,))
        print("IPs in VARCHAR order:", [r[0] for r in cursor.fetchall()])
        print("Statements sent to the server:", QUERY_COUNT)
    except mysql.connector.Error as err:
        conn.rollback()
        print("Database error:", err)
        raise
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
