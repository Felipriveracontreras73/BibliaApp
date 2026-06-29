import fitz  # PyMuPDF
import mysql.connector
import os
import re
import sys
import unicodedata

# Reconfigure stdout to UTF-8 to prevent Windows terminal crash
sys.stdout.reconfigure(encoding='utf-8')

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

# Lowercase mapping to canonical book names
CANONICAL_BOOKS_MAP = {b.lower(): b for b in LIBROS_BIBLIA}

# Regular expression patterns for strict header matching
books_pattern = "|".join([re.escape(b.lower()) for b in LIBROS_BIBLIA])

# Exact match: "Book Chapter:Verse" (case-insensitive)
regex_exact = re.compile(rf"^({books_pattern})\s+(\d+):(\d+)[\.:]?$", re.IGNORECASE)

# Start match: "Book Chapter:Verse - ..." or quotes
regex_start_quote = re.compile(rf"^({books_pattern})\s+(\d+):(\d+)(?:\s*-\s*|\s*)(?:\"|“|«|'|'|\u201c)", re.IGNORECASE)

def conectar_db():
    return mysql.connector.connect(
        host="localhost",
        user="root", 
        password="", 
        database="biblia_app",
        charset='utf8mb4',
        collation='utf8mb4_general_ci'
    )

def guardar_en_db(cursor, libro, capitulo, versiculo, texto, explicacion):
    # Clean up multiple whitespaces
    texto_clean = re.sub(r'\s+', ' ', texto).strip()
    explicacion_clean = re.sub(r'\s+', ' ', explicacion).strip()
    
    # Don't save empty/useless records
    if not libro or not texto_clean:
        return
        
    try:
        query = "INSERT INTO versiculos_explicados (libro, capitulo, versiculo, texto_biblico, explicacion) VALUES (%s, %s, %s, %s, %s)"
        cursor.execute(query, (libro, capitulo, versiculo, texto_clean, explicacion_clean))
    except Exception as e:
        print(f"Error al guardar {libro} {capitulo}:{versiculo}: {e}")

def procesar_pdfs():
    conexion = conectar_db()
    cursor = conexion.cursor()
    
    print("Limpiando base de datos antigua...")
    cursor.execute("TRUNCATE TABLE versiculos_explicados")
    conexion.commit()
    
    # Directory where PDFs are located
    directorio = "C:/Users/Andres/Desktop/apk"
    if not os.path.exists(directorio):
        # Fallback to local directory if desktop path doesn't exist
        directorio = "./"
        
    print(f"Buscando archivos PDF en: {directorio}...")
    pdf_files = [f for f in os.listdir(directorio) if f.endswith(".pdf")]
    
    if not pdf_files:
        print("¡Error! No se encontraron archivos PDF para procesar.")
        cursor.close()
        conexion.close()
        return

    # Set of lowercase canonical book names to clean running headers
    libros_lower_set = {b.lower() for b in LIBROS_BIBLIA}

    for archivo in sorted(pdf_files):
        pdf_path = os.path.join(directorio, archivo)
        archivo_nfc = unicodedata.normalize("NFC", archivo)
        print(f"Procesando: {archivo_nfc}...")
        
        try:
            documento = fitz.open(pdf_path)
        except Exception as e:
            print(f"Error al abrir {archivo_nfc}: {e}")
            continue

        # 1. Extract and clean all lines into a flat document stream
        doc_lines = []
        for pagina in documento:
            texto_pag = unicodedata.normalize("NFC", pagina.get_text("text"))
            lineas = texto_pag.split('\n')
            for line in lineas:
                line = line.strip()
                if not line:
                    continue
                # Skip pure page numbers
                if line.isdigit():
                    continue
                # Skip running headers/footers (exactly equal to a book name)
                line_clean = line.strip("*").strip().lower()
                if line_clean in libros_lower_set or re.match(rf"^({books_pattern})\s+\d+$", line_clean):
                    continue
                doc_lines.append(line)
        
        documento.close()

        # 2. Iterate flat stream and detect headers
        libro_actual = ""
        capitulo_actual = 0
        versiculo_actual = 0
        texto_acumulado = ""
        explicacion_acumulada = ""
        es_explicacion = False

        total_lineas = len(doc_lines)
        for i in range(total_lineas):
            linea = doc_lines[i]
            cleaned_line = linea.strip().strip("*").strip().strip("_").strip()
            
            m_exact = regex_exact.match(cleaned_line)
            m_quote = regex_start_quote.match(cleaned_line)
            
            is_header = False
            match_obj = None
            
            if m_quote:
                is_header = True
                match_obj = m_quote
            elif m_exact:
                # Context check: verify if any of the next 3 lines contains indicators of explanation/quotes
                has_indicator = False
                for offset in range(1, 4):
                    if i + offset < total_lineas:
                        next_line = doc_lines[i+offset].strip().lower()
                        if any(k in next_line for k in ["cita", "explicaci", "comentario", "reflexi", "«", "“", "\"", "este versículo", "el versículo"]):
                            has_indicator = True
                            break
                if has_indicator:
                    is_header = True
                    match_obj = m_exact
            
            if is_header:
                # Save previous verse before starting the new one
                if libro_actual:
                    guardar_en_db(cursor, libro_actual, capitulo_actual, versiculo_actual, texto_acumulado, explicacion_acumulada)
                
                # Setup new verse details
                book_matched = match_obj.group(1).lower()
                libro_actual = CANONICAL_BOOKS_MAP[book_matched]
                capitulo_actual = int(match_obj.group(2))
                versiculo_actual = int(match_obj.group(3))
                
                # If matched a quote inline, start the text accumulation with the rest of the line
                if m_quote:
                    # Remove the matched header prefix
                    prefix = match_obj.group(0)
                    texto_acumulado = cleaned_line[len(prefix):].strip()
                    # If it ends with quote, clean it or keep it as is
                    if texto_acumulado.startswith("-"):
                        texto_acumulado = texto_acumulado.lstrip("-").strip()
                else:
                    texto_acumulado = ""
                    
                explicacion_acumulada = ""
                es_explicacion = False
            else:
                # If we are currently inside a verse structure, accumulate the text
                if libro_actual:
                    cleaned_lower = cleaned_line.lower()
                    if "explicación:" in cleaned_lower or "comentario:" in cleaned_lower or "explicación" in cleaned_lower:
                        es_explicacion = True
                        explicacion_acumulada += linea + "\n"
                    else:
                        if es_explicacion:
                            explicacion_acumulada += linea + " "
                        else:
                            texto_acumulado += linea + " "
                            
        # Save last verse
        if libro_actual:
            guardar_en_db(cursor, libro_actual, capitulo_actual, versiculo_actual, texto_acumulado, explicacion_acumulada)
            
        conexion.commit()

    cursor.close()
    conexion.close()
    print("¡Proceso completado! Todos los datos han sido importados correctamente en UTF-8.")

if __name__ == "__main__":
    procesar_pdfs()