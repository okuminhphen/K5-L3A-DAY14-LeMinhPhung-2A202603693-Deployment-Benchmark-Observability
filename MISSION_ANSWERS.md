# Day 14 Lab — Mission Answers

> Tài liệu tổng hợp câu trả lời và kết quả chạy kiểm tra thực tế cho **Part 1, Part 2, Part 4, Part 5** (cùng phần đọc hiểu của **Part 3**).  
> Các mục cần deploy URL public (CP6) và output `check_production_ready.py` (CP5) sẽ được bổ sung sau khi hoàn thành Part 6.

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns phát hiện trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secrets trong mã nguồn (`L17-L18`):** `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"` ghi thẳng trong code; push lên Git sẽ lộ secret ngay lập tức.
2. **Hardcode cấu hình (`L21-L22`):** `DEBUG = True`, `MAX_TOKENS = 500` viết cứng, không đổi được theo từng môi trường (dev/staging/production) qua biến môi trường.
3. **Dùng `print()` và log lộ API key (`L33-L38`):** In thẳng `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this` ra console; log không có cấu trúc JSON nên khó lọc/truy vấn trên hệ thống log tập trung và làm rò rỉ secret.
4. **Thiếu endpoint kiểm tra sức khỏe `/health` và `/ready` (`L42`):** Platform (Docker, Railway, Render, Kubernetes) không biết app còn sống hay đã sẵn sàng nhận traffic để restart hoặc điều hướng tải.
5. **Bind `host="localhost"` và cố định `port=8000` (`L51-L52`):** Nghe trên `127.0.0.1` khiến container không nhận được kết nối từ bên ngoài (host, Nginx, load balancer); không đọc biến `PORT` do cloud platform cấp.
6. **Bật `reload=True` và không xử lý graceful shutdown (`L53`):** `reload=True` gây tốn tài nguyên và không an toàn trong production; thiếu `lifespan` / xử lý `SIGTERM` khiến container tắt đột ngột, dễ cắt ngang request đang xử lý.

### Exercise 1.2: Kết quả chạy bản develop

Chạy `python app.py` trong `01-localhost-vs-production/develop/` và gọi qua query param (`?question=Hello`):

```text
POST http://localhost:8000/ask?question=Hello
HTTP Status: 200
Response: {"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

Console log phía server in ra dòng lộ secret:
```text
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.
```

### Exercise 1.3: So sánh `develop/app.py` vs `production/app.py`

| Feature | Develop (`develop/app.py`) | Production (`production/app.py` & `config.py`) | Tại sao quan trọng? |
|---|---|---|---|
| **Config & Secrets** | Hardcode `OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG`, `MAX_TOKENS` (`L17-L22`) | Lớp `Settings` đọc toàn bộ từ `os.getenv(...)` và `validate()` fail-fast nếu `ENVIRONMENT=production` mà thiếu `AGENT_API_KEY` (`config.py L14-L50`) | Không làm lộ secret trong Git; đổi cấu hình giữa dev/staging/prod không cần sửa code |
| **Health check** | Không có `/health`, `/ready` | Có `GET /health` (liveness: trả `status`, `uptime_seconds`, `version`, `timestamp`, `L135-L149`) và `GET /ready` (readiness: kiểm tra `is_ready`, trả `503` nếu chưa sẵn sàng, `L152-L161`) | Platform biết khi nào cần restart container và khi nào có thể route traffic vào |
| **Logging** | `print(...)` tự do, in cả `OPENAI_API_KEY` (`L33-L38`) | Structured JSON logging qua `logging.basicConfig(format='{"time":...}')` + `json.dumps(...)`, chỉ log `question_length`, `client_ip` (`L28-L31`, `L111-L122`) | Dễ parse/tìm kiếm trên Loki/Datadog, không làm rò rỉ thông tin nhạy cảm |
| **Network binding** | `host="localhost"`, `port=8000`, `reload=True` (`L49-L54`) | `host=settings.host` (`0.0.0.0`), `port=settings.port` (từ env `PORT`), `reload=settings.debug` (`L194-L199`) | `0.0.0.0` cho phép Docker port mapping, Nginx và cloud LB gửi traffic vào container |
| **Shutdown** | Tắt đột ngột | `lifespan` chuyển `is_ready = False` khi shutdown và chờ hoàn tất request, kèm `signal.signal(signal.SIGTERM, handle_sigterm)` (`L39-L68`, `L180-L189`) | Tránh rớt request đang xử lý dở (lỗi 502) khi deploy/restart container |

Kết quả test bản `01-localhost-vs-production/production/`:
- `GET /health` → `200` `{"status":"ok","uptime_seconds":4.1,"version":"1.0.0","environment":"development",...}`
- `POST /ask` với JSON `{"question":"Hello"}` → `200` `{"question":"Hello","answer":"...","model":"gpt-4o-mini"}`

---

## Part 2: Docker

### Exercise 2.1: Phân tích `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11` (bản đầy đủ gồm OS Debian + toolchain + Python, dung lượng lớn ~1 GB).
2. **Working directory:** `/app` (`WORKDIR /app`).
3. **Tại sao `COPY 02-docker/develop/requirements.txt .` đứng trước `COPY 02-docker/develop/app.py .`?**  
   Để tận dụng **Docker layer cache**. `requirements.txt` ít thay đổi hơn code trong `app.py`; khi chỉ sửa code `app.py`, Docker tái sử dụng layer `RUN pip install` đã cache thay vì tải và cài lại toàn bộ thư viện.
4. **`CMD` vs `ENTRYPOINT` khác nhau thế nào?**  
   - `CMD` định nghĩa lệnh/tham số mặc định khi container chạy và **dễ bị ghi đè** khi truyền lệnh ở cuối `docker run <image> <command>`.
   - `ENTRYPOINT` cố định chương trình thực thi chính của container; tham số truyền thêm ở `docker run` (hoặc `CMD`) sẽ được nối làm đối số cho `ENTRYPOINT`.

### Exercise 2.2: Build và chạy container `my-agent:develop`

Build từ thư mục gốc repo:
```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -d --rm --name test-p2-dev -p 8010:8000 my-agent:develop
```

Kết quả gọi container:
```text
GET http://127.0.0.1:8010/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":2.6,"container":true}

POST http://127.0.0.1:8010/ask?question=What%20is%20Docker%3F
HTTP/1.1 200 OK
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

### Exercise 2.3: So sánh Multi-stage Build (`my-agent:develop` vs `my-agent:advanced`)

- **Stage 1 (`builder`):** dùng `python:3.11-slim`, cài `gcc` và `libpq-dev` để biên dịch các package nếu cần, rồi chạy `pip install --no-cache-dir --user -r requirements.txt` vào `/root/.local`.
- **Stage 2 (`runtime`):** dùng `python:3.11-slim` sạch, tạo user non-root `appuser`, chỉ copy `/root/.local` từ `builder` sang `/home/appuser/.local`, copy code (`main.py`, `utils/mock_llm.py`), thêm `HEALTHCHECK` và chạy `uvicorn` bằng `appuser`.
- **Tại sao image nhỏ hơn?** Loại bỏ hoàn toàn `gcc`, `libpq-dev`, header/cache biên dịch của stage `builder` và dùng base `python:3.11-slim` thay cho `python:3.11` đầy đủ.

Số đo thực tế bằng `docker images my-agent` và `docker image inspect`:
- **Develop (`my-agent:develop`):** `1.15GB` (`1,154,311,927` bytes ≈ `1,100.84 MiB` / `1,154.3 MB`)
- **Production (`my-agent:advanced`):** `163MB` (`162,882,434` bytes ≈ `155.34 MiB` / `162.9 MB`)
- **Chênh lệch (giảm):** **`85.89%`** (nhỏ hơn ~7.1 lần, đạt chuẩn `< 500 MB`).

### Exercise 2.4: Docker Compose stack (`02-docker/production/`)

Sơ đồ kiến trúc các service trên network `internal` (driver `bridge`):
```text
Client ──► nginx (:80 / :443) ──► agent (:8000, uvicorn 2 workers)
                                       ├──► redis (:6379, session/rate limit, volume redis_data)
                                       └──► qdrant (:6333, vector DB, volume qdrant_data)
```

Cách giao tiếp:
- Chỉ `nginx` mở port ra ngoài (`80:80`, `443:443`) và áp dụng security headers + rate limit (`10r/s`), proxy request sang `agent:8000`.
- `agent` không mở port trực tiếp ra host; `depends_on` đợi `redis` và `qdrant` ở trạng thái `service_healthy` trước khi khởi động, và giao tiếp qua Docker DNS (`redis://redis:6379/0`, `http://qdrant:6333`).

Kết quả chạy `docker compose -p k5-day14-docker up -d --build` và test qua Nginx:
```text
GET http://127.0.0.1/health
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block
{"status":"ok","uptime_seconds":1.1,"version":"2.0.0","timestamp":"2026-11-25T11:32:19.618686"}

POST http://127.0.0.1/ask   (body: {"question":"Explain microservices"})
HTTP/1.1 200 OK
Server: nginx
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy Agent Part 6 (CP6)

- **Nền tảng chính:** *(Sẽ điền URL public, lệnh test 4 mã HTTP và link ảnh `screenshots/` sau khi hoàn thành Part 6 và CP6).*

### So sánh `railway.toml` vs `render.yaml`

| Tiêu chí | `03-cloud-deployment/railway/railway.toml` | `03-cloud-deployment/render/render.yaml` |
|---|---|---|
| **Định dạng & phạm vi** | TOML; cấu hình **1 service** riêng lẻ | YAML (Blueprint / IaC); khai báo **nhiều service** cùng lúc (cả `type: web` và `type: redis`) |
| **Build & Start** | `[build] builder = "NIXPACKS"` (hoặc `DOCKERFILE`), `[deploy] startCommand = "uvicorn ... --port $PORT"` | `runtime: python` (hoặc `docker`), khai báo `buildCommand`, `startCommand`, `region`, `plan` |
| **Health check & Restart** | `healthcheckPath = "/health"`, `healthcheckTimeout = 30`, `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries = 3` | `healthCheckPath: /health`, `autoDeploy: true` |
| **Biến môi trường & Secret** | Không khai báo trong `railway.toml`; đặt riêng trên Railway Dashboard hoặc `railway variables set` | Khai báo ngay trong `envVars:` của YAML, dùng `sync: false` (nhập trên dashboard) hoặc `generateValue: true` (tự sinh random) để không lộ secret trong Git |

**Tại sao khác nhau?** Railway hướng tới trải nghiệm nhanh theo từng service (dùng Dashboard/CLI để gắn thêm Redis và env vars), trong khi Render Blueprint (`render.yaml`) đi theo hướng Infrastructure-as-Code đầy đủ để dựng lại toàn bộ web service + Redis + env config chỉ từ một file YAML trong Git.

### Exercise 3.3: GCP Cloud Run CI/CD (`cloudbuild.yaml` & `service.yaml`)

Pipeline trong `03-cloud-deployment/production-cloud-run/cloudbuild.yaml` tự động chạy 4 bước tuần tự (`waitFor`) khi có commit lên `main`:
1. **`test`:** dùng container `python:3.11-slim`, cài `requirements.txt` + `pytest` và chạy `pytest tests/ -v --tb=short`.
2. **`build`:** build Docker image gắn 2 tag (`gcr.io/$PROJECT_ID/ai-agent:$COMMIT_SHA` và `:latest`, tận dụng `--cache-from`).
3. **`push`:** đẩy cả 2 tag lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **`deploy`:** chạy `gcloud run deploy ai-agent` lên region `asia-southeast1` với `--min-instances=1` (tránh cold start), `--max-instances=10`, `512Mi` RAM, `1` CPU, lấy secrets từ Secret Manager (`--set-secrets`) và đối chiếu cấu hình Knative trong `service.yaml` (`containerConcurrency: 80`, `livenessProbe` `/health`, `startupProbe` `/ready`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/app.py`)

- API key được kiểm tra trong dependency `verify_api_key` dùng `APIKeyHeader(name="X-API-Key", auto_error=False)` (`L36-L54`), inject vào `POST /ask` qua `Depends(verify_api_key)`.
- Nếu thiếu key → trả `401`; nếu sai key (khác `AGENT_API_KEY`) → bản develop trả `403` (sang Part 6 thống nhất trả `401` cho cả thiếu và sai).
- **Cách rotate key:** không hardcode key trong code, đọc từ biến môi trường `AGENT_API_KEY`; khi rotate không downtime có thể hỗ trợ tạm thời 2 key hợp lệ (key cũ + key mới, ví dụ `AGENT_API_KEYS=new,old`), cập nhật client sang key mới rồi gỡ key cũ khỏi env.

Output `curl -i` thực tế:
```text
=== Không có X-API-Key ===
HTTP/1.1 401 Unauthorized
content-type: application/json
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

=== Có X-API-Key: secret-key-123 ===
HTTP/1.1 200 OK
content-type: application/json
{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

### Exercise 4.2 & 4.3: JWT Authentication & Rate Limiting (`04-api-gateway/production/`)

Trả lời câu hỏi đọc `rate_limiter.py`:
- **Thuật toán:** Sliding Window (`deque` lưu timestamp của từng request trong cửa sổ `window_seconds = 60`, tự động `popleft()` các mốc `< now - 60`).
- **Giới hạn:** `10 requests / 60 giây` cho user thường (`student`, `rate_limiter_user`); `100 requests / 60 giây` cho admin (`teacher`, `rate_limiter_admin`).
- **Xử lý tier/bypass cho admin:** trong `app.py` (`L141`), dựa vào `user["role"]` giải mã từ JWT để chọn `rate_limiter_admin` nếu `role == "admin"` (hoặc bỏ qua check limiter nếu muốn bypass hoàn toàn cho admin).

Output `curl -i` thực tế (token đã được che):
```text
=== POST /auth/token (student / demo123) ===
Token received, expires_in_minutes=60, token=<REDACTED_TOKEN>

=== POST /ask không gửi Authorization header ===
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
content-type: application/json
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

=== Vòng lặp 12 requests với Bearer <REDACTED_TOKEN> ===
--- Request 1 ---
HTTP/1.1 200 OK
content-type: application/json
{"question":"Test 1","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}

... (Requests 2..9 đều trả HTTP/1.1 200 OK, requests_remaining giảm từ 8 xuống 1) ...

--- Request 10 ---
HTTP/1.1 200 OK
content-type: application/json
{"question":"Test 10","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":0,"budget_remaining_usd":0.000188}}

--- Request 11 ---
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795606327
retry-after: 59
content-type: application/json
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}

Request 12: HTTP/1.1 429 Too Many Requests | {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Cách làm Cost Guard (`04-api-gateway/production/cost_guard.py`)

- **Tại sao cần cả Rate Limit và Cost Guard:** Rate Limit giới hạn *tần suất* (số request/phút) để chống spam/DDoS, còn Cost Guard giới hạn *tổng chi phí tiền thật* (USD/ngày) dựa trên số token tiêu thụ — ngăn trường hợp user gọi chậm (không chạm 429) nhưng gửi prompt rất dài làm tốn ngân sách LLM.
- **Cách triển khai:**
  1. **Trước khi gọi LLM (`check_budget`):** kiểm tra tổng chi phí hệ thống (`>= $10/ngày` → `503`) và chi phí của user (`>= $1/ngày` → `402 Payment Required`). Nếu đạt ngưỡng `80%` thì ghi log warning.
  2. **Sau khi gọi LLM (`record_usage`):** tính tiền theo đơn giá token (`$0.00015 / 1K input tokens`, `$0.0006 / 1K output tokens`) rồi cộng dồn vào bộ đếm theo ngày.
  3. **Khi chuyển sang Production / Part 6:** thay dict in-memory bằng **Redis** (`INCRBYFLOAT` + `EXPIRE`) để nhiều worker/container dùng chung bộ đếm và không mất khi restart.

---

## Part 5: Scaling & Reliability

### Exercise 5.1 & 5.2: Health Check, Readiness & Graceful Shutdown (`05-scaling-reliability/develop/app.py`)

- **`GET /health` (Liveness probe):** kiểm tra tiến trình còn sống không (nếu fail → platform restart container). Khi test trả về `200 OK`:
  ```json
  {"status":"degraded","uptime_seconds":1.1,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T11:31:18.501087+00:00","checks":{"memory":{"status":"degraded","used_percent":97.1}}}
  ```
- **`GET /ready` (Readiness probe):** kiểm tra app đã sẵn sàng nhận traffic chưa (trả `503` khi đang khởi động, đang shutdown, hoặc mất kết nối dependency như Redis). Khi test trả về `200 OK`:
  ```json
  {"ready":true,"in_flight_requests":1}
  ```
- **Graceful Shutdown:** Khi nhận `SIGTERM`, `lifespan` chuyển `_is_ready = False` để load balancer ngừng gửi request mới, middleware `track_requests` theo dõi `_in_flight_requests` để chờ toàn bộ request đang xử lý chạy xong (tối đa `timeout_graceful_shutdown=30`), sau đó mới thoát sạch với exit code `0`.

### Exercise 5.3–5.5: Stateless Design với Redis & Nginx (`05-scaling-reliability/production/`)

- **Tại sao state trong RAM bị hỏng khi scale:** Khi chạy 3 instance, request 1 của user vào `agent-1` sẽ lưu session vào RAM của `agent-1`; request 2 bị Nginx chia sang `agent-2` sẽ không thấy session đó.
- **Giải pháp:** Lưu toàn bộ session (`session:{session_id}`, TTL `3600s`, tối đa `20` messages) vào **1 Redis chung**, phía trước đặt Nginx round-robin phân tải trên cổng `8080`.

Kết quả chạy `docker compose -p k5-day14-scaling up -d --build --scale agent=3` (`3` agent healthy + `redis` + `nginx`) và `python test_stateless.py`:

```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: f67f0cf5-1f72-4ff6-9d67-99709efc5a2c

Request 1: [instance-c5ff4c]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-3e588a]
  Q: Why do we need containers?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

Request 3: [instance-c5ff4c]
  Q: What is Kubernetes?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

Request 4: [instance-44e4d8]
  Q: How does load balancing work?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

Request 5: [instance-3e588a]
  Q: What is Redis used for?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-3e588a', 'instance-44e4d8', 'instance-c5ff4c'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...
  [user]: What is Kubernetes?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...
  [user]: How does load balancing work?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...
  [user]: What is Redis used for?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...

✅ Session history preserved across all instances via Redis!
```

**Giải thích kết quả:** 5 request trong cùng 1 `session_id` được Nginx điều phối sang cả 3 container khác nhau (`instance-c5ff4c`, `instance-3e588a`, `instance-44e4d8`), nhưng cuối phiên gọi `GET /chat/{session_id}/history` vẫn còn nguyên vẹn `10` tin nhắn (5 lượt hỏi/đáp) do toàn bộ state nằm trong Redis.

---

## Part 6: Output `check_production_ready.py`

Chạy kiểm tra đầy đủ trong `06-lab-complete/` (môi trường Linux/POSIX + Docker 28.0.1 + Redis):

```text
================================================================
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

- Kích thước Docker image thực tế: **`201 MB`** (`< 500 MB`).
- `docker stop`: **`exit code 0, 1.6s`** (`< 10s`).
- `SIGTERM` lúc đang có request: **`exit code 0`**, request đang chạy vẫn trả `200`.

---

## AI log

1. **Part 1–5 (Giải thích khái niệm & đối chiếu code):**
   - **Hỏi AI:** Giải thích các khái niệm query param vs JSON body, lộ secret qua `print()`, `host="0.0.0.0"` vs `localhost` kèm ví dụ IP/port, cơ chế `lifespan` + `SIGTERM`, thuật toán Sliding Window trong `rate_limiter.py`, vị trí Rate Limiting & Cost Guard trong luồng xử lý request, và kiến trúc stateless + `/health` vs `/ready` trong Part 5.
   - **Nhận được:** Giải thích chi tiết gắn với số dòng cụ thể trong `01-localhost-vs-production/`, `03-cloud-deployment/`, `04-api-gateway/`, `05-scaling-reliability/`.
   - **Tự kiểm tra:** Đã chạy trực tiếp từng app và Docker Compose stack trên máy (`01-localhost-vs-production`, `docker build` đo kích thước `1.15GB` vs `163MB`, `04-api-gateway` thu thập `401/200/429`, `05-scaling-reliability` `--scale agent=3` + `test_stateless.py`), đối chiếu toàn bộ số liệu và output thực tế trước khi ghi vào `MISSION_ANSWERS.md`.
2. **Part 6 (`06-lab-complete/` — Final Project):**
   - **Hỏi AI:** Hướng dẫn chi tiết cách `check_production_ready.py` kiểm tra 12 tiêu chí (tĩnh, runtime, Docker), vị trí `.dockerignore` và cơ chế inject `.env` lúc chạy container, cùng triển khai các TODO trong `06-lab-complete/app/`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`.
   - **Nhận được:** Mã nguồn đầy đủ cho 6 module trong `06-lab-complete/app/` (FastAPI, `APIKeyHeader` 401, Redis Sorted Set sliding window rate limiter, Redis `INCRBYFLOAT` daily cost guard 402, JSON logger, `lifespan` + `SIGTERM` chaining) và cấu hình multi-stage Docker / Compose / deploy.
   - **Tự kiểm tra:** Đã chạy `check_production_ready.py` trên Windows (`42/42 checks passed`, `11/12` + `⚠️` do Windows không gửi `SIGTERM`) và chạy đầy đủ trong container Linux (`posix`) với Docker 28.0.1 + Redis, đạt **`PASS 12/12` (43/43 checks passed)**; giữ nguyên không sửa `check_production_ready.py`.
