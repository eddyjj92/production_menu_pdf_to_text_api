import mimetypes
import os
import time

import docx2txt
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import google.generativeai as genai
from pdf2image import convert_from_bytes
from PIL import Image
from dotenv import load_dotenv
from io import BytesIO
from typing import Optional

from helpers import limpiar_y_parsear_json

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
    Procesa un archivo (PDF, imagen o documento) desde una URL y extrae los platillos.

    Args:
        pdf_url: URL del archivo a procesar
        timeout: Tiempo máximo de espera para descargar (en segundos)

    Returns:
        JSON con los platillos encontrados y métricas
    """
    try:
        tiempo_inicio_total = time.time()
        print(f"📥 Descargando archivo desde {pdf_url}...")

        try:
            response = requests.get(pdf_url, timeout=timeout)
            response.raise_for_status()
            archivo_bytes = response.content
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error al descargar el archivo: {str(e)}"
            )

        # Detectar tipo de contenido
        tipo = response.headers.get("Content-Type") or mimetypes.guess_type(pdf_url)[0]
        print(f"📄 Tipo de archivo detectado: {tipo}")

        platillos = []
        tiempos_paginas = {}
        prompt = (
            'Analiza esto. Si es un menú de restaurante, extrae todos los platillos en formato JSON. '
            'Estructura requerida para cada platillo: '
            '{"name":"string","description":"string","price":"string","quantity":"string"}. '
            'Devuelve SOLO el JSON, sin comentarios, sin ```json ```, sin texto adicional. '
            'Si no hay platillos, devuelve exactamente: []'
        )

        if tipo == "application/pdf":
            # PDF → imágenes
            print("🔄 Convirtiendo PDF a imágenes...")
            tiempo_inicio_conversion = time.time()
            imagenes = convert_from_bytes(archivo_bytes)
            tiempo_conversion = time.time() - tiempo_inicio_conversion
            print(f"✅ PDF convertido a {len(imagenes)} páginas en {tiempo_conversion:.2f}s")

            for i, imagen in enumerate(imagenes):
                tiempo_inicio_pagina = time.time()
                try:
                    img_byte_arr = BytesIO()
                    imagen.save(img_byte_arr, format='PNG')
                    img_byte_arr.seek(0)

                    respuesta = modelo.generate_content([Image.open(img_byte_arr), prompt])
                    platillos.extend(limpiar_y_parsear_json(respuesta.text))

                except Exception as e:
                    print(f"⚠️ Error procesando página {i + 1}: {e}")
                finally:
                    tiempos_paginas[f"p{i + 1}"] = round(time.time() - tiempo_inicio_pagina, 2)
                    print(f"⚠️ Página {i + 1} procesada, tiempo transcurrido: {tiempos_paginas[f"p{i + 1}"]}s")

        elif tipo and tipo.startswith("image/"):
            # Imagen directa
            print("🖼️ Procesando imagen...")
            try:
                img = Image.open(BytesIO(archivo_bytes))
                respuesta = modelo.generate_content([img, prompt])
                platillos.extend(limpiar_y_parsear_json(respuesta.text))

                tiempos_paginas["p1"] = round(time.time() - tiempo_inicio_total, 2)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Error al procesar la imagen: {e}")

        elif tipo == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            # DOCX
            print("📄 Procesando documento DOCX...")
            try:
                with BytesIO(archivo_bytes) as doc_io:
                    with open("/tmp/temp.docx", "wb") as temp_file:
                        temp_file.write(doc_io.read())
                    texto = docx2txt.process("/tmp/temp.docx")
                    respuesta = modelo.generate_content([texto, prompt])
                    platillos.extend(limpiar_y_parsear_json(respuesta.text))

                    tiempos_paginas["p1"] = round(time.time() - tiempo_inicio_total, 2)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Error al procesar DOCX: {e}")

        elif tipo == "text/plain":
            # TXT
            print("📄 Procesando archivo de texto...")
            try:
                texto = archivo_bytes.decode("utf-8")
                respuesta = modelo.generate_content([texto, prompt])
                platillos.extend(limpiar_y_parsear_json(respuesta.text))

                tiempos_paginas["p1"] = round(time.time() - tiempo_inicio_total, 2)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Error al procesar TXT: {e}")

        else:
            raise HTTPException(status_code=415, detail="Tipo de archivo no soportado")

        # Respuesta
        tiempo_total = round(time.time() - tiempo_inicio_total, 2)
        resultado = {
            "status": "success",
            "data": {
                "platillos": platillos,
                "metricas": {
                    "total_platillos": len(platillos),
                    "tiempo_total": tiempo_total,
                    "tiempos_por_pagina": tiempos_paginas
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
