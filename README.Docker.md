# راهنمای Docker

## راه‌اندازی سریع

### 1. تنظیم Environment Variables

ابتدا فایل `.env.example` را کپی کرده و تنظیمات خود را اعمال کنید:

```bash
cp .env.example .env
```

سپس فایل `.env` را ویرایش کرده و مقادیر مناسب را وارد کنید:

- `SECRET_KEY`: یک کلید امنیتی برای session management (برای production حتماً تغییر دهید)
- `BACKEND_URL`: آدرس API بکند (پیش‌فرض: https://bugsbuzzy.ir/api)

### 2. Build و Run

برای ساخت و اجرای کانتینر:

```bash
docker-compose up -d
```

برای مشاهده لاگ‌ها:

```bash
docker-compose up
```

### 3. دسترسی به سرویس

پس از راه‌اندازی، سرویس روی `http://localhost:9000` در دسترس است.

## مدیریت کانتینر

### توقف سرویس

```bash
docker-compose down
```

### راه‌اندازی مجدد

```bash
docker-compose restart
```

### مشاهده لاگ‌ها

```bash
docker-compose logs -f uploader
```

### ریستارت کانتینر

```bash
docker-compose restart uploader
```

## داده‌های ذخیره‌شده

دو volume برای نگهداری داده‌ها وجود دارد:

- `./uploads`: فایل‌های آپلود شده
- `./uploads.db`: دیتابیس SQLite

⚠️ **توجه**: در production، حتماً از این volume‌ها backup بگیرید.

## Build تکی Docker Image

اگر فقط می‌خواهید image را build کنید:

```bash
docker build -t bugsbuzzy-uploader:latest .
```

و سپس اجرا کنید:

```bash
docker run -d \
  --name bugsbuzzy-uploader \
  -p 9000:9000 \
  -v $(pwd)/uploads:/app/uploads \
  -v $(pwd)/uploads.db:/app/uploads.db \
  -e SECRET_KEY=your-secret-key \
  -e BACKEND_URL=https://bugsbuzzy.ir/api \
  bugsbuzzy-uploader:latest
```

## Health Check

کانتینر دارای health check است که هر 30 ثانیه بررسی می‌کند. برای مشاهده وضعیت:

```bash
docker ps
```

ستون `STATUS` باید `healthy` را نشان دهد.

## Troubleshooting

### خطا در اتصال به دیتابیس

اگر خطای permission گرفتید:

```bash
chmod 755 uploads
touch uploads.db
chmod 644 uploads.db
```

### بررسی لاگ‌های خطا

```bash
docker-compose logs uploader | grep ERROR
```

### پاک کردن و شروع از نو

```bash
docker-compose down -v
docker-compose up -d --build
```
