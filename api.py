from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import mysql.connector
import sqlite3
import uvicorn
import re
import sys
import os
import unicodedata
from pathlib import Path
from typing import Optional
import google.generativeai as genai
from dotenv import load_dotenv

# Reconfigure stdout to UTF-8 to prevent Windows terminal encoding crashes
sys.stdout.reconfigure(encoding='utf-8')

# --- CONFIGURACIÓN ---
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Configuración de rutas
STATIC_DIR = BASE_DIR / "static"

# Configuración IA
gemini_key = os.getenv("GEMINI_API_KEY", "AQ.Ab8RN6KySRXuzK578Ni3ZvXT7Jol7rEfwO4NShQ_Sr35oqnw0g")
gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
genai.configure(api_key=gemini_key)
model = genai.GenerativeModel(gemini_model)

LIBROS_BIBLIA = [
    "Génesis", "Éxodo", "Levítico", "Números", "Deuteronomio", "Josué", "Jueces", "Rut", 
    "1 Samuel", "2 Samuel", "1 Reyes", "2 Reyes", "1 Crónicas", "2 Crónicas", "Esdras", 
    "Nehemías", "Ester", "Job", "Salmos", "Proverbios", "Eclesiastés", "Cantares", 
    "Isaías", "Jeremías", "Lamentaciones", "Ezequiel", "Daniel", "Oseas", "Joel", "Amós", 
    "Abdías", "Jonás", "Miqueas", "Nahúm", "Habacuc", "Sofonías", "Hageo", "Zacarías", 
    "Malaquías", "Mateo", "Marcos", "Lucas", "Juan", "Hechos", "Romanos", "1 Corintios", 
    "2 Corintios", "Gálatas", "Efesios", "Filipenses", "Colosenses", "1 Tesalonicenses", 
    "2 Tesalonicenses", "1 Timoteo", "2 Timoteo", "Tito", "Filemón", "Hebreos", 
    "Santiago", "1 Pedro", "2 Pedro", "1 Juan", "2 Juan", "3 Juan", "Judas", "Apocalipsis"
]

# Caché de libros cargada en el inicio
LIBROS_CACHE = []

def conectar_db():
    # Intentar usar SQLite si el archivo db.sqlite3 existe (ideal para producción gratuita en Render)
    sqlite_file = BASE_DIR / "db.sqlite3"
    if sqlite_file.exists():
        conn = sqlite3.connect(sqlite_file)
        conn.row_factory = sqlite3.Row  # Retorna filas tipo diccionario
        return conn, True
    
    # Fallback a MySQL
    conn = mysql.connector.connect(
        host="localhost", user="root", password="", database="biblia_app",
        charset='utf8mb4'
    )
    return conn, False

def ejecutar_consulta(conexion, is_sqlite, query, params=()):
    if is_sqlite:
        cursor = conexion.cursor()
        # Adaptar placeholders de MySQL (%s) a SQLite (?) y RAND() a random()
        query_adapted = query.replace("%s", "?").replace("RAND()", "random()")
        cursor.execute(query_adapted, params)
        filas = [dict(row) for row in cursor.fetchall()]
        cursor.close()
        return filas
    else:
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(query, params)
        filas = cursor.fetchall()
        cursor.close()
        return filas

def inicializar_fts5():
    sqlite_file = BASE_DIR / "db.sqlite3"
    if not sqlite_file.exists():
        return
    
    try:
        conn = sqlite3.connect(sqlite_file)
        cursor = conn.cursor()
        
        # 1. Crear tabla virtual FTS5 si no existe
        cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS versiculos_explicados_fts USING fts5(
            libro,
            texto_biblico,
            explicacion,
            content='versiculos_explicados',
            content_rowid='id'
        )
        """)
        
        # 2. Crear triggers para mantener FTS5 sincronizada
        cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS t_fts_ai AFTER INSERT ON versiculos_explicados BEGIN
            INSERT INTO versiculos_explicados_fts(rowid, libro, texto_biblico, explicacion) 
            VALUES (new.id, new.libro, new.texto_biblico, new.explicacion);
        END;
        """)
        
        cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS t_fts_ad AFTER DELETE ON versiculos_explicados BEGIN
            INSERT INTO versiculos_explicados_fts(versiculos_explicados_fts, rowid, libro, texto_biblico, explicacion) 
            VALUES('delete', old.id, old.libro, old.texto_biblico, old.explicacion);
        END;
        """)
        
        cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS t_fts_au AFTER UPDATE ON versiculos_explicados BEGIN
            INSERT INTO versiculos_explicados_fts(versiculos_explicados_fts, rowid, libro, texto_biblico, explicacion) 
            VALUES('delete', old.id, old.libro, old.texto_biblico, old.explicacion);
            INSERT INTO versiculos_explicados_fts(rowid, libro, texto_biblico, explicacion) 
            VALUES (new.id, new.libro, new.texto_biblico, new.explicacion);
        END;
        """)
        
        # 3. Si la tabla FTS5 está vacía, poblarla con los datos existentes
        cursor.execute("SELECT COUNT(*) FROM versiculos_explicados_fts")
        if cursor.fetchone()[0] == 0:
            print("Poblando tabla FTS5 con registros existentes...")
            cursor.execute("""
            INSERT INTO versiculos_explicados_fts(rowid, libro, texto_biblico, explicacion)
            SELECT id, libro, texto_biblico, explicacion FROM versiculos_explicados
            """)
            conn.commit()
            print("Tabla FTS5 poblada correctamente.")
            
        conn.close()
    except Exception as e:
        print(f"Error al inicializar FTS5 en SQLite: {e}")

def cargar_libros_cache():
    global LIBROS_CACHE
    try:
        conexion, is_sqlite = conectar_db()
        query = "SELECT libro, MAX(capitulo) as max_capitulo FROM versiculos_explicados GROUP BY libro"
        filas = ejecutar_consulta(conexion, is_sqlite, query)
        conexion.close()
        
        libro_max_cap = {f['libro']: f['max_capitulo'] for f in filas}
        
        cache = []
        for libro in LIBROS_BIBLIA:
            if libro in libro_max_cap:
                cache.append({
                    "libro": libro,
                    "capitulos": libro_max_cap[libro]
                })
        LIBROS_CACHE = cache
        print(f"Caché de libros cargada: {len(LIBROS_CACHE)} libros disponibles.")
    except Exception as e:
        print(f"Error al cargar caché de libros: {e}")
        LIBROS_CACHE = [{"libro": l, "capitulos": 1} for l in LIBROS_BIBLIA]

@app.on_event("startup")
def startup_event():
    inicializar_fts5()
    cargar_libros_cache()

def obtener_explicacion_ia(texto):
    try:
        prompt = (
            f"Actúa como un teólogo y erudito bíblico experto. Explica el versículo o tema: '{texto}'.\n\n"
            f"Es muy importante que estructures tu respuesta usando exactamente las siguientes etiquetas de sección en tu respuesta en español:\n\n"
            f"[EXPLICACION]\n"
            f"Proporciona una explicación clara, sencilla y edificante del versículo o tema.\n\n"
            f"[CONTEXTO]\n"
            f"Explica brevemente el contexto histórico, cultural y literario del pasaje.\n\n"
            f"[APLICACION]\n"
            f"Ofrece 2 o 3 aplicaciones prácticas o reflexiones para la vida diaria hoy en día.\n\n"
            f"Usa un tono respetuoso, inspirador y pastoral. Mantén cada sección concisa y bien redactada."
        )
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"No se pudo generar explicación: {e}"

def eliminar_acentos(texto):
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )

def resolver_libro_canonico(libro_busqueda):
    if not libro_busqueda:
        return None
    
    libro_busqueda_clean = eliminar_acentos(libro_busqueda.strip().lower())
    
    # Búsqueda exacta
    for b in LIBROS_BIBLIA:
        b_clean = eliminar_acentos(b.lower())
        if b_clean == libro_busqueda_clean:
            return b
            
    # Búsqueda por abreviatura (mínimo 3 letras)
    if len(libro_busqueda_clean) >= 3:
        for b in LIBROS_BIBLIA:
            b_clean = eliminar_acentos(b.lower())
            if b_clean.startswith(libro_busqueda_clean):
                return b
                
    return None

# --- RUTAS ---

@app.get("/")
def inicio():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC_DIR / "icon-192.png")

@app.get("/libros")
def obtener_libros():
    return {"libros": LIBROS_CACHE}

@app.get("/capitulo")
def obtener_capitulo(libro: str, capitulo: int):
    try:
        conexion, is_sqlite = conectar_db()
        libro_canonico = resolver_libro_canonico(libro)
        libro_query = libro_canonico if libro_canonico else libro
        
        query = "SELECT * FROM versiculos_explicados WHERE libro = %s AND capitulo = %s ORDER BY versiculo"
        params = (libro_query, capitulo)
        
        filas = ejecutar_consulta(conexion, is_sqlite, query, params)
        conexion.close()
        return {"resultados": filas, "total": len(filas)}
    except Exception as e:
        return {"error": str(e)}

@app.get("/aleatorio")
def obtener_aleatorio():
    try:
        conexion, is_sqlite = conectar_db()
        filas = ejecutar_consulta(conexion, is_sqlite, "SELECT * FROM versiculos_explicados ORDER BY RAND() LIMIT 1")
        conexion.close()
        return {"resultado": filas[0] if filas else None}
    except Exception as e:
        return {"error": str(e)}

@app.get("/buscar")
def buscar(texto: Optional[str] = Query(None)):
    if not texto: return {"resultados": [], "total": 0}
    try:
        conexion, is_sqlite = conectar_db()
        texto_clean = texto.strip()
        
        # 1. Intentar coincidir con patrón de versículo "Libro Capítulo:Versículo-Versículo"
        # Ej: "Génesis 1:1-5" o "Génesis 1:1" o "Génesis 1"
        match = re.match(r"^(.*?)\s*(\d+)(?::(\d+)(?:\s*-\s*(\d+))?)?$", texto_clean)
        
        if match:
            libro_raw = match.group(1).strip()
            cap = int(match.group(2))
            ver_start = match.group(3)
            ver_end = match.group(4)
            
            libro_canonico = resolver_libro_canonico(libro_raw)
            libro_query = libro_canonico if libro_canonico else libro_raw
            
            if ver_start:
                ver_start = int(ver_start)
                if ver_end:
                    ver_end = int(ver_end)
                    query = "SELECT * FROM versiculos_explicados WHERE libro = %s AND capitulo = %s AND versiculo >= %s AND versiculo <= %s ORDER BY versiculo LIMIT 50"
                    params = (libro_query, cap, ver_start, ver_end)
                else:
                    query = "SELECT * FROM versiculos_explicados WHERE libro = %s AND capitulo = %s AND versiculo = %s LIMIT 10"
                    params = (libro_query, cap, ver_start)
            else:
                query = "SELECT * FROM versiculos_explicados WHERE libro = %s AND capitulo = %s ORDER BY versiculo LIMIT 50"
                params = (libro_query, cap)
                
            filas = ejecutar_consulta(conexion, is_sqlite, query, params)
        else:
            # 2. Búsqueda por palabras clave
            filas = []
            if is_sqlite:
                try:
                    # Limpiamos el texto para evitar errores de sintaxis en FTS5
                    query_fts_clean = re.sub(r'[^\w\s]', ' ', texto_clean).strip()
                    if query_fts_clean:
                        query = """
                        SELECT * FROM versiculos_explicados 
                        WHERE id IN (
                            SELECT rowid FROM versiculos_explicados_fts 
                            WHERE versiculos_explicados_fts MATCH ?
                        )
                        LIMIT 50
                        """
                        # Buscamos prefijos con comodines e intercalamos con AND
                        terminos = [f"{t}*" for t in query_fts_clean.split() if t]
                        query_match = " AND ".join(terminos) if terminos else query_fts_clean
                        
                        filas = ejecutar_consulta(conexion, is_sqlite, query, (query_match,))
                except Exception as fts_error:
                    print(f"FTS5 falló, usando fallback de LIKE: {fts_error}")
                    filas = []
            
            if not filas:
                query = "SELECT * FROM versiculos_explicados WHERE libro LIKE %s OR texto_biblico LIKE %s OR explicacion LIKE %s LIMIT 50"
                search = f"%{texto_clean}%"
                params = (search, search, search)
                filas = ejecutar_consulta(conexion, is_sqlite, query, params)
        
        conexion.close()
        
        # Si no hay resultados en BD, consultamos a la IA
        if not filas:
            explicacion = obtener_explicacion_ia(texto_clean)
            return {"resultados": [], "total": 0, "explicacion_ia": explicacion}
        
        return {"resultados": filas, "total": len(filas)}
    except Exception as e:
        return {"error": str(e)}

# Montar archivos estáticos
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8051))
    print(f"Servidor listo en http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)