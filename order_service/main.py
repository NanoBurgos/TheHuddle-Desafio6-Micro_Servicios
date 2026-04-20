# Este servicio orquesta el sistema: recibe una orden y reserva stock en inventory_service.
import os
from fastapi import FastAPI, Depends, HTTPException, Header
# FastAPI: clase principal de la app web
# Depends: inyección de dependencias (ejecuta funciones antes del endpoint)
# HTTPException: detiene ejecución y devuelve un error HTTP

from pydantic import BaseModel
# Pydantic: valida datos, convierte JSON → objetos Python, verifica tipos

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
# tenacity: reintentos automáticos con backoff exponencial

import pybreaker
# pybreaker: implementación del patrón Circuit Breaker
# Actúa como un disyuntor eléctrico: corta la conexión cuando un servicio
# falla repetidamente, evitando saturarlo y devolviendo error inmediato al cliente.

import requests
# requests: hace HTTP requests desde Python (permite llamar a otros microservicios)

import logging

from auth import verify_token # función de autenticación con HTTPBearer

app = FastAPI()

# ------------------------
# LOGGING
# ------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ------------------------
# VARIABLES DE ENTORNO
# ------------------------

# Se leen desde el entorno con os.environ.get().
# El segundo argumento es el valor por defecto si la variable no está definida,
# lo que permite correr el servicio localmente sin configurar nada.
# En docker-compose.yml se define: SECRET_TOKEN=penguin-token-123
SECRET_TOKEN = os.environ.get("SECRET_TOKEN", "penguin-token-123")

# INVENTORY_URL: URL interna del contenedor inventory_service.
# "inventory_service" no es un dominio público — es el nombre del contenedor Docker.
# Docker crea una red interna donde los contenedores se encuentran por nombre.
# Esto funciona porque ambos servicios están en la misma red (microservices_net).
# En docker-compose.yml se define: INVENTORY_URL=http://inventory_service:8002/inventory/reserve
INVENTORY_URL = os.environ.get("INVENTORY_URL", "http://inventory_service:8002/inventory/reserve")


# ------------------------
# MODELO REQUEST
# ------------------------

class OrderCreate(BaseModel):
    product_id: int
    quantity: int


# ------------------------
# CIRCUIT BREAKER
# ------------------------
#
# El Circuit Breaker tiene 3 estados:
#
#   CERRADO (normal) → los requests pasan, si hay fallos los cuenta
#   ABIERTO (cortado) → rechaza requests inmediatamente sin llamar al servicio
#   SEMI-ABIERTO (prueba) → deja pasar 1 request para ver si el servicio se recuperó
#
# Flujo con los parámetros definidos abajo:
#   - 3 fallos consecutivos → ABRE el circuito
#   - Circuito abierto por 30 segundos → pasa a SEMI-ABIERTO
#   - 1 request de prueba exitoso → CIERRA el circuito (vuelve a normal)
#   - 1 request de prueba fallido → vuelve a ABIERTO (otros 30 segundos)
#
# Diferencia con retry (tenacity):
#   RETRY: falla → espera → reintenta → falla → espera → reintenta → error (lento)
#   CIRCUIT BREAKER: después de N fallos → corta → error INMEDIATO (rápido)
#   Juntos: retry maneja fallos transitorios, circuit breaker maneja caídas prolongadas.

inventory_breaker = pybreaker.CircuitBreaker(
    fail_max=3,        # abre el circuito después de 3 fallos consecutivos
    reset_timeout=30,  # segundos que espera en ABIERTO antes de pasar a SEMI-ABIERTO
    name="inventory_service"  # nombre para identificarlo en logs
)


# ------------------------
# LLAMADA A INVENTORY SERVICE
# ------------------------
#
# Orden de los decoradores (se ejecutan de afuera hacia adentro):
#   1. @inventory_breaker → si el circuito está ABIERTO, lanza CircuitBreakerError
#                           inmediatamente sin ejecutar nada más
#   2. @retry             → si el circuito está CERRADO, maneja fallos de red
#                           reintentando hasta 3 veces con backoff exponencial
#   3. función real       → hace el HTTP request a inventory_service
#
# Esto significa que un fallo de red cuenta como 1 fallo para el circuit breaker
# solo cuando se agotan todos los reintentos de tenacity.

@inventory_breaker
@retry(
    stop=stop_after_attempt(3),  # máximo 3 intentos antes de rendirse
    wait=wait_exponential(multiplier=1, min=1, max=5),
    # backoff exponencial entre intentos:
    # intento 1 → espera ~1s, intento 2 → espera ~2s, intento 3 → espera ~4s (máx 5s)
    retry=retry_if_exception_type(requests.exceptions.RequestException)
    # solo reintenta errores de red/HTTP, no errores de lógica
)
def call_inventory_service(payload):
    logger.info(f"Calling inventory service for product {payload['product_id']}")

    response = requests.post(
        INVENTORY_URL,
        json=payload,
        headers={
            # order_service se autentica ante inventory_service con el token compartido
            "Authorization": "Bearer " + SECRET_TOKEN
        },
        timeout=3 # si inventory_service no responde en 3s → RequestException → retry
    )

    if response.status_code != 200:
        logger.warning(f"Inventory error: {response.status_code}, retrying...")
        # forzar retry si inventory_service responde con error
        raise requests.exceptions.RequestException("Inventory failed")

    return response


# ------------------------
# CREAR ORDEN
# ------------------------

@app.post("/orders", dependencies=[Depends(verify_token)])
# dependencies=[Depends(verify_token)]: ejecuta verify_token antes del endpoint.
# Si el token es inválido, create_order nunca se ejecuta.
def create_order(order: OrderCreate):

    payload = {
        "product_id": order.product_id,
        "quantity": order.quantity
    }

    try:
        response = call_inventory_service(payload)

    except pybreaker.CircuitBreakerError:
        # El circuito está ABIERTO: inventory_service falló demasiadas veces.
        # No se hizo ningún request — el error es inmediato.
        # Mensaje diferenciado para que el cliente sepa que es temporal.
        logger.error("Circuit breaker OPEN — inventory_service bloqueado temporalmente")
        raise HTTPException(
            status_code=503,
            detail="Inventory service temporarily unavailable (circuit open). Try again in 30 seconds."
        )

    except requests.exceptions.RequestException:
        # Se agotaron los reintentos de tenacity pero el circuito aún no abrió.
        # Ocurre en los primeros 1-2 fallos (antes de llegar a fail_max=3).
        logger.error("Inventory service unavailable after retries")
        raise HTTPException(
            status_code=503,
            detail="Inventory service unavailable after retries"
        )

    logger.info(f"Order created successfully for product {order.product_id}")

    return { # devuelve JSON de confirmación al cliente
        "product_id": order.product_id,
        "quantity": order.quantity,
        "status": "created"
    }

# Lógica del flujo completo:
# 1. Cliente llama POST /orders con product_id y quantity
# 2. verify_token valida el Bearer token
# 3. circuit breaker verifica si el circuito está abierto
# 4. Si cerrado: tenacity llama a inventory_service con reintentos
# 5. inventory_service valida stock y lo descuenta atómicamente
# 6. Si todo OK → devuelve {"status": "created"}

# Posibles problemas si fuera un sistema real:
# - Condiciones de carrera: dos usuarios compran simultáneamente, ambos ven stock disponible

