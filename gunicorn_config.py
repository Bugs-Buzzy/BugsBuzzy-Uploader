import multiprocessing

bind = "0.0.0.0:1000"
backlog = 2048

workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000
timeout = 300  

keepalive = 5

accesslog = "access.log"
errorlog = "error.log"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

proc_name = "bugsbuzzy_upload"

daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

max_requests = 1000
max_requests_jitter = 50
preload_app = True
graceful_timeout = 30
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190