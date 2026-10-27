"""Storage measurement: modern against baseline, same data in both.

Run:  python measure_storage.py      (needs DB_PASSWORD set, see app_modern.py)
Run generate_data.py first, so both versions hold identical rows.

Sizes are DATA_LENGTH and INDEX_LENGTH from information_schema.TABLES after
ANALYZE TABLE: the space InnoDB has allocated. InnoDB allocates in 1 MB steps
once a table passes a few dozen pages, so on small tables a difference can be
rounded by up to 1 MB. That is why generate_data.py loads 200,000 rows per table.

DATA_LENGTH includes the primary key, because InnoDB stores the table inside
its primary-key index. INDEX_LENGTH is all secondary indexes.

Each pair is measured twice: as loaded, and after OPTIMIZE TABLE rebuilt it
with packed pages. "As loaded" is what a table that grew by random inserts
looks like. "After OPTIMIZE" is closer to what the column types alone save.
Row counts come from COUNT(*) (TABLE_ROWS is only an estimate in InnoDB).
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
    data, index = (int(v) for v in cursor.fetchone())
    return {"rows": rows, "data": data, "index": index}


def row(name, m, b):
    pct = 100 * (b - m) / b if b else 0
    return f"{name:<22}{m:>12}{b:>12}{b - m:>12}{pct:>9.1f}%"


def report(label, m, b):
    print(f"== {label} ({m['rows']} rows modern, {b['rows']} rows baseline)")
    print(f"{'':<22}{'modern':>12}{'baseline':>12}{'saved':>12}{'saved %':>10}")
    print(row("data bytes", m["data"], b["data"]))
    print(row("index bytes", m["index"], b["index"]))
    print(row("total bytes", m["data"] + m["index"], b["data"] + b["index"]))
    tm, tb = m["data"] + m["index"], b["data"] + b["index"]
    print(f"{'bytes per row':<22}{tm / m['rows']:>12.1f}{tb / b['rows']:>12.1f}\n")


def main():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT VERSION()")
        print("MariaDB version:", cursor.fetchone()[0])
        cursor.execute("SELECT @@innodb_page_size")
        print("InnoDB page size:", cursor.fetchone()[0], "bytes\n")

        print("######## AS LOADED ########\n")
        for label, modern, baseline in PAIRS:
            report(label, measure(cursor, modern),
                   measure(cursor, baseline))

        for _label, modern, baseline in PAIRS:
            for table in (modern, baseline):
                cursor.execute(f"OPTIMIZE TABLE {table}")  # fixed names
                cursor.fetchall()

        print("######## AFTER OPTIMIZE TABLE (pages packed) ########\n")
        for label, modern, baseline in PAIRS:
            report(label, measure(cursor, modern),
                   measure(cursor, baseline))
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()