import os
import jwt
import bcrypt
import logging
from datetime import datetime, timedelta
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from azure.storage.blob import BlobServiceClient
from bson import ObjectId
from dotenv import load_dotenv
from pydantic import BaseModel

# Konfiguracja logowania błędów
logging.basicConfig(level=logging.ERROR)

# Wczytaj zmienne środowiskowe
load_dotenv()

app = FastAPI()

# 🔹 Konfiguracja aplikacji
SECRET_KEY = os.getenv("SECRET_KEY")  # Powinien być ustawiony w Azure Configuration lub GitHub Secrets
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# 🔹 Połączenie z bazą Cosmos DB (MongoDB API)
COSMOS_DB_URL = os.getenv("COSMOS_DB_URL")
client = MongoClient(COSMOS_DB_URL, tls=True, retryWrites=False)
db = client.marketplace
users_collection = db.users
products_collection = db.products

# 🔹 Połączenie z Azure Blob Storage
AZURE_BLOB_CONNECTION_STRING = os.getenv("AZURE_BLOB_CONNECTION_STRING")
AZURE_STORAGE_ACCOUNT_NAME = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
CONTAINER_NAME = "product-images"

blob_service_client = BlobServiceClient.from_connection_string(AZURE_BLOB_CONNECTION_STRING)

# 🔹 Obsługa CORS dla frontendu
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://orange-ocean-095b25503.4.azurestaticapps.net"],  # Adres Twojego frontendu
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔹 Modele Pydantic
class UserSignup(BaseModel):
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

# 🔹 Funkcje pomocnicze
def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# 🔹 Endpointy użytkowników
@app.post("/signup")
def signup(user: UserSignup):
    if users_collection.find_one({"username": user.username}):
        raise HTTPException(status_code=400, detail="Użytkownik już istnieje")

    hashed_password = bcrypt.hashpw(user.password.encode(), bcrypt.gensalt())
    users_collection.insert_one({"username": user.username, "password": hashed_password.decode()})
    
    return {"message": "Rejestracja zakończona sukcesem"}

@app.post("/login")
def login(user: UserLogin):
    db_user = users_collection.find_one({"username": user.username})
    if not db_user or not bcrypt.checkpw(user.password.encode(), db_user["password"].encode()):
        raise HTTPException(status_code=400, detail="Nieprawidłowe dane logowania")

    token = create_access_token({"sub": user.username})
    return {"access_token": token, "token_type": "bearer"}

# 🔹 Endpointy produktów
@app.get("/products")
def get_products():
    try:
        products = list(products_collection.find({}, {"_id": 1, "name": 1, "description": 1, "price": 1, "category": 1, "image_url": 1}))
        return [{"id": str(p["_id"]), **p} for p in products]
    except Exception as e:
        logging.error(f"Błąd pobierania produktów: {str(e)}")
        raise HTTPException(status_code=500, detail="Błąd pobierania produktów")

@app.post("/add_product")
async def add_product(
    name: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    category: str = Form(...),
    image: UploadFile = File(...)
):
    """ Dodaje nowy produkt do Cosmos DB i Azure Blob Storage """
    try:
        # 🔹 Przesyłanie pliku do Azure Blob Storage
        blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=image.filename)
        blob_client.upload_blob(image.file, overwrite=True)

        # 🔹 Tworzenie URL do pobrania obrazu z Azure Blob Storage
        image_url = f"https://{AZURE_STORAGE_ACCOUNT_NAME}.blob.core.windows.net/{CONTAINER_NAME}/{image.filename}"

        # 🔹 Zapis produktu do Cosmos DB
        product = {
            "name": name,
            "description": description,
            "price": price,
            "category": category,
            "image_url": image_url
        }
        inserted = products_collection.insert_one(product)
        return {"message": "Produkt dodany!", "id": str(inserted.inserted_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd dodawania produktu: {str(e)}")

@app.delete("/delete_product/{product_id}")
def delete_product(product_id: str):
    """ Usuwa produkt z Cosmos DB """
    try:
        result = products_collection.delete_one({"_id": ObjectId(product_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Produkt nie znaleziony")
        return {"message": "Produkt usunięty"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd usuwania produktu: {str(e)}")

# 🔹 Debugowanie zmiennych środowiskowych
@app.get("/debug/env")
def debug_env():
    return {
        "COSMOS_DB_URL": os.getenv("COSMOS_DB_URL"),
        "AZURE_BLOB_CONNECTION_STRING": os.getenv("AZURE_BLOB_CONNECTION_STRING"),
        "PORT": os.getenv("PORT"),
        "WEBSITES_PORT": os.getenv("WEBSITES_PORT"),
        "APP_ENV": os.getenv("APP_ENV")
    }

# 🔹 Uruchomienie aplikacji
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))  # Pobiera port od Azure, domyślnie 8000
    uvicorn.run(app, host="0.0.0.0", port=port)
