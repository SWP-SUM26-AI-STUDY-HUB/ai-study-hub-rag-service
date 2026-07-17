# Langfuse Metrics API v2 Cookbook — Admin Dashboard

Spec cho Java backend (`ai-study-hub-api`) gọi **Langfuse Metrics API v2** để feed trang thống kê admin.

> Mọi query dưới đây đã **test thật** trên Langfuse Cloud (JP region) với dữ liệu RAG service. Response mẫu là output thực, không phải giả lập.

---

## 1. Setup

### Auth (Basic)
```
Authorization: Basic base64(LANGFUSE_PUBLIC_KEY:LANGFUSE_SECRET_KEY)
```
- Keys lấy từ Langfuse UI → Project Settings → API Keys (hoặc `.env` của RAG service).
- Java backend cần 2 env mới: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` (= `https://jp.cloud.langfuse.com` hoặc self-host URL).

### Endpoint
```
GET {LANGFUSE_BASE_URL}/api/public/v2/metrics?query={URL_ENCODED_JSON}
```
- `query` là JSON object, **phải URL-encode** (`application/x-www-form-urlencoded`).
- Response: `{ "data": [ {...}, ... ] }` — list of rows, mỗi row = 1 group (dimension value + metric values).

### Rate limit
- Free tier: ~ các query trả trong 1-3s. Dashboard nên **cache 1-5 phút** (Redis) để tránh spam API + giảm latency.
- Gọi **async** (không block request user) + timeout 10s.

---

## 2. Query anatomy

```jsonc
{
  "view": "observations",            // "observations" | "scores-numeric" | "scores-categorical"
  "metrics": [
    {"measure": "latency", "aggregation": "p95"}   // có thể nhiều metrics cùng lúc
  ],
  "dimensions": [{"field": "name"}], // GROUP BY — chỉ field có sẵn (KHÔNG group được metadata.*)
  "filters": [                       // WHERE — filter được metadata.* qua type=stringObject
    {"column": "metadata", "operator": "=", "key": "route", "value": "qa", "type": "stringObject"}
  ],
  "timeDimension": {"granularity": "day"},  // optional: "hour"|"day"|"week"|"month" → time series
  "fromTimestamp": "2026-07-10T00:00:00Z",  // ISO 8601 UTC, BẮT BUỘC
  "toTimestamp": "2026-07-18T00:00:00Z",
  "orderBy": [{"field": "p95_latency", "direction": "desc"}],
  "config": {"row_limit": 100}       // default 100, max 1000
}
```

### Measures & aggregations

| Measure | Aggregations | Ý nghĩa |
|---|---|---|
| `latency` | `p50, p75, p90, p95, p99, avg, min, max` | ms — thời gian observation |
| `totalTokens` | `sum, avg` | tổng token LLM |
| `totalCost` | `sum, avg` | USD — **auto-tính** từ model price built-in |
| `count` | `count` | số observation |
| `timeToFirstToken` | `p50, p95, avg` | ms (nếu streaming) |

**Tên field trả về** = `{aggregation}_{measure}`, ví dụ `p95_latency`, `sum_totalTokens`, `count_count`, `avg_value`.

### Dimensions khả dụng (observations view)
`id, traceId, traceName, environment, parentObservationId, type, name, level, version, providedModelName, promptName, promptVersion, userId, sessionId, traceRelease, traceVersion, scoreName`

> **KHÔNG group được** `metadata.*` (route, refused, empty_retrieval...). Phải filter từng giá trị rồi count, hoặc dùng listing API + aggregate client-side.

### Filter operators
| Type | Operators |
|---|---|
| `string` | `=`, `contains`, `does not contain`, `starts with`, `<>` |
| `stringObject` (metadata) | `=`, `contains` — **BẮT BUỘC dùng cho metadata** |
| `number` | `=`, `<>`, `>`, `<`, `>=`, `<=` |

> Metadata values luôn là string. `metadata.refused=true` (Python bool) → filter `value: "true"` (string).

---

## 3. Queries cho dashboard (verified)

### 3.1. Latency p95 per stage (histogram funnel)
**Mục đích**: xem stage nào chậm nhất trong pipeline.

```json
{
  "view": "observations",
  "metrics": [{"measure": "latency", "aggregation": "p95"}],
  "dimensions": [{"field": "name"}],
  "filters": [],
  "fromTimestamp": "2026-07-10T00:00:00Z",
  "toTimestamp": "2026-07-18T00:00:00Z",
  "orderBy": [{"field": "p95_latency", "direction": "desc"}],
  "config": {"row_limit": 20}
}
```
**Response thực:**
```json
[
  {"name": "retrieval-funnel", "p95_latency": 2504},
  {"name": "chat", "p95_latency": 2421.6},
  {"name": "ingest-index", "p95_latency": 2091},
  {"name": "bm25_rebuild", "p95_latency": 1842},
  {"name": "ChatGoogleGenerativeAI", "p95_latency": 1532},
  {"name": "hybrid_search", "p95_latency": 1340.1}
]
```

### 3.2. Endpoint volume (request count per trace name)
```json
{
  "view": "observations",
  "metrics": [{"measure": "count", "aggregation": "count"}],
  "dimensions": [{"field": "traceName"}],
  "filters": [{"column": "type", "operator": "=", "value": "SPAN", "type": "string"}],
  "fromTimestamp": "2026-07-10T00:00:00Z",
  "toTimestamp": "2026-07-18T00:00:00Z",
  "orderBy": [{"field": "count_count", "direction": "desc"}],
  "config": {"row_limit": 20}
}
```
**Response thực:**
```json
[
  {"traceName": "chat", "count_count": 17},
  {"traceName": "quiz", "count_count": 8},
  {"traceName": "flashcard", "count_count": 4},
  {"traceName": "ingest-index", "count_count": 3}
]
```

### 3.3. Endpoint latency p95
```json
{
  "view": "observations",
  "metrics": [{"measure": "latency", "aggregation": "p95"}],
  "dimensions": [{"field": "traceName"}],
  "filters": [{"column": "type", "operator": "=", "value": "SPAN", "type": "string"}],
  "fromTimestamp": "...", "toTimestamp": "...",
  "orderBy": [{"field": "p95_latency", "direction": "desc"}]
}
```
**Response:** `chat: 2745ms, ingest-index: 2066ms, quiz: 1575ms, flashcard: 1393ms`

### 3.4. Token usage by model
```json
{
  "view": "observations",
  "metrics": [{"measure": "totalTokens", "aggregation": "sum"}],
  "dimensions": [{"field": "providedModelName"}],
  "filters": [],
  "fromTimestamp": "...", "toTimestamp": "...",
  "orderBy": [{"field": "sum_totalTokens", "direction": "desc"}]
}
```
**Response thực:** `[{"providedModelName": "gemini-2.5-flash-lite", "sum_totalTokens": 51379}]`

### 3.5. Cost by model (USD — auto-tính)
```json
{
  "view": "observations",
  "metrics": [{"measure": "totalCost", "aggregation": "sum"}],
  "dimensions": [{"field": "providedModelName"}],
  "fromTimestamp": "...", "toTimestamp": "..."
}
```
**Response thực:** `[{"providedModelName": "gemini-2.5-flash-lite", "sum_totalCost": 0.0036994}]`

> ✅ Langfuse Cloud **đã có giá Gemini built-in** — không cần config Model Definitions. Nếu self-host sau, cần thêm price trong UI.

### 3.6. Token time series (daily chart)
```json
{
  "view": "observations",
  "metrics": [{"measure": "totalTokens", "aggregation": "sum"}],
  "dimensions": [],
  "timeDimension": {"granularity": "day"},
  "fromTimestamp": "...", "toTimestamp": "...",
  "config": {"row_limit": 50}
}
```
**Response thực:**
```json
[
  {"time_dimension": "2026-07-16", "sum_totalTokens": 0},
  {"time_dimension": "2026-07-17", "sum_totalTokens": 51379}
]
```

### 3.7. Citation coverage avg (RAG quality score)
```json
{
  "view": "scores-numeric",
  "metrics": [{"measure": "value", "aggregation": "avg"}],
  "dimensions": [{"field": "name"}],
  "filters": [{"column": "name", "operator": "=", "value": "citation_coverage", "type": "string"}],
  "fromTimestamp": "...", "toTimestamp": "..."
}
```
**Response thực:** `[{"name": "citation_coverage", "avg_value": 0.5}]`

### 3.8. Refusal count (quiz/flashcard bị từ chối)
```json
{
  "view": "observations",
  "metrics": [{"measure": "count", "aggregation": "count"}],
  "dimensions": [{"field": "name"}],
  "filters": [
    {"column": "metadata", "operator": "=", "key": "refused", "value": "true", "type": "stringObject"}
  ],
  "fromTimestamp": "...", "toTimestamp": "..."
}
```
**Response thực:** `[{"name": "quiz", "count_count": 2}, {"name": "flashcard", "count_count": 1}]`

### 3.9. Route distribution (chat intent split)
Vì metadata không group được → **chạy N query** (1 per route value), hoặc dùng pattern loop:
```python
# Pseudocode — Java tương đương
routes = ["qa", "smalltalk", "summary", "guardrail_block", "quiz", "flashcard"]
for route in routes:
    query = {
        "view": "observations",
        "metrics": [{"measure": "count", "aggregation": "count"}],
        "dimensions": [],
        "filters": [
            {"column": "metadata", "operator": "=", "key": "route", "value": route, "type": "stringObject"}
        ],
        "fromTimestamp": "...", "toTimestamp": "..."
    }
    # count_count của row đầu tiên = số request route này
```
**Response thực (test):** `qa:1, smalltalk:2, summary:1, guardrail_block:1, quiz:2, flashcard:1`

### 3.10. Empty retrieval rate (QA không tìm thấy docs)
```json
{
  "view": "observations",
  "metrics": [{"measure": "count", "aggregation": "count"}],
  "dimensions": [{"field": "name"}],
  "filters": [
    {"column": "metadata", "operator": "=", "key": "empty_retrieval", "value": "true", "type": "stringObject"}
  ],
  "fromTimestamp": "...", "toTimestamp": "..."
}
```
> Chia cho tổng QA count (3.9 route=qa) để ra rate.

---

## 4. Gotchas

| Vấn đề | Giải pháp |
|---|---|
| Metadata KHÔNG group được (chỉ filter) | Route distribution → N query hoặc client-side aggregate từ listing API |
| Metadata filter type BẮT BUỘC `stringObject` | `"type": "stringObject"`, value luôn string (`"true"` không phải `true`) |
| Filter operator dùng `=`/`<>` | KHÔNG dùng `"equals"` / `"not equals"` |
| Timestamp BẮT BUỘC ISO 8601 UTC | `"2026-07-17T00:00:00Z"` (có `Z`) |
| Field trả về = `{aggregation}_{measure}` | `p95_latency`, `sum_totalTokens`, `count_count`, `avg_value` |
| Row limit default 100 | Set `config.row_limit` tối đa 1000 nếu cần |
| Data delay ≤10 phút (SDK v4 realtime) | Dashboard refresh mỗi 1-5 phút là đủ |

---

## 5. Java implementation guide

### 5.1. HTTP client pattern (Spring `RestTemplate` / `WebClient`)

```java
@Service
public class LangfuseMetricsClient {

    @Value("${langfuse.base-url}")
    private String baseUrl;

    private final RestTemplate restTemplate;
    private final String authHeader;  // "Basic " + Base64(publicKey:secretKey)

    public JsonNode query(Map<String, Object> queryPayload, String fromTs, String toTs) {
        queryPayload.put("fromTimestamp", fromTs);
        queryPayload.put("toTimestamp", toTs);

        String url = UriComponentsBuilder.fromHttpUrl(baseUrl + "/api/public/v2/metrics")
            .queryParam("query", objectMapper.writeValueAsString(queryPayload))
            .build().toUriString();

        HttpHeaders headers = new HttpHeaders();
        headers.set("Authorization", authHeader);

        ResponseEntity<JsonNode> resp = restTemplate.exchange(
            url, HttpMethod.GET, new HttpEntity<>(headers), JsonNode.class);

        return resp.getBody().get("data");  // ArrayNode
    }
}
```

### 5.2. Caching (Redis, 5 phút TTL)

```java
@Cacheable(value = "langfuse-metrics", key = "#metricType + #fromTs + #toTs")
public DashboardStats getStats(String metricType, String fromTs, String toTs) {
    // gọi LangfuseMetricsClient, map response -> DTO
}
```
- TTL 300s (`spring.cache.redis.time-to-live=300s`).
- Cache key = metric type + time range.

### 5.3. Controller pattern (async, timeout)

```java
@GetMapping("/api/v1/admin/statistics/ai")
public CompletableFuture<DashboardStats> getAiStats() {
    return CompletableFuture.supplyAsync(() -> {
        try {
            return statsService.getStats("overview", last7Days(), now());
        } catch (Exception e) {
            log.warn("Langfuse query failed, returning empty stats", e);
            return DashboardStats.empty();  // fail-open — dashboard không crash
        }
    }).orTimeout(10, TimeUnit.SECONDS);
}
```

> **Fail-open bắt buộc**: nếu Langfuse down/rate-limit → trả empty stats, KHÔNG 500. Dashboard là phụ trợ, không được làm sập trang admin.

### 5.4. Recommended dashboard widgets → queries

| Widget | Query (section) | Refresh |
|---|---|---|
| Request volume (bar chart per endpoint) | 3.2 | 5 min |
| Endpoint latency p95 (table) | 3.3 | 5 min |
| Token usage by model (donut) | 3.4 | 5 min |
| Cost total (number card) | 3.5 | 1 hour |
| Token time series (line chart) | 3.6 | 5 min |
| Citation coverage avg (gauge) | 3.7 | 5 min |
| Refusal rate (number card) | 3.8 ÷ 3.2 | 5 min |
| Chat route distribution (pie) | 3.9 | 5 min |
| Empty retrieval rate (number card) | 3.10 ÷ 3.9(qa) | 5 min |
| Latency funnel (waterfall) | 3.1 | 5 min |

---

## 6. Env vars cho Java backend

```bash
LANGFUSE_BASE_URL=https://jp.cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```
Thêm vào `application.yml` / `.env` của `ai-study-hub-api`. Không commit keys.
