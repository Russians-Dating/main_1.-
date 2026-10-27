import sqlite3

conn = sqlite3.connect('lovebot.db')
c = conn.cursor()
c.execute("SELECT COUNT(*) FROM reports WHERE status='pending'")
print('Pending:', c.fetchone()[0])
c.execute("SELECT * FROM reports ORDER BY id DESC LIMIT 5")
for r in c.fetchall():
    print(r)
conn.close()
