import google.generativeai as genai

# Pega aquí tu NUEVA clave API
API_KEY = "AQ.Ab8RN6KySRXuzK578Ni3ZvXT7Jol7rEfwO4NShQ_Sr35oqnw0g"

genai.configure(api_key=API_KEY)

try:
    # Probamos con 'gemini-pro', que es el modelo más estándar y estable
    model = genai.GenerativeModel('gemini-pro')
    response = model.generate_content("Hola, ¿estás funcionando?")
    print("✅ ¡Conexión exitosa! La IA respondió: " + response.text)
except Exception as e:
    print(f"❌ ERROR: {e}")