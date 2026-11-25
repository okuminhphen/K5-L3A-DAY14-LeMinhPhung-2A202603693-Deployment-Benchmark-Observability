# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây được lấy trực tiếp từ các file report JSON trong `reports/`, CSV trong `benchmark-results/` và output thực tế của Prometheus/Docker logs.

**Họ tên:** Le Minh Phung (MSSV: 2A202603693)  
**Ngày chạy:** 2026-11-25  
**Môi trường:** Windows 11, Python 3.12.2, Docker Desktop 28.0.1

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | `< 500 ms` | Mock LLM có base latency 120–180ms + retrieval ~20ms; ngưỡng 500ms đảm bảo ≥ 95% người dùng nhận phản hồi nhanh, chỉ các request tail (~3%) vượt ngưỡng |
| Error rate `/ask` | `< 2.0 %` | Mock LLM có tỉ lệ lỗi upstream ~1%; ngưỡng 2% cho phép dung sai nhiễu nhỏ trước khi coi là vi phạm SLO |
| Accuracy trên golden dataset | `≥ 80 %` | Đảm bảo chất lượng trả lời trước khi merge/deploy (riêng sau khi vá KB đặt gate `100%`) |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

*(Nguồn: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`, mỗi mức 300 requests)*

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.11 | 201.2 | 234.1 | 1722.9 | 1.00% | PASS |
| 10 | 38.33 | 194.0 | 230.3 | 1694.3 | 0.00% | PASS |
| 50 | 102.93 | 205.6 | 342.4 | 1704.1 | 1.00% | PASS |
| 100 | 61.13 | 691.6 | 4058.3 | 4391.6 | 0.00% | FAIL |

**Nhận xét:** RPS **không** tăng tuyến tính mãi theo concurrency. Từ `c=1 → 10 → 50`, RPS tăng mạnh (`4.11 → 38.33 → 102.93`) vì agent chạy async không chặn event loop. Nhưng đến `c=100`, hệ thống chạm ngưỡng bão hòa (saturation / nghẽn hàng đợi xử lý 1 process trên Windows): RPS tụt xuống `61.13`, còn p50 nhảy lên `691.6 ms` và p95 vọt lên `4058.3 ms` (vi phạm SLO).

### 2.2 Tail latency (`--requests 300 --concurrency 20`)

*(Nguồn: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`)*

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 190.7 | 219.8 | 230.4 |
| 0.03 (mặc định) | 247.6 | 238.8 | 1722.1 |
| 0.1 | 389.2 | 1699.2 | 1723.1 |

**Nhận xét:** **`p99` và `p95`** nhạy nhất với các request chậm bất thường: ở mức `0.03`, `avg` chỉ tăng từ `190.7 ms → 247.6 ms` (+56.9 ms), trông vẫn bình thường, nhưng **`p99` vọt từ `230.4 ms → 1722.1 ms` (~7.5 lần)**. Khi `MOCK_SLOW_RATE=0.1` (> 5% request bị chậm), cả **`p95` cũng nhảy lên `1699.2 ms`** trong khi `avg` mới ở `389.2 ms`. Do đó không nên đặt SLO theo average vì average che giấu trải nghiệm tệ của nhóm người dùng gặp tail latency; SLO phải đặt theo `p95` / `p99`.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

*(Nguồn: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`)*

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 57.0 | 109.3 | 113.7 |
| Tổng cost (USD) | $0.000403 | $0.000764 | $0.000790 |
| Cost / câu đúng (USD) | $0.00040335 | $0.00003639 | $0.00003436 |
| Quality gate | FAIL | PASS (`min 80%`) | PASS (`min 100%`, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry từ khóa `["jwt"]` vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` (và đồng bộ sang `production/utils/mock_llm.py`) giải thích JWT là token có chữ ký số và thời điểm hết hạn |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry từ khóa `["hpa", "kubernetes", "autoscal"]` vào `KNOWLEDGE_BASE` mô tả HPA scale pod theo CPU, memory và custom metrics |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**  
Agent v2 dùng retrieval (RAG) nên prompt dài hơn (avg token tăng gần gấp đôi: `57.0 → 109.3–113.7` tokens/câu) và thêm ~20ms bước retrieval. Tuy tổng cost của v2 cao hơn gần gấp đôi (`$0.000764` vs `$0.000403`), nhưng nhờ accuracy tăng từ `4.35% → 100%`, **cost trên mỗi câu trả lời đúng của v2 rẻ hơn ~11.7 lần** (`$0.00003436` vs `$0.00040335`).

**CI Quality Gate (Exercise 7.3):**  
Đã tạo workflow [.github/workflows/eval.yml](.github/workflows/eval.yml) chạy `python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85 --baseline reports/eval_v2.json`. Script `run_eval.py` trả về **exit code `1`** nếu accuracy thấp hơn `--min-accuracy` hoặc có bất kỳ câu nào bị regression so với baseline, khiến GitHub Actions fail job và chặn merge Pull Request.

---

## 4. Observability stack (production)

### 4.1 Screenshot & Quan sát Dashboard (Exercise 7.4)

- [x] [Dashboard Grafana khi đang có tải](screenshots/grafana-dashboard.png)
- [x] [Một trace chậm trong Jaeger](screenshots/jaeger-slow-trace.png)
- [x] [Một trace lỗi trong Jaeger](screenshots/jaeger-error-trace.png)
- [x] [Trang Alerts của Prometheus với ≥ 2 alert đang firing](screenshots/prometheus-alert-firing.png)

**Trả lời Exercise 7.4 (số liệu đo từ Prometheus trong lúc tạo tải):**
1. **Khoảng cách `avg` ↔ `p95`:** Trong đợt tạo tải hỗn hợp có fault injection, Prometheus ghi nhận `avg = 655.8 ms` trong khi `p95 = 1900.2 ms`; khoảng cách lớn cho thấy phân phối latency lệch phải mạnh do tail latency (~1.7s–1.9s).
2. **Nginx cân bằng tải:** Panel `Requests/s` theo instance chia tải qua 2 container agent (`172.27.0.4:8000` và `172.27.0.6:8000` đạt ~4.1–6.0 req/s trong cửa sổ 5m).
3. **Vì sao `input_tokens/s` > `output_tokens/s`:** Đo thực tế `input = 628.09 tokens/s` vs `output = 327.54 tokens/s` (gấp ~1.92 lần) vì input prompt của agent v2 chứa cả `SYSTEM_PROMPT` + tài liệu retrieve được từ `KNOWLEDGE_BASE` + câu hỏi.
4. **`curl -i http://localhost:8080/metrics`:** Trả về **`HTTP/1.1 404 Not Found`** (từ Nginx) vì `nginx.conf` chủ động chặn `/metrics` từ bên ngoài, chỉ cho phép Prometheus trong mạng nội bộ `obs_net` scrape trực tiếp container agent.

### 4.2 Thí nghiệm "phá hệ thống"

*(Đã unit test trước bộ rule bằng `promtool test rules /p/alert_rules_test.yml` → `SUCCESS`)*

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | `76.2s` *(pending ở `16.0s`, vượt ngưỡng 5% → firing sau `for: 1m`; val `19.49%`)* | Error rate & LLM calls ok/error |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | `136.3s` *(pending ở `16.0s`, p95 > 1s → firing sau `for: 2m`; val `1.90s`)* | Latency & Traffic (`p50/p95/p99/avg`) |
| C | `LLM_MODEL=mock-llm-large` *(tính theo cấu hình `alert_rules.yml`)* | `LLMCostBurnRateHigh` *(cũng đã firing ở `5.9s` khi tốc độ đốt vượt `$2/giờ`, đạt `$5.14/giờ`)* | `for: 2m` (khi burn rate 5m > `$2/giờ`) | Cost 1h / LLM cost USD/giờ |
| D | `docker pause` 1 instance (`k5-day14-observability-agent-1`) | `AgentInstanceDown` | `45.3s` *(pending ở `+15.2s`, firing sau `for: 30s`)* | Instances up & Requests/s theo instance |
| E | `AGENT_VERSION=v1` *(phân tích)* | Không có alert nào | Không firing | Retrieval hit ratio tụt về 0, tokens/s giảm |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**  
Các alert hạ tầng chỉ đo HTTP status, latency, uptime và cost — khi chuyển về `v1`, agent vẫn trả `HTTP 200` nhanh và rẻ hơn nên mọi đèn hạ tầng đều xanh. Để phát hiện suy giảm chất lượng trả lời cần: (1) chạy **Eval CI/CD quality gate** trên golden dataset trước mỗi lần deploy, và (2) theo dõi thêm metric nghiệp vụ/RAG như **retrieval hit ratio**, **user feedback (thumbs up/down)** hoặc **LLM-as-a-judge online sampling** trên traffic thật.

**Ghi chú thêm về Thí nghiệm D:** Khi `docker pause` một instance, Prometheus vẫn giữ container đó trong DNS nên `up{job="agent"} == 0` và kích hoạt `AgentInstanceDown`. Nếu request rơi đúng vào container bị pause trước khi Nginx timeout, Nginx trả lỗi `504`, nên metric của chính agent không đếm lỗi đó (cần giám sát thêm log/metric của Nginx hoặc synthetic probe từ ngoài).

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất tìm được trong logs / Jaeger:

- `trace_id`: `88de1f62d04299170701ece6fc264652`
- Tổng thời gian: `1771.8 ms`
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (`1685.3 ms`, chiếm `95.1%` tổng thời gian request — nguyên nhân nằm ở độ trễ của LLM call, không phải code Python)
- Dòng log JSON tương ứng (từ `docker compose -p k5-day14-observability logs agent`):

```json
{"ts": "2026-11-25T14:34:41.187469+00:00", "level": "INFO", "service": "observable-agent", "instance": "fca996b7dec4", "event": "llm_call", "trace_id": "88de1f62d04299170701ece6fc264652", "span_id": "6927ca57734c6117", "request_id": "7927d2b26165", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 74, "output_tokens": 37, "cost_usd": 3.3e-05, "llm_ms": 1685.3}
{"ts": "2026-11-25T14:34:41.190008+00:00", "level": "INFO", "service": "observable-agent", "instance": "fca996b7dec4", "event": "http_request", "trace_id": "88de1f62d04299170701ece6fc264652", "span_id": "6927ca57734c6117", "request_id": "7927d2b26165", "method": "POST", "route": "/ask", "status": 200, "ms": 1771.8}
```

Ví dụ 1 dòng log lỗi (`llm_error`) để đối chiếu trace lỗi trong Jaeger:
```json
{"ts": "2026-11-25T14:31:04.145277+00:00", "level": "INFO", "service": "observable-agent", "instance": "fca996b7dec4", "event": "llm_error", "trace_id": "145bcfb7438ebd967f4e172765b97f3f", "span_id": "72585cb5ff98a339", "request_id": "5eb1dbc608e2", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

*(Nguồn: `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv`, số liệu dòng `POST /ask`)*

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 60.19 | 190 | 230 | 1700 | 68 / 7187 (0.95%) |
| 3 | 60.74 | 190 | 230 | 1700 | 75 / 7253 (1.03%) |

*(Tổng hợp `Aggregated` gồm cả `GET /health`: 1 instance = `7888` reqs, `66.06` RPS, `p95=220 ms`; 3 instances = `7939` reqs, `66.49` RPS, `p95=220 ms`.)*

**Giải thích kết quả:** Scale từ 1 lên 3 instance gần như **không làm thay đổi `p95` (`230 ms`) hay RPS (`60.19 → 60.74`)**. Nguyên nhân vì agent xử lý bất đồng bộ (`async` / `asyncio.sleep`) và bị **I/O-bound ở bước gọi LLM** (~120–180ms mỗi request, ~3% request chậm ~1.7s). Ở mức tải 100 users có thời gian nghỉ giữa các lượt (wait time), 1 instance async chưa bị bão hòa CPU; nút thắt nằm ở **latency của upstream LLM**, nên thêm container không rút ngắn được thời gian chờ của từng request.

---

## 6. Kết luận

- 3 điều học được về benchmark & observability:
  1. **Average che giấu tail latency:** phải đặt SLO và cảnh báo theo `p95` / `p99` thay vì trung bình.
  2. **Đánh đổi chất lượng ↔ chi phí qua `cost / câu đúng`:** RAG (v2) tốn gấp ~2x token nhưng giảm chi phí trên mỗi câu đúng xuống ~10x so với v1, và cần CI quality gate để chống regression.
  3. **Liên kết 3 trụ cột (Metrics → Traces → Logs):** dùng Grafana phát hiện tăng latency/error → sang Jaeger tìm span chậm (`chat mock-llm-small`) → lấy `trace_id` grep log JSON để chẩn đoán tận gốc.
- Nếu đưa agent này lên production thật, nên bổ sung thêm:
  - Alert kiểm tra lỗi 5xx ở tầng **Nginx/Ingress** và **synthetic health probe** từ ngoài.
  - Metric theo dõi **cache/retrieval hit ratio**, **token/request percentile**, và **online eval sampling / user feedback** để phát hiện suy giảm chất lượng trả lời.
