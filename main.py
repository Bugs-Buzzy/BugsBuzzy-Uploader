import os
import hashlib
from pathlib import Path
from typing import Optional
from datetime import datetime
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
import glob

app = FastAPI(title="BugsBuzzy Upload Server")
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
PUBLIC_DIR = BASE_DIR / "public"
MAX_FILE_SIZE = 512 * 1024 * 1024  
MAX_TEAM_STORAGE = 1 * 1024 * 1024 * 1024  # 1GB per team

ALLOWED_EXTENSIONS = ['.zip']
ALLOWED_MIME_TYPES = ['application/zip', 'application/x-zip-compressed', 'application/octet-stream']

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production-please")
ALLOWED_KEYS_FILE = os.getenv("ALLOWED_KEYS_FILE")
ALLOWED_KEYS_ENV = os.getenv("ALLOWED_KEYS")  

AUTH_TOKEN_URL = os.getenv("AUTH_TOKEN_URL", "https://bugsbuzzy.ir/api/token")
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "https://bugsbuzzy.ir/api")

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

async def verify_session_with_backend(team_number: str, upload_code: str) -> dict:
    """
    Verify session with Django backend to prevent session manipulation.
    Returns team info if valid, raises HTTPException if invalid.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{BACKEND_API_URL}/inperson/verify-upload-session/",
                json={
                    "team_number": team_number,
                    "upload_code": upload_code
                },
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                raise HTTPException(status_code=401, detail="تیم یافت نشد یا کد آپلود نامعتبر است")
            elif response.status_code == 403:
                raise HTTPException(status_code=403, detail="تیم هنوز در ایونت شرکت نکرده است")
            else:
                raise HTTPException(status_code=401, detail="خطا در تأیید اعتبار session")
                
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="خطا در اتصال به سرور احراز هویت")

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

def generate_unique_filename(team_num: str, file_hash: str) -> str:
    """Generate filename in format: <TEAM_NUMBER>-<HASH>-<TIMEDATE>.zip"""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    # Use first 16 characters of SHA256 hash
    short_hash = file_hash[:16]
    return f"{""}-{short_hash}-{timestamp}.zip"

def get_team_files(team_num: str) -> list[Path]:
    """Get all files for a specific team, sorted by modification time (oldest first)"""
    pattern = f"{team_num}-*.zip"
    files = list(UPLOAD_DIR.glob(pattern))
    return sorted(files, key=lambda f: f.stat().st_mtime)

def get_team_total_size(team_num: str) -> int:
    """Calculate total storage used by a team"""
    team_files = get_team_files(team_num)
    return sum(f.stat().st_size for f in team_files)

def manage_team_storage(team_num: str, new_file_size: int) -> dict:
    """
    Check if team has enough storage space. 
    Returns info about files that will be deleted if needed.
    """
    current_size = get_team_total_size(team_num)
    future_size = current_size + new_file_size
    
    if future_size <= MAX_TEAM_STORAGE:
        return {"needs_cleanup": False, "current_size": current_size, "files_to_delete": []}
    
    # Need to delete old files
    team_files = get_team_files(team_num)
    files_to_delete = []
    size_to_free = future_size - MAX_TEAM_STORAGE
    freed_size = 0
    
    for old_file in team_files:
        if freed_size >= size_to_free:
            break
        file_size = old_file.stat().st_size
        files_to_delete.append({
            "filename": old_file.name,
            "size": file_size,
            "upload_time": datetime.fromtimestamp(old_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        })
        freed_size += file_size
    
    return {
        "needs_cleanup": True,
        "current_size": current_size,
        "future_size": future_size,
        "max_size": MAX_TEAM_STORAGE,
        "files_to_delete": files_to_delete
    }

def cleanup_old_files(team_num: str, new_file_size: int) -> None:
    """Delete oldest files if team storage exceeds limit"""
    storage_info = manage_team_storage(team_num, new_file_size)
    
    if storage_info["needs_cleanup"]:
        for file_info in storage_info["files_to_delete"]:
            file_path = UPLOAD_DIR / file_info["filename"]
            if file_path.exists():
                file_path.unlink()

@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "Server is running"}

@app.post("/api/check-upload")
async def check_upload(request: Request, file_size: int = Form(...)):
    """
    Pre-check endpoint to verify if team has enough storage before uploading.
    Returns storage status and warnings if cleanup is needed.
    """
    try:
        if not request.session.get("verified") or not request.session.get("team_number"):
            raise HTTPException(status_code=401, detail='ابتدا باید کد آپلود تیم را تأیید کنید')
        
        team_number = request.session.get("team_number")
        upload_code = request.session.get("upload_code")
        
        # Verify session with backend BEFORE any processing
        await verify_session_with_backend(team_number, upload_code)
        
        # Validate file size
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f'حجم فایل بیش از حد مجاز است. حداکثر {MAX_FILE_SIZE / 1024 / 1024:.0f} مگابایت')
        
        if file_size <= 0:
            raise HTTPException(status_code=400, detail='حجم فایل نامعتبر است')
        
        # Get current team storage
        current_team_size = get_team_total_size(team_number)
        remaining_space = MAX_TEAM_STORAGE - current_team_size
        
        # Check if storage cleanup is needed
        storage_info = manage_team_storage(team_number, file_size)
        
        response_data = {
            "can_upload": True,
            "needs_cleanup": storage_info["needs_cleanup"],
            "storage": {
                "current_size_mb": current_team_size / 1024 / 1024,
                "new_file_size_mb": file_size / 1024 / 1024,
                "future_size_mb": (current_team_size + file_size) / 1024 / 1024,
                "max_size_mb": MAX_TEAM_STORAGE / 1024 / 1024,
                "remaining_mb": remaining_space / 1024 / 1024,
                "usage_percent": (current_team_size / MAX_TEAM_STORAGE) * 100
            }
        }
        
        if storage_info["needs_cleanup"]:
            response_data["warning"] = {
                "message": f"فضای ذخیره‌سازی کافی نیست. فایل‌های قدیمی حذف خواهند شد.",
                "files_to_delete": storage_info["files_to_delete"]
            }
        
        return response_data
        
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

@app.post("/api/upload")
async def upload_file(request: Request, file: UploadFile = File(...), confirmed: bool = Form(False)):
    """
    Upload file endpoint. Should be called after /api/check-upload confirms upload is safe.
    If confirmed=true, will proceed with cleanup if needed.
    """
    try:
        if not request.session.get("verified") or not request.session.get("team_number"):
            raise HTTPException(status_code=401, detail='ابتدا باید کد آپلود تیم را تأیید کنید')

        team_number = request.session.get("team_number")
        upload_code = request.session.get("upload_code")
        
        # Verify session with backend BEFORE reading file
        await verify_session_with_backend(team_number, upload_code)

        is_valid_ext = Path(file.filename).suffix.lower() in ALLOWED_EXTENSIONS
        if not is_valid_ext:
            raise HTTPException(status_code=400, detail='فقط فایل های ZIP مجاز هستند!')

        if not file.filename.lower().endswith('.zip'):
            raise HTTPException(status_code=400, detail='فقط فایل های ZIP مجاز هستند!')
        
        # Read the file and calculate hash
        temp_chunks = []
        total_written = 0
        chunk_size = 1024 * 1024  
        file_hash = hashlib.sha256()

        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            total_written += len(chunk)
            if total_written > MAX_FILE_SIZE:
                raise HTTPException(status_code=400, detail='حجم فایل بیش از حد مجاز است. حداکثر 512 مگابایت')
            
            temp_chunks.append(chunk)
            file_hash.update(chunk)

        # Calculate file hash (SHA256)
        sha256_hash = file_hash.hexdigest()
        
        # Get storage info to see if cleanup is needed
        storage_info = manage_team_storage(team_number, total_written)
        
        # If cleanup is needed and user confirmed, do cleanup
        if storage_info["needs_cleanup"]:
            if not confirmed:
                # Should not happen - frontend should call /api/check-upload first
                files_list = "\n".join([
                    f"📁 {f['filename']} ({f['size'] / 1024 / 1024:.2f} MB) - {f['upload_time']}"
                    for f in storage_info["files_to_delete"]
                ])
                
                return JSONResponse(status_code=409, content={
                    "error": "فضای ذخیره‌سازی تیم شما پر است",
                    "code": "STORAGE_LIMIT_EXCEEDED",
                    "message": f"حجم کل فایل‌های شما به {storage_info['current_size'] / 1024 / 1024:.2f} MB رسیده است.\n"
                               f"با آپلود این فایل ({total_written / 1024 / 1024:.2f} MB)، حد مجاز 1GB را رد می‌کنید.\n\n"
                               f"⚠️ فایل‌های زیر به‌طور خودکار حذف خواهند شد:\n{files_list}\n\n"
                               f"آیا مطمئن هستید؟",
                    "current_size_mb": storage_info["current_size"] / 1024 / 1024,
                    "new_file_size_mb": total_written / 1024 / 1024,
                    "max_size_mb": MAX_TEAM_STORAGE / 1024 / 1024,
                    "files_to_delete": storage_info["files_to_delete"],
                    "file_hash": sha256_hash
                })
            
            # User confirmed, do cleanup
            cleanup_old_files(team_number, total_written)

        # Generate unique filename using the file's hash
        filename = generate_unique_filename(team_number, sha256_hash)
        file_path = UPLOAD_DIR / filename

        # Write file
        try:
            async with aiofiles.open(file_path, 'wb') as out_f:
                for chunk in temp_chunks:
                    await out_f.write(chunk)
        finally:
            await file.close()

        # Get updated storage info
        new_total_size = get_team_total_size(team_number)
        team_files = get_team_files(team_number)

        return {
            "success": True,
            "filename": filename,
            "originalName": file.filename,
            "size": total_written,
            "hash": sha256_hash,
            "team_storage": {
                "total_size_mb": new_total_size / 1024 / 1024,
                "max_size_mb": MAX_TEAM_STORAGE / 1024 / 1024,
                "usage_percent": (new_total_size / MAX_TEAM_STORAGE) * 100,
                "total_files": len(team_files)
            },
            "deleted_files": storage_info.get("files_to_delete", []) if storage_info["needs_cleanup"] else []
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

@app.get("/api/team-files")
async def get_team_files_list(request: Request):
    """Get list of all files uploaded by the team"""
    if not request.session.get("verified") or not request.session.get("team_number"):
        raise HTTPException(status_code=401, detail='ابتدا باید کد آپلود تیم را تأیید کنید')
    
    team_number = request.session.get("team_number")
    team_files = get_team_files(team_number)
    
    files_list = []
    for file_path in team_files:
        stat = file_path.stat()
        files_list.append({
            "filename": file_path.name,
            "size": stat.st_size,
            "size_mb": stat.st_size / 1024 / 1024,
            "upload_time": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "download_url": f"/uploads/{file_path.name}"
        })
    
    total_size = sum(f["size"] for f in files_list)
    
    return {
        "files": files_list,
        "total_files": len(files_list),
        "storage": {
            "total_size_mb": total_size / 1024 / 1024,
            "max_size_mb": MAX_TEAM_STORAGE / 1024 / 1024,
            "usage_percent": (total_size / MAX_TEAM_STORAGE) * 100,
            "remaining_mb": (MAX_TEAM_STORAGE - total_size) / 1024 / 1024
        }
    }

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
            f"{backend_url}/inperson/verify-team-code/",  # اول InPerson
            f"{backend_url}/gamejam/verify-team-code/",   # بعد GameJam
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
                        request.session["team_number"] = data["team"].get("team_number", code)  # استفاده از team_number یا fallback به code
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
