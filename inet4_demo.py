"""INET4 demo: the same IP addresses in both versions, two queries each.

Run:  python inet4_demo.py      (needs DB_PASSWORD set, see app_modern.py)

1. ORDER BY ip_address
2. ip_address BETWEEN '192.168.1.2' AND '192.168.1.20'

The expected answer is computed in Python with the ipaddress module, so
"correct" means correct numerically, not "whatever the database returned".
"""
import ipaddress
import time
import uuid

from app_modern import get_connection, hash_password

# Deliberately not in order. The cases that trip up text sorting:
# .9 vs .10 vs .100, and 10.x.x.x vs 9.x.x.x vs 100.x.x.x.
IPS = [
    "192.168.1.10", "10.0.0.2", "192.168.1.9", "192.168.1.100",
    "9.255.255.255", "192.168.1.2", "10.0.0.10", "100.0.0.1",
]
LOW, HIGH = "192.168.1.2", "192.168.1.20"


def numeric(ip):
    return int(ipaddress.IPv4Address(ip))


def seed(cursor):
    """Same user and same IPs into both versions. Returns the two user ids."""
    email = f"inet4demo_{int(time.time())}@example.com"
    pw = hash_password("demo password")

    cursor.execute(
        "INSERT INTO users_modern (email, password_hash) VALUES (%s, %s) RETURNING id",
        (email, pw),
    )
    (uid_modern,) = cursor.fetchone()
    for ip in IPS:
        cursor.execute(
            "INSERT INTO login_log_modern (user_id, ip_address) VALUES (%s, %s)",
            (uid_modern, ip),
        )

    uid_base = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO users_baseline (id, email, password_hash) VALUES (%s, %s, %s)",
        (uid_base, email, pw),
    )
    for ip in IPS:
        cursor.execute(
            "INSERT INTO login_log_baseline (id, user_id, ip_address) VALUES (%s, %s, %s)",
            (str(uuid.uuid4()), uid_base, ip),
        )
    return uid_modern, uid_base


def column(cursor, sql, params):
    cursor.execute(sql, params)
    return [str(r[0]) for r in cursor.fetchall()]


def main():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        uid_m, uid_b = seed(cursor)
        conn.commit()

        # ---- Query 1: ORDER BY ------------------------------------------
        modern = column(cursor, "SELECT ip_address FROM login_log_modern "
                                "WHERE user_id = %s ORDER BY ip_address", (uid_m,))
        base = column(cursor, "SELECT ip_address FROM login_log_baseline "
                              "WHERE user_id = %s ORDER BY ip_address", (uid_b,))
        expected = sorted(IPS, key=numeric)

        print("QUERY 1: SELECT ip_address ... ORDER BY ip_address\n")
        print(f"{'position':<9}{'expected':<16}{'INET4':<16}{'VARCHAR(15)':<16}")
        for i, (e, m, b) in enumerate(zip(expected, modern, base), 1):
            flag = "" if b == e else "   <-- wrong"
            print(f"{i:<9}{e:<16}{m:<16}{b:<16}{flag}")
        print("\nINET4 order correct:      ", modern == expected)
        print("VARCHAR(15) order correct:", base == expected)

        # ---- Query 2: range ---------------------------------------------
        want = sorted([ip for ip in IPS if numeric(LOW) <= numeric(ip) <= numeric(HIGH)],
                      key=numeric)
        modern_r = column(cursor,
                          "SELECT ip_address FROM login_log_modern WHERE user_id = %s "
                          "AND ip_address BETWEEN %s AND %s", (uid_m, LOW, HIGH))
        base_r = column(cursor,
                        "SELECT ip_address FROM login_log_baseline WHERE user_id = %s "
                        "AND ip_address BETWEEN %s AND %s", (uid_b, LOW, HIGH))

        print(f"\nQUERY 2: ip_address BETWEEN '{LOW}' AND '{HIGH}'\n")
        print("expected:   ", want)
        print("INET4:      ", sorted(modern_r, key=numeric))
        print("VARCHAR(15):", sorted(base_r, key=numeric))
        print("\nINET4 range correct:      ", set(modern_r) == set(want))
        print("VARCHAR(15) range correct:", set(base_r) == set(want))
        missing = sorted(set(want) - set(base_r), key=numeric)
        if missing:
            print("VARCHAR(15) silently missed:", missing)
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
