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

#dodaje
from jose.exceptions import JWTError

SMTP_SERVER = "smtp.gmail.com"  # Możesz użyć innego serwera SMTP
SMTP_PORT = 587
SMTP_EMAIL = os.getenv("SMTP_EMAIL")  # Twój adres e-mail
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
# 🔹 Sprawdzenie, czy SECRET_KEY jest ustawiony
if not SECRET_KEY:
    raise RuntimeError("❌ ERROR: SECRET_KEY is not set! Sprawdź zmienne środowiskowe.")
APP_ENV = os.getenv("APP_ENV", "development")
BACKEND_URL = "https://my-backend-fastapi-hffeg4hcchcddhac.westeurope-01.azurewebsites.net"

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

from pydantic import BaseModel, EmailStr

class UserSignup(BaseModel):
    username: str
    email: EmailStr  # 👈 Sprawdzamy poprawność adresu e-mail
    password: str

from pydantic import ValidationError

@app.post("/signup")
async def signup(user: UserSignup):
    try:
        if users_collection.find_one({"email": user.email}):
            raise HTTPException(status_code=400, detail="Email już istnieje.")

        if users_collection.find_one({"username": user.username}):
            raise HTTPException(status_code=400, detail="Nazwa użytkownika już istnieje.")

        hashed_password = pwd_context.hash(user.password)
        confirm_token = create_access_token({"email": user.email}, timedelta(minutes=60))

        users_collection.insert_one({
            "username": user.username,
            "email": user.email,
            "password": hashed_password,
            "confirmed": False,
            "confirm_token": confirm_token
        })

        confirm_link = f"{BACKEND_URL}/confirm_email/{confirm_token}"
        send_email(user.email, "Potwierdź email", f"Kliknij tutaj: {confirm_link}")

        return {"message": "Zarejestrowano! Sprawdź email, aby potwierdzić konto."}

    except ValidationError as e:
        raise HTTPException(status_code=422, detail="Niepoprawne dane wejściowe.")

    except Exception as e:
        print(f"❌ Błąd rejestracji: {e}")
        raise HTTPException(status_code=500, detail="Błąd serwera.")

from pydantic import BaseModel, EmailStr

class UserLogin(BaseModel):
    email: EmailStr  # 👈 Logowanie tylko przez e-mail
    password: str

@app.post("/login")
def login(user: UserLogin):
    try:
        print(f"📩 Logowanie: {user.dict()}")

        user_data = users_collection.find_one({"email": user.email})
        if not user_data:
            raise HTTPException(status_code=401, detail="Niepoprawne dane logowania.")

        if not pwd_context.verify(user.password, user_data["password"]):
            raise HTTPException(status_code=401, detail="Niepoprawne dane logowania.")

        if not user_data.get("confirmed", False):
            raise HTTPException(status_code=403, detail="Email niepotwierdzony.")

        token = create_access_token({"sub": user.email})  # 👈 Token na e-mail, nie username!
        return {"token": token}

    except Exception as e:
        print(f"❌ Błąd logowania: {e}")
        raise HTTPException(status_code=500, detail="Wewnętrzny błąd serwera.")


@app.get("/confirm_email/{token}")
def confirm_email(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("email")
        user = users_collection.find_one({"email": email})

        if not user:
            raise HTTPException(status_code=404, detail="Użytkownik nie istnieje.")

        if user.get("confirmed"):
            return {"message": "Email już został potwierdzony."}

        users_collection.update_one({"email": email}, {"$set": {"confirmed": True}})
        return {"message": "Email potwierdzony! Możesz teraz się zalogować."}

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="Token wygasł.")
    except jwt.PyJWTError:
        raise HTTPException(status_code=400, detail="Nieprawidłowy token.")
    
class ForgotPasswordRequest(BaseModel):
    email: EmailStr  # 👈 Automatyczna walidacja poprawności e-maila

@app.post("/forgot_password")
def forgot_password(request: ForgotPasswordRequest):
    user = users_collection.find_one({"email": request.email})
    if not user:
        raise HTTPException(status_code=400, detail="Email not found.")

    reset_token = create_access_token({"email": request.email}, timedelta(minutes=30))
    reset_link = f"https://my-backend-fastapi-hffeg4hcchcddhac.westeurope-01.azurewebsites.net/reset_password/{reset_token}"

    send_email(request.email, "Reset your password", f"Click here to reset your password: {reset_link}")
    return {"message": "Check your email for password reset link."}

from fastapi import Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

@app.get("/reset_password/{token}", response_class=HTMLResponse)
def reset_password_page(token: str):
    """ Strona resetowania hasła """
    return f"""
    <html>
    <body>
        <h2>Reset your password</h2>
        <form method="post" action="/reset_password/{token}">
            <input type="password" name="new_password" placeholder="New Password" required>
            <button type="submit">Reset Password</button>
        </form>
    </body>
    </html>
    """

class ResetPasswordRequest(BaseModel):
    new_password: str

@app.post("/reset_password/{token}", response_class=HTMLResponse)
async def reset_password(token: str, request: Request):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("email")
        user = users_collection.find_one({"email": email})

        if not user:
            return HTMLResponse("<h2>Nie znaleziono użytkownika.</h2>", status_code=400)

        form_data = await request.form()
        new_password = form_data["new_password"]

        hashed_password = pwd_context.hash(new_password)
        users_collection.update_one({"email": email}, {"$set": {"password": hashed_password}})

        # 👇 Wyświetlenie komunikatu + przekierowanie po 3 sekundach
        return HTMLResponse("""
        <html>
        <head>
            <script>
                setTimeout(function() {
                    window.location.href = 'https://orange-ocean-095b25503.4.azurestaticapps.net/';
                }, 3000); // Przekierowanie po 3 sekundach
            </script>
        </head>
        <body>
            <h2>Hasło zostało zmienione pomyślnie! ✅</h2>
            <p>Za chwilę zostaniesz przekierowany na stronę główną...</p>
        </body>
        </html>
        """)

    except jwt.ExpiredSignatureError:
        return HTMLResponse("<h2>Token wygasł. Spróbuj ponownie.</h2>", status_code=400)
    except jwt.PyJWTError:
        return HTMLResponse("<h2>Nieprawidłowy token.</h2>", status_code=400)

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
    from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

@app.post("/add_product")
async def add_product(
    name: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    category: str = Form(...),
    image: UploadFile = File(...),
    token: str = Depends(oauth2_scheme)  
):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user_email = payload.get("email")
        user = users_collection.find_one({"email": user_email})

        if not user:
            print("❌ Błąd: Nie znaleziono użytkownika")
            raise HTTPException(status_code=401, detail="Nieprawidłowy token.")

        print(f"🔹 Użytkownik: {user_email} dodaje produkt: {name}")

        # Upload pliku do Azure Blob Storage
        blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=image.filename)
        blob_client.upload_blob(image.file, overwrite=True)
        image_url = f"https://{AZURE_STORAGE_ACCOUNT_NAME}.blob.core.windows.net/{CONTAINER_NAME}/{image.filename}"

        # Wstawienie produktu do bazy
        result = collection.insert_one({
            "name": name,
            "description": description,
            "price": price,
            "category": category,
            "image_url": image_url,
            "owner": user_email
        })

        print(f"✅ Produkt dodany do bazy: {result.inserted_id}")

        return {"message": "Produkt dodany!"}

    except Exception as e:
        print(f"❌ Błąd dodawania produktu: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd serwera: {e}")

from fastapi import Depends

@app.delete("/delete_product/{product_id}")
def delete_product(product_id: str, token: str = Depends(oauth2_scheme)):
    """ Usuwa produkt z Cosmos DB - tylko dla zalogowanych użytkowników """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user_email = payload.get("sub")
        user = users_collection.find_one({"email": user_email})

        if not user:
            raise HTTPException(status_code=401, detail="Nieautoryzowany.")

        result = collection.delete_one({"_id": ObjectId(product_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Produkt nie został znaleziony")

        return {"message": "Produkt usunięty"}

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Sesja wygasła. Zaloguj się ponownie.")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Nieprawidłowy token.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd usuwania produktu: {str(e)}")

from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal Server Error: {str(exc)}"},
    )

@app.get("/debug/env")
def debug_env():
    """ Debugowanie zmiennych środowiskowych """
    return {
        "COSMOS_DB_URL": os.getenv("COSMOS_DB_URL"),
        "AZURE_BLOB_CONNECTION_STRING": os.getenv("AZURE_BLOB_CONNECTION_STRING"),
        "PORT": os.getenv("PORT"),
        "WEBSITES_PORT": os.getenv("WEBSITES_PORT"),
        "APP_ENV": os.getenv("APP_ENV"),
        "SECRET_KEY": os.getenv("SECRET_KEY"), 
        "SMTP_EMAIL": os.getenv("SMTP_EMAIL")
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))  # Pobiera port od Azure, domyślnie 8000
    uvicorn.run(app, host="0.0.0.0", port=port)




