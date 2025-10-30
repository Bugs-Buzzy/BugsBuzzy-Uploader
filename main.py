import os
import hashlib
import json
import tempfile
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
import aiosqlite
from datetime import datetime

app = FastAPI(title="BugsBuzzy Upload Server")
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
PUBLIC_DIR = BASE_DIR / "public"
DB_PATH = BASE_DIR / "uploads.db"

# تغییر محدودیت: هر تیم می‌تواند تا 1GB آپلود کند
MAX_TEAM_TOTAL_SIZE = 1024 * 1024 * 1024  # 1GB
ALLOWED_EXTENSIONS = ['.zip']
ALLOWED_MIME_TYPES = ['application/zip', 'application/x-zip-compressed', 'application/octet-stream']

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production-please")
ALLOWED_KEYS_FILE = os.getenv("ALLOWED_KEYS_FILE")
ALLOWED_KEYS_ENV = os.getenv("ALLOWED_KEYS")
BACKEND_URL = os.getenv("BACKEND_URL", "https://bugsbuzzy.ir/api")

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

# ============================================
# Database functions
# ============================================

async def init_db():
    """Initialize the SQLite database"""
    async with aiosqlite.connect(DB_PATH) as db:
        # جدول فایل‌ها: اطلاعات هر فایل آپلود شده
        await db.execute("""
            CREATE TABLE IF NOT EXISTS uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_number TEXT NOT NULL,
                original_filename TEXT,
                stored_filename TEXT NOT NULL UNIQUE,
                file_hash TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                uploaded_at TEXT NOT NULL,
                upload_code TEXT NOT NULL
            )
        """)
        
        # ایندکس برای جستجوی سریع‌تر
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_team_number ON uploads(team_number)
        """)
        
        await db.commit()

async def get_team_total_size(team_number: str) -> int:
    """Get total size of all uploaded files for a team"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT SUM(file_size) FROM uploads WHERE team_number = ?",
            (team_number,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row and row[0] else 0

async def get_team_files(team_number: str) -> list[dict]:
    """Get all uploaded files for a team"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT id, original_filename, stored_filename, file_hash, file_size, uploaded_at
               FROM uploads WHERE team_number = ? ORDER BY uploaded_at ASC""",
            (team_number,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "id": row[0],
                    "original_filename": row[1],
                    "stored_filename": row[2],
                    "hash": row[3],
                    "size": row[4],
                    "uploaded_at": row[5]
                }
                for row in rows
            ]

async def save_file_record(team_number: str, original_filename: str, stored_filename: str,
                          file_hash: str, file_size: int, upload_code: str):
    """Save file metadata to database"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO uploads (team_number, original_filename, stored_filename, file_hash, file_size, uploaded_at, upload_code)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (team_number, original_filename, stored_filename, file_hash, file_size,
             datetime.now().isoformat(), upload_code)
        )
        await db.commit()

async def delete_file_record(file_id: int, team_number: str) -> Optional[dict]:
    """Delete file record from database and return file info"""
    async with aiosqlite.connect(DB_PATH) as db:
        # ابتدا اطلاعات فایل رو بگیر
        async with db.execute(
            "SELECT stored_filename, file_size FROM uploads WHERE id = ? AND team_number = ?",
            (file_id, team_number)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            
            stored_filename, file_size = row
            
            # حذف از دیتابیس
            await db.execute(
                "DELETE FROM uploads WHERE id = ? AND team_number = ?",
                (file_id, team_number)
            )
            await db.commit()
            
            return {"stored_filename": stored_filename, "file_size": file_size}

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    await init_db()

# ============================================
# API Endpoints
# ============================================

@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "Server is running"}

@app.get("/api/team-stats")
async def get_team_stats(request: Request):
    """Get team statistics: total size and remaining quota"""
    if not request.session.get("verified") or not request.session.get("team_id"):
        raise HTTPException(status_code=401, detail='ابتدا باید کد آپلود تیم را تأیید کنید')
    
    team_number = str(request.session.get("team_id"))
    total_size = await get_team_total_size(team_number)
    remaining = MAX_TEAM_TOTAL_SIZE - total_size
    
    return {
        "total_size": total_size,
        "max_size": MAX_TEAM_TOTAL_SIZE,
        "remaining": remaining,
        "total_size_formatted": format_bytes(total_size),
        "max_size_formatted": format_bytes(MAX_TEAM_TOTAL_SIZE),
        "remaining_formatted": format_bytes(remaining)
    }

@app.get("/api/files")
async def get_files(request: Request):
    """Get list of uploaded files for current team"""
    if not request.session.get("verified") or not request.session.get("team_id"):
        raise HTTPException(status_code=401, detail='ابتدا باید کد آپلود تیم را تأیید کنید')
    
    team_number = str(request.session.get("team_id"))
    files = await get_team_files(team_number)
    
    # اضافه کردن شماره سابمیت (1, 2, 3, ...)
    for i, f in enumerate(files, 1):
        f["submit_number"] = i
    
    return {"files": files}

@app.delete("/api/files/{file_id}")
async def delete_file(file_id: int, request: Request):
    """Delete an uploaded file"""
    if not request.session.get("verified") or not request.session.get("team_id"):
        raise HTTPException(status_code=401, detail='ابتدا باید کد آپلود تیم را تأیید کنید')
    
    team_number = str(request.session.get("team_id"))
    
    # حذف از دیتابیس
    file_info = await delete_file_record(file_id, team_number)
    
    if not file_info:
        raise HTTPException(status_code=404, detail="فایل پیدا نشد")
    
    # حذف فایل فیزیکی
    file_path = UPLOAD_DIR / file_info["stored_filename"]
    try:
        if file_path.exists():
            file_path.unlink()
    except Exception as e:
        # اگر فایل فیزیکی پاک نشد، مشکلی نیست (ممکنه قبلا پاک شده باشه)
        pass
    
    return {"success": True, "deleted_file": file_info["stored_filename"]}

@app.post("/api/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    temp_file_path = None
    try:
        if not request.session.get("verified") or not request.session.get("upload_code"):
            raise HTTPException(status_code=401, detail='ابتدا باید کد آپلود تیم را تأیید کنید')

        team_code = request.session.get("upload_code")
        team_number = str(request.session.get("team_id"))
        
        # بررسی نوع فایل
        is_valid_ext = Path(file.filename).suffix.lower() in ALLOWED_EXTENSIONS
        if not is_valid_ext:
            raise HTTPException(status_code=400, detail='فقط فایل های ZIP مجاز هستند!')

        orig_name = Path(file.filename).name
        if not orig_name.lower().endswith('.zip'):
            raise HTTPException(status_code=400, detail='فقط فایل های ZIP مجاز هستند!')
        
        # بررسی محدودیت کل حجم تیم
        existing_total = await get_team_total_size(team_number)
        
        # خواندن فایل و هش کردن همزمان
        file_hash = hashlib.sha256()
        total_written = 0
        chunk_size = 1024 * 1024  # 1MB chunks
        
        # ایجاد فایل موقت برای ذخیره فایل قبل از هش کامل
        fd, temp_file_path = tempfile.mkstemp(dir=UPLOAD_DIR, suffix='.tmp')
        temp_file_path = Path(temp_file_path)
        
        try:
            # باز کردن فایل موقت به صورت async
            async with aiofiles.open(fd, 'wb') as temp_file:
                while True:
                    chunk = await file.read(chunk_size)
                    if not chunk:
                        break
                    total_written += len(chunk)
                    await temp_file.write(chunk)
                    file_hash.update(chunk)
                    
                    # بررسی محدودیت حجم تیم
                    new_total = existing_total + total_written
                    if new_total > MAX_TEAM_TOTAL_SIZE:
                        raise HTTPException(
                            status_code=400, 
                            detail=f'ظرفیت تیم تکمیل شده است! حجم باقیمانده: {format_bytes(MAX_TEAM_TOTAL_SIZE - existing_total)}'
                        )
        finally:
            await file.close()
        
        sha256_hash = file_hash.hexdigest()
        
        # نام فایل: {team_number}_{hash}.zip
        stored_filename = f"{team_number}_{sha256_hash}.zip"
        file_path = UPLOAD_DIR / stored_filename
        
        # حذف فایل نهایی اگر قبلاً وجود داشته باشد (برای overwrite)
        if file_path.exists():
            file_path.unlink()
        
        # جابجایی فایل موقت به محل نهایی
        try:
            temp_file_path.rename(file_path)
            temp_file_path = None  # موفقیت‌آمیز بود، دیگر نیازی به پاک کردن نیست
        except Exception as e:
            if temp_file_path and temp_file_path.exists():
                temp_file_path.unlink()
            raise HTTPException(status_code=500, detail=f'خطا در ذخیره فایل: {str(e)}')
        
        # ذخیره اطلاعات در دیتابیس
        await save_file_record(
            team_number=team_number,
            original_filename=orig_name,
            stored_filename=stored_filename,
            file_hash=sha256_hash,
            file_size=total_written,
            upload_code=team_code
        )
        
        return {
            "success": True,
            "filename": stored_filename,
            "originalName": orig_name,
            "size": total_written,
            "hash": sha256_hash,
            "team_total_size": existing_total + total_written,
            "team_remaining": MAX_TEAM_TOTAL_SIZE - (existing_total + total_written)
        }

    except HTTPException as e:
        # پاک کردن فایل موقت در صورت خطا
        if temp_file_path and temp_file_path.exists():
            try:
                temp_file_path.unlink()
            except:
                pass
        return JSONResponse(
            status_code=e.status_code,
            content={"error": e.detail}
        )
    except Exception as e:
        # پاک کردن فایل موقت در صورت خطا
        if temp_file_path and temp_file_path.exists():
            try:
                temp_file_path.unlink()
            except:
                pass
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
        endpoints = [
            f"{BACKEND_URL}/inperson/verify-team-code/",  # اول InPerson
            f"{BACKEND_URL}/gamejam/verify-team-code/",   # بعد GameJam
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

def format_bytes(bytes_size):
    """Format bytes to human readable format"""
    if bytes_size == 0:
        return '0 بایت'
    k = 1024
    sizes = ['بایت', 'کیلوبایت', 'مگابایت', 'گیگابایت', 'ترابایت']
    i = 0
    size = float(bytes_size)
    while size >= k and i < len(sizes) - 1:
        size /= k
        i += 1
    return f'{size:.2f} {sizes[i]}'

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
