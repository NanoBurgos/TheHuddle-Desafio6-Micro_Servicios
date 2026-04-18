# El inventory service es el único que puede modificar el stock.
from fastapi import FastAPI, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from auth import verify_token
import os

# PERSISTENCIA: se crea la carpeta /app/data dentro del contenedor si no existe.
# Esta carpeta está mapeada al volumen definido en docker-compose.yml,
# por lo que cualquier archivo escrito aquí persiste en tu PC.
os.makedirs("data", exist_ok=True)
# exist_ok=True: no lanza error si la carpeta ya existe

# La DB ahora vive en /app/data/inventory.db dentro del contenedor,
# que corresponde a ./data/inventory/inventory.db en tu PC.
DATABASE_URL = "sqlite:///./data/inventory.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
    # SQLite por defecto solo permite uso desde el mismo hilo.
    # FastAPI usa múltiples threads → se desactiva esa restricción.
)

SessionLocal = sessionmaker(
    autocommit=False, # los cambios no se guardan automáticamente
    autoflush=False,  # evita sincronización automática antes de consultas
    bind=engine       # vincula las sesiones con el engine creado
)

Base = declarative_base() # clase base para todos los modelos ORM

app = FastAPI()

SECRET_TOKEN = "penguin-token-123"


# ------------------------
# MODELO DB
# ------------------------

class Inventory(Base): # representa la tabla inventory en SQL
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, unique=True) # UNIQUE: un registro por producto
    stock = Column(Integer)


Base.metadata.create_all(bind=engine)
# ejecuta CREATE TABLE inventory (...) si no existe todavía


# ------------------------
# DEPENDENCY DB
# ------------------------

def get_db():
    db = SessionLocal() # sesión nueva para este request
    try:
        yield db # entrega la sesión al endpoint
    finally:
        db.close() # cierre garantizado aunque haya error


# ------------------------
# MODELOS REQUEST
# ------------------------

class InventoryCreate(BaseModel):
    product_id: int
    stock: int


class ReserveRequest(BaseModel):
    product_id: int
    quantity: int


# ------------------------
# CREAR INVENTARIO
# ------------------------

@app.post("/inventory", dependencies=[Depends(verify_token)])
def create_inventory(data: InventoryCreate, db: Session = Depends(get_db)):

    item = Inventory( # objeto ORM — todavía no existe en la DB
        product_id=data.product_id,
        stock=data.stock
    )

    db.add(item)     # prepara el INSERT (todavía no ejecuta SQL)
    db.commit()      # ejecuta: INSERT INTO inventory (product_id, stock) VALUES (...)
    db.refresh(item) # recarga desde DB para obtener el id autogenerado

    return item


# ------------------------
# RESERVAR STOCK (ATÓMICO)
# Va ANTES de GET /inventory/{product_id} — ver comentario en ese endpoint.
# ------------------------

@app.post("/inventory/reserve", dependencies=[Depends(verify_token)])
def reserve_stock(data: ReserveRequest, db: Session = Depends(get_db)):

    # SQL atómico: descuenta stock solo si hay suficiente cantidad disponible.
    # La condición "AND stock >= :quantity" garantiza que nunca quede en negativo.
    query = text("""
        UPDATE inventory
        SET stock = stock - :quantity
        WHERE product_id = :product_id
        AND stock >= :quantity
    """)

    result = db.execute(
        query,
        {
            "product_id": data.product_id,
            "quantity": data.quantity
        }
    )

    db.commit() # confirma la transacción

    if result.rowcount == 0: # rowcount = cuántas filas fueron modificadas
        # rowcount == 0 significa: producto no existe O stock insuficiente
        raise HTTPException(
            status_code=400,
            detail="Not enough stock"
        )

    return {"status": "reserved"}


# ------------------------
# CONSULTAR STOCK
# IMPORTANTE: este endpoint va DESPUÉS de /inventory/reserve.
# {product_id} es un parámetro dinámico que captura cualquier segmento del path.
# Si estuviera declarado antes, FastAPI capturaría "reserve" como product_id
# al recibir POST /inventory/reserve → error 422 Unprocessable Entity.
# Regla: rutas fijas siempre antes que rutas con parámetros dinámicos.
# ------------------------

@app.get("/inventory/{product_id}", dependencies=[Depends(verify_token)])
def get_inventory(product_id: int, db: Session = Depends(get_db)):

    item = db.query(Inventory).filter(
        Inventory.product_id == product_id
    ).first()
    # SQL equivalente:
    # SELECT * FROM inventory WHERE product_id = ? LIMIT 1

    if not item:
        raise HTTPException(status_code=404, detail="Product not found")

    return item
