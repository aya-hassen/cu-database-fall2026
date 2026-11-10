"""Which feature saves what? UUID alone, INET4 alone, both, and server-made ids.

Run:  python measure_split.py [users] [logins]     (defaults: 200000 and 200000)
Run generate_data.py first with the SAME sizes: this script needs the rows in
users_modern and users_baseline, because every login row points at a user.

The earlier measurement (measure_storage.py) showed login_log about 48% smaller
with UUID and INET4 together. It could not say how much each one contributes.
This script builds five login_log tables from exactly the same rows, in exactly
the same order (rows come from generate_data.build_rows, same seed):

  baseline         CHAR(36) ids,  VARCHAR(15) address
  inet4_only       CHAR(36) ids,  INET4 address
  uuid_only        UUID ids,      VARCHAR(15) address
  modern           UUID ids,      INET4 address
  modern_serverid  like modern, but the SERVER makes each login id with
                   DEFAULT UUID() instead of receiving a random one

Structure is identical in all five (same primary key, same index on user_id,
same foreign key, InnoDB). Only the column types differ, and in the last one
where the login id comes from. The five tables are created here and dropped
at the end, so the four project tables are not touched.

Sizes: information_schema DATA_LENGTH and INDEX_LENGTH after ANALYZE TABLE,
as loaded and after OPTIMIZE TABLE. Before any size is reported, each table
is checked against the baseline with a checksum, so a size is never shown for
different data.
"""
import sys

from app_modern import get_connection
from generate_data import build_rows, insert_chunks

ASCII_ID = "CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL"
ASCII_IP = "VARCHAR(15) CHARACTER SET ascii NOT NULL"

# name: (id column, user_id column, ip column, parent users table, server makes id)
VARIANTS = {
    "baseline":        (ASCII_ID, ASCII_ID, ASCII_IP, "users_baseline", False),
    "inet4_only":      (ASCII_ID, ASCII_ID, "INET4 NOT NULL", "users_baseline", False),
    "uuid_only":       ("UUID NOT NULL", "UUID NOT NULL", ASCII_IP, "users_modern", False),
    "modern":          ("UUID NOT NULL", "UUID NOT NULL", "INET4 NOT NULL", "users_modern", False),
    "modern_serverid": ("UUID NOT NULL DEFAULT UUID()", "UUID NOT NULL",
                        "INET4 NOT NULL", "users_modern", True),
}
ORDER = list(VARIANTS)


def table(name):
    return f"split_{name}"


def create(cursor, name):
    id_col, user_col, ip_col, parent, _ = VARIANTS[name]
    t = table(name)
    cursor.execute(f"DROP TABLE IF EXISTS {t}")  # fixed names, no user input
    cursor.execute(
        f"CREATE TABLE {t} ("
        f" id {id_col}, user_id {user_col}, ip_address {ip_col},"
        " logged_in_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        " PRIMARY KEY (id),"
        f" KEY idx_{t}_user (user_id),"
        f" CONSTRAINT fk_{t}_user FOREIGN KEY (user_id) REFERENCES {parent} (id)"
        ") ENGINE=InnoDB")


def load(cursor, name, login_rows):
    t = table(name)
    if VARIANTS[name][4]:  # the server makes the login id
        insert_chunks(cursor, f"INSERT INTO {t} (user_id, ip_address) VALUES (%s, %s)",
                      [(user_id, ip) for _id, user_id, ip in login_rows])
    else:
        insert_chunks(cursor, f"INSERT INTO {t} (id, user_id, ip_address) "
                      "VALUES (%s, %s, %s)", login_rows)


def checksum(cursor, name, with_id):
    """Row count plus a sum of CRC32 over each column's text form."""
    t = table(name)
    id_part = "SUM(CRC32(CAST(id AS CHAR)))" if with_id else "0"
    cursor.execute(
        f"SELECT COUNT(*), {id_part}, SUM(CRC32(CAST(user_id AS CHAR))), "
        f"SUM(CRC32(CAST(ip_address AS CHAR))) FROM {t}")
    return cursor.fetchone()


def size(cursor, name):
    t = table(name)
    cursor.execute(f"ANALYZE TABLE {t}")
    cursor.fetchall()
    cursor.execute(
        "SELECT DATA_LENGTH, INDEX_LENGTH FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s", (t,))
    data, index = (int(v) for v in cursor.fetchone())
    return data, index


def report(title, sizes, rows):
    print(f"######## {title} ########\n")
    base_total = sum(sizes["baseline"])
    print(f"{'variant':<17}{'data':>13}{'index':>13}{'total':>13}"
          f"{'per row':>10}{'saved vs baseline':>20}")
    for name in ORDER:
        data, index = sizes[name]
        total = data + index
        saved = 100 * (base_total - total) / base_total
        print(f"{name:<17}{data:>13}{index:>13}{total:>13}{total / rows:>10.1f}"
              f"{saved:>19.1f}%")
    each = {n: (base_total - sum(sizes[n])) / rows
            for n in ("inet4_only", "uuid_only", "modern")}
    print(f"\nBytes saved per row compared with baseline:")
    print(f"  INET4 alone           {each['inet4_only']:>7.1f}")
    print(f"  UUID alone            {each['uuid_only']:>7.1f}")
    print(f"  the two added up      {each['inet4_only'] + each['uuid_only']:>7.1f}")
    print(f"  both together         {each['modern']:>7.1f}\n")


def main():
    n_users = int(sys.argv[1]) if len(sys.argv) > 1 else 200000
    n_logins = int(sys.argv[2]) if len(sys.argv) > 2 else 200000
    # The password hash is not used here, so any text will do.
    _users, login_rows = build_rows(n_users, n_logins, "unused")

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT VERSION()")
        print("MariaDB version:", cursor.fetchone()[0])
        for t in ("users_modern", "users_baseline"):
            cursor.execute(f"SELECT COUNT(*) FROM {t}")
            if cursor.fetchone()[0] != n_users:
                sys.exit(f"{t} does not hold {n_users} rows. Run "
                         f"'python generate_data.py {n_users} {n_logins}' first.")
        print(f"Rows per table: {n_logins} logins (users: {n_users})\n")

        for name in ORDER:
            create(cursor, name)
            load(cursor, name, login_rows)
            conn.commit()

        # Same data in every table? Compare with the baseline.
        ref = checksum(cursor, "baseline", True)
        print("Data check against baseline (rows, ids, user ids, addresses):")
        for name in ORDER:
            got = checksum(cursor, name, not VARIANTS[name][4])
            want = ref if not VARIANTS[name][4] else (ref[0], 0, ref[2], ref[3])
            note = " (login ids differ by design: made by the server)" \
                if VARIANTS[name][4] else ""
            print(f"  {name:<17}{'identical' if got == want else 'DIFFERENT'}{note}")
            if got != want:
                sys.exit("Data differs, so the sizes would not be comparable.")
        print()

        report("AS LOADED", {n: size(cursor, n) for n in ORDER}, n_logins)

        for name in ORDER:
            cursor.execute(f"OPTIMIZE TABLE {table(name)}")  # fixed names
            cursor.fetchall()
        report("AFTER OPTIMIZE TABLE (pages packed)",
               {n: size(cursor, n) for n in ORDER}, n_logins)
    finally:
        for name in ORDER:
            cursor.execute(f"DROP TABLE IF EXISTS {table(name)}")
        conn.commit()
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()