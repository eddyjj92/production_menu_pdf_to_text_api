import os
import json
import time
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import google.generativeai as genai
from pdf2image import convert_from_bytes
from PIL import Image
from dotenv import load_dotenv
from io import BytesIO
from typing import Optional

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DEVELOPMENT = os.getenv("DEVELOPMENT")

if DEVELOPMENT == 'True':
    os.environ['HTTP_PROXY'] = "http://localhost:5000"
    os.environ['HTTPS_PROXY'] = "http://localhost:5000"

app = FastAPI(
    title="PDF Menu Processor API",
    description="API para extraer platillos de menús en PDF",
    version="1.0.0"
)

# Configuración de Gemini
genai.configure(api_key=GEMINI_API_KEY, transport='rest')

config = genai.GenerationConfig(
    temperature=0.2,
    top_p=0.8,
)

modelo = genai.GenerativeModel(
    model_name="models/gemini-1.5-flash-latest",
    generation_config=config
)

@app.post("/procesar-menu")
async def procesar_menu(pdf_url: str, timeout: Optional[int] = 30):
    """
    Procesa un menú en PDF desde una URL y extrae los platillos

    Args:
        pdf_url: URL del PDF a procesar
        timeout: Tiempo máximo de espera para descargar el PDF (en segundos)

    Returns:
        JSON con los platillos encontrados y métricas de tiempo
    """
    try:
        # 1. Descargar el PDF
        tiempo_inicio_total = time.time()
        print(f"📥 Descargando PDF desde {pdf_url}...")

        try:
            response = requests.get(pdf_url, timeout=timeout)
            response.raise_for_status()
            pdf_bytes = response.content
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error al descargar el PDF: {str(e)}"
            )

        # 2. Convertir PDF a imágenes
        print("🔄 Convirtiendo PDF a imágenes...")
        tiempo_inicio_conversion = time.time()

        try:
            imagenes = convert_from_bytes(pdf_bytes)
            tiempo_conversion = time.time() - tiempo_inicio_conversion
            print(f"✅ PDF convertido a {len(imagenes)} páginas en {tiempo_conversion:.2f}s")
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error al convertir PDF: {str(e)}"
            )

        # 3. Procesar cada página
        platillos = []
        tiempos_paginas = {}
        prompt = (
            'Analiza esta página. Si es un menú de restaurante, extrae todos los platillos en formato JSON. '
            'Estructura exacta requerida para cada platillo: '
            '{"name":"string","description":"string","price":"string","quantity":"string"}. '
            'Devuelve SOLO el JSON, sin comentarios, sin ```json ```, sin texto adicional. '
            'Si no hay platillos, devuelve exactamente: []'
        )

        for i, imagen in enumerate(imagenes):
            tiempo_inicio_pagina = time.time()
            pagina_actual = i + 1

            try:
                # Convertir imagen a bytes para procesar
                img_byte_arr = BytesIO()
                imagen.save(img_byte_arr, format='PNG')
                img_byte_arr.seek(0)

                # Procesar con Gemini
                respuesta = modelo.generate_content([Image.open(img_byte_arr), prompt])
                respuesta_texto = respuesta.text.strip()

                # Limpiar respuesta
                if respuesta_texto.startswith('```json'):
                    respuesta_texto = respuesta_texto[7:-3].strip()
                elif respuesta_texto.startswith('```'):
                    respuesta_texto = respuesta_texto[3:-3].strip()

                # Parsear JSON
                try:
                    datos_pagina = json.loads(respuesta_texto)
                    if isinstance(datos_pagina, list):
                        platillos.extend(datos_pagina)
                except json.JSONDecodeError:
                    continue

            except Exception as e:
                print(f"⚠️ Error en página {pagina_actual}: {str(e)}")
            finally:
                tiempo_pagina = time.time() - tiempo_inicio_pagina
                tiempos_paginas[pagina_actual] = tiempo_pagina

        # 4. Preparar respuesta
        tiempo_total = time.time() - tiempo_inicio_total

        resultado = {
            "status": "success",
            "data": {
                "platillos": platillos,
                "metricas": {
                    "total_paginas": len(imagenes),
                    "total_platillos": len(platillos),
                    "tiempo_total": round(tiempo_total, 2),
                    "tiempo_promedio_pagina": round(tiempo_total / len(imagenes), 2),
                    "tiempo_conversion_pdf": round(tiempo_conversion, 2),
                    "tiempos_por_pagina": {f"""p{k}""": round(v, 2) for k, v in tiempos_paginas.items()}
                }
            }
        }

        return JSONResponse(content=resultado, status_code=200)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error interno del servidor: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=7000)