FROM python:3.11-slim 
#Descarga una imagen base de Python.

WORKDIR /app
#Directorio de trabajo dentro del contenedor.

COPY requirements.txt .
#Copia dependencias.

RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Copia el codigo del servicio

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
# Ejecuta el servidor Uvicorn.



# Desglose del comando RUN pip install --no-cache-dir -r requirements.txt
# 1. RUN: Es la instrucción de Docker que ejecuta comandos dentro del contenedor durante la construcción de la imagen. Lo que haga este comando (instalar, crear archivos, etc.)
# quedará "grabado" en la imagen.

# 2. pip install: Es el instalador de paquetes de Python. Busca e instala librerías desde PyPI (Python Package Index).

# 3. --no-cache-dir: Esta parte es muy importante para optimizar la imagen. Le dice a pip que NO guarde los archivos temporales de instalación.
# Sin esta opción: pip descarga los paquetes, los instala, y además guarda una copia en caché dentro del contenedor. Esa copia ocupa espacio pero 
# no sirve para nada en producción.
# Con esta opción: pip instala los paquetes y borra los archivos temporales, haciendo la imagen final más pequeña.

# 4. -r requirements.txt : El -r significa "requirements file" (archivo de requerimientos). Le dice a pip: "Instala todas las librerías que están listadas en el archivo 
#requirements.txt".