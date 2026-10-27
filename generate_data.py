"""Data generator: identical synthetic data in the modern and baseline tables.

Run:  python generate_data.py [users] [logins]     (defaults: 200000 users, 200000 logins)
Needs DB_PASSWORD set, see app_modern.py.

A fixed random seed means every run produces exactly the same ids, e-mails
and IP addresses (only the shared password hash differs between runs, and it
has the same length every time, so it does not change any size).

Why this big: InnoDB reserves space in 1 MB steps, so on a table of a few
hundred KB a size difference can be rounded up or down by that much. At
200,000 rows the tables are tens of MB and that rounding is a few percent.

The ids are random version-4 UUIDs inserted in random primary-key order,
the same order into both versions. That is the worst case for page fill and
it is identical on both sides, so only the column types differ. WARNING: it first empties (TRUNCATE) all four tables.
All users share one password hash, because hashing 200,000 passwords with
200,000 iterations each would take minutes and tells us nothing about the
features we compare.
"""
import random
import sys
import uuid

from app_modern import get_connection, hash_password

SEED = 42
CHUNK = 1000


def random_ip(rng):
    """Mix of ranges, so addresses have 1, 2 and 3 digit parts and text sorting breaks."""
    kind = rng.choice(["private_c", "private_a", "single_digit", "hundreds", "any"])
    if kind == "private_c":
        return f"192.168.{rng.randint(0, 255)}.{rng.randint(1, 254)}"
    if kind == "private_a":
        return f"10.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"
    if kind == "single_digit":
        return f"{rng.randint(1, 9)}.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"
    if kind == "hundreds":
        return f"{rng.randint(100, 223)}.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"
    return f"{rng.randint(1, 223)}.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"


def new_uuid(rng):
    """A valid version-4 UUID made from the seeded generator (uuid.uuid4 is not repeatable)."""
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def insert_chunks(cursor, sql, rows):
    for i in range(0, len(rows), CHUNK):
        cursor.executemany(sql, rows[i:i + CHUNK])


def main():
    n_users = int(sys.argv[1]) if len(sys.argv) > 1 else 200000
    n_logins = int(sys.argv[2]) if len(sys.argv) > 2 else 200000
    rng = random.Random(SEED)
    pw = hash_password("demo password")

    user_rows = [(new_uuid(rng), f"user{i}@example.com", pw) for i in range(n_users)]
    user_ids = [r[0] for r in user_rows]
    login_rows = [(new_uuid(rng), rng.choice(user_ids), random_ip(rng))
                  for _ in range(n_logins)]

    conn = get_connection()
    cursor = conn.cursor()
    try:
        # TRUNCATE, not DELETE: DELETE leaves the old pages allocated, so a
        # re-run with fewer rows would report sizes left over from the earlier
        # run. TRUNCATE rebuilds the table empty. A table that a foreign key
        # points at cannot be truncated while checks are on, so switch them off
        # for these four statements only.
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        for table in ("login_log_modern", "login_log_baseline",
                      "users_modern", "users_baseline"):
            cursor.execute(f"TRUNCATE TABLE {table}")  # fixed table names, no user input
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")

        for suffix in ("modern", "baseline"):
            insert_chunks(cursor,
                          f"INSERT INTO users_{suffix} (id, email, password_hash) "
                          "VALUES (%s, %s, %s)", user_rows)
            insert_chunks(cursor,
                          f"INSERT INTO login_log_{suffix} (id, user_id, ip_address) "
                          "VALUES (%s, %s, %s)", login_rows)
        conn.commit()

        for table in ("users_modern", "users_baseline",
                      "login_log_modern", "login_log_baseline"):
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            print(f"{table:<22}{cursor.fetchone()[0]} rows")
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()