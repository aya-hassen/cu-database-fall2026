"""Modern version: uses UUID, INET4 and RETURNING.

Run:  python app_modern.py
Connection settings come from environment variables, never from the code:
    DB_HOST (default 127.0.0.1), DB_USER (default root),
    DB_PASSWORD (required), DB_NAME (default sql_features_project)
"""
import hashlib
import os
import secrets
import time

import mysql.connector

# Counts every statement sent to the server, so the measurements later
# can compare round trips between the modern and baseline versions.
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
    """One statement: INSERT ... RETURNING gives back the server-made id
    and created_at, so no follow-up SELECT is needed."""
    run(
        cursor,
        "INSERT INTO users_modern (email, password_hash) VALUES (%s, %s) "
        "RETURNING id, created_at",
        (email, hash_password(password)),
    )
    return cursor.fetchone()


def log_login(cursor, user_id, ip_address):
    """ip_address goes into an INET4 column as a normal dotted string."""
    run(
        cursor,
        "INSERT INTO login_log_modern (user_id, ip_address) VALUES (%s, %s) "
        "RETURNING id, logged_in_at",
        (user_id, ip_address),
    )
    return cursor.fetchone()


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

        run(cursor, "SELECT ip_address FROM login_log_modern "
                    "WHERE user_id = %s ORDER BY ip_address", (user_id,))
        print("IPs in INET4 order:", [r[0] for r in cursor.fetchall()])
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