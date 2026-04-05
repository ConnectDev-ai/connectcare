import psycopg2
conn = psycopg2.connect(
      host='aws-1-us-east-2.pooler.supabase.com',
      port=6543,
      user='postgres.ceprzonmxserzkxxkwrj',
      password='rJf7*m2k8ziSwh@',
      dbname='postgres',
      sslmode='require'
  )
print('OK:', conn.get_dsn_parameters())
conn.close()