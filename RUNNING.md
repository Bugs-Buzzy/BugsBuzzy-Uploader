# راهنمای اجرای سرویس آپلودر

## نحوه اجرا

### ⚠️ برای Development (توسعه):
```bash
python3 main.py
```
- یک worker process
- قابلیت reload خودکار
- برای تست و توسعه مناسب است
- **برای استفاده واقعی مناسب نیست**

### ✅ برای Production (استفاده واقعی):

#### روش 1: استفاده از Gunicorn (توصیه می‌شود)
```bash
gunicorn main:app -c gunicorn_config.py
```

یا اگر gunicorn نصب نیست:
```bash
pip install gunicorn
gunicorn main:app -c gunicorn_config.py
```

**مزایا:**
- چند worker process (به تعداد CPU * 2 + 1)
- قابلیت handle کردن درخواست‌های همزمان بیشتر
- مناسب برای production
- Worker ها به طور خودکار restart می‌شن

#### روش 2: استفاده از Uvicorn با چند worker
```bash
uvicorn main:app --host 0.0.0.0 --port 9000 --workers 4
```

یا در `main.py` خطوط زیر رو uncomment کنید:
```python
workers = multiprocessing.cpu_count() * 2 + 1
reload = False
```

#### روش 3: استفاده از Docker (بهترین روش)
```bash
docker-compose up -d
```

## مقایسه روش‌ها

| روش | Workers | Concurrent Requests | مناسب برای |
|-----|---------|---------------------|------------|
| `python3 main.py` | 1 | محدود (~100) | Development |
| `uvicorn --workers 4` | 4 | متوسط (~400) | Production کوچک |
| `gunicorn` | CPU*2+1 | بالا (~1000+) | Production |
| Docker + Gunicorn | CPU*2+1 | بالا (~1000+) | Production (بهترین) |

## توصیه

برای **استفاده واقعی روی سرور**، حتماً از **Gunicorn** یا **Docker** استفاده کنید:

```bash
# روش ساده با Gunicorn:
gunicorn main:app -c gunicorn_config.py

# یا با systemd (برای اجرای دائمی):
sudo systemctl start bugsbuzzy-uploader
sudo systemctl enable bugsbuzzy-uploader
```

## تعداد همزمان‌ها

با Gunicorn و چند worker:
- می‌تونه به **صدها تا هزاران کاربر همزمان** سرویس بده
- بستگی به تعداد CPU و RAM سرور داره
- برای مثال: سرور با 4 CPU = 9 workers = تا ~9000 همزمان (با worker_connections=1000)

**نکته مهم:** برای آپلود فایل‌های بزرگ، درخواست‌های همزمان کمتری رو می‌تونه handle کنه.

