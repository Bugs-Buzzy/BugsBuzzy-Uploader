import os
import hashlib
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, File, UploadFile, HTTPException, Request, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import ClientDisconnect
import re
import time
import aiofiles
import httpx

app = FastAPI(title="BugsBuzzy Upload Server")
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
PUBLIC_DIR = BASE_DIR / "public"
MAX_FILE_SIZE = 512 * 1024 * 1024  

ALLOWED_EXTENSIONS = ['.zip']
ALLOWED_MIME_TYPES = ['application/zip', 'application/x-zip-compressed', 'application/octet-stream']

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production-please")
ALLOWED_KEYS_FILE = os.getenv("ALLOWED_KEYS_FILE")
ALLOWED_KEYS_ENV = os.getenv("ALLOWED_KEYS")  

AUTH_TOKEN_URL = os.getenv("AUTH_TOKEN_URL", "https://bugsbuzzy.ir/api/token")

def load_allowed_keys() -> set[str] | None:
    if ALLOWED_KEYS_FILE and Path(ALLOWED_KEYS_FILE).exists():
        try:
            with open(ALLOWED_KEYS_FILE, 'r', encoding='utf-8') as f:
                return {line.strip() for line in f if line.strip()}
        except Exception:
            return None
    if ALLOWED_KEYS_ENV:
        return {k.strip() for k in ALLOWED_KEYS_ENV.split(',') if k.strip()}
    return None

ALLOWED_KEYS_SET = load_allowed_keys()

RATE_LIMIT_WINDOW_SEC = 60
RATE_LIMIT_MAX_ATTEMPTS = 20
_rate_limit_bucket: dict[str, list[float]] = {}

UPLOAD_DIR.mkdir(exist_ok=True)
PUBLIC_DIR.mkdir(exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax", https_only=False)

def validate_file(file: UploadFile, file_size: int) -> tuple[bool, Optional[str]]:
    """اعتبارسنجی فایل"""

    if file_size > MAX_FILE_SIZE:
        return False, 'حجم فایل بیش از حد مجاز است. حداکثر 512 مگابایت'

    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        return False, 'فقط فایل های ZIP مجاز هستند!'

    content_type = file.content_type
    if content_type and content_type not in ALLOWED_MIME_TYPES:
        return False, 'نوع فایل مجاز نیست! لطفا فایل ZIP معتبر آپلود کنید.'

    return True, None

def generate_unique_filename(original_filename: str) -> str:
    """تولید نام فایل یونیک"""
    hash_value = hashlib.md5(os.urandom(16)).hexdigest()[:16]
    ext = Path(original_filename).suffix
    return f"{hash_value}{ext}"

@app.get("/health")
async def health_check():
    """بررسی سلامت سرور"""
    return {"status": "ok", "message": "سرور آپلود در حال اجرا است"}

@app.post("/api/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    """آپلود فایل"""

    try:

        is_valid_ext = Path(file.filename).suffix.lower() in ALLOWED_EXTENSIONS
        if not is_valid_ext:
            raise HTTPException(status_code=400, detail='فقط فایل های ZIP مجاز هستند!')

        orig_name = Path(file.filename).name
        if not orig_name.lower().endswith('.zip'):
            raise HTTPException(status_code=400, detail='فقط فایل های ZIP مجاز هستند!')
        provided_key = orig_name[:-4]
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,128}", provided_key or ""):
            raise HTTPException(status_code=400, detail='کلید نامعتبر است. فقط حروف، اعداد، - و _ مجاز است.')
        expected_filename = f"{provided_key}.zip"

        file_path = UPLOAD_DIR / expected_filename

        overwrite = request.query_params.get("overwrite") in {"1", "true", "True"}
        if file_path.exists() and not overwrite:
            return JSONResponse(status_code=409, content={
                "error": "فایل با این کلید قبلاً آپلود شده است. آیا مایل به جایگزینی هستید؟",
                "code": "FILE_EXISTS",
                "filename": expected_filename
            })

        total_written = 0
        chunk_size = 1024 * 1024  

        try:
            async with aiofiles.open(file_path, 'wb') as out_f:
                while True:
                    chunk = await file.read(chunk_size)
                    if not chunk:
                        break
                    total_written += len(chunk)
                    if total_written > MAX_FILE_SIZE:

                        try:
                            await out_f.flush()
                        except Exception:
                            pass
                        try:
                            os.remove(file_path)
                        except FileNotFoundError:
                            pass
                        raise HTTPException(status_code=400, detail='حجم فایل بیش از حد مجاز است. حداکثر 512 مگابایت')
                    await out_f.write(chunk)
        finally:

            await file.close()

        file_url = f"{request.url.scheme}://{request.url.netloc}/uploads/{expected_filename}"

        return {
            "success": True,
            "filename": expected_filename,
            "originalName": expected_filename,
            "size": total_written,
            "url": file_url
        }

    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"error": e.detail}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"خطای سرور: {str(e)}"}
        )

@app.get("/api/session")
async def get_session(request: Request):
    key = request.session.get("key")
    group_name = request.session.get("group_name")
    return {"authenticated": bool(key), "key": key, "group_name": group_name}

@app.post("/api/logout")
async def logout(request: Request):
    request.session.clear()
    return {"success": True}

@app.get("/api/token")
async def test_token(hash: str):
    if hash == "AAAAAAAA":
        return {"group_name": "Nautilus", "key": "AAAAAAAA"}
    return JSONResponse(status_code=401, content={"error": "کلید نامعتبر است"})

@app.get("/api/files")
async def list_files():
    """لیست فایل‌های آپلود شده"""

    try:
        files = [f.name for f in UPLOAD_DIR.iterdir() if f.is_file()]
        return {"files": files}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": "خطا در دریافت لیست فایل‌ها"}
        )

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="public")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=1000,
        reload=True
    )