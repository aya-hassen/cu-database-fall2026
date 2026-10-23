import sys
import time
import uuid

import mysql.connector

from app_modern import get_connection, hash_password

IPS = ("192.168.1.10", "192.168.1.9", "10.0.0.2")


class Counter:
    """Counts every statement sent to the server (one round trip each)."""

    def __init__(self):
        self.n = 0

    def run(self, cursor, sql, params=None):
        self.n += 1
        cursor.execute(sql, params)


def seed(cursor, prefix, n, pw):
    """Setup, not counted. Same users and same logins in both versions."""
    users = []
    for i in range(n):
        email = f"{prefix}-{i}@example.com"

        cursor.execute(
            "INSERT INTO users_modern (email, password_hash) VALUES (%s, %s) RETURNING id",
            (email, pw),
        )
        (uid_m,) = cursor.fetchone()
        for ip in IPS:
            cursor.execute(
                "INSERT INTO login_log_modern (user_id, ip_address) VALUES (%s, %s)",
                (uid_m, ip),
            )

        uid_b = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO users_baseline (id, email, password_hash) VALUES (%s, %s, %s)",
            (uid_b, email, pw),
        )
        for ip in IPS:
            cursor.execute(
                "INSERT INTO login_log_baseline (id, user_id, ip_address) VALUES (%s, %s, %s)",
                (str(uuid.uuid4()), uid_b, ip),
            )
        users.append((email, uid_m, uid_b))
    return users


def cleanup(cursor, prefix):
    """Remove everything this run created (not counted)."""
    like = prefix + "-%"
    for version in ("modern", "baseline"):
        cursor.execute(
            f"DELETE FROM login_log_{version} WHERE user_id IN "
            f"(SELECT id FROM users_{version} WHERE email LIKE %s)",
            (like,),
        )
        cursor.execute(f"DELETE FROM users_{version} WHERE email LIKE %s", (like,))


# ---- Scenario A: change e-mail, return old and new ----------------------------

def change_email_modern(c, cursor, user_id, new_email):
    c.run(
        cursor,
        "UPDATE users_modern SET email = %s WHERE id = %s "
        "RETURNING OLD_VALUE(email) AS old_email, email AS new_email",
        (new_email, user_id),
    )
    return [tuple(r) for r in cursor.fetchall()]


def change_email_baseline(c, cursor, user_id, new_email):
    c.run(cursor, "SELECT email FROM users_baseline WHERE id = %s FOR UPDATE", (user_id,))
    row = cursor.fetchone()
    c.run(cursor, "UPDATE users_baseline SET email = %s WHERE id = %s", (new_email, user_id))
    # The new value is the one we just wrote, so it needs no read-back.
    return [(row[0], new_email)]


# ---- Scenario B: delete login history, return deleted rows -------------------

def delete_logins_modern(c, cursor, user_id):
    c.run(
        cursor,
        "DELETE FROM login_log_modern WHERE user_id = %s RETURNING ip_address",
        (user_id,),
    )
    return sorted(str(r[0]) for r in cursor.fetchall())


def delete_logins_baseline(c, cursor, user_id):
    c.run(
        cursor,
        "SELECT ip_address FROM login_log_baseline WHERE user_id = %s FOR UPDATE",
        (user_id,),
    )
    rows = sorted(str(r[0]) for r in cursor.fetchall())
    c.run(cursor, "DELETE FROM login_log_baseline WHERE user_id = %s", (user_id,))
    return rows


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    prefix = f"returning-demo-{int(time.time())}"
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT VERSION()")
        print("Server:", cursor.fetchone()[0])
        print(f"Operations per scenario: {n}\n")

        users = seed(cursor, prefix, n, hash_password("demo password"))
        conn.commit()

        results = []  # (label, modern_count, baseline_count, identical, t_modern, t_base)

        # ---- Scenario A ----------------------------------------------------
        label = "A. change e-mail, need old + new"
        cm, cb = Counter(), Counter()
        same, tm, tb = True, 0.0, 0.0
        skipped = False
        try:
            for i, (_email, uid_m, uid_b) in enumerate(users):
                new_email = f"{prefix}-{i}-new@example.com"
                t = time.perf_counter()
                got_m = change_email_modern(cm, cursor, uid_m, new_email)
                conn.commit()
                tm += time.perf_counter() - t

                t = time.perf_counter()
                got_b = change_email_baseline(cb, cursor, uid_b, new_email)
                conn.commit()
                tb += time.perf_counter() - t

                same = same and got_m == got_b
        except mysql.connector.Error as err:
            conn.rollback()
            if err.errno == 1064:  # syntax error: server too old
                skipped = True
                print("Scenario A skipped: this server does not accept UPDATE ... RETURNING")
                print("(it needs MariaDB 13.0 or newer).\n")
            else:
                raise
        if not skipped:
            results.append((label, cm.n, cb.n, same, tm, tb))

        # ---- Scenario B ----------------------------------------------------
        label = "B. delete logins, need deleted rows"
        cm, cb = Counter(), Counter()
        same, tm, tb = True, 0.0, 0.0
        for _email, uid_m, uid_b in users:
            t = time.perf_counter()
            got_m = delete_logins_modern(cm, cursor, uid_m)
            conn.commit()
            tm += time.perf_counter() - t

            t = time.perf_counter()
            got_b = delete_logins_baseline(cb, cursor, uid_b)
            conn.commit()
            tb += time.perf_counter() - t

            same = same and got_m == got_b == sorted(IPS)
        results.append((label, cm.n, cb.n, same, tm, tb))

        # ---- Report --------------------------------------------------------
        print(f"{'scenario':<38}{'modern':>8}{'baseline':>10}{'saved':>7}  results identical")
        for label, m, b, ok, _tm, _tb in results:
            print(f"{label:<38}{m:>8}{b:>10}{b - m:>7}  {ok}")
        print("\nStatements = round trips sent to the server (seeding, cleanup, COMMIT not counted).")
        print("\nWall-clock for the whole scenario (one run, local server, NOT a measurement):")
        for label, _m, _b, _ok, tm, tb in results:
            print(f"  {label:<36} modern {tm * 1000:7.1f} ms   baseline {tb * 1000:7.1f} ms")
    finally:
        try:
            conn.rollback()
            cleanup(cursor, prefix)
            conn.commit()
        finally:
            cursor.close()
            conn.close()


if __name__ == "__main__":
    main()