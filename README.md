# BugsBuzzy Uploader

سرویس آپلود فایل برای تیم‌های رقابت حضوری باگزبازی

## ویژگی‌ها

- ✅ سیستم احراز هویت با کد تیم
- ✅ پشتیبانی از تیم‌های InPerson و GameJam
- ✅ آپلود چند فایل ZIP (حجم کل تا 1 گیگابایت)
- ✅ Session-based authentication
- ✅ رابط کاربری Pixel Art
- ✅ Docker support
- ✅ File Manager با امکان حذف و مشاهده هش
- ✅ نمایش ظرفیت باقیمانده تیم
- ✅ نام‌گذاری خودکار: `{team_number}_{sha256_hash}.zip`
- ✅ Database SQLite برای مدیریت فایل‌ها

## نحوه استفاده

### Development

1. نصب dependencies:
```bash
pip install -r requirements.txt
```

2. اجرای سرور:
```bash
python main.py
```

سرویس روی پورت 9000 در دسترس است: http://localhost:9000

### Production با Docker

برای راه‌اندازی با Docker، به [README.Docker.md](README.Docker.md) مراجعه کنید.

بطور خلاصه:

1. کپی کردن environment variables:
```bash
cp .env.example .env
```

2. ویرایش `.env` و تنظیم متغیرها

3. Build و اجرا:
```bash
docker-compose up -d
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | کلید مخفی برای session | `change-me-in-production-please` |
| `BACKEND_URL` | آدرس API بکند | `https://bugsbuzzy.ir/api` |

## API Endpoints

### `POST /api/verify-code`
تأیید کد آپلود تیم

**Request Body:**
```json
{
  "code": "ABC12345"
}
```

**Response:**
```json
{
  "success": true,
  "team": {
    "id": 1,
    "name": "Team Name",
    "leader": {...},
    "member_count": 3
  },
  "team_type": "inperson"
}
```

### `POST /api/upload`
آپلود فایل (نیاز به session معتبر دارد)

**Request:**
- `file`: فایل ZIP
- نام فایل باید `{CODE}.zip` باشد

**Response:**
```json
{
  "success": true,
  "filename": "1_a1b2c3d4...zip",
  "originalName": "MYSITE.zip",
  "size": 1024000,
  "hash": "a1b2c3d4...",
  "team_total_size": 524288000,
  "team_remaining": 536870912
}
```

### `GET /api/team-stats`
دریافت آمار حجم استفاده تیم

**Response:**
```json
{
  "total_size": 524288000,
  "max_size": 1073741824,
  "remaining": 549453824,
  "total_size_formatted": "500.00 مگابایت",
  "max_size_formatted": "1.00 گیگابایت",
  "remaining_formatted": "524.00 مگابایت"
}
```

### `GET /api/files`
دریافت لیست فایل‌های آپلود شده تیم

**Response:**
```json
{
  "files": [
    {
      "id": 1,
      "original_filename": "project.zip",
      "stored_filename": "1_a1b2c3d4...zip",
      "hash": "a1b2c3d4...",
      "size": 1024000,
      "uploaded_at": "2024-01-01T12:00:00",
      "submit_number": 1
    }
  ]
}
```

### `DELETE /api/files/{file_id}`
حذف یک فایل

**Response:**
```json
{
  "success": true,
  "deleted_file": "1_a1b2c3d4...zip"
}
```

### `GET /api/session`
دریافت اطلاعات session فعلی

### `POST /api/logout`
خروج و پاک کردن session

### `GET /health`
Health check endpoint

## جریان کار

1. تیم در رویداد شرکت می‌کند (`status="attended"`)
2. کد آپلود در پنل نمایش داده می‌شود
3. عضو تیم به uploader می‌رود و کد را وارد می‌کند
4. پس از تأیید، می‌تواند چندین فایل ZIP آپلود کند (تا مجموعاً 1GB)
5. هر فایل با نام `{team_number}_{sha256_hash}.zip` ذخیره می‌شود
6. تیم می‌تواند فایل‌های خود را در File Manager مشاهده، هش را کپی و فایل‌ها را حذف کند

## ساختار فایل‌ها

```
BugsBuzzy-Uploader/
├── main.py              # FastAPI application
├── Dockerfile           # Docker image
├── docker-compose.yml   # Docker Compose config
├── requirements.txt     # Python dependencies
├── gunicorn_config.py   # Gunicorn configuration
├── uploads.db           # SQLite database
├── public/              # Frontend files
│   ├── index.html
│   ├── bkg-workshops.png
│   └── unixel.woff
└── uploads/             # Uploaded files (mounted as volume)
```

## امنیت

- فقط تیم‌های با `status="attended"` می‌توانند آپلود کنند
- هر کد منحصر به یک تیم است
- Session-based authentication
- اعتبارسنجی در هر دو سمت frontend و backend
- محدودیت حجم کل تیم: 1GB
- فقط فایل‌های ZIP مجاز هستند
- هر فایل با SHA-256 هش می‌شود برای اطمینان از یکتایی و صحت
- امکان حذف فایل فقط برای تیم مالک

## License

MIT
