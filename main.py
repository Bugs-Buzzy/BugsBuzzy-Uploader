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
    hash_value = hashlib.md5(os.urandom(16)).hexdigest()[:16]
    ext = Path(original_filename).suffix
    return f"{hash_value}{ext}"

@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "Server is running"}

@app.post("/api/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    try:
        if not request.session.get("verified") or not request.session.get("upload_code"):
            raise HTTPException(status_code=401, detail='ابتدا باید کد آپلود تیم را تأیید کنید')

        team_code = request.session.get("upload_code")

        is_valid_ext = Path(file.filename).suffix.lower() in ALLOWED_EXTENSIONS
        if not is_valid_ext:
            raise HTTPException(status_code=400, detail='فقط فایل های ZIP مجاز هستند!')

        orig_name = Path(file.filename).name
        if not orig_name.lower().endswith('.zip'):
            raise HTTPException(status_code=400, detail='فقط فایل های ZIP مجاز هستند!')
        
        provided_key = orig_name[:-4]
        if provided_key != team_code:
            raise HTTPException(status_code=400, detail=f'نام فایل باید {team_code}.zip باشد')
        
        expected_filename = f"{team_code}.zip"

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
        file_hash = hashlib.sha256()

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
                    file_hash.update(chunk)
        finally:

            await file.close()

        sha256_hash = file_hash.hexdigest()

        return {
            "success": True,
            "filename": expected_filename,
            "originalName": expected_filename,
            "size": total_written,
            "hash": sha256_hash
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

@app.post("/api/verify-code")
async def verify_upload_code(request: Request, code: str = Form(...)):
    if not code or len(code) != 8:
        raise HTTPException(status_code=400, detail="کد آپلود باید 8 کاراکتر باشد")
    
    try:
        backend_url = os.getenv("BACKEND_URL", "https://bugsbuzzy.ir/api")
        
        endpoints = [
            f"{backend_url}/inperson/verify-upload-code/",  # اول InPerson
            f"{backend_url}/gamejam/verify-upload-code/",   # بعد GameJam
        ]
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            last_error = None
            
            for verify_url in endpoints:
                try:
                    response = await client.post(verify_url, json={"code": code})
                    
                    if response.status_code == 200:
                        data = response.json()
                        # ذخیره اطلاعات تیم در session
                        request.session["team_id"] = data["team"]["id"]
                        request.session["team_name"] = data["team"]["name"]
                        request.session["upload_code"] = code
                        request.session["verified"] = True
                        
                        # تشخیص نوع تیم از URL
                        team_type = "inperson" if "inperson" in verify_url else "gamejam"
                        request.session["team_type"] = team_type
                        
                        return {
                            "success": True,
                            "team": data["team"],
                            "team_type": team_type
                        }
                    elif response.status_code == 404:
                        # کد در این endpoint پیدا نشد، endpoint بعدی رو امتحان می‌کنیم
                        continue
                    elif response.status_code == 403:
                        # تیم پیدا شد ولی هنوز شرکت نکرده
                        raise HTTPException(status_code=403, detail="این تیم هنوز در رویداد شرکت نکرده است")
                    else:
                        error_detail = response.json().get("error", "خطا در تأیید کد")
                        last_error = error_detail
                        
                except httpx.RequestError:
                    continue
            
            # اگر هیچ endpoint جواب نداد
            if last_error:
                raise HTTPException(status_code=400, detail=last_error)
            else:
                raise HTTPException(status_code=404, detail="کد آپلود نامعتبر است")
                
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="خطای اتصال به سرور. لطفا دوباره تلاش کنید")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطای سرور: {str(e)}")

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="public")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=9000,
        reload=True
    )
