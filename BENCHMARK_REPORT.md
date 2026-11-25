# Benchmark & Observability Report — Day 14

> Mọi con số lấy từ file JSON trong `reports/` (Part 7 Bước 1) và CSV trong `benchmark-results/` (Bước 2).

**Họ tên:** Tran Quoc Tuan Khanh
**Ngày chạy:** 2026-11-25
**Môi trường:** Windows 11 Pro, Python 3.12.10, Docker Desktop 29.7.2 (Bước 2: agent giới hạn 0,5 CPU / 256 MB mỗi container). Agent (1 process uvicorn) và `load_test.py` chạy trên cùng máy. Agent v2 chạy ở cổng **8012** thay vì 8002 vì cổng 8002 trên máy đã bị một container khác chiếm; ngoài cổng, lệnh giữ nguyên như CHECKPOINTS.

---

## 1. SLO của agent

| SLI                           | SLO                                     | Lý do chọn ngưỡng này                                                                                                                                                                                        |
| ----------------------------- | --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| p95 latency `/ask`          | < 500 ms                                | Mock LLM trả lời ~200 ms (p50 ≈ 200 ms đo được); 500 ms chừa ~2,5× headroom cho retrieval và mạng mà người dùng chat vẫn thấy "nhanh". Khớp `--slo-p95-ms` mặc định của `load_test.py`. |
| Error rate `/ask`           | < 2 %                                   | Mock LLM có `MOCK_ERROR_RATE=1%` lỗi upstream không tránh được; 2% = gấp đôi mức nền làm error budget, vượt mức này là có sự cố thật.                                                     |
| Accuracy trên golden dataset | ≥ 80 % (gate release); mục tiêu 100% | 80% là ngưỡng mặc định của `run_eval.py`. Bộ 23 câu đều là kiến thức trong knowledge base, nên sau khi sửa KB, đặt `--min-accuracy 1.0` để mọi câu sai đều chặn merge.               |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS    | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO        |
| ----------- | ------ | -------- | -------- | -------- | ---------- | ---------- |
| 1           | 4.27   | 199.9    | 234.5    | 1683.2   | 1.00%      | PASS       |
| 10          | 39.84  | 196.9    | 237.1    | 1695.7   | 0.67%      | PASS       |
| 50          | 105.85 | 210.3    | 266.0    | 1722.6   | 0.67%      | PASS       |
| 100         | 67.1   | 293.2    | 2685.8   | 3104.8   | 1.00%      | FAIL (p95) |

Nguồn: `reports/load_v2_c{1,10,50,100}.json` (300 request mỗi mức).

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

Gần tuyến tính từ 1 → 10 (4,27 → 39,84 req/s, ×9,3) vì handler `/ask` là `async`: trong lúc một request chờ mock LLM (`asyncio.sleep`), event loop phục vụ request khác, latency mỗi request gần như không đổi (p50 ≈ 200 ms) nên RPS ≈ concurrency / 0,2 s. Từ 10 → 50 RPS chỉ tăng ×2,7 (105,85 req/s, đáng lẽ ~240 nếu tuyến tính) và p50 bắt đầu nhích lên 210 ms: event loop một process bắt đầu tốn CPU cho việc parse JSON, middleware metrics, logging. Ở 100, hệ thống đã quá tải: RPS **giảm** còn 67,1, p50 lên 293 ms và p95 vọt lên 2685,8 ms (vi phạm SLO). Request phải xếp hàng chờ CPU, mà agent và load generator lại chạy chung một máy nên tranh nhau CPU (giả thuyết hợp lý nhất, chưa đo CPU riêng từng process). Kết luận: một instance chịu được khoảng 50 request đồng thời; muốn hơn thì phải scale ngang (Mục 5).

Các request chậm ~1,7 s ở p99 tại mọi mức concurrency là tail latency giả lập của mock (`MOCK_SLOW_RATE=0.03`, +1500 ms), không phải do tải.

### 2.2 Tail latency

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
| ------------------ | -------- | -------- | -------- |
| 0                  | 191.9    | 232.8    | 241.9    |
| 0.03 (mặc định) | 222.4    | 238.8    | 1691.3   |
| 0.1                | 354.8    | 1682.0   | 1721.8   |

Nguồn: `reports/load_v2_slow_{0,0.03,0.1}.json` (300 request, concurrency 20).

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

**p99 nhạy nhất.** Chỉ cần 3% request chậm là p99 nhảy từ 241,9 lên 1691,3 ms (×7), trong khi avg chỉ tăng 191,9 → 222,4 ms (+16%) và p95 gần như không đổi (232,8 → 238,8), vì 3% request chậm vẫn nằm trong 5% đuôi mà p95 bỏ qua. Khi tỉ lệ chậm lên 10%, vượt quá 5% đuôi đó, p95 cũng vọt lên 1682,0 ms, còn avg vẫn chỉ 354,8 ms: nhìn avg tưởng "chậm hơn chút", thật ra cứ 10 người thì 1 người chờ gần 2 giây.

SLO không nên đặt theo average vì avg gộp đuôi chậm vào số đông nhanh rồi chia đều, nên che mất đúng những người dùng có trải nghiệm tệ nhất. p95/p99 trả lời trực tiếp câu "x% người dùng chờ không quá bao lâu", đúng thứ ta muốn cam kết. Avg cũng dễ bị một vài outlier cực lớn kéo lệch.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số                 | Agent v1              | Agent v2                               | Agent v2 (sau khi sửa KB)                             |
| ------------------------ | --------------------- | -------------------------------------- | ------------------------------------------------------ |
| Accuracy                 | 4.35% (1/23)          | 91.3% (21/23)                          | 100.0% (23/23)                                         |
| Avg tokens / câu        | 55.9                  | 109.1                                  | 117.6                                                  |
| Tổng cost (USD)         | 0.000388              | 0.000762                               | 0.000824                                               |
| Cost / câu đúng (USD) | 0.00038775            | 0.00003627                             | 0.00003583                                             |
| Quality gate             | FAIL (accuracy < 80%) | PASS (≥ 80%, 0 regression so với v1) | PASS (`--min-accuracy 1.0`, 0 regression so với v2) |

Nguồn: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`.

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID                                                                   | Keyword bị thiếu                      | Bạn đã sửa gì                                                                                                                                                                                                                                                                                                                               |
| -------------------------------------------------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| security-02 ("JWT khác gì API key trong xác thực?")              | `token`, `hết hạn`, `chữ ký`  | KB chưa có tài liệu nào về JWT nên retrieval trả về rỗng, LLM trả câu chung chung. Thêm entry vào `KNOWLEDGE_BASE` với từ khoá kích hoạt `jwt`, `api key`, `xác thực`, nội dung giải thích JWT là token tự chứa, server kiểm chữ ký, có thời điểm hết hạn (claim `exp`), khác API key cố định. |
| scaling-03 ("Kubernetes HPA scale dựa trên những chỉ số nào?") | `cpu`, `memory`, `custom metrics` | Tương tự, KB không có tài liệu về HPA. Thêm entry kích hoạt bởi `kubernetes`, `hpa`, `autoscal`: HPA scale theo CPU, memory utilization hoặc custom metrics.                                                                                                                                                                  |

Trước khi thêm, đã grep `golden_dataset.jsonl` để chắc các từ khoá kích hoạt mới chỉ xuất hiện trong đúng 2 câu này, không "cướp" retrieval của câu khác (eval cuối báo 0 regression). Không sửa `golden_dataset.jsonl`. Đã chép bản sửa sang `production/utils/mock_llm.py` để stack Docker dùng cùng KB.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- **Chất lượng:** v2 (retrieval → prompt) tăng accuracy từ 4,35% lên 91,3% (+87 điểm %); v1 chỉ trả lời chung chung.
- **Chi phí:** v2 tốn gần gấp đôi token mỗi câu (55,9 → 109,1) vì prompt có thêm context, nên tổng cost tăng ~2× (0.000388 → 0.000762 USD). Nhưng **cost / câu đúng giảm ~10,7×** (0.00038775 → 0.00003627 USD), vì v1 trả tiền cho 22 câu sai. Đây là lý do so sánh theo cost/câu đúng chứ không theo cost/câu: một câu trả lời sai có giá trị bằng 0 dù rẻ.
- **Latency:** v2 thêm bước retrieval (~20 ms) và prompt dài hơn (+0,2 ms/token), nên p50 eval tăng từ 167,7 lên 184,7 ms (+17 ms, `latency_ms` trong `eval_v1.json` / `eval_v2.json`), vẫn dưới SLO 500 ms. (p95 eval của v2 = 1523,8 ms là do một câu trúng tail latency giả lập; với 23 mẫu thì một request chậm đủ kéo p95, nên latency phải đọc từ load test, không đọc từ eval.)
- Sửa KB thêm +8,5 token/câu (+8% cost) để lên 100%; cost/câu đúng vẫn giảm nhẹ (0.00003627 → 0.00003583). Đáng đổi.

**Chặn merge bằng exit code (Exercise 7.3):** `run_eval.py` trả exit code `1` khi accuracy < `--min-accuracy` hoặc có câu regression so với `--baseline`, ngược lại trả `0`. File [`.github/workflows/eval-quality-gate.yml`](.github/workflows/eval-quality-gate.yml) chạy agent v2 rồi chạy eval trong mỗi pull request; exit code 1 làm step fail, job fail, và khi bật branch protection "Require status checks to pass" cho job `eval` thì nút Merge bị khoá. Đã kiểm lại cục bộ: lệnh eval v1 trả `exit=1` (FAIL), eval v2 và eval cuối trả `exit=0` (PASS).

---

## 4. Observability stack (production)

### 4.0 Exercise 7.4 — đọc stack khi có tải

Stack bật bằng `docker compose -p k5-day14-observability ...`, 2 instance agent, Locust headless 30 user. Số đọc từ Prometheus (cùng PromQL với panel Grafana), cửa sổ 1 phút:

1. **p95 = 292 ms, avg = 230 ms.** Khoảng cách nhỏ (~60 ms) vì phần lớn request mất ~200 ms; nhưng p99 vẫn ~1,7 s do 3% request chậm giả lập. Khoảng cách avg ↔ p99 mới là tail latency, avg không thấy nó.
2. **Requests/s theo instance:** 9,45 và 9,45 req/s — Nginx chia đều (round-robin). Khi benchmark 3 instance: 2475 / 2413 / 2418 request trong 2 phút.
3. **Input tokens/s (1483) > output tokens/s (789)** vì v2 nhét tài liệu retrieve được + system prompt vào prompt, nên input dài hơn câu trả lời; câu trả lời của mock chính là một tài liệu ngắn.
4. **`curl http://localhost:8080/metrics` → `404`.** `nginx.conf` có `location = /metrics { return 404; }`: metrics lộ route, lưu lượng, version… nên chỉ Prometheus scrape trực tiếp trong mạng Docker nội bộ (`agent:8000/metrics`), không public ra ngoài.

Unit test alert rules: `promtool test rules alert_rules_test.yml` → `SUCCESS`.

### 4.1 Screenshot

- [ ] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals)
- [ ] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian)
- [ ] Một trace lỗi trong Jaeger (có event `exception`)
- [ ] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi                   | Alert nào firing       | Thời gian từ lúc đổi → firing      | Panel nào phản ánh rõ nhất                                                                          |
| - | ---------------------------- | ----------------------- | ---------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| A | `MOCK_ERROR_RATE=0.2`      | `AgentHighErrorRate`  | 91 s (pending ở +31 s, + `for: 1m`)   | Error rate (lên 18,9%)                                                                                  |
| B | `MOCK_SLOW_RATE=0.3`       | `AgentHighLatencyP95` | 152 s (pending ở +31 s, + `for: 2m`)  | p50/p95/p99 theo thời gian: p95 1917 ms, p99 1983 ms nhưng avg chỉ 640 ms                             |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | 147 s (pending ở ~+21 s, + `for: 2m`) | Cost USD/giờ: 2,50 → 36,0 (×14,4); LLM p95 197 → 494 ms (×2,5)                                      |
| D | `docker pause` 1 instance  | `AgentInstanceDown`   | 45 s (pending ở +15 s, + `for: 30s`)  | Instances up (2 → 1); `up{instance="172.22.0.8:8000"} = 0`                                            |
| E | `AGENT_VERSION=v1`         | Không có              | —                                       | Retrieval hit ratio (100% → không còn series), tokens/s (input 1441 → 667), bảng version (v2 → v1) |

Thời gian đo bằng script hỏi `GET /api/v1/alerts` mỗi 5 s, tính từ lúc chạy `docker compose up -d` (hoặc `docker pause`). Tải nền: Locust 30 user, 2 instance. Mỗi thí nghiệm trả `.env` về mặc định trước khi làm thí nghiệm sau.

Quan sát thêm:

- **Ngưỡng cost đặt thấp hơn mức chi tiêu bình thường.** Ở tải nền 30 user (~19 req/s, v2, model small) cost burn rate đã là 2,0–2,5 USD/giờ, nên `LLMCostBurnRateHigh` firing ngay cả khi chưa phá gì (và nhấp nháy quanh ngưỡng). Với thí nghiệm C, thời gian 147 s vì vậy không "sạch". Production cần đặt ngưỡng theo baseline thực tế (vd 2–3× chi phí bình thường) hoặc theo budget/ngày.
- **Trong B, cost alert tự tắt:** request chậm → user Locust (vòng kín) gửi ít request hơn → tiền đốt chậm hơn. Một sự cố latency có thể "làm đẹp" một metric khác.
- **Trong D:** Nginx log 29 lỗi `504` trong 2 phút pause, nhưng error rate do agent tự đo chỉ 0,7% (panel xanh), vì request timeout ở Nginx chưa bao giờ được agent xử lý xong. Cần giám sát ở tầng load balancer hoặc synthetic check từ ngoài.
- Sau khi đổi sang v1, `AgentHighLatencyP95` vào `pending` một nhịp (instance mới, ít mẫu) rồi tự về `inactive`: `for: 2m` chặn được báo động giả.
- Ảnh `prometheus-alert-firing.png` chụp lúc chạy A + D cùng lúc: `AgentHighErrorRate` và `AgentInstanceDown` cùng firing.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Đây là lỗi chất lượng, không phải lỗi hạ tầng: request vẫn 200, nhanh hơn, rẻ hơn — mọi Golden Signal đều "đẹp". Cách phát hiện:

1. **Chặn trước khi deploy:** chạy eval golden dataset trong CI (Mục 3: v1 chỉ 4,35% → quality gate FAIL, exit code 1), nên bản v1 không được merge/deploy.
2. **Giám sát sau khi deploy:** chạy eval định kỳ (synthetic) trên production và đẩy accuracy thành metric để alert; alert theo **metric hành vi** như retrieval hit ratio giảm về 0, tokens/request giảm đột ngột, hoặc `agent_info` version đổi ngoài lịch release.
3. **Tín hiệu người dùng:** tỉ lệ thumbs-down/feedback, LLM-as-judge chấm mẫu ngẫu nhiên traffic thật.

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: `691365cf6cdd5c44774f493ad06fb73e`
- Tổng thời gian: 1718,0 ms
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (1694,0 ms, 98,6%), còn `agent.retrieve_context` chỉ 21,8 ms (1,3%). Request chậm vì LLM upstream (tail latency), không phải code của agent; tối ưu retrieval không giúp được.

```
POST /ask                    1718.0 ms  100%
└── agent.run                1716.0 ms  99.9%
    ├── agent.retrieve_context  21.8 ms   1.3%
    └── chat mock-llm-small   1694.0 ms  98.6%   input_tokens=95 output_tokens=55
```

- Dòng log tương ứng (`docker compose -p k5-day14-observability logs agent | grep 691365cf...`):

```json
{"ts": "2026-11-25T09:37:42.471033+00:00", "level": "INFO", "service": "observable-agent", "instance": "ca373a8e00c8", "event": "llm_call", "trace_id": "691365cf6cdd5c44774f493ad06fb73e", "span_id": "a0466dea035080b1", "request_id": "29a754eb99b9", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 95, "output_tokens": 55, "cost_usd": 4.7e-05, "llm_ms": 1693.7}
{"ts": "2026-11-25T09:37:42.471413+00:00", "level": "INFO", "service": "observable-agent", "instance": "ca373a8e00c8", "event": "http_request", "trace_id": "691365cf6cdd5c44774f493ad06fb73e", "span_id": "a0466dea035080b1", "request_id": "29a754eb99b9", "method": "POST", "route": "/ask", "status": 200, "ms": 1717.5}
```

**Trace lỗi** (trong thí nghiệm A): `trace_id` `fa6217e3d897825776c45110f8f3a8f4`, 873,7 ms, HTTP 503. Span `chat mock-llm-small` (846,6 ms) có status ERROR, `error.type=upstream_unavailable` và event `exception`: `utils.mock_llm.LLMError: Upstream LLM error: 503 Service Unavailable (mock)`. Log khớp:

```json
{"ts": "2026-11-25T09:37:20.284306+00:00", "level": "INFO", "service": "observable-agent", "instance": "44949294bca3", "event": "llm_error", "trace_id": "fa6217e3d897825776c45110f8f3a8f4", "span_id": "5f337dca21347481", "request_id": "7b82bc1235b0", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS   | p50 (ms) | p95 (ms) | p99 (ms) | Failures          |
| ------------ | ----- | -------- | -------- | -------- | ----------------- |
| 1            | 59.99 | 190      | 230      | 1700     | 71 / 7149 (0,99%) |
| 3            | 60.24 | 190      | 220      | 1700     | 65 / 7181 (0,91%) |

Nguồn: dòng `POST /ask` trong `benchmark-results/scale_1_stats.csv` và `scale_3_stats.csv` (Locust headless `-u 100 -r 10 -t 2m`). Locust làm tròn percentile theo bucket (190, 220, 1700…). Failures đều là `503` do `MOCK_ERROR_RATE=1%`.

Đã kiểm số instance thật trong lúc chạy: 1 instance nhận 7301 request; 3 instance nhận 2475 / 2413 / 2418. **Lưu ý:** lệnh trong CHECKPOINTS (`docker compose run --rm locust ...`) khởi động lại service phụ thuộc theo `deploy.replicas: 2` của compose, ghi đè `--scale` (lần chạy đầu cả `scale_1` lẫn `scale_3` thực chất đều 2 instance, số liệu giống hệt nhau). Hai file nộp được chạy lại với `docker compose run --rm --no-deps locust ...` để giữ đúng số instance.

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

**Không** — RPS (59,99 → 60,24) và p95 (230 → 220 ms) gần như không đổi. Hai lý do:

1. **Tải bị giới hạn ở phía client, không phải server.** Locust là tải vòng kín: mỗi user chờ `between(0.5, 2)` giây (TB 1,25 s) giữa các request, nên 100 user tạo tối đa ≈ 100 / (1,25 + 0,23) ≈ 67 req/s — đúng bằng tổng RPS đo được (66,4 gồm cả `/health`). Lúc cao điểm chỉ có 22 request đang xử lý cùng lúc trên cả hệ thống, 1 instance chưa bão hoà, nên thêm instance không có gì để "gánh" thêm.
2. **Nút thắt latency là LLM.** Mỗi request phải chờ mock LLM ~200 ms (98% thời gian trace, Mục 4.3); scale ngang chia tải nhưng không làm một lần gọi LLM nhanh hơn, và p99 1700 ms là tail latency của LLM ở cả hai cấu hình.

Scale ngang chỉ cải thiện p95 khi instance thật sự quá tải (như c=100 ở Mục 2.1, p95 lên 2,7 s); muốn thấy lợi ích cần tải mở (open-loop, RPS cố định) hoặc nhiều user hơn. Lợi ích chắc chắn của 3 instance ở đây là **availability** (thí nghiệm D: mất 1 instance vẫn phục vụ được).

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Đo đúng chỉ số và đúng điều kiện:** Average dễ che giấu tail latency (p99 nhảy ~1,7 s dù avg chỉ nhích nhẹ), eval nhỏ dễ bị nhiễu latency nên cần load test để đo p95/p99, và benchmark scaling phải lưu ý cơ chế vòng kín của client cũng như `--no-deps` để số instance phản ánh đúng thực tế.
  2. **Đánh giá trade-off chất lượng, chi phí và độ trễ:** Agent v2 (retrieval + context) nâng accuracy từ 4,35% lên 91,3% (và 100% sau khi bổ sung KB cho `security-02` & `scaling-03`), đồng thời giảm cost trên mỗi câu đúng ~10,7× dù tổng token/cost cao hơn; gắn eval vào CI (`exit=1` khi fail) giúp chặn regression trước khi merge.
  3. **Kết hợp metrics, logs, traces và alerts thay vì nhìn một tín hiệu đơn lẻ:** Trace/log giúp định vị nhanh bottleneck nằm ở upstream LLM (~98,6% thời gian span `chat mock-llm-small`) thay vì retrieval hay code agent; đồng thời cần cảnh giác điểm mù của alert (ngưỡng cost đặt thấp gây nhiễu, lỗi timeout ở Nginx/LB chưa chạm tới metric của agent, hoặc lỗi sai logic/chất lượng như v1 không kích hoạt alert hạ tầng).
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

**Metrics:**

* *Edge / Load Balancer metrics* (Nginx/gateway status 502/503/504, upstream timeout/retry count) để bắt lỗi khi instance down hoặc quá tải trước khi chạm agent.
* *Per-stage latency & token breakdown* (TTFT / time-to-first-token, retrieval latency, LLM latency, queue wait time) và *per-tenant / per-endpoint cost & token usage* để kiểm soát chi phí theo khách hàng/tác vụ.
* *Quality & behavioral telemetry* (tỷ lệ fallback/empty retrieval, độ dài context/prompt bất thường, tỷ lệ phản hồi lỗi schema/hallucination hoặc feedback người dùng).

**Alerts:**

* *Gateway 5xx / 504 spike* và *SLO burn-rate alert* (multi-window burn rate theo error budget và p95/p99 thay vì ngưỡng cố định dễ báo động giả).
* *Cost anomaly / burn-rate alert* đặt theo baseline thực tế (ví dụ > 2–3× mức trung bình theo cửa sổ trượt hoặc gần hạn mức ngân sách/ngày).
* *Behavioral / quality drift alert* (ví dụ retrieval hit ratio hoặc độ chính xác trên bộ synthetic eval định kỳ sụt giảm đột ngột, hoặc `agent_info` version thay đổi ngoài kế hoạch release).
