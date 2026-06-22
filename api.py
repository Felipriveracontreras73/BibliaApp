from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import mysql.connector
import sqlite3
import uvicorn
import re
import sys
import unicodedata
from pathlib import Path
from typing import Optional
import google.generativeai as genai

# Reconfigure stdout to UTF-8 to prevent Windows terminal encoding crashes
sys.stdout.reconfigure(encoding='utf-8')

# --- CONFIGURACIÓN ---
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Configuración de rutas
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# Configuración IA
genai.configure(api_key="AQ.Ab8RN6KySRXuzK578Ni3ZvXT7Jol7rEfwO4NShQ_Sr35oqnw0g")
model = genai.GenerativeModel('gemini-2.5-flash')

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

def obtener_explicacion_ia(texto):
    try:
        prompt = f"Actúa como un experto bíblico. Explica brevemente el versículo o tema: '{texto}'. Usa un lenguaje claro y edificante."
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
        
        # Intentar coincidir con patrón de versículo "Libro Capítulo:Versículo"
        match = re.match(r"^(.*?)\s*(\d+)(?::(\d+))?$", texto.strip())
        
        if match:
            libro_raw, cap, ver = match.group(1).strip(), match.group(2), match.group(3)
            libro_canonico = resolver_libro_canonico(libro_raw)
            libro_query = libro_canonico if libro_canonico else libro_raw
            
            if ver:
                query = "SELECT * FROM versiculos_explicados WHERE libro = %s AND capitulo = %s AND versiculo = %s LIMIT 10"
                params = (libro_query, cap, ver)
            else:
                query = "SELECT * FROM versiculos_explicados WHERE libro = %s AND capitulo = %s LIMIT 20"
                params = (libro_query, cap)
        else:
            # Fallback a búsqueda por palabras clave si no encaja con "Libro Cap:Ver"
            query = "SELECT * FROM versiculos_explicados WHERE libro LIKE %s OR texto_biblico LIKE %s OR explicacion LIKE %s LIMIT 50"
            search = f"%{texto}%"
            params = (search, search, search)
        
        filas = ejecutar_consulta(conexion, is_sqlite, query, params)
        conexion.close()
        
        # Si no hay resultados en BD, consultamos a la IA
        if not filas:
            explicacion = obtener_explicacion_ia(texto)
            return {"resultados": [], "total": 0, "explicacion_ia": explicacion}
        
        return {"resultados": filas, "total": len(filas)}
    except Exception as e:
        return {"error": str(e)}

# Montar archivos estáticos
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if __name__ == "__main__":
    print("Servidor listo en http://localhost:8051")
    uvicorn.run(app, host="0.0.0.0", port=8051)