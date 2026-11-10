"""Migration time: how long does it take to convert baseline tables to native types?

Run:  python measure_migration.py [runs]      (default 3 runs)
Run generate_data.py first: this script copies the rows of users_baseline and
login_log_baseline.

Question: a team already has tables with CHAR(36) ids and VARCHAR(15)
addresses. What does switching to UUID and INET4 cost?

Each run, in a scratch database (sql_features_migration), so the four project
tables are never altered:
  1. create copies of the two baseline tables and copy the rows in (not timed)
  2. time four steps, with ALTER TABLE on the filled tables:
       a. drop the foreign key
       b. users.id            CHAR(36) -> UUID
       c. login_log id, user_id, ip_address -> UUID, UUID, INET4   (one ALTER)
       d. add the foreign key back
  3. verify: every migrated row equals the matching row in the modern tables
  4. read the size of the migrated tables

The scratch database is dropped at the end. Times are wall-clock seconds as
seen by the client; the three runs show how much they vary.
"""
import statistics
import sys
import time

from app_modern import get_connection

SCRATCH = "sql_features_migration"
SOURCE_USERS = "users_baseline"
SOURCE_LOGINS = "login_log_baseline"


def build_scratch(cursor):
    cursor.execute(f"DROP DATABASE IF EXISTS {SCRATCH}")
    cursor.execute(f"CREATE DATABASE {SCRATCH} CHARACTER SET utf8mb4 "
                   "COLLATE utf8mb4_unicode_ci")
    # The baseline tables exactly as in database/schema.sql.
    cursor.execute(f"""
        CREATE TABLE {SCRATCH}.users_baseline (
            id            CHAR(36)     CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
            email         VARCHAR(255) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uq_users_baseline_email (email)
        ) ENGINE=InnoDB""")
    cursor.execute(f"""
        CREATE TABLE {SCRATCH}.login_log_baseline (
            id           CHAR(36)    CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
            user_id      CHAR(36)    CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
            ip_address   VARCHAR(15) CHARACTER SET ascii NOT NULL,
            logged_in_at TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_login_log_baseline_user (user_id),
            CONSTRAINT fk_login_log_baseline_user
                FOREIGN KEY (user_id) REFERENCES users_baseline (id)
        ) ENGINE=InnoDB""")
    cursor.execute(f"INSERT INTO {SCRATCH}.users_baseline "
                   f"SELECT * FROM {SOURCE_USERS}")
    cursor.execute(f"INSERT INTO {SCRATCH}.login_log_baseline "
                   f"SELECT * FROM {SOURCE_LOGINS}")


def timed(cursor, sql):
    start = time.perf_counter()
    cursor.execute(sql)
    return time.perf_counter() - start


def migrate(cursor):
    """The four timed steps. Returns {step: seconds}."""
    t = {}
    t["drop foreign key"] = timed(cursor,
        f"ALTER TABLE {SCRATCH}.login_log_baseline DROP FOREIGN KEY fk_login_log_baseline_user")
    t["users.id to UUID"] = timed(cursor,
        f"ALTER TABLE {SCRATCH}.users_baseline MODIFY id UUID NOT NULL")
    t["login_log to UUID, UUID, INET4"] = timed(cursor,
        f"ALTER TABLE {SCRATCH}.login_log_baseline MODIFY id UUID NOT NULL, "
        "MODIFY user_id UUID NOT NULL, MODIFY ip_address INET4 NOT NULL")
    t["add foreign key"] = timed(cursor,
        f"ALTER TABLE {SCRATCH}.login_log_baseline ADD CONSTRAINT "
        "fk_login_log_baseline_user FOREIGN KEY (user_id) "
        f"REFERENCES {SCRATCH}.users_baseline (id)")
    t["TOTAL"] = sum(t.values())
    return t


def verify(cursor):
    """Rows that match the modern tables on every column. Must equal the row counts."""
    cursor.execute(
        f"SELECT COUNT(*) FROM {SCRATCH}.login_log_baseline m "
        "JOIN login_log_modern r ON r.id = m.id AND r.user_id = m.user_id "
        "AND r.ip_address = m.ip_address")
    (logins_ok,) = cursor.fetchone()
    cursor.execute(
        f"SELECT COUNT(*) FROM {SCRATCH}.users_baseline m "
        "JOIN users_modern r ON r.id = m.id AND r.email = m.email")
    (users_ok,) = cursor.fetchone()
    cursor.execute(f"SELECT COUNT(*) FROM {SCRATCH}.users_baseline")
    (users_n,) = cursor.fetchone()
    cursor.execute(f"SELECT COUNT(*) FROM {SCRATCH}.login_log_baseline")
    (logins_n,) = cursor.fetchone()
    return users_ok, users_n, logins_ok, logins_n


def sizes(cursor, schema, tables):
    total = 0
    for t in tables:
        cursor.execute(f"ANALYZE TABLE {schema}.{t}")  # fixed names, no user input
        cursor.fetchall()
    cursor.execute(
        "SELECT SUM(DATA_LENGTH + INDEX_LENGTH) FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN (%s, %s)", (schema, *tables))
    (total,) = cursor.fetchone()
    return int(total)


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT VERSION()")
        print("MariaDB version:", cursor.fetchone()[0])
        cursor.execute("SELECT DATABASE()")
        (project_db,) = cursor.fetchone()
        cursor.execute(f"SELECT COUNT(*) FROM {SOURCE_USERS}")
        (n_users,) = cursor.fetchone()
        cursor.execute(f"SELECT COUNT(*) FROM {SOURCE_LOGINS}")
        (n_logins,) = cursor.fetchone()
        if not n_users or not n_logins:
            sys.exit("The baseline tables are empty. Run generate_data.py first.")
        print(f"Migrating {n_users} users and {n_logins} logins, {runs} runs\n")

        all_runs, last_check, migrated_size = [], None, None
        for i in range(1, runs + 1):
            build_scratch(cursor)
            conn.commit()
            times = migrate(cursor)
            conn.commit()
            all_runs.append(times)
            last_check = verify(cursor)
            migrated_size = sizes(cursor, SCRATCH, ("users_baseline", "login_log_baseline"))
            print(f"run {i}: " + "   ".join(f"{k} {v:.2f}s" for k, v in times.items()))

        steps = list(all_runs[0])
        print(f"\n{'step':<34}" + "".join(f"{'run ' + str(i + 1):>9}" for i in range(runs))
              + f"{'median':>9}")
        for s in steps:
            vals = [r[s] for r in all_runs]
            print(f"{s:<34}" + "".join(f"{v:>8.2f}s" for v in vals)
                  + f"{statistics.median(vals):>8.2f}s")

        users_ok, users_n, logins_ok, logins_n = last_check
        print(f"\nVerification after migration: users {users_ok} of {users_n} rows "
              f"match the modern table, logins {logins_ok} of {logins_n}.")
        modern_size = sizes(cursor, project_db, ("users_modern", "login_log_modern"))
        print(f"Size of the migrated tables: {migrated_size} bytes "
              f"(the modern tables as loaded: {modern_size} bytes).")
        if (users_ok, logins_ok) != (users_n, logins_n):
            sys.exit("Migration changed data. Do not report these times.")
    finally:
        cursor.execute(f"DROP DATABASE IF EXISTS {SCRATCH}")
        conn.commit()
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()