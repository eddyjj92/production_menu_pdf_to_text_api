import json


def limpiar_y_parsear_json(respuesta_texto):
    respuesta_texto = respuesta_texto.strip()
    if respuesta_texto.startswith("```json"):
        respuesta_texto = respuesta_texto[7:].strip()
    elif respuesta_texto.startswith("```"):
        respuesta_texto = respuesta_texto[3:].strip()
    if respuesta_texto.endswith("```"):
        respuesta_texto = respuesta_texto[:-3].strip()

    try:
        datos = json.loads(respuesta_texto)
        if isinstance(datos, list):
            return datos
    except json.JSONDecodeError as e:
        print(f"⚠️ Error al parsear JSON: {e}")
    return []