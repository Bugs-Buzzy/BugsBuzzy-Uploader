# رفع مشکل 403 برای آپلود فایل‌های بزرگ

## مشکل
ریکوئست‌های آپلود فایل‌های با حجم بالا و حذف فایل خطای 403 می‌دهند.

## راه حل

### 1. پیدا کردن فایل کانفیگ nginx

فایل کانفیگ nginx رو پیدا کنید:
```bash
# معمولاً در یکی از این مسیرهاست:
/etc/nginx/sites-available/your-site
/etc/nginx/conf.d/your-site.conf
/etc/nginx/nginx.conf
```

### 2. اضافه کردن این تنظیمات

در بخش `server` مربوط به آپلودر، این خطوط رو اضافه/ویرایش کنید:

```nginx
server {
    listen 80;
    # یا listen 443 ssl; برای HTTPS
    
    server_name your-domain.com;
    
    # ⭐ مهم: افزایش محدودیت حجم فایل (حداقل 1.5GB)
    client_max_body_size 1536M;
    
    # ⭐ Timeout برای آپلود فایل‌های بزرگ
    proxy_connect_timeout 600;
    proxy_send_timeout 600;
    proxy_read_timeout 600;
    send_timeout 600;
    
    # ⭐ غیرفعال کردن buffering برای فایل‌های بزرگ
    proxy_buffering off;
    proxy_request_buffering off;
    
    # ⭐ افزایش buffer size
    client_body_buffer_size 128k;
    
    location / {
        proxy_pass http://localhost:9000;  # پورت سرویس شما
        
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # ⭐ مهم: Headers برای آپلود فایل‌های بزرگ
        proxy_set_header Connection "";
        proxy_http_version 1.1;
        proxy_read_timeout 600;
        proxy_send_timeout 600;
    }
}
```

### 3. اعمال تغییرات

```bash
# بررسی کانفیگ
sudo nginx -t

# اگر OK بود، reload کنید
sudo systemctl reload nginx
# یا
sudo nginx -s reload
```

### 4. Restart سرویس آپلودر

```bash
# اگر با Docker:
docker-compose restart uploader

# یا اگر مستقیماً:
sudo systemctl restart your-service-name
```

## نکات مهم

1. **`client_max_body_size`** باید حتماً **بیشتر از 1GB** باشه چون هر تیم می‌تونه تا 1GB آپلود کنه.

2. اگر چند تا `server` block دارید، این تنظیمات رو در **همه**‌شون اعمال کنید.

3. اگر از HTTPS استفاده می‌کنید، این تنظیمات رو در block مربوط به port 443 هم اعمال کنید.

4. بعد از تغییرات، **حتماً** nginx و سرویس آپلودر رو restart کنید.

## بررسی مشکل

اگر بعد از اعمال تغییرات هنوز مشکل دارید:

```bash
# لاگ nginx رو چک کنید
sudo tail -f /var/log/nginx/error.log

# لاگ سرویس آپلودر رو چک کنید
docker-compose logs -f uploader
```

اگر در لاگ‌ها خطای 413 می‌بینید، یعنی `client_max_body_size` هنوز کم است و باید بیشتر کنید.

