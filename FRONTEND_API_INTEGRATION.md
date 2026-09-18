# Frontend → Backend API Integration Guide

This document describes exactly how the frontend (Member 2's responsibility)
should integrate with the GridWise backend at `POST /optimize-energy`.

Every field name, type, and example below is derived from the actual
Pydantic schemas in `app/schemas/` and the live route in
`app/api/routes.py`. Nothing here is invented.

> **Scope reminder.** The frontend only talks to the backend. The Gemini
> API key lives **only** in the backend environment (`.env` /
> `GEMINI_API_KEY`). The frontend must never see, send, store, or proxy
> it.

---

## 1. Endpoints

| Purpose | Method | URL (local dev) |
|---|---|---|
| Readiness probe | `GET` | `http://localhost:8000/health` |
| Run the optimization | `POST` | `http://localhost:8000/optimize-energy` |

The local server is started with:

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

(or `uvicorn app.main:app --reload` during development). Both bind to
`0.0.0.0` so the browser / `curl` from another machine can reach it.

> **Deployment override (Phase 10).** When the backend is deployed, the
> frontend must use the deployed base URL instead of `localhost:8000`,
> e.g. `https://gridwise.example.com`. The two endpoint paths (`/health`,
> `/optimize-energy`) stay the same. See §10 for details.

---

## 2. Required HTTP headers

For `POST /optimize-energy`:

| Header | Value | Required? |
|---|---|---|
| `Content-Type` | `application/json` | **Yes** |
| `Accept` | `application/json` | Recommended |

No authentication headers. No cookies. No API key.

---

## 3. Request body — `POST /optimize-energy`

The body must be a JSON object matching the Pydantic model
`OptimizeEnergyRequest` (`app/schemas/request.py`).

### 3.1 Field reference

| Field | Type | Required | Constraints |
|---|---|---|---|
| `scenario_id` | string | Yes | Non-empty. Echoed back in the response. |
| `operator_notes` | string[] | Yes | **1 to 3** entries. Each must be a non-empty natural-language string. |
| `hours` | object[] | Yes | **Exactly 24** entries. Each must have `hour` ∈ [0, 23], ascending, unique. |
| `battery` | object | Yes | See `BatterySpec` below. |

#### `hours[i]`

| Field | Type | Required | Constraints |
|---|---|---|---|
| `hour` | integer | Yes | 0 ≤ hour ≤ 23. Must cover 0..23 exactly once. |
| `demand_kwh` | number | Yes | ≥ 0. |
| `solar_kwh` | number | Yes | ≥ 0 (raw forecast; may be reduced by LLM directive). |
| `tariff_bdt_per_kwh` | number | Yes | ≥ 0. |

#### `battery`

| Field | Type | Required | Constraints |
|---|---|---|---|
| `capacity_kwh` | number | Yes | > 0. |
| `initial_energy_kwh` | number | Yes | ≥ 0, ≤ `capacity_kwh`, ≥ `minimum_energy_kwh`. |
| `minimum_energy_kwh` | number | Yes | ≥ 0, ≤ `capacity_kwh`. |
| `max_charge_kwh_per_hour` | number | Yes | ≥ 0. |
| `max_discharge_kwh_per_hour` | number | Yes | ≥ 0. |

### 3.2 Realistic request example (complete; copy-pasteable)

This is the official public sample **SAMPLE-01** from
`tests/data/public_samples.json`. The body below is exactly the
contents of `.cases[0].input` and is **100% complete (all 24 hours)**.
You can copy-paste it straight into a `fetch()` body or `curl --data`
and the backend will accept it.

```http
POST /optimize-energy HTTP/1.1
Host: localhost:8000
Content-Type: application/json
Accept: application/json

{
  "scenario_id": "SAMPLE-01",
  "operator_notes": [
    "Facilities will wash the rooftop solar panels from noon until 2 PM. During cleaning, usable solar should be treated as roughly 25% of the forecast.",
    "The sports office moved next month's registration deadline."
  ],
  "hours": [
    { "hour": 0,  "demand_kwh": 90,  "solar_kwh": 0,   "tariff_bdt_per_kwh": 6 },
    { "hour": 1,  "demand_kwh": 85,  "solar_kwh": 0,   "tariff_bdt_per_kwh": 6 },
    { "hour": 2,  "demand_kwh": 80,  "solar_kwh": 0,   "tariff_bdt_per_kwh": 5 },
    { "hour": 3,  "demand_kwh": 80,  "solar_kwh": 0,   "tariff_bdt_per_kwh": 5 },
    { "hour": 4,  "demand_kwh": 85,  "solar_kwh": 0,   "tariff_bdt_per_kwh": 5 },
    { "hour": 5,  "demand_kwh": 95,  "solar_kwh": 0,   "tariff_bdt_per_kwh": 6 },
    { "hour": 6,  "demand_kwh": 110, "solar_kwh": 5,   "tariff_bdt_per_kwh": 8 },
    { "hour": 7,  "demand_kwh": 130, "solar_kwh": 20,  "tariff_bdt_per_kwh": 10 },
    { "hour": 8,  "demand_kwh": 150, "solar_kwh": 50,  "tariff_bdt_per_kwh": 12 },
    { "hour": 9,  "demand_kwh": 165, "solar_kwh": 90,  "tariff_bdt_per_kwh": 14 },
    { "hour": 10, "demand_kwh": 175, "solar_kwh": 130, "tariff_bdt_per_kwh": 16 },
    { "hour": 11, "demand_kwh": 180, "solar_kwh": 160, "tariff_bdt_per_kwh": 16 },
    { "hour": 12, "demand_kwh": 185, "solar_kwh": 180, "tariff_bdt_per_kwh": 15 },
    { "hour": 13, "demand_kwh": 180, "solar_kwh": 170, "tariff_bdt_per_kwh": 14 },
    { "hour": 14, "demand_kwh": 170, "solar_kwh": 140, "tariff_bdt_per_kwh": 13 },
    { "hour": 15, "demand_kwh": 165, "solar_kwh": 90,  "tariff_bdt_per_kwh": 14 },
    { "hour": 16, "demand_kwh": 170, "solar_kwh": 45,  "tariff_bdt_per_kwh": 18 },
    { "hour": 17, "demand_kwh": 185, "solar_kwh": 10,  "tariff_bdt_per_kwh": 22 },
    { "hour": 18, "demand_kwh": 205, "solar_kwh": 0,   "tariff_bdt_per_kwh": 28 },
    { "hour": 19, "demand_kwh": 215, "solar_kwh": 0,   "tariff_bdt_per_kwh": 30 },
    { "hour": 20, "demand_kwh": 205, "solar_kwh": 0,   "tariff_bdt_per_kwh": 26 },
    { "hour": 21, "demand_kwh": 175, "solar_kwh": 0,   "tariff_bdt_per_kwh": 18 },
    { "hour": 22, "demand_kwh": 135, "solar_kwh": 0,   "tariff_bdt_per_kwh": 10 },
    { "hour": 23, "demand_kwh": 105, "solar_kwh": 0,   "tariff_bdt_per_kwh": 7 }
  ],
  "battery": {
    "capacity_kwh": 220,
    "initial_energy_kwh": 110,
    "minimum_energy_kwh": 40,
    "max_charge_kwh_per_hour": 50,
    "max_discharge_kwh_per_hour": 50
  }
}
```

---

## 4. Successful response — HTTP 200

The response is a JSON object matching the Pydantic model
`OptimizeEnergyResponse` (`app/schemas/response.py`).

### 4.1 Field reference

| Field | Type | Description |
|---|---|---|
| `scenario_id` | string | Echoes the request's `scenario_id`. |
| `directive_interpretation` | object[] | One entry per `operator_notes` (1..3), in `note_index` order. |
| `hourly_plan` | object[] | Exactly 24 entries, hours 0..23 ascending. |
| `total_grid_kwh` | number | ≥ 0. Sum of `hourly_plan[].grid_kwh`. |
| `total_cost_bdt` | number | ≥ 0. Sum of `grid_kwh × tariff` over all hours. |
| `peak_grid_kwh` | number | ≥ 0. Max of `hourly_plan[].grid_kwh`. |
| `plan_summary` | string | Non-empty human-readable explanation. |

#### `directive_interpretation[i]`

| Field | Type | Description |
|---|---|---|
| `note_index` | integer | The 0-based index of the operator note this directive came from. |
| `applies` | boolean | `true` for an active directive; `false` for `no_op`. |
| `directive_type` | string | One of: `solar_reduction`, `minimum_battery_reserve`, `no_charge_window`, `no_discharge_window`, `max_grid_window`, `no_op`. |
| `structured_adjustment` | object \| null | The parsed numeric values + hours. `null` when `directive_type == "no_op"`. |
| `explanation` | string | Non-empty human-readable rationale. |

#### `hourly_plan[h]`

| Field | Type | Description |
|---|---|---|
| `hour` | integer | 0..23. |
| `grid_kwh` | number | ≥ 0. Energy drawn from the grid this hour. |
| `solar_used_kwh` | number | ≥ 0. Solar energy used this hour (≤ effective solar). |
| `battery_action` | string | `"charge"`, `"discharge"`, or `"idle"`. |
| `battery_kwh` | number | ≥ 0. Magnitude of `battery_action` (0 when `"idle"`). |
| `battery_energy_after_kwh` | number | ≥ 0. Battery state at end of hour. |

### 4.2 Realistic response example (truncated for readability)

```json
{
  "scenario_id": "SAMPLE-01",
  "directive_interpretation": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "solar_reduction",
      "structured_adjustment": {
        "hours": [12, 13],
        "factor": 0.25
      },
      "explanation": "Solar availability is reduced to 25% during the panel-cleaning window."
    },
    {
      "note_index": 1,
      "applies": false,
      "directive_type": "no_op",
      "structured_adjustment": null,
      "explanation": "This note does not affect today's 24-hour energy schedule."
    }
  ],
  "hourly_plan": [
    { "hour": 0,  "grid_kwh": 90,  "solar_used_kwh": 0,  "battery_action": "idle",      "battery_kwh": 0,  "battery_energy_after_kwh": 110 },
    { "hour": 12, "grid_kwh": 90,  "solar_used_kwh": 45, "battery_action": "discharge", "battery_kwh": 50, "battery_energy_after_kwh": 105 },
    { "hour": 23, "grid_kwh": 155, "solar_used_kwh": 0,  "battery_action": "charge",    "battery_kwh": 50, "battery_energy_after_kwh": 110 }
  ],
  "total_grid_kwh": 2692.5,
  "total_cost_bdt": 38365.0,
  "peak_grid_kwh": 175.0,
  "plan_summary": "Uses the reduced midday solar availability, ignores the unrelated note, and shifts battery energy toward higher-tariff hours while restoring the initial battery level. (scenario SAMPLE-01)."
}
```

(The actual response contains all 24 hourly_plan rows.)

---

## 5. How the frontend should send each block

| Block | How to build it |
|---|---|
| `scenario_id` | Any short non-empty string the frontend uses to label the run. Will be echoed in the response. |
| `operator_notes` | 1–3 free-form text strings from operator input. Each must be non-empty after trim. Pass them as an array of strings in the order the operator gave them. |
| `hours` | Build the 24-entry array in JavaScript by iterating `for (let h = 0; h < 24; h++)`. Demand/solar/tariff numbers come from the forecast inputs. The `hour` field is just `h`. Do NOT sort client-side; send ascending 0..23. |
| `battery` | Single object with the five battery fields from the operator's input form. Validate `initial_energy_kwh` between `minimum_energy_kwh` and `capacity_kwh` before sending. |

The frontend should validate the array length (exactly 24) and the note
count (1..3) **before** sending — the backend will also validate and
return 422 if the constraints are violated, but client-side validation
gives instant feedback.

---

## 6. Expected success status code

`200 OK` with a full JSON body of the shape described in §4.

---

## 7. Error status codes

The orchestrator in `app/services/optimize.py` translates typed
exceptions into HTTP status codes. The frontend should branch on the
status code first, then optionally inspect `response.detail`.

| Status | When | What it means for the user |
|---|---|---|
| **200** | Success | Show the optimized plan. |
| **422 Unprocessable Entity** | The request is well-formed JSON but fails Pydantic validation OR the orchestrator rejects LLM output / solver / validator. | Show a clear error: invalid input or the LLM returned an unexpected structure. |
| **502 Bad Gateway** | The upstream LLM (Google Gemini) failed: persistent 5xx, empty body, non-JSON, quota exceeded, invalid key, etc. | "Upstream LLM unavailable, try again." This is a transient infrastructure error, not a bug in the frontend payload. |
| **500 Internal Server Error** | Genuine server-side problem: `GEMINI_API_KEY` not set, unexpected exception, etc. | "Server error, please contact the team." |

**Don't show raw `detail` strings to end users.** They are intended for
debugging and may contain stack-trace-like prefixes
(`internal_error: KeyError: ...`). Map each status to a friendly message.

### 7.1 Example 422 body

```json
{
  "detail": "llm_guardrail_violation: NoteMappingError: LLM returned 0 directives but the request has 2 operator_notes (expected exactly 2)"
}
```

### 7.2 Example 502 body

```json
{
  "detail": "upstream_llm_unavailable: ClientError: 429 RESOURCE_EXHAUSTED. ..."
}
```

### 7.3 Example 500 body

```json
{
  "detail": "llm_provider_misconfigured: GEMINI_API_KEY is not set. ..."
}
```

### 7.4 Validation 422 (Pydantic) — different `detail` shape

When the request itself is malformed (e.g. wrong number of hours,
negative `demand_kwh`), FastAPI's own Pydantic validation produces a
different `detail` shape — a list of error objects:

```json
{
  "detail": [
    {
      "type": "too_short",
      "loc": ["body", "operator_notes"],
      "msg": "List should have at least 1 item after validation, not 0",
      "input": []
    }
  ]
}
```

The frontend should treat this as a normal validation error and surface
the messages to the user.

---

## 8. CORS requirements — **TODO, NOT YET CONFIGURED**

> **Action required for frontend integration.** The backend currently has
> **no CORS middleware installed** (verified — `app/main.py` does not
> register `fastapi.middleware.cors.CORSMiddleware`). A browser-based
> frontend served from a different origin (e.g. `http://localhost:5173`)
> will be blocked by the browser's same-origin policy on the POST.

### Workarounds during local development

Pick one of these until CORS is added in a follow-up:

1. **Proxy the API through the frontend dev server** (Vite, Next.js, CRA).
   Configure the dev server to forward `/optimize-energy` and `/health`
   to `http://localhost:8000` so the browser sees the same origin.
2. **Run the frontend from the same origin.** Serve the built frontend
   at `/` from FastAPI itself (added in a follow-up).
3. **Temporarily allow the dev origin.** Add
   `fastapi.middleware.cors.CORSMiddleware` to `app/main.py` with
   `allow_origins=["http://localhost:5173"]` (and any other dev ports).
   **Do this only for development**; the production deployment must
   restrict `allow_origins` to the real frontend host.

### Recommended production fix (Phase 10)

In `app/main.py`, before `app.include_router(router)`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-frontend.example.com"],  # the deployed origin
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
```

This is a tracked TODO; it is intentionally not silently added in this
document so the team can confirm the production origin before exposing it.

---

## 9. Frontend `fetch()` example

Vanilla browser JavaScript. Replace `API_BASE` per §10 when deploying.

```javascript
const API_BASE = "http://localhost:8000"; // dev — change for deployment

/**
 * Run the GridWise optimizer for one scenario.
 * @param {string} scenarioId
 * @param {string[]} operatorNotes  — 1..3 non-empty strings
 * @param {{hour:number, demand_kwh:number, solar_kwh:number, tariff_bdt_per_kwh:number}[]} hours
 * @param {{capacity_kwh:number, initial_energy_kwh:number, minimum_energy_kwh:number,
 *          max_charge_kwh_per_hour:number, max_discharge_kwh_per_hour:number}} battery
 * @returns {Promise<object>}  — OptimizeEnergyResponse
 */
async function optimizeEnergy(scenarioId, operatorNotes, hours, battery) {
  const response = await fetch(`${API_BASE}/optimize-energy`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Accept": "application/json",
    },
    body: JSON.stringify({
      scenario_id: scenarioId,
      operator_notes: operatorNotes,
      hours: hours,
      battery: battery,
    }),
  });

  if (response.status === 200) {
    return await response.json();        // OptimizeEnergyResponse
  }

  // Non-200: read the JSON error body and throw a typed error.
  const errBody = await response.json().catch(() => ({ detail: response.statusText }));

  if (response.status === 422) {
    // Could be either Pydantic validation (detail is an array) or
    // orchestrator rejection (detail is a string with a prefix).
    throw new Error(`Invalid request or plan: ${JSON.stringify(errBody.detail)}`);
  }
  if (response.status === 502) {
    throw new Error("Upstream LLM unavailable. Please try again in a minute.");
  }
  if (response.status === 500) {
    throw new Error("Server error. Please contact the team.");
  }
  throw new Error(`Unexpected status ${response.status}`);
}
```

### Display the result

```javascript
const result = await optimizeEnergy("SAMPLE-01", notes, hours, battery);

// 1. Show the totals — these are the headline numbers.
console.log("Total grid energy:", result.total_grid_kwh, "kWh");
console.log("Total cost:        ", result.total_cost_bdt, "BDT");
console.log("Peak grid demand:  ", result.peak_grid_kwh, "kWh");

// 2. Show the human-readable plan summary.
console.log("Plan:", result.plan_summary);

// 3. Show the directive interpretation (which notes were honoured).
for (const d of result.directive_interpretation) {
  console.log(`Note ${d.note_index}: ${d.directive_type} ` +
              `(applies=${d.applies}) — ${d.explanation}`);
}

// 4. Render the 24-hour schedule as a table or chart.
for (const row of result.hourly_plan) {
  // row.hour is 0..23
  // row.grid_kwh, row.solar_used_kwh are numbers
  // row.battery_action is "charge" | "discharge" | "idle"
  // row.battery_kwh is the magnitude (0 when idle)
  // row.battery_energy_after_kwh is the SoC after this hour
}
```

---

## 10. Deployment

The local base URL is `http://localhost:8000`. When the backend is
deployed (Phase 10 of the project plan), the deployed URL replaces it
and **nothing else changes** — the endpoint paths, methods, headers,
request shape, and response shape are identical.

| Setup | The `local` var in code becomes... |
|---|---|
| Local development (this guide) | `"http://localhost:8000"` |
| Docker on the same host | `"http://localhost:8000"` (port-forwarded) |
| Deployed to a public host (Phase 10) | `"https://gridwise.your-domain.example"` |

**The frontend must read the backend URL from a config / env file**,
not hard-code `localhost`. Even during development, prefer
`import.meta.env.VITE_API_BASE` (Vite) or `process.env.REACT_APP_API_BASE`
(CRA) so swapping to the deployed URL is a one-line change.

A few deployment-time considerations the frontend should be ready for:

- **HTTPS.** The deployed URL will be `https://`. The fetch example above
  works as-is.
- **Latency.** Each call runs the full pipeline (1 LLM call + OR-Tools).
  Expect 2–10 seconds per request in production. Show a spinner.
- **Retries.** A 502 is transient (LLM upstream hiccup). The frontend may
  retry the same payload once after a short delay. Do NOT retry on 422
  (it won't get better) or 500 (server-side bug).

---

## 11. Security note — the API key never crosses the boundary

The Gemini API key (`GEMINI_API_KEY`) is read by
`app/llm/factory.py:get_llm_provider()` **on the backend** and never
appears in any HTTP response, log line, or error message. The frontend
must:

- Never accept a "Gemini key" input from the user.
- Never read it from `import.meta.env` / `process.env` on the frontend.
- Never proxy it via a header.
- Never echo it back if a backend error message somehow contains it
  (this would be a backend bug; report it, do not display it).

The key is set in `backend/.env` (gitignored) and shipped to the
deployed container via `--env-file` / `-e` at runtime.

---

## 12. Quick local smoke check (for the frontend developer)

From the backend project root, with `.env` populated:

```bash
# Terminal 1: start the server.
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminal 2: health check.
curl http://localhost:8000/health
# -> {"status":"ok"}

# Terminal 2: full request using SAMPLE-01.
#
# IMPORTANT: tests/data/public_samples.json is the entire sample pack
# ({_meta, cases: [...]}). The endpoint expects a single OptimizeEnergyRequest,
# so you must extract one case's .input block first. Use `jq`:

jq '.cases[0].input' tests/data/public_samples.json \
  | curl -X POST http://localhost:8000/optimize-energy \
      -H "Content-Type: application/json" \
      -H "Accept: application/json" \
      --data-binary @-

# Change `[0]` to pick a different case (cases are 0-indexed:
# [0]=SAMPLE-01, [3]=SAMPLE-04, ..., [9]=SAMPLE-10).

# If you don't have `jq`, use python instead:
python -c "import json; print(json.dumps(json.load(open('tests/data/public_samples.json'))['cases'][0]['input']))" \
  | curl -X POST http://localhost:8000/optimize-energy \
      -H "Content-Type: application/json" \
      --data-binary @-
```

If both work, the frontend can integrate against `http://localhost:8000`
exactly as shown in §9.