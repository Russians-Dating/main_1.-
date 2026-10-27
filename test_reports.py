import sqlite3
from database import get_conn, dict_from_row
from keyboards import report_action_kb
from utils import escape_html

# Тестируем show_admin_reports вручную
try:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM reports WHERE status = 'pending'")
        total = cur.fetchone()[0]
        print(f"Total pending: {total}")
        if total == 0:
            print("No reports")
        else:
            cur.execute('''
                SELECT r.*,
                       u1.name as reporter_name, u1.tg_id as reporter_tg,
                       u2.name as reported_name, u2.tg_id as reported_tg
                FROM reports r
                LEFT JOIN users u1 ON r.reporter_id = u1.id
                LEFT JOIN users u2 ON r.reported_id = u2.id
                WHERE r.status = 'pending'
                ORDER BY r.created_at DESC
                LIMIT 5 OFFSET 0
            ''')
            rows = cur.fetchall()
            print(f"Rows found: {len(rows)}")
            for r in rows:
                d = dict_from_row(r)
                print(f"  Report #{d['id']}: reported_id={d['reported_id']}, reason={d['reason']}")
                # Проверяем report_action_kb
                kb = report_action_kb(d['reported_id'], d['id'])
                print(f"  KB: {kb.keyboard}")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
