from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from passlib.context import CryptContext
from datetime import datetime, timedelta
from urllib.parse import quote
import jwt
import os
import shutil

# 🔹 Konfiguracja aplikacji FastAPI
app = FastAPI()

# 🔹 Konfiguracja CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔹 Sekretne klucze i JWT
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# 🔹 Haszowanie haseł
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# 🔹 Konfiguracja MongoDB
try:
    client = MongoClient(os.getenv("COSMOS_DB_URL"))
    db = client.marketplace
    users_collection = db.users
    products_collection = db.products
except ConnectionFailure:
    raise HTTPException(status_code=500, detail="Błąd połączenia z bazą danych")

# 🔹 Konfiguracja Azure Blob Storage
AZURE_STORAGE_ACCOUNT_NAME = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
CONTAINER_NAME = os.getenv("AZURE_BLOB_CONTAINER_NAME")

# 🔹 Funkcja do generowania URL dla plików w Azure Blob Storage
def generate_blob_url(filename):
    encoded_filename = quote(filename)
    return f"https://{AZURE_STORAGE_ACCOUNT_NAME}.blob.core.windows.net/{CONTAINER_NAME}/{encoded_filename}"

# ✅ **Rejestracja użytkownika**
@app.post("/signup")
def signup(username: str = Form(...), password: str = Form(...)):
    if users_collection.find_one({"username": username}):
        raise HTTPException(status_code=400, detail="Użytkownik już istnieje")

    hashed_password = pwd_context.hash(password)
    users_collection.insert_one({"username": username, "password": hashed_password})
    return {"message": "Konto utworzone!"}

# ✅ **Logowanie użytkownika**
@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = users_collection.find_one({"username": form_data.username})
    if not user or not pwd_context.verify(form_data.password, user["password"]):
        raise HTTPException(status_code=401, detail="Nieprawidłowe dane")

    token = jwt.encode({"sub": user["username"], "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)}, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}

# ✅ **Autoryzacja użytkownika**
def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Nieautoryzowany")
        return username
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Sesja wygasła")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Nieprawidłowy token")

# ✅ **Dodawanie nowego produktu**
@app.post("/add-product")
async def add_product(
    name: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    category: str = Form(...),
    image: UploadFile = File(...),
    current_user: str = Depends(get_current_user)
):
    try:
        file_location = f"temp_{image.filename}"
        with open(file_location, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)

        # Generowanie URL do Azure Blob Storage
        image_url = generate_blob_url(image.filename)

        product = {
            "name": name,
            "description": description,
            "price": price,
            "category": category,
            "image_url": image_url,
            "added_by": current_user
        }
        products_collection.insert_one(product)
        return {"message": "Produkt dodany!", "product": product}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd dodawania produktu: {str(e)}")

# ✅ **Pobieranie produktów**
@app.get("/products")
def get_products():
    try:
        products = list(products_collection.find({}, {"_id": 1, "name": 1, "description": 1, "price": 1, "category": 1, "image_url": 1}))
        return [
            {
                "id": str(p["_id"]),
                "name": p.get("name", ""),
                "description": p.get("description", ""),
                "price": p.get("price", 0),
                "category": p.get("category", ""),
                "image_url": p.get("image_url", "")
            }
            for p in products
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania produktów: {str(e)}")

# ✅ **Debugowanie połączenia z MongoDB**
@app.get("/debug/mongo")
def debug_mongo():
    try:
        db_list = client.list_database_names()
        return {"message": "MongoDB działa!", "databases": db_list}
    except Exception as e:
        return {"error": str(e)}

# ✅ **Debugowanie konfiguracji Blob Storage**
@app.get("/debug/blob")
def debug_blob():
    return {
        "storage_account": AZURE_STORAGE_ACCOUNT_NAME,
        "container": CONTAINER_NAME,
    }
