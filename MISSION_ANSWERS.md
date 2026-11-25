# Day 14 Lab — Mission Answers

> Môi trường: Windows 11 Pro, Python 3.12.10, Docker Desktop 29.7.2. Ngày chạy: 2026-11-25.
> Mọi output dưới đây là output thật của các lệnh đã chạy (token đã che).

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`

| # | Anti-pattern | Dòng | Hậu quả |
|---|---|---|---|
| 1 | Hard-code secret: `OPENAI_API_KEY = "sk-..."`, `DATABASE_URL` chứa `admin:password123` | 17–18 | Push lên GitHub là lộ key/mật khẩu; đổi key phải sửa code và deploy lại |
| 2 | **Log ra secret**: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` | 34 | Key nằm trong log của platform, ai đọc được log là có key (đã thấy thật khi chạy, xem 1.2) |
| 3 | Dùng `print()` thay vì logging có cấu trúc, log cả câu hỏi và câu trả lời của người dùng | 33, 38 | Không có level, timestamp, không parse/lọc được; lộ dữ liệu người dùng |
| 4 | Không có health check (`/health`) hay readiness (`/ready`) | 42–43 | Platform không biết agent chết để restart, load balancer không biết để ngừng route (thật: `/health` → 404) |
| 5 | Port cố định `port=8000` | 52 | Railway/Render cấp port qua biến `PORT`; app không nghe đúng port → deploy fail |
| 6 | Bind `host="localhost"` | 51 | Trong container chỉ nhận kết nối từ chính container, bên ngoài không gọi vào được |
| 7 | `reload=True` và `DEBUG = True` cứng trong code | 21, 53 | Reloader tốn tài nguyên, theo dõi file, chạy thêm process; debug mode lộ thông tin |
| 8 | Config (`DEBUG`, `MAX_TOKENS`) là hằng số, không đọc từ env | 21–22 | Muốn đổi giữa dev/staging/prod phải sửa code |
| 9 | Không xử lý shutdown (không lifespan/SIGTERM) | — | Platform tắt container là request đang chạy bị cắt ngang |
| 10 | `/ask` nhận `question` qua query string, không validate độ dài | 31 | Câu hỏi nằm trong URL → bị ghi vào access log, proxy log; không giới hạn input |

### Exercise 1.2: Chạy bản develop

Bản develop nhận `question` qua query string (gửi JSON bị 422):

```text
$ curl -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
content-type: application/json

{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}

$ curl -i -X POST http://localhost:8000/ask -H 'Content-Type: application/json' -d '{"question": "Hello"}'
HTTP/1.1 422 Unprocessable Entity
content-type: application/json

{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}

$ curl -i http://localhost:8000/health
HTTP/1.1 404 Not Found
content-type: application/json

{"detail":"Not Found"}
```

Log server lúc nhận request — secret bị in thẳng ra log:

```text
INFO:     Uvicorn running on http://localhost:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [18660] using WatchFiles
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Đây là câu trả lời từ AI agent (mock). ...
```

**Quan sát:** chạy được, nhưng không production-ready: chỉ nghe `localhost:8000`, không có health check, lộ secret trong log, có reloader.

### Exercise 1.3: So sánh develop và production

Bản production chạy thử (không cần `.env`, config có giá trị mặc định):

```text
$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":6.0,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T10:06:04.799727+00:00"}

$ curl -i http://localhost:8000/ready
HTTP/1.1 200 OK
{"ready":true}

$ curl -i -X POST http://localhost:8000/ask -H 'Content-Type: application/json' -d '{"question": "Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","model":"gpt-4o-mini"}
```
Server nghe `0.0.0.0:8000` (`netstat`), không có reloader.

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hằng số trong code (`DEBUG = True`, key, DB URL) | `config.py` đọc env (`os.getenv`), `.env.example` liệt kê biến, validate fail-fast (thiếu `AGENT_API_KEY` khi `ENVIRONMENT=production` → crash ngay lúc start) | Cùng một image chạy được ở dev/staging/prod chỉ bằng đổi env; secret không nằm trong Git; thiếu config thì lỗi ngay lúc deploy thay vì lỗi lúc có người dùng |
| Secrets | Hard-code và còn in ra log | Đọc từ env, không log secret, chỉ log `question_length` | Lộ key = mất tiền/dữ liệu; log thường được nhiều người và nhiều hệ thống đọc |
| Health check | Không có (`/health` → 404) | `/health` (liveness, uptime/version) + `/ready` (readiness, 503 khi chưa sẵn sàng) | Platform dùng `/health` để restart container chết, load balancer dùng `/ready` để không gửi traffic vào instance đang khởi động/tắt |
| Logging | `print()`, log cả secret và nội dung câu hỏi | Định dạng JSON (`{"time","level","msg"}`), log metadata thay vì nội dung | Log JSON parse/lọc/đếm được trong Loki/Datadog; không lộ dữ liệu nhạy cảm |
| Shutdown | Đột ngột, không có hook | `lifespan` (đánh dấu not-ready, dọn dẹp) + handler SIGTERM | Platform gửi SIGTERM khi deploy/scale-down; xử lý êm thì request đang chạy không bị mất |
| Host / Port | `localhost:8000` cố định | `HOST=0.0.0.0`, `PORT` từ env | Container cần bind `0.0.0.0`; Railway/Render inject `PORT` |
| Reload / debug | `reload=True` luôn bật | `reload` chỉ khi `DEBUG=true` | Reloader ở production tốn tài nguyên và có thể restart app ngoài ý muốn |
| CORS | Không cấu hình | `ALLOWED_ORIGINS` từ env | Chỉ frontend được phép mới gọi được API từ trình duyệt |

**Điều phát hiện thêm khi chạy bản production:** log JSON thực tế **không được in ra**. Lúc import, `config.py` gọi `logging.warning("OPENAI_API_KEY not set ...")` trước khi `app.py` gọi `logging.basicConfig(format=JSON)`; lời gọi `warning` đầu tiên tự cấu hình root logger (format mặc định, level WARNING), nên `basicConfig` sau đó không có tác dụng và mọi `logger.info(...)` bị bỏ. Bằng chứng trong log: dòng `WARNING:root:OPENAI_API_KEY not set — using mock LLM` (format mặc định, không phải JSON) và không có dòng `startup`/`agent_request` nào. Cách sửa: gọi `basicConfig(..., force=True)` hoặc cấu hình logging trước khi import `config`. Ở Part 6 mình tự gắn `JsonFormatter` vào logger riêng (`agent`, `propagate=False`) để tránh lỗi này.

---

## Part 2: Docker

### Exercise 2.1: Câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11` — bản Python đầy đủ (Debian + compiler, header…), rất nặng.
2. **Working directory:** `/app` (`WORKDIR /app`) — mọi lệnh `COPY`/`RUN`/`CMD` sau đó chạy trong thư mục này.
3. **Vì sao `COPY requirements.txt` trước:** Docker cache theo layer, layer nào thay đổi thì nó và mọi layer sau phải build lại. `requirements.txt` ít đổi, code đổi liên tục; copy requirements + `pip install` trước thì khi chỉ sửa code, layer cài dependencies vẫn dùng cache, build mất vài giây thay vì cài lại toàn bộ. Nếu `COPY . .` trước thì mỗi lần sửa code là `pip install` lại.
4. **CMD vs ENTRYPOINT:** `CMD` là lệnh/tham số mặc định, bị ghi đè khi `docker run image <lệnh khác>`. `ENTRYPOINT` là chương trình cố định của container, tham số của `docker run` được nối vào sau nó (muốn đổi phải dùng `--entrypoint`). Dùng chung: `ENTRYPOINT ["uvicorn"]` + `CMD ["app:app", "--port", "8000"]` để có lệnh cố định và tham số mặc định đổi được. Cả hai nên viết dạng exec (JSON array) để process là PID 1 và nhận được SIGTERM.

### Exercise 2.2: Build và chạy bản develop

```text
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run -d -p 8000:8000 my-agent:develop

$ curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"
HTTP/1.1 200 OK
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":5.1,"container":true}
```

### Exercise 2.3: Multi-stage build và kích thước image

- **Stage 1 (`builder`, `python:3.11-slim`):** cài công cụ build (`gcc`, `libpq-dev`) rồi `pip install --user` để mọi package nằm gọn trong `/root/.local`. Stage này không được deploy.
- **Stage 2 (`runtime`, `python:3.11-slim`):** base slim mới, chỉ `COPY --from=builder /root/.local` (package đã cài, 40,8 MB theo `docker history`) và source code; tạo user `appuser` non-root, có `HEALTHCHECK`.
- **Vì sao nhỏ hơn:** (1) base `slim` thay vì bản Python đầy đủ; (2) `gcc`, header, cache apt/pip chỉ có ở stage builder và bị bỏ lại, image cuối không chứa chúng (ít dung lượng và ít lỗ hổng bảo mật).

Kích thước đo được:

```text
$ docker images my-agent
REPOSITORY:TAG      SIZE
my-agent:advanced   240MB
my-agent:develop    1.67GB
```

- Develop: **1670 MB** (1.67 GB)
- Production: **240 MB**
- Chênh lệch: **giảm 85,6%** ((1670 − 240) / 1670)

`docker image inspect -f '{{.Size}}'` (Docker Desktop đếm dung lượng nén của layer) cho 426 320 304 byte và 57 409 048 byte, tức giảm 86,5%. Hai cách đo cho số tuyệt đối khác nhau nhưng tỉ lệ giảm gần như nhau.

### Exercise 2.4: Docker Compose stack

```text
                      ┌───────────────── network "internal" (bridge) ────────────────┐
 Client ──HTTP :80──▶ │  nginx (reverse proxy, rate limit 10r/s, security headers)    │
                      │     │ proxy_pass http://agent_backend                          │
                      │     ▼                                                          │
                      │  agent :8000 (FastAPI, không publish ra host)                  │
                      │     ├──▶ redis :6379   (session cache, rate limit)             │
                      │     └──▶ qdrant :6333  (vector DB cho RAG)                     │
                      └──────────────────────────────────────────────────────────────┘
```

- 4 service được start: `redis`, `qdrant` (có healthcheck), `agent` (chỉ start khi redis và qdrant `service_healthy`), `nginx`.
- Giao tiếp qua mạng bridge `internal` bằng tên service (Docker DNS): Nginx → `agent:8000`, agent → `redis://redis:6379/0`, `http://qdrant:6333`.
- Chỉ Nginx publish cổng ra host (80, 443). Agent, Redis, Qdrant không có port ra ngoài.

```text
$ docker compose -p k5-day14-docker up -d --build
$ docker compose -p k5-day14-docker ps
agent   Up 5 seconds (healthy)    8000/tcp
nginx   Up 5 seconds              0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
qdrant  Up 16 seconds (healthy)   6333-6334/tcp
redis   Up 16 seconds (healthy)   6379/tcp

$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":4.5,"version":"2.0.0","timestamp":"2026-11-25T10:12:02.883321"}

$ curl -i -X POST http://localhost/ask -H 'Content-Type: application/json' -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}

$ curl http://localhost:8000/health        # gọi thẳng agent từ host
→ không kết nối được (000): agent chỉ đi được qua Nginx
# trong container agent: kết nối redis:6379 → ok, qdrant:6333 → ok
```

---

## Part 3: Cloud Deployment

### Exercise 3.2 (nền tảng chính): Deploy agent Part 6 lên Render

- URL: **https://production-ai-agent-si7x.onrender.com**
- Nền tảng: Render Blueprint (`06-lab-complete/render.yaml`): web service Docker + Key Value (Redis), gói Free. Railway (Exercise 3.1) không dùng được vì tài khoản đã hết hạn dùng thử và đòi gói trả phí.
- Chi tiết, biến môi trường và ảnh chụp: [DEPLOYMENT.md](DEPLOYMENT.md), `screenshots/dashboard.png`, `running.png`, `test.png`.

4 lệnh tự kiểm của CP6:

```text
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
200
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
200
$ curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'
401
$ curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'
200
```

### Nền tảng còn lại: so sánh `railway.toml` và `render.yaml` (của `06-lab-complete/`)

| | `railway.toml` | `render.yaml` |
|---|---|---|
| Định dạng / vai trò | TOML, cấu hình **build + deploy của 1 service**; service, Redis và biến môi trường tạo bằng CLI/dashboard (`railway add`, `railway variables`) | YAML Blueprint, **Infrastructure as Code cho cả hệ thống**: khai báo web service *và* Redis (`type: keyvalue`) trong cùng file |
| Build | `builder = "DOCKERFILE"`, `dockerfilePath` | `runtime: docker`, `dockerfilePath`, thêm `rootDir: 06-lab-complete` vì Render đọc Blueprint từ gốc repo |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout` | `healthCheckPath: /health` |
| Restart | `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries` | Render tự quản lý, không khai báo |
| Secret | Không nằm trong file; đặt bằng `railway variables set AGENT_API_KEY=...` | Khai báo tên biến với `sync: false` (Render hỏi giá trị khi tạo Blueprint), không ghi giá trị |
| Nối Redis | `REDIS_URL` đặt bằng biến tham chiếu tới service Redis trên dashboard | `fromService: {type: keyvalue, name: agent-redis, property: connectionString}`: Render tự điền URL |
| Port | Không khai báo: Railway inject `PORT`, Dockerfile nghe `${PORT:-8000}` | Không khai báo: Render inject `PORT` |
| Plan | Theo project | `plan: free` khai báo trong file |

**Vì sao khác:** Railway thiên về CLI/dashboard, file config chỉ mô tả cách build và chạy một service. Render Blueprint mô tả toàn bộ hạ tầng (nhiều service, cách chúng nối nhau, secret nào cần nhập) để tạo lại cả hệ thống chỉ từ repo. Cả hai đều dựa vào cùng một Dockerfile và đều inject `PORT`, nên code không phải sửa khi đổi nền tảng.

### Exercise 3.3: Pipeline Cloud Run (`03-cloud-deployment/production-cloud-run/`)

Mỗi lần push, Cloud Build chạy `cloudbuild.yaml` gồm 4 bước tuần tự (`waitFor`): (1) **test**: cài requirements, chạy `pytest tests/`, test fail thì dừng pipeline; (2) **build**: build image gắn tag `$COMMIT_SHA` và `latest`, dùng `--cache-from` image `latest` để tận dụng layer cache; (3) **push**: đẩy cả hai tag lên Container Registry; (4) **deploy**: `gcloud run deploy` image theo đúng `$COMMIT_SHA` lên region `asia-southeast1`, 1–10 instance, 512 Mi/1 CPU, timeout 60 s, `ENVIRONMENT=production`, `OPENAI_API_KEY` lấy từ Secret Manager. `service.yaml` mô tả cùng service đó ở dạng khai báo (Knative): `minScale: 1` để tránh cold start, `maxScale: 10`, `containerConcurrency: 80`, secret qua `secretKeyRef`, `livenessProbe` gọi `/health` và `startupProbe` gọi `/ready`.

---

## Part 4: API Security

### Exercise 4.1: API key (`04-api-gateway/develop/app.py`, chạy với `AGENT_API_KEY=secret-key-123`)

- **Key được check ở đâu:** hàm dependency `verify_api_key` (dòng 39–54) đọc header `X-API-Key` qua `APIKeyHeader`, gắn vào `/ask` bằng `Depends(verify_api_key)` (dòng 70). Endpoint nào thêm dependency này thì được bảo vệ; `/` không có nên public.
- **Sai key:** thiếu key → **401**, key sai → **403** (`"Invalid API key."`). Ở Part 6, hợp đồng chấm yêu cầu cả hai trường hợp đều 401, nên `06-lab-complete/app/auth.py` trả 401 cho cả hai và so sánh bằng `hmac.compare_digest` (tránh timing attack).
- **Rotate key:** key đọc từ env `AGENT_API_KEY` (dòng 35), nên đổi biến môi trường trên platform rồi restart/redeploy, không sửa code. Muốn không downtime thì cho phép tạm thời 2 key (cũ và mới, vd `AGENT_API_KEYS=old,new`), chuyển client sang key mới rồi xoá key cũ.
- **Lưu ý:** bản này có giá trị mặc định `"demo-key-change-in-production"` khi không đặt env, tức là quên đặt biến thì vẫn chạy với key ai cũng biết. Part 6 làm ngược lại: không có key thì từ chối mọi request (fail closed).

```text
$ curl -i -X POST http://localhost:8000/ask -H 'Content-Type: application/json' -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i -X POST http://localhost:8000/ask -H 'X-API-Key: wrong-key' -H 'Content-Type: application/json' -d '{"question": "Hello"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

$ curl -i -X POST http://localhost:8000/ask -H 'X-API-Key: secret-key-123' -H 'Content-Type: application/json' -d '{"question": "Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

### Exercise 4.2: JWT (`04-api-gateway/production/`)

**Flow (`auth.py`):** `POST /auth/token` với username/password → `authenticate_user` kiểm tra → `create_token` ký payload `{sub, role, iat, exp = now + 60 phút}` bằng HS256 với `JWT_SECRET` → client gửi `Authorization: Bearer <token>` → `verify_token` kiểm chữ ký và hạn, lấy `username` và `role` từ payload mà không cần tra database. Thiếu token → 401, hết hạn → 401, token sai/giả → 403.

```text
$ curl -i -X POST http://localhost:8000/auth/token -H 'Content-Type: application/json' -d '{"username": "student", "password": "demo123"}'
HTTP/1.1 200 OK
{"access_token":"<đã che>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer eyJhbGciOiJIUzI1NiIs..."}

$ curl -i -X POST http://localhost:8000/ask -H 'Content-Type: application/json' -d '{"question": "Explain JWT"}'   # không có token
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer eyJhbGciOi...<đã che>" -H 'Content-Type: application/json' -d '{"question": "Explain JWT"}'
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}

$ curl -i -X POST http://localhost:8000/ask -H 'Authorization: Bearer not-a-real-token' ...
HTTP/1.1 403 Forbidden
{"detail":"Invalid token."}

$ curl -i -X POST http://localhost:8000/auth/token ... -d '{"username": "student", "password": "wrong"}'
HTTP/1.1 401 Unauthorized
{"detail":"Invalid credentials"}
```

Phát hiện: field `budget_remaining_usd` trong response thực ra là **số tiền đã tiêu** (`app.py` gán `usage.total_cost_usd`), không phải số còn lại; đúng ra phải là `daily_budget_usd - total_cost_usd`.

### Exercise 4.3: Rate limiting (`rate_limiter.py`)

- **Thuật toán:** sliding window. Mỗi user có một `deque` timestamp; mỗi request xoá các timestamp cũ hơn 60 giây rồi đếm số còn lại. Docstring gọi là "Sliding Window Counter", nhưng vì lưu từng timestamp nên chính xác hơn là *sliding window log*.
- **Giới hạn:** user thường 10 request/60 giây (`rate_limiter_user`), admin 100 request/60 giây (`rate_limiter_admin`).
- **Admin "bypass":** không bỏ hẳn giới hạn: `app.py` đọc `role` trong JWT, `admin` thì dùng limiter 100/phút. Muốn bỏ hẳn thì bỏ qua `limiter.check()` khi `role == "admin"`, nhưng vẫn nên có giới hạn cao để chặn token admin bị lộ.
- **Hạn chế:** state nằm trong RAM của process: chạy nhiều instance thì mỗi instance đếm riêng (giới hạn thật = 10 × số instance), restart là reset. Part 6 chuyển sang Redis sorted set (`ZREMRANGEBYSCORE` → `ZCARD` → `ZADD` + `EXPIRE`), nên mọi worker/instance dùng chung và state còn sau restart (script chấm xác nhận: restart vẫn 429).

Vòng lặp 20 request bằng token `student` (request 200 ở trên đã dùng 1 lượt trong cửa sổ):

```text
$ for i in {1..20}; do curl -s -o /dev/null -w "$i: %{http_code}\n" -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"question": "Test '$i'"}'; done
1: 200
2: 200
3: 200
4: 200
5: 200
6: 200
7: 200
8: 200
9: 200
10: 429
11: 429
...
20: 429

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer eyJhbGciOi...<đã che>" ...
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795601652
retry-after: 54

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":54}}
```

### Exercise 4.4: Cost guard

Cài đặt trong `06-lab-complete/app/cost_guard.py` (Part 6, dùng Redis):

1. **Hai mức budget, đọc từ env:** `DAILY_BUDGET_USD` và `MONTHLY_BUDGET_USD`. Key Redis theo thời gian UTC: `cost:daily:YYYY-MM-DD` và `cost:monthly:YYYY-MM`. Sang ngày/tháng mới thì key mới, nên **tự reset** mà không cần cron; `EXPIRE` 2 ngày / 32 ngày để Redis tự dọn key cũ.
2. **`check_budget()` gọi TRƯỚC khi gọi LLM:** `MGET` hai key; tổng đã tiêu ≥ budget ngày hoặc tháng → `HTTPException(402)`. Chặn trước nên không tốn thêm tiền cho request bị từ chối.
3. **`record_cost()` gọi SAU khi gọi LLM:** tính cost thật từ token (`input/1000 × $0.00015 + output/1000 × $0.0006`, giá gpt-4o-mini; mock không trả usage nên ước lượng ~4 ký tự/token), rồi `INCRBYFLOAT` vào cả hai key trong một pipeline `MULTI/EXEC`. `INCRBYFLOAT` là atomic, nên nhiều worker/instance cộng đồng thời vẫn không mất số.
4. **Vì sao Redis:** bản `04-api-gateway/production/cost_guard.py` lưu trong dict của process, nên restart là mất số đã tiêu, nhiều instance thì mỗi cái có budget riêng (budget thật = budget × số instance).

So với lời giải mẫu trong CODE_LAB (`check_budget(user_id, estimated_cost)` cộng ước lượng ngay khi kiểm tra):
- Mình ghi **chi phí thật sau khi gọi** thay vì ước lượng trước, nên request lỗi không bị tính tiền. Đổi lại, nhiều request song song cùng lúc có thể vượt budget một chút (tối đa bằng chi phí các request đang chạy).
- Budget là **toàn hệ thống** (bảo vệ hoá đơn LLM của cả agent), không theo từng user. Muốn theo user thì thêm `user_id` vào key: `cost:daily:{user_id}:{date}`.

Kiểm chứng: script chấm Part 6 với `DAILY_BUDGET_USD=0.000001` → `402` (`✅ Khi chạy: hết budget → 402`); tự test với fakeredis: `200, 402, 402`.

**Rate limit và cost guard bảo vệ hai thứ khác nhau:** rate limit chặn *tốc độ* (một client spam làm nghẽn service), cost guard chặn *tổng tiền* (nhiều client hợp lệ, mỗi client đều dưới rate limit, nhưng cộng lại vẫn đốt hết budget LLM). Cần cả hai.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health và readiness (`05-scaling-reliability/develop/app.py`)

- `/health` (liveness): luôn 200 khi process còn chạy, kèm uptime, version, kiểm tra RAM bằng `psutil` (`degraded` nếu > 90%).
- `/ready` (readiness): 503 khi `_is_ready = False` (đang khởi động hoặc đang shutdown), 200 khi sẵn sàng, kèm số request đang xử lý.
- **Khác nhau:** liveness fail → platform **restart** container; readiness fail → load balancer **ngừng gửi traffic** nhưng không restart (vd Redis tạm mất kết nối: restart không giải quyết được, chỉ cần chờ). Vì vậy Part 6 cho `/health` luôn 200 kể cả khi Redis chết, còn `/ready` trả 503.

Chạy trong container `python:3.11-slim`:

```text
$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":1.3,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T10:14:46.338632+00:00","checks":{"memory":{"status":"ok","used_percent":17.5}}}

$ curl -i http://localhost:8000/ready
HTTP/1.1 200 OK
{"ready":true,"in_flight_requests":1}
```
(`in_flight_requests: 1` chính là request `/ready` đang được đếm.)

### Exercise 5.2: Graceful shutdown

Chạy app trong container (Windows không gửi được SIGTERM), gửi `/ask` rồi `docker stop` (SIGTERM) ngay 50 ms sau:

```text
$ curl -X POST "http://localhost:8000/ask?question=Long%20task" &   # request đang chạy
$ docker stop k5-p5-dev                                          # gửi SIGTERM ngay sau đó
[docker stop xong sau 0.63s, exit code 0]
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
[request kết thúc] HTTP 200 sau 0.149688s

$ docker logs k5-p5-dev
INFO:     172.17.0.1:57408 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Shutting down
INFO:     Waiting for application shutdown.
2026-11-25 10:14:54,327 INFO 🔄 Graceful shutdown initiated...
2026-11-25 10:14:54,327 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [1]
2026-11-25 10:14:54,327 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

Request đang chạy vẫn trả **200**, process thoát **exit code 0** sau 0,63 s (không bị SIGKILL sau 10 s).

Trình tự: uvicorn nhận SIGTERM → ngừng nhận kết nối mới → chờ request đang chạy xong (tối đa `timeout_graceful_shutdown=30`) → chạy phần sau `yield` của `lifespan` (đặt `_is_ready=False`, chờ `_in_flight_requests` về 0) → thoát. Dòng `Received signal 15` từ handler tự viết lại in ra **cuối cùng**: uvicorn 0.30 tạm giữ handler SIGTERM của nó trong lúc chạy và gọi lại handler cũ sau khi tắt xong. Vì vậy handler tự viết **không** nên tự `sys.exit()` hay chặn signal, nếu không sẽ phá quy trình tắt của uvicorn. Part 6 chỉ dùng `lifespan` để dọn dẹp (đóng Redis), và script chấm xác nhận `docker stop` → exit code 0 trong 0,7 s.

### Exercise 5.3: Stateless design

Bản `05-scaling-reliability/production/app.py` lưu session/history trong Redis: `save_session` dùng `SETEX session:{id}` (TTL 1 giờ), `load_session` dùng `GET`, `append_to_history` giữ 20 message gần nhất. Mỗi response trả `served_by` (ID instance) để thấy request nào đi qua instance nào.

**Vì sao:** khi chạy nhiều instance sau load balancer, request liên tiếp của cùng một user có thể vào instance khác nhau. Nếu history nằm trong dict của process thì instance B không thấy những gì user đã nói với instance A, và mọi thứ mất khi restart/redeploy. Đưa state ra Redis thì instance nào cũng đọc được, instance có thể tắt/thêm bất cứ lúc nào.

Lưu ý: code có nhánh dự phòng `_memory_store` khi không kết nối được Redis. Như vậy nếu Redis chết thì app **âm thầm** quay lại lưu trong RAM, đúng anti-pattern cần tránh. Production nên trả 503 (như `/ready` của Part 6) thay vì fallback.

### Exercise 5.4: Load balancing

```text
$ docker compose -p k5-day14-scaling up -d --build --scale agent=3
k5-day14-scaling-agent-1   Up 8 seconds (healthy)
k5-day14-scaling-agent-2   Up 8 seconds (healthy)
k5-day14-scaling-agent-3   Up 8 seconds (healthy)
k5-day14-scaling-nginx-1   Up 8 seconds
k5-day14-scaling-redis-1   Up 19 seconds (healthy)

$ for i in {1..10}; do curl -s -X POST http://localhost:8080/chat -H 'Content-Type: application/json' -d '{"question": "Request '$i'"}' | python -c 'import json,sys;print(json.load(sys.stdin)["served_by"])'; done | sort | uniq -c
      3 instance-2c6f74
      4 instance-5e4068
      3 instance-fef1a4
```

Nginx (`upstream agent_cluster { server agent:8000; }`, `resolver 127.0.0.11`) phân tán request round-robin qua 3 container.

### Exercise 5.5: Test stateless

```text
$ python test_stateless.py
Session ID: dd6b9493-1046-4ef3-af12-a9d4ba99f304

Request 1: [instance-2c6f74]   Q: What is Docker?
Request 2: [instance-fef1a4]   Q: Why do we need containers?
Request 3: [instance-5e4068]   Q: What is Kubernetes?
Request 4: [instance-2c6f74]   Q: How does load balancing work?
Request 5: [instance-fef1a4]   Q: What is Redis used for?
------------------------------------------------------------
Total requests: 5
Instances used: {'instance-fef1a4', 'instance-5e4068', 'instance-2c6f74'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  ...
  [user]: What is Redis used for?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...

✅ Session history preserved across all instances via Redis!
```

**Giải thích:** 5 câu của cùng một session đi qua cả 3 instance, nhưng history vẫn đủ 10 message (5 user + 5 assistant) đúng thứ tự, vì mỗi instance đọc và ghi session từ cùng một Redis, không instance nào giữ state riêng.

`test_stateless.py` không tắt instance nào, nên mình làm thêm bước "kill instance" trong CODE_LAB: mở session, `docker stop` một instance, gửi tiếp 6 request cùng session:

```text
session: d8cfe531-d223-4914-a74c-c45710966293
$ docker stop k5-day14-scaling-agent-1
$ 6 request tiếp theo cùng session:
HTTP200 instance-fef1a4
HTTP200 instance-5e4068
HTTP200 instance-fef1a4
HTTP200 instance-fef1a4
HTTP200 instance-5e4068
HTTP200 instance-fef1a4
$ history:
count 14 ['turn 1 before kill', 'turn 2 after kill', ..., 'turn 7 after kill']
```

Không request nào lỗi (Nginx có `proxy_next_upstream error timeout http_503`, nên request trúng instance đã tắt được thử lại ở instance khác) và history giữ đủ 7 lượt (14 message), kể cả lượt trả lời bởi instance đã bị tắt.

---

## Part 6: Final Project — output `check_production_ready.py`

```text
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

_Chạy đầy đủ (có Docker) trong WSL2 Ubuntu, Python 3.12 trong venv, `python check_production_ready.py` từ thư mục `06-lab-complete/`._

---

## AI log

| # | Hỏi / nhờ AI làm gì | Nhận được gì | Tự sửa và kiểm tra thế nào |
|---|---|---|---|
| 1 | Dùng Claude Code (Claude Opus) đọc `check_production_ready.py` và README Part 6, rồi viết các file TODO của `06-lab-complete/` (`app/*.py`, Dockerfile, compose, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`) | Code hoàn chỉnh cho 12 tiêu chí | Chạy `check_production_ready.py` bản tĩnh (28/28) và đầy đủ có Docker (42/42 checks, 11/12 tiêu chí; còn SIGTERM cần WSL) |
| 2 | Nhờ AI tìm nguyên nhân khi script chấm báo hàng loạt 503 | AI xác định Docker Hub trả `429 Too Many Requests` khi pull `redis`/`python`, agent trả 503 vì không có Redis (đúng thiết kế); test logic bằng fakeredis trong lúc chờ | Pull lại sau khi hết giới hạn, chạy lại bản đầy đủ |
| 3 | Nhờ AI chạy Part 7 Bước 1 (load test 4 mức concurrency, 3 mức `MOCK_SLOW_RATE`, eval v1/v2) và sửa `KNOWLEDGE_BASE` cho 2 câu sai | File JSON trong `reports/`, entry KB mới cho JWT và Kubernetes HPA, job CI `.github/workflows/eval-quality-gate.yml` | Eval cuối 23/23, quality gate PASS, 0 regression; grep golden dataset để chắc từ khoá mới không ảnh hưởng câu khác; mọi số trong báo cáo lấy thẳng từ JSON |
| 4 | Nhờ AI chạy Part 7 Bước 2 (stack observability, Locust, thí nghiệm alert A–E, tìm trace) | AI sửa lỗi Dockerfile của stack (`PYTHONUSERBASE`), phát hiện lệnh `docker compose run` ghi đè `--scale` nên chạy lại benchmark với `--no-deps`, đo thời gian tới lúc alert firing | Kiểm số instance thật bằng Prometheus trong lúc chạy; ảnh Grafana/Jaeger/Prometheus tự chụp |
| 5 | Nhờ AI chạy các ví dụ Part 1, 2, 4, 5 và soạn file này | Output thật của các lệnh, câu trả lời nháp | Đọc lại từng câu trả lời, đối chiếu với code (số dòng, tên hàm) và output đã chạy |
