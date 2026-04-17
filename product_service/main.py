from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from pydantic import BaseModel
from auth import verify_token
from sqlalchemy.exc import IntegrityError
import os

# PERSISTENCIA: se crea la carpeta /app/data dentro del contenedor si no existe.
# Esta carpeta está mapeada al volumen definido en docker-compose.yml,
# por lo que cualquier archivo escrito aquí persiste en tu PC.
os.makedirs("data", exist_ok=True)
# exist_ok=True: no lanza error si la carpeta ya existe

# La DB ahora vive en /app/data/products.db dentro del contenedor,
# que corresponde a ./data/products/products.db en tu PC.
DATABASE_URL = "sqlite:///./data/products.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
# "check_same_thread": False permite multithreading en SQLite
# (necesario porque FastAPI usa múltiples threads para manejar requests)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

app = FastAPI(title="Product Service")

class Product(Base): # tabla productos — SQLAlchemy la convierte en SQL
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True) # UNIQUE: no puede repetirse
    price = Column(Integer)

Base.metadata.create_all(bind=engine) # si la tabla no existe, la crea automáticamente

class ProductCreate(BaseModel): # modelo de entrada API, define el JSON esperado en el body
    name: str
    price: int

def get_db():
    db = SessionLocal() # crea sesión nueva para este request
    try:
        yield db # yield entrega la sesión al endpoint que la necesita
    finally:
        db.close() # garantiza cierre de conexión aunque haya error

# POST /products — Endpoint para crear productos
# dependencies=[Depends(verify_token)]: antes de ejecutar create_product,
# FastAPI ejecuta verify_token. Si falla, create_product nunca se ejecuta.
@app.post("/products", dependencies=[Depends(verify_token)])
def create_product(product: ProductCreate, db: Session = Depends(get_db)):

    # model_dump() convierte el modelo Pydantic en dict: {"name": "coca", "price": 5000}
    # El ** (desempaquetado) lo convierte en argumentos: Product(name="coca", price=5000)
    p = Product(**product.model_dump())

    try:
        db.add(p)      # marca el objeto para inserción (aún no ejecuta SQL)
        db.commit()    # ejecuta: INSERT INTO products (name, price) VALUES (...)
        db.refresh(p)  # recarga desde DB para obtener el id autogenerado
        return p       # FastAPI convierte el objeto ORM a JSON automáticamente
    except IntegrityError:
        # si el nombre ya existe (columna UNIQUE), rollback y error descriptivo
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Product already exists"
        )

# GET /products — Devuelve todos los productos (público, sin token)
@app.get("/products")
def list_products(db: Session = Depends(get_db)):
    return db.query(Product).all() # SELECT * FROM products
