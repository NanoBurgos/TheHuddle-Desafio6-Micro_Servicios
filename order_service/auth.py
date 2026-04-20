import os
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# VARIABLE DE ENTORNO: el token se lee desde el entorno, no está hardcodeado.
# En docker-compose.yml se define: SECRET_TOKEN=penguin-token-123
SECRET_TOKEN = os.environ.get("SECRET_TOKEN", "penguin-token-123")

# HTTPBearer: esquema estándar de FastAPI para tokens Bearer.
# Swagger UI muestra el botón "Authorize" (candado 🔓) arriba a la derecha.
# El usuario ingresa solo el token (sin "Bearer "), Swagger agrega el prefijo solo.
def verify_token(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())):
    # credentials.credentials contiene el token extraído (sin el prefijo "Bearer ")
    if credentials.credentials != SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")
