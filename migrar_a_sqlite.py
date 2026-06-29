import mysql.connector
import sqlite3
import os
import sys

# Configure stdout to UTF-8 to prevent console encoding crashes
sys.stdout.reconfigure(encoding='utf-8')

def migrar():
    print("Iniciando migración de MySQL a SQLite...")
    
    # Connect to MySQL
    try:
        mysql_conn = mysql.connector.connect(
            host="localhost",
            user="root",
            password="",
            database="biblia_app",
            charset='utf8mb4'
        )
        mysql_cur = mysql_conn.cursor(dictionary=True)
    except Exception as e:
        print(f"Error al conectar a MySQL: {e}")
        return

    # Connect to SQLite (creates the file db.sqlite3)
    sqlite_path = "./db.sqlite3"
    if os.path.exists(sqlite_path):
        os.remove(sqlite_path)
        
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_cur = sqlite_conn.cursor()

    # Create table in SQLite
    sqlite_cur.execute("""
    CREATE TABLE IF NOT EXISTS versiculos_explicados (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        libro TEXT,
        capitulo INTEGER,
        versiculo INTEGER,
        texto_biblico TEXT,
        explicacion TEXT
    )
    """)
    
    # Create indexes in SQLite for fast searches
    sqlite_cur.execute("CREATE INDEX IF NOT EXISTS idx_libro ON versiculos_explicados (libro)")
    sqlite_cur.execute("CREATE INDEX IF NOT EXISTS idx_texto ON versiculos_explicados (texto_biblico)")
    sqlite_conn.commit()

    # Read rows from MySQL and insert into SQLite
    mysql_cur.execute("SELECT libro, capitulo, versiculo, texto_biblico, explicacion FROM versiculos_explicados")
    
    batch = []
    count = 0
    
    for row in mysql_cur:
        batch.append((
            row['libro'],
            row['capitulo'],
            row['versiculo'],
            row['texto_biblico'],
            row['explicacion']
        ))
        count += 1
        
        if len(batch) >= 1000:
            sqlite_cur.executemany(
                "INSERT INTO versiculos_explicados (libro, capitulo, versiculo, texto_biblico, explicacion) VALUES (?, ?, ?, ?, ?)",
                batch
            )
            sqlite_conn.commit()
            print(f"Migrados {count} registros...")
            batch = []
            
    if batch:
        sqlite_cur.executemany(
            "INSERT INTO versiculos_explicados (libro, capitulo, versiculo, texto_biblico, explicacion) VALUES (?, ?, ?, ?, ?)",
            batch
        )
        sqlite_conn.commit()
        print(f"Migrados {count} registros...")

    mysql_cur.close()
    mysql_conn.close()
    sqlite_cur.close()
    sqlite_conn.close()
    
    file_size_mb = os.path.getsize(sqlite_path) / 1024 / 1024
    print(f"¡Migración completada con éxito!")
    print(f"Base de datos SQLite guardada en '{sqlite_path}' ({file_size_mb:.2f} MB).")

if __name__ == "__main__":
    migrar()
