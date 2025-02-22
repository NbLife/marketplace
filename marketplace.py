import os
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext
from pymongo import MongoClient
from azure.storage.blob import BlobServiceClient
from bson import ObjectId
from datetime import datetime, timedelta
from jose import JWTError, jwt
from dotenv import load_dotenv

# Konfiguracja
load_dotenv()
app = FastAPI()
SECRET_KEY = os.getenv("SECRET_KEY", "supersecret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Połączenie z MongoDB
client = MongoClient(os.getenv("COSMOS_DB_URL"))
db = client.marketplace
users_collection = db.users
products_collection = db.products

# Połączenie z Azure Blob Storage
blob_service_client = BlobServiceClient.from_connection_string(os.getenv("AZURE_BLOB_CONNECTION_STRING"))
CONTAINER_NAME = "product-images"

# Obsługa CORS
origins = [
    "https://orange-ocean-095b25503.4.azurestaticapps.net",
    "https://my-backend-fastapi-hffeg4hcchcddhac.westeurope-01.azurewebsites.net"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Obsługa haseł
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")

def hash_password(password: str):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: timedelta):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

@app.post("/signup")
def signup(username: str = Form(...), password: str = Form(...)):
    if users_collection.find_one({"username": username}):
        raise HTTPException(status_code=400, detail="Użytkownik już istnieje")
    users_collection.insert_one({"username": username, "password": hash_password(password)})
    return {"message": "Rejestracja zakończona sukcesem"}

@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = users_collection.find_one({"username": form_data.username})
    if not user or not verify_password(form_data.password, user["password"]):
        raise HTTPException(status_code=401, detail="Nieprawidłowe dane logowania")
    access_token = create_access_token({"sub": user["username"]}, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users/me")
def read_users_me(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Nieprawidłowy token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Nieprawidłowy token")
    return {"username": username}

@app.post("/add_product")
async def add_product(
    name: str = Form(...), description: str = Form(...), price: float = Form(...),
    category: str = Form(...), image: UploadFile = File(...)):
    blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=image.filename)
    blob_client.upload_blob(image.file, overwrite=True)
    image_url = f"https://{blob_client.account_name}.blob.core.windows.net/{CONTAINER_NAME}/{image.filename}"
    product = {"name": name, "description": description, "price": price, "category": category, "image_url": image_url}
    inserted = products_collection.insert_one(product)
    return {"message": "Produkt dodany", "id": str(inserted.inserted_id)}

@app.get("/products")
def get_products():
    products = list(products_collection.find({}, {"_id": 1, "name": 1, "description": 1, "price": 1, "category": 1, "image_url": 1}))
    return [{"id": str(p["_id"]), "name": p["name"], "description": p["description"], "price": p["price"], "category": p["category"], "image_url": p["image_url"]} for p in products]

@app.delete("/delete_product/{product_id}")
def delete_product(product_id: str):
    result = products_collection.delete_one({"_id": ObjectId(product_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Produkt nie znaleziony")
    return {"message": "Produkt usunięty"}