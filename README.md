# BugsBuzzy Uploader

سرویس آپلود فایل برای تیم‌های رقابت حضوری باگزبازی

## ویژگی‌ها

- ✅ سیستم احراز هویت با کد تیم
- ✅ پشتیبانی از تیم‌های InPerson 
- ✅ آپلود فایل‌های ZIP تا 512 مگابایت
- ✅ Session-based authentication
- ✅ رابط کاربری Pixel Art
- ✅ Docker support

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
  "filename": "ABC12345.zip",
  "size": 1024000,
  "url": "http://..."
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
4. پس از تأیید، می‌تواند فایل ZIP آپلود کند
5. فایل با نام کد تیم ذخیره می‌شود

## ساختار فایل‌ها

```
BugsBuzzy-Uploader/
├── main.py              # FastAPI application
├── Dockerfile           # Docker image
├── docker-compose.yml   # Docker Compose config
├── requirements.txt     # Python dependencies
├── gunicorn_config.py   # Gunicorn configuration
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
- محدودیت حجم فایل: 512MB
- فقط فایل‌های ZIP مجاز هستند

## License

MIT
