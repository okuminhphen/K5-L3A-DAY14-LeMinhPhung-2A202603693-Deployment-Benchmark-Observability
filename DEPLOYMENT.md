# Deployment Information

## Public URL
https://k5-l3a-day14-leminhphung-2a202603693.onrender.com

## Platform
Render (Web Service — Docker, Root Directory `06-lab-complete`, kèm Render Key Value / Redis)

## Test Commands

### 1. Health Check (`/health` → 200)
```bash
curl -sS -i https://k5-l3a-day14-leminhphung-2a202603693.onrender.com/health
# Expected: HTTP 200 {"status":"ok"}
```

### 2. Readiness Check (`/ready` → 200)
```bash
curl -sS -i https://k5-l3a-day14-leminhphung-2a202603693.onrender.com/ready
# Expected: HTTP 200 {"status":"ready"}
```

### 3. Auth Check (`/ask` không có API key → 401)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST https://k5-l3a-day14-leminhphung-2a202603693.onrender.com/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
# Expected: 401
```

### 4. API Test (có `X-API-Key` → 200)
```bash
curl -sS -X POST https://k5-l3a-day14-leminhphung-2a202603693.onrender.com/ask \
  -H "X-API-Key: YOUR_AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
# Expected: HTTP 200 {"question":"Hello","answer":"...","user_id":"test"}
```

## Environment Variables Set (trên Render Dashboard)
- `ENVIRONMENT=production`
- `AGENT_API_KEY` *(secret, đặt trên Render Dashboard, không lưu trong Git)*
- `REDIS_URL` *(trỏ tới Render Key Value / Redis)*
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`
- `PORT` *(Render tự inject)*

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
