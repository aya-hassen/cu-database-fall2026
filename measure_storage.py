"""Storage measurement: modern against baseline, same data in both.

Run:  python measure_storage.py      (needs DB_PASSWORD set, see app_modern.py)
Run generate_data.py first, so both versions hold identical rows.

Sizes come from information_schema.TABLES after ANALYZE TABLE.
Row counts come from COUNT(*) (TABLE_ROWS is only an estimate in InnoDB).
DATA_LENGTH includes the primary key, because InnoDB stores the table
inside its primary-key index. INDEX_LENGTH is all secondary indexes.
"""
from app_modern import get_connection

PAIRS = [
    ("users", "users_modern", "users_baseline"),
    ("login_log", "login_log_modern", "login_log_baseline"),
]


def measure(cursor, table):
    cursor.execute(f"ANALYZE TABLE {table}")  # fixed table names, no user input
    cursor.fetchall()  # ANALYZE returns a result set that must be read
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    (rows,) = cursor.fetchone()
    cursor.execute(
        "SELECT DATA_LENGTH, INDEX_LENGTH FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s", (table,))
    data, index = cursor.fetchone()
    return rows, int(data), int(index)


def main():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT VERSION()")
        print("MariaDB version:", cursor.fetchone()[0], "\n")
        for label, modern, baseline in PAIRS:
            m_rows, m_data, m_idx = measure(cursor, modern)
            b_rows, b_data, b_idx = measure(cursor, baseline)
            print(f"== {label} ({m_rows} rows modern, {b_rows} rows baseline)")
            print(f"{'':<14}{'modern':>12}{'baseline':>12}{'saved':>12}{'saved %':>10}")
            for name, m, b in (("data bytes", m_data, b_data),
                               ("index bytes", m_idx, b_idx),
                               ("total bytes", m_data + m_idx, b_data + b_idx)):
                pct = 100 * (b - m) / b if b else 0
                print(f"{name:<14}{m:>12}{b:>12}{b - m:>12}{pct:>9.1f}%")
            print(f"{'bytes per row':<14}{(m_data + m_idx) / m_rows:>12.1f}"
                  f"{(b_data + b_idx) / b_rows:>12.1f}\n")
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()