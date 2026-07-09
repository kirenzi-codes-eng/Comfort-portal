import os
import psycopg2

print('ENV', os.environ.get('DATABASE_URL'), os.environ.get('DB_HOST'))
database_url = os.environ.get('DATABASE_URL') or os.environ.get('NEON_DATABASE_URL')
if database_url:
    conn = psycopg2.connect(database_url, sslmode='require')
else:
    host = os.environ.get('DB_HOST')
    dbname = os.environ.get('DB_NAME')
    user = os.environ.get('DB_USER')
    password = os.environ.get('DB_PASSWORD') or os.environ.get('DB_PASS')
    port = os.environ.get('DB_PORT', '5432')
    conn = psycopg2.connect(host=host, dbname=dbname, user=user, password=password, port=port, sslmode='require')
cur = conn.cursor()
cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='members';")
for row in cur.fetchall():
    print(row)
cur.execute('SELECT COUNT(*) FROM members;')
count_row = cur.fetchone()
print('COUNT', count_row["count"] if isinstance(count_row, dict) else count_row[0])
conn.close()
