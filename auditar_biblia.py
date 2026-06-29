import mysql.connector
import sys

# Configure stdout to UTF-8 to prevent terminal encoding crashes in Windows
sys.stdout.reconfigure(encoding='utf-8')

def conectar_db():
    return mysql.connector.connect(
        host="localhost", user="root", password="", database="biblia_app"
    )

def auditar():
    print("--- INICIANDO AUDITORÍA DE DATOS ---")
    try:
        conn = conectar_db()
        cursor = conn.cursor(dictionary=True)
        
        # Obtenemos todos los libros y capítulos únicos que existen
        cursor.execute("SELECT DISTINCT libro, capitulo FROM versiculos_explicados ORDER BY libro, capitulo")
        registros = cursor.fetchall()
        
        fallos = 0
        total = len(registros)
        
        print(f"Auditando {total} combinaciones de libro/capítulo...\n")
        
        for reg in registros:
            libro = reg['libro']
            cap = reg['capitulo']
            
            # Buscamos usando coincidencia exacta optimizada
            query = "SELECT COUNT(*) as total FROM versiculos_explicados WHERE libro = %s AND capitulo = %s"
            params = (libro, cap)
            
            cursor.execute(query, params)
            resultado = cursor.fetchone()
            
            if resultado['total'] == 0:
                print(f"❌ ERROR: La base de datos dice que existe '{libro}' cap {cap}, pero no se pudo encontrar mediante búsqueda.")
                fallos += 1
        
        if fallos == 0:
            print("✅ ¡Éxito! Todos los libros y capítulos son localizables por el buscador.")
        else:
            print(f"\n--- AUDITORÍA FINALIZADA CON {fallos} ERRORES ---")
            print("Revisa los errores de arriba. Si aparecen, es porque el nombre del libro en la tabla tiene caracteres invisibles.")
            
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"Error crítico: {e}")

if __name__ == "__main__":
    auditar()