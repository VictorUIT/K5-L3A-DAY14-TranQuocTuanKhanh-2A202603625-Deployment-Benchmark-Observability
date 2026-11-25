# Deployment Information

## Public URL

https://production-ai-agent-si7x.onrender.com

## Platform

**Render** (Blueprint, gói Free), deploy agent Part 6 trong `06-lab-complete/`.

Railway là lựa chọn đầu tiên nhưng tài khoản Railway đã hết hạn dùng thử và đòi gói trả phí, nên chuyển sang Render. Rubric chấm Railway hoặc Render như nhau.

| Tài nguyên | Loại | Gói | Ghi chú |
|---|---|---|---|
| `production-ai-agent` | Web service, runtime Docker | Free | Build từ `06-lab-complete/Dockerfile` (multi-stage, user non-root), health check `/health` |
| `agent-redis` | Key Value (Redis) | Free | Chỉ nhận kết nối trong mạng nội bộ Render (`ipAllowList: []`); dùng cho rate limit và cost guard |

Cách tạo: Render Dashboard → New → Blueprint → repo này, branch `main`, **Blueprint Path** `06-lab-complete/render.yaml` → nhập `AGENT_API_KEY` → Deploy Blueprint.

Gói Free tự ngủ sau ~15 phút không có request; request đầu tiên sau đó mất khoảng 30–60 giây để khởi động lại.

## Test Commands

Đặt `BASE` là URL public, `AGENT_API_KEY` là key đã nhập trên Render (không ghi trong repo). Mỗi lệnh chỉ in mã HTTP.

```bash
BASE=https://production-ai-agent-si7x.onrender.com

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả đã chạy (2026-11-25):

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

### Health Check

```bash
curl https://production-ai-agent-si7x.onrender.com/health
# {"status":"ok"}

curl https://production-ai-agent-si7x.onrender.com/ready
# {"status":"ready","redis":"ok"}
```

### API Test (with authentication)

```bash
curl -X POST https://production-ai-agent-si7x.onrender.com/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "What is deployment?"}'
# {"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được."}
```

### Rate limit trên cloud

11 request liên tiếp (2 request trước đó đã nằm trong cửa sổ 60 giây):

```text
200 200 200 200 200 200 200 200 429 429 429
HTTP/1.1 429 Too Many Requests
retry-after: 42
{"detail":"Rate limit exceeded: 10 requests per 60s"}
```

### Script chấm

```text
$ python check_production_ready.py --static-only --public-url https://production-ai-agent-si7x.onrender.com
✅ 12. Public URL ready (Railway / Render config)
     ✅ Public URL: GET https://production-ai-agent-si7x.onrender.com/health → 200
```

## Environment Variables Set

| Biến | Giá trị | Đặt ở đâu |
|---|---|---|
| `PORT` | Render tự cấp | Platform inject; Dockerfile nghe `${PORT:-8000}` |
| `AGENT_API_KEY` | _(secret, không ghi ở đây)_ | Nhập trên Render Dashboard lúc tạo Blueprint (`sync: false` trong `render.yaml`) |
| `REDIS_URL` | Connection string nội bộ của `agent-redis` | Render tự điền qua `fromService` (`property: connectionString`) |
| `ENVIRONMENT` | `production` | `render.yaml` (tắt `/docs` ở production) |
| `RATE_LIMIT_PER_MINUTE` | `10` | `render.yaml` |
| `DAILY_BUDGET_USD` | `1.0` | `render.yaml` |
| `MONTHLY_BUDGET_USD` | `10.0` | `render.yaml` |
| `LOG_LEVEL` | `INFO` (mặc định trong code) | Không đặt |

Không có secret nào nằm trong code hay trong Git: `AGENT_API_KEY` chỉ tồn tại trên Render, `REDIS_URL` do Render sinh ra.

## Screenshots

- [Render dashboard](screenshots/dashboard.png)
- [Service đang chạy](screenshots/running.png)
- [Kết quả test](screenshots/test.png)
