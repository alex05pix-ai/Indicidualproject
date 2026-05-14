# Общие правила проксирования к Flask/Gunicorn-приложению.
# Подключается через `include /etc/nginx/conf.d/proxy.inc;` в server-блоках.

# ---- Безопасность ----
add_header X-Frame-Options "DENY" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;

# ---- Rate limiting ----
limit_req zone=api_zone burst=20 nodelay;

# ---- Статика напрямую из app-контейнера ----
location ^~ /static/ {
    proxy_pass http://app_upstream;
    proxy_set_header Host $host;
    proxy_cache_bypass $http_upgrade;
    expires 7d;
    add_header Cache-Control "public, max-age=604800, immutable";
    access_log off;
}

# ---- Service Worker и manifest должны отдаваться с корня без агрессивного кеша ----
location = /sw.js {
    proxy_pass http://app_upstream;
    proxy_set_header Host $host;
    add_header Cache-Control "no-cache";
    add_header Service-Worker-Allowed "/";
}

location = /manifest.json {
    proxy_pass http://app_upstream;
    proxy_set_header Host $host;
    expires 1d;
}

# ---- Поиск (отдельный жёсткий лимит) ----
location = /search {
    limit_req zone=search_zone burst=3 nodelay;

    proxy_pass http://app_upstream;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;
}

# ---- WebSocket для Socket.IO ----
location /socket.io/ {
    proxy_pass http://app_upstream;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    proxy_buffering off;
}

# ---- Всё остальное — обычный proxy ----
location / {
    proxy_pass http://app_upstream;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;
    proxy_connect_timeout 10s;
}
