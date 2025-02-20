import os
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from azure.storage.blob import BlobServiceClient
from bson import ObjectId

app = FastAPI()

from marketplace import app  # Import aplikacji z pliku marketplace.py



# 🔹 Pobranie Connection String do Cosmos DB (MongoDB API) i Azure Blob Storage
COSMOS_DB_URL = os.getenv("COSMOS_DB_URL")  # Używamy poprawnego connection stringa dla MongoDB API
AZURE_BLOB_CONNECTION_STRING = os.getenv("AZURE_BLOB_STORAGE_CONNECTION_STRING")
AZURE_STORAGE_ACCOUNT_NAME = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")  
CONTAINER_NAME = "product-images"


SECRET_KEY = os.getenv("SECRET_KEY")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")


# 🔹 Połączenie z Cosmos DB (MongoDB API)
try:
    client = MongoClient(COSMOS_DB_URL)
    db = client.marketplace
    collection = db.products
    print("Połączono z Cosmos DB (MongoDB API)")
except Exception as e:
    print(f"Błąd połączenia z Cosmos DB: {e}")

# 🔹 Połączenie z Azure Blob Storage
try:
    blob_service_client = BlobServiceClient.from_connection_string(AZURE_BLOB_CONNECTION_STRING)
    print("Połączono z Azure Blob Storage")
except Exception as e:
    print(f"Błąd połączenia z Blob Storage: {e}")

# 🔹 Obsługa CORS dla frontendu
origins = [
    "https://orange-ocean-095b25503.4.azurestaticapps.net",
    "https://my-backend-fastapi.azurewebsites.net"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/products")
def get_products():
    """ Pobiera listę produktów z Cosmos DB """
    try:
        products = list(collection.find({}, {"_id": 1, "name": 1, "description": 1, "price": 1, "category": 1, "image_url": 1}))
        return [{"id": str(p["_id"]), **p} for p in products]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania produktów: {str(e)}")

@app.post("/add_product")
async def add_product(
    name: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    category: str = Form(...),
    image: UploadFile = File(...)
):
    """ Dodaje nowy produkt do Cosmos DB i Azure Blob Storage """
    if not name or not description or not price or not category or not image:
        raise HTTPException(status_code=400, detail="Wszystkie pola są wymagane!")

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
        inserted = collection.insert_one(product)
        return {"message": "Produkt dodany!", "id": str(inserted.inserted_id)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd dodawania produktu: {str(e)}")

@app.delete("/delete_product/{product_id}")
def delete_product(product_id: str):
    """ Usuwa produkt z Cosmos DB """
    try:
        result = collection.delete_one({"_id": ObjectId(product_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Produkt nie został znaleziony")
        return {"message": "Produkt usunięty"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd usuwania produktu: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

