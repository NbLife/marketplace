import os
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from azure.storage.blob import BlobServiceClient
from bson import ObjectId
from dotenv import load_dotenv
import logging

#dodaje
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from datetime import datetime, timedelta
import jwt

#dodaje
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_SERVER = "smtp.gmail.com"  # Możesz użyć innego serwera SMTP
SMTP_PORT = 587
SMTP_EMAIL = os.getenv("lifartlook@gmail.com")  # Twój adres e-mail
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")  # Hasło lub klucz API

def send_email(to_email, subject, body):
    msg = MIMEMultipart()
    msg["From"] = SMTP_EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.sendmail(SMTP_EMAIL, to_email, msg.as_string())



# Konfiguracja logowania błędów
logging.basicConfig(level=logging.ERROR)

# Wczytaj zmienne środowiskowe z pliku .env (tylko dla lokalnych testów)
load_dotenv()

app = FastAPI()

# 🔹 Pobranie Connection String do Cosmos DB (MongoDB API) i Azure Blob Storage
COSMOS_DB_URL = os.getenv("COSMOS_DB_URL")  # Zmieniona zmienna
AZURE_BLOB_CONNECTION_STRING = os.getenv("AZURE_BLOB_CONNECTION_STRING")
AZURE_STORAGE_ACCOUNT_NAME = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
CONTAINER_NAME = "product-images"
SECRET_KEY = os.getenv("SECRET_KEY")
APP_ENV = os.getenv("APP_ENV", "development")

#dodaje
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# 🔹 Połączenie z Cosmos DB (MongoDB API)
try:
    client = MongoClient(COSMOS_DB_URL, tls=True, tlsAllowInvalidCertificates=False, retryWrites=False, connectTimeoutMS=3000)
    db = client.marketplace
    collection = db.products
    users_collection = db.users
    print("✅ Połączono z Cosmos DB (MongoDB API)")
except Exception as e:
    print(f"❌ Błąd połączenia z Cosmos DB: {e}")

# 🔹 Połączenie z Azure Blob Storage
try:
    blob_service_client = BlobServiceClient.from_connection_string(AZURE_BLOB_CONNECTION_STRING)
    print("✅ Połączono z Azure Blob Storage")
except Exception as e:
    print(f"❌ Błąd połączenia z Blob Storage: {e}")

# 🔹 Obsługa CORS dla frontendu
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

@app.get("/")
def read_root():
    return {"message": "Backend działa!", "env": APP_ENV}

from pydantic import BaseModel

class UserSignup(BaseModel):
    username: str
    password: str

@app.post("/signup")
def signup(user: UserSignup):
    existing_user = users_collection.find_one({"email": user.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already exists.")

    hashed_password = pwd_context.hash(user.password)
    token = create_access_token({"email": user.email}, timedelta(minutes=60))

    users_collection.insert_one({
        "username": user.username,
        "email": user.email,
        "password": hashed_password,
        "confirmed": False,
        "confirm_token": token
    })

    confirm_link = f"https://my-backend-fastapi-hffeg4hcchcddhac.westeurope-01.azurewebsites.net/confirm_email/{token}"
    send_email(user.email, "Confirm your email", f"Click here to confirm: {confirm_link}")

    return {"message": "User registered! Please check your email to confirm your account."}

from pydantic import BaseModel

class UserLogin(BaseModel):
    username: str
    password: str

@app.post("/login")
def login(user: UserLogin):
    user_data = users_collection.find_one({"username": user.username})
    if not user_data or not pwd_context.verify(user.password, user_data["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    token = create_access_token({"sub": user.username})
    return {"token": token}

@app.get("/confirm_email/{token}")
def confirm_email(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("email")
        users_collection.update_one({"email": email}, {"$set": {"confirmed": True}})
        return {"message": "Email confirmed!"}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="Token expired.")
    except jwt.PyJWTError:
        raise HTTPException(status_code=400, detail="Invalid token.")
    
@app.post("/forgot_password")
def forgot_password(email: str):
    user = users_collection.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=400, detail="Email not found.")

    reset_token = create_access_token({"email": email}, timedelta(minutes=30))
    reset_link = f"https://my-backend-fastapi-hffeg4hcchcddhac.westeurope-01.azurewebsites.net/reset_password/{reset_token}"

    send_email(email, "Reset your password", f"Click here to reset your password: {reset_link}")
    return {"message": "Check your email for password reset link."}

@app.post("/reset_password/{token}")
def reset_password(token: str, new_password: str = Form(...)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("email")

        hashed_password = pwd_context.hash(new_password)
        users_collection.update_one({"email": email}, {"$set": {"password": hashed_password}})

        return {"message": "Password reset successful!"}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="Token expired.")
    except jwt.PyJWTError:
        raise HTTPException(status_code=400, detail="Invalid token.")



from fastapi import Depends

def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token.")
        return username
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired.")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token.")


@app.get("/products")
def get_products():
    try:
        products = list(collection.find({}, {"_id": 1, "name": 1, "description": 1, "price": 1, "category": 1, "image_url": 1}))
        return [{"id": str(p["_id"]), "name": p["name"], "description": p["description"], "price": p["price"], "category": p["category"], "image_url": p["image_url"]} for p in products]
    except Exception as e:
        logging.error(f"Błąd pobierania produktów: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Błąd pobierania produktów: {str(e)}")
    
@app.post("/add_product")
async def add_product(
    name: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    category: str = Form(...),
    image: UploadFile = File(...),
    current_user: str = Depends(get_current_user)
):
    """ Dodaje nowy produkt do Cosmos DB i Azure Blob Storage """
    if not name or not description or not price or not category or not image:
        raise HTTPException(status_code=400, detail="Wszystkie pola są wymagane!")

    try:
        blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=image.filename)
        blob_client.upload_blob(image.file, overwrite=True)

        from urllib.parse import quote
        encoded_filename = quote(image.filename)
        image_url = f"https://{AZURE_STORAGE_ACCOUNT_NAME}.blob.core.windows.net/{CONTAINER_NAME}/{encoded_filename}"

        product = {
            "name": name,
            "description": description,
            "price": price,
            "category": category,
            "image_url": image_url,
            "owner": current_user
        }
        inserted = collection.insert_one(product)
        return {"message": "Produkt dodany!", "id": str(inserted.inserted_id)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd dodawania produktu: {str(e)}")

'''@app.post("/add_product")
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
        from urllib.parse import quote

        encoded_filename = quote(image.filename)
        image_url = f"https://{AZURE_STORAGE_ACCOUNT_NAME}.blob.core.windows.net/{CONTAINER_NAME}/{encoded_filename}"
        
        """from urllib.parse import quote
       

        AZURE_STORAGE_ACCOUNT_NAME = os.getenv("AZURE_STORAGE_ACCOUNT_NAME", "mymarketplaceblob")  # Ustaw wartość domyślną
        CONTAINER_NAME = os.getenv("AZURE_BLOB_CONTAINER_NAME", "product-images")  # Sprawdź, czy to właściwy kontener

        def generate_blob_url(filename):
            encoded_filename = quote(filename)
            return f"https://{AZURE_STORAGE_ACCOUNT_NAME}.blob.core.windows.net/{CONTAINER_NAME}/{encoded_filename}"

            # Przykład użycia w funkcji dodawania produktu:
             image_url = generate_blob_url(image.filename)"""


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
        raise HTTPException(status_code=500, detail=f"Błąd dodawania produktu: {str(e)}")'''

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

@app.get("/debug/env")
def debug_env():
    """ Debugowanie zmiennych środowiskowych """
    return {
        "COSMOS_DB_URL": os.getenv("COSMOS_DB_URL"),
        "AZURE_BLOB_CONNECTION_STRING": os.getenv("AZURE_BLOB_CONNECTION_STRING"),
        "PORT": os.getenv("PORT"),
        "WEBSITES_PORT": os.getenv("WEBSITES_PORT"),
        "APP_ENV": os.getenv("APP_ENV")
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))  # Pobiera port od Azure, domyślnie 8000
    uvicorn.run(app, host="0.0.0.0", port=port)



