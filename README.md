# Smart Campus Energy Optimizer (GridWise)

> Submission for the **BUP CSE Fest 2026 — GridWise LLM Hackathon** (Online Preliminary).
>
> An LLM-assisted 24-hour campus energy scheduler. The operator drops 1–3
> natural-language notes ("no charging between 1 PM and 3 PM", "treat
> solar as 30% usable after the panel cleaning"), and the service returns
> a fully validated, cost-optimal 24-hour battery + grid schedule.

**Live deployment:** https://smart-campus-energy-optimizer-2ip5.onrender.com

| | |
|---|---|
| `GET /health` | `https://smart-campus-energy-optimizer-2ip5.onrender.com/health` |
| `POST /optimize-energy` | `https://smart-campus-energy-optimizer-2ip5.onrender.com/optimize-energy` |
| Source | this repository |
| Stack | FastAPI · Pydantic v2 · Google Gemini · OR-Tools CP-SAT · pytest |

---

## 1. What this service does

You give it **a 24-hour forecast + 1–3 operator notes**. You get back:

1. A **machine-checkable interpretation** of each note (`directive_interpretation`).
2. A **24-hour plan** that minimizes grid-import cost while obeying every
   directive, the battery's physical limits, the per-hour energy balance,
   and the end-of-day neutrality requirement
   (`hourly_plan`).
3. **Three totals** — total grid kWh, total cost in BDT, peak grid kWh —
   re-derived from the plan by the validator so they are guaranteed
   consistent.
4. A short **human-readable summary** (`plan_summary`).

The LLM is **untrusted**: its output is validated by deterministic
guardrails before any directive is applied, and the optimized plan is
checked by a final validator before it leaves the service. If anything
fails a check, the API returns a clean `422` (or `502` if the upstream
LLM is unavailable) — never a silently-fake success.

---

## 2. Repository layout

```
smart-campus-energy-optimizer/
├── app/
│   ├── api/routes.py            # FastAPI router: GET /health, POST /optimize-energy
│   ├── directives/apply.py      # LLM output → AppliedDirectives
│   ├── guardrails/              # Deterministic validation of LLM output
│   ├── llm/                     # Gemini provider + StaticProvider for tests
│   ├── optimizer/solver.py      # OR-Tools CP-SAT 24-hour scheduler
│   ├── samples/loader.py        # Loads tests/data/public_samples.json
│   ├── schemas/                 # Pydantic v2 models (extra="forbid")
│   ├── services/optimize.py     # End-to-end orchestrator
│   ├── validator/               # Final-plan validator
│   └── main.py                  # FastAPI app factory
├── tests/
│   ├── data/public_samples.json # 10 organizer-provided public cases
│   ├── _public_sample_helpers.py
│   ├── test_public_samples.py   # Deterministic round-trip on all 10 cases
│   ├── test_live_samples.py     # LLM-driven, gated on GEMINI_API_KEY
│   ├── test_final_validator.py  # Validator unit tests
│   └── …                        # 152 deterministic tests total
├── Dockerfile                   # python:3.11-slim, uv, non-root, /health probe
├── .dockerignore
├── .env.example
├── FRONTEND_API_INTEGRATION.md  # Frontend integration guide
├── pyproject.toml
├── uv.lock
└── README.md                    # ← this file
```

---

## 3. Architecture at a glance

```
                ┌───────────────────────────────────────────────┐
  POST          │  app/api/routes.py                            │
  /optimize-    │      │                                        │
  energy   ─────►  OptimizeEnergyRequest (Pydantic)             │
                │      │                                        │
                │      ▼                                        │
                │  app/services/optimize.py                    │
                │      │                                        │
                │      ▼                                        │
                │  app/llm/provider.py  (Gemini)                │
                │      │ raw JSON {"directives":[...]}          │
                │      ▼                                        │
                │  app/guardrails/validator.py                  │
                │      │ validated DirectiveInterpretation list │
                │      ▼                                        │
                │  app/directives/apply.py                      │
                │      │ AppliedDirectives (per-hour constraints)│
                │      ▼                                        │
                │  app/optimizer/solver.py  (OR-Tools CP-SAT)    │
                │      │ OptimizationResult                      │
                │      ▼                                        │
                │  app/validator/validate.py                    │
                │      │ ValidatedPlan (re-derived totals)       │
                │      ▼                                        │
                │  OptimizeEnergyResponse (Pydantic)            │
                └───────────────────────────────────────────────┘
```

Each stage's typed exceptions are translated to clean HTTP status codes
in `app/services/optimize.py`:

| Stage | Failure → HTTP |
|---|---|
| LLM transport / 5xx | `502 upstream_llm_unavailable` |
| LLM returns 4xx (bad key, quota) | `502 upstream_llm_unavailable` |
| LLM missing `GEMINI_API_KEY` | `500 llm_provider_misconfigured` |
| Guardrails reject LLM JSON | `422 llm_guardrail_violation` |
| Guardrails reject LLM JSON (BadLLMOutput) | `422 llm_output_invalid` |
| Optimizer infeasible | `422 schedule_infeasible` |
| Final validator finds a constraint violation | `422 plan_validation_failed` |
| Anything else | `500 internal_error` |

The orchestrator is intentionally **fail-closed**: when the LLM is
untrusted, we never silently fall back to a `no_op` directive list and
return a fake success. The judge harness sees the failure, the response
shape stays honest.

---

## 4. The six supported directives

The LLM must choose exactly one `directive_type` per note. The list is
fixed by the Problem Statement and enforced by both the LLM
`response_schema` and the post-LLM guardrails.

| `directive_type` | `structured_adjustment` | What it does |
|---|---|---|
| `solar_reduction` | `{hours: [int…], factor: 0..1}` | Multiplies raw `solar_kwh` by `factor` in the listed hours. **`factor` is the *usable* fraction**, so "80% reduction" → `factor=0.2`. |
| `minimum_battery_reserve` | `{hours: [int…], minimum_energy_kwh: ≥0}` | Raises the floor on `battery_energy_after_kwh` for those hours. The validator floors it at `battery.minimum_energy_kwh`. |
| `no_charge_window` | `{hours: [int…]}` | Battery is forbidden to charge (`battery_action != "charge"`) in those hours. |
| `no_discharge_window` | `{hours: [int…]}` | Battery is forbidden to discharge (`battery_action != "discharge"`) in those hours. |
| `max_grid_window` | `{hours: [int…], max_grid_kwh: ≥0}` | Caps `grid_kwh` per listed hour. |
| `no_op` | `null` | Note is irrelevant to today's schedule. `applies` must be `false`. |

**Time-window semantics.** Windows are **start-inclusive, end-exclusive**.
"1 PM to 3 PM" → `[13, 14]`. "6 PM to 9 PM" → `[18, 19, 20]`.

---

## 5. Optimization problem

For each of the 24 hours `h`, the CP-SAT solver picks:

* `grid[h] ≥ 0`              — kWh imported from the grid
* `solar_used[h] ∈ [0, eff[h]]` — kWh of usable solar actually consumed
* `charge[h] ∈ [0, c_rate]`  — kWh pushed into the battery
* `discharge[h] ∈ [0, d_rate]` — kWh drawn from the battery
* `battery_action[h] ∈ {charge, discharge, idle}` — exact action label

subject to:

1. **Per-hour energy balance** —  
   `grid[h] + solar_used[h] + discharge[h] = demand[h] + charge[h]`
2. **`solar_used[h] ≤ effective_solar[h]`** (after `solar_reduction`)
3. **Battery state transition** —  
   `e_after[h] = e_after[h-1] + charge[h] - discharge[h]` (with `e_after[-1] = initial_energy_kwh`)
4. **Battery bounds** —  
   `min_active[h] ≤ e_after[h] ≤ capacity_kwh` (where `min_active[h]` is the max of the spec's `minimum_energy_kwh` and any `minimum_battery_reserve` floor for hour `h`)
5. **Charge / discharge rate caps** — `charge[h] ≤ max_charge_kwh_per_hour`, `discharge[h] ≤ max_discharge_kwh_per_hour`
6. **Directive constraints** — `no_charge_window`, `no_discharge_window`, `max_grid_window`
7. **End-of-day neutrality** — `e_after[23] == initial_energy_kwh`

Objective: **minimize Σ grid[h] × tariff[h]** (total BDT cost).

The model is built in integer milli-kWh (`_scale = 1000`) and solved with
the default CP-SAT search. The wall-clock limit is `OPTIMIZER_TIME_LIMIT_SECONDS`
(env var, default `10`). If the model is infeasible, the optimizer
raises `InfeasibleProblem` → HTTP `422 schedule_infeasible`.

---

## 6. API

### `GET /health`

Readiness probe. Returns `{"status":"ok"}` once uvicorn has finished
importing the app.

```bash
curl https://smart-campus-energy-optimizer-2ip5.onrender.com/health
# {"status":"ok"}
```

### `POST /optimize-energy`

Request body — exactly matches `app/schemas/request.py:OptimizeEnergyRequest`:

```json
{
  "scenario_id": "SAMPLE-01",
  "operator_notes": [
    "Facilities will wash the rooftop solar panels from noon until 2 PM. During cleaning, usable solar should be treated as roughly 25% of the forecast.",
    "The sports office moved next month's registration deadline."
  ],
  "hours": [
    {"hour": 0,  "demand_kwh": 90,  "solar_kwh": 0,   "tariff_bdt_per_kwh": 6},
    {"hour": 1,  "demand_kwh": 85,  "solar_kwh": 0,   "tariff_bdt_per_kwh": 6},
    {"hour": 2,  "demand_kwh": 80,  "solar_kwh": 0,   "tariff_bdt_per_kwh": 5},
    {"hour": 3,  "demand_kwh": 80,  "solar_kwh": 0,   "tariff_bdt_per_kwh": 5},
    {"hour": 4,  "demand_kwh": 85,  "solar_kwh": 0,   "tariff_bdt_per_kwh": 5},
    {"hour": 5,  "demand_kwh": 95,  "solar_kwh": 0,   "tariff_bdt_per_kwh": 6},
    {"hour": 6,  "demand_kwh": 110, "solar_kwh": 5,   "tariff_bdt_per_kwh": 8},
    {"hour": 7,  "demand_kwh": 130, "solar_kwh": 20,  "tariff_bdt_per_kwh": 10},
    {"hour": 8,  "demand_kwh": 150, "solar_kwh": 50,  "tariff_bdt_per_kwh": 12},
    {"hour": 9,  "demand_kwh": 165, "solar_kwh": 90,  "tariff_bdt_per_kwh": 14},
    {"hour": 10, "demand_kwh": 175, "solar_kwh": 130, "tariff_bdt_per_kwh": 16},
    {"hour": 11, "demand_kwh": 180, "solar_kwh": 160, "tariff_bdt_per_kwh": 16},
    {"hour": 12, "demand_kwh": 185, "solar_kwh": 180, "tariff_bdt_per_kwh": 15},
    {"hour": 13, "demand_kwh": 180, "solar_kwh": 170, "tariff_bdt_per_kwh": 14},
    {"hour": 14, "demand_kwh": 170, "solar_kwh": 140, "tariff_bdt_per_kwh": 13},
    {"hour": 15, "demand_kwh": 165, "solar_kwh": 90,  "tariff_bdt_per_kwh": 14},
    {"hour": 16, "demand_kwh": 170, "solar_kwh": 45,  "tariff_bdt_per_kwh": 18},
    {"hour": 17, "demand_kwh": 185, "solar_kwh": 10,  "tariff_bdt_per_kwh": 22},
    {"hour": 18, "demand_kwh": 205, "solar_kwh": 0,   "tariff_bdt_per_kwh": 28},
    {"hour": 19, "demand_kwh": 215, "solar_kwh": 0,   "tariff_bdt_per_kwh": 30},
    {"hour": 20, "demand_kwh": 205, "solar_kwh": 0,   "tariff_bdt_per_kwh": 26},
    {"hour": 21, "demand_kwh": 175, "solar_kwh": 0,   "tariff_bdt_per_kwh": 18},
    {"hour": 22, "demand_kwh": 135, "solar_kwh": 0,   "tariff_bdt_per_kwh": 10},
    {"hour": 23, "demand_kwh": 105, "solar_kwh": 0,   "tariff_bdt_per_kwh": 7}
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

**Field constraints** (Pydantic v2, `extra="forbid"`):

* `scenario_id` — non-empty string
* `operator_notes` — 1 to 3 non-empty strings (`MIN_OPERATOR_NOTES=1`, `MAX_OPERATOR_NOTES=3`)
* `hours` — exactly 24 entries, unique, sorted ascending, covering hours 0..23; each row has `hour∈[0,23]`, `demand_kwh≥0`, `solar_kwh≥0`, `tariff_bdt_per_kwh≥0`
* `battery` — `capacity_kwh>0`, `initial_energy_kwh∈[minimum_energy_kwh, capacity_kwh]`, `minimum_energy_kwh∈[0, capacity_kwh]`, both rate limits `≥0`

Response body — exactly matches `app/schemas/response.py:OptimizeEnergyResponse`:

```json
{
  "scenario_id": "SAMPLE-01",
  "directive_interpretation": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "solar_reduction",
      "structured_adjustment": {"hours": [12, 13], "factor": 0.25},
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
    {"hour": 0,  "grid_kwh": 90,   "solar_used_kwh": 0,   "battery_action": "idle",      "battery_kwh": 0,  "battery_energy_after_kwh": 110},
    {"hour": 1,  "grid_kwh": 45,   "solar_used_kwh": 0,   "battery_action": "discharge", "battery_kwh": 40, "battery_energy_after_kwh": 70},
    {"hour": 2,  "grid_kwh": 130,  "solar_used_kwh": 0,   "battery_action": "charge",    "battery_kwh": 50, "battery_energy_after_kwh": 120},
    {"hour": 3,  "grid_kwh": 130,  "solar_used_kwh": 0,   "battery_action": "charge",    "battery_kwh": 50, "battery_energy_after_kwh": 170},
    {"hour": 4,  "grid_kwh": 135,  "solar_used_kwh": 0,   "battery_action": "charge",    "battery_kwh": 50, "battery_energy_after_kwh": 220},
    {"hour": 5,  "grid_kwh": 95,   "solar_used_kwh": 0,   "battery_action": "idle",      "battery_kwh": 0,  "battery_energy_after_kwh": 220},
    {"hour": 6,  "grid_kwh": 105,  "solar_used_kwh": 5,   "battery_action": "idle",      "battery_kwh": 0,  "battery_energy_after_kwh": 220},
    {"hour": 7,  "grid_kwh": 110,  "solar_used_kwh": 20,  "battery_action": "idle",      "battery_kwh": 0,  "battery_energy_after_kwh": 220},
    {"hour": 8,  "grid_kwh": 100,  "solar_used_kwh": 50,  "battery_action": "idle",      "battery_kwh": 0,  "battery_energy_after_kwh": 220},
    {"hour": 9,  "grid_kwh": 75,   "solar_used_kwh": 90,  "battery_action": "idle",      "battery_kwh": 0,  "battery_energy_after_kwh": 220},
    {"hour": 10, "grid_kwh": 0,    "solar_used_kwh": 130, "battery_action": "discharge", "battery_kwh": 45, "battery_energy_after_kwh": 175},
    {"hour": 11, "grid_kwh": 0,    "solar_used_kwh": 160, "battery_action": "discharge", "battery_kwh": 20, "battery_energy_after_kwh": 155},
    {"hour": 12, "grid_kwh": 90,   "solar_used_kwh": 45,  "battery_action": "discharge", "battery_kwh": 50, "battery_energy_after_kwh": 105},
    {"hour": 13, "grid_kwh": 152.5,"solar_used_kwh": 42.5,"battery_action": "charge",    "battery_kwh": 15, "battery_energy_after_kwh": 120},
    {"hour": 14, "grid_kwh": 80,   "solar_used_kwh": 140, "battery_action": "charge",    "battery_kwh": 50, "battery_energy_after_kwh": 170},
    {"hour": 15, "grid_kwh": 125,  "solar_used_kwh": 90,  "battery_action": "charge",    "battery_kwh": 50, "battery_energy_after_kwh": 220},
    {"hour": 16, "grid_kwh": 125,  "solar_used_kwh": 45,  "battery_action": "idle",      "battery_kwh": 0,  "battery_energy_after_kwh": 220},
    {"hour": 17, "grid_kwh": 145,  "solar_used_kwh": 10,  "battery_action": "discharge", "battery_kwh": 30, "battery_energy_after_kwh": 190},
    {"hour": 18, "grid_kwh": 155,  "solar_used_kwh": 0,   "battery_action": "discharge", "battery_kwh": 50, "battery_energy_after_kwh": 140},
    {"hour": 19, "grid_kwh": 165,  "solar_used_kwh": 0,   "battery_action": "discharge", "battery_kwh": 50, "battery_energy_after_kwh": 90},
    {"hour": 20, "grid_kwh": 155,  "solar_used_kwh": 0,   "battery_action": "discharge", "battery_kwh": 50, "battery_energy_after_kwh": 40},
    {"hour": 21, "grid_kwh": 175,  "solar_used_kwh": 0,   "battery_action": "idle",      "battery_kwh": 0,  "battery_energy_after_kwh": 40},
    {"hour": 22, "grid_kwh": 155,  "solar_used_kwh": 0,   "battery_action": "charge",    "battery_kwh": 20, "battery_energy_after_kwh": 60},
    {"hour": 23, "grid_kwh": 155,  "solar_used_kwh": 0,   "battery_action": "charge",    "battery_kwh": 50, "battery_energy_after_kwh": 110}
  ],
  "total_grid_kwh": 2692.5,
  "total_cost_bdt": 38365,
  "peak_grid_kwh": 175,
  "plan_summary": "Uses the reduced midday solar availability, ignores the unrelated note, and shifts battery energy toward higher-tariff hours while restoring the initial battery level."
}
```

**Response field constraints:**

* `scenario_id` echoes the request
* `directive_interpretation` has **exactly one entry per `operator_notes`**, in `note_index` order
* `hourly_plan` has **exactly 24 entries**, ascending 0..23; each row has `battery_action ∈ {"charge","discharge","idle"}`, `battery_kwh ≥ 0`, `battery_energy_after_kwh ≥ 0`
* `total_grid_kwh`, `total_cost_bdt`, `peak_grid_kwh` are all `≥ 0` and are re-derived from `hourly_plan` by the final validator (so they are guaranteed consistent)
* `plan_summary` is a non-empty human-readable string

---

## 7. Local quickstart

### 7.1 Prerequisites

* Python **3.11+**
* [`uv`](https://github.com/astral-sh/uv) (already used by the project) — `pip install 'uv>=0.5,<1.0'`
* A Google Gemini API key from <https://aistudio.google.com/apikey>

### 7.2 Clone + install

```bash
git clone <your-fork-or-clone-url> smart-campus-energy-optimizer
cd smart-campus-energy-optimizer
uv sync                  # installs runtime + dev deps from uv.lock
```

### 7.3 Configure

```bash
cp .env.example .env
# then edit .env and put your real key:
#   GEMINI_API_KEY=your_gemini_api_key_here
#   GEMINI_MODEL=gemini-3.6-flash
```

### 7.4 Run the server

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then in another shell:

```bash
curl http://localhost:8000/health
# {"status":"ok"}

# Smoke-test /optimize-energy by piping one case's .input from the
# public sample pack. Using jq:
jq '.cases[0].input' tests/data/public_samples.json \
  | curl -X POST http://localhost:8000/optimize-energy \
      -H "Content-Type: application/json" \
      --data-binary @-

# Or, without jq:
python -c "import json,sys; print(json.dumps(json.load(open('tests/data/public_samples.json'))['cases'][0]['input']))" \
  | curl -X POST http://localhost:8000/optimize-energy \
      -H "Content-Type: application/json" \
      --data-binary @-
```

The full SAMPLE-01 input/response pair is shown in §6 above.

---

## 8. Environment variables

Read from `.env` (locally) or process env (in Docker / on Render). Names
match `.env.example` exactly.

| Variable | Default | Required? | Purpose |
|---|---|---|---|
| `LLM_PROVIDER` | `gemini` | no | `gemini` (production) or `static` (offline tests) |
| `GEMINI_API_KEY` | — | **yes** for live LLM | API key from AI Studio. Missing key → `500 llm_provider_misconfigured`. |
| `GEMINI_MODEL` | `gemini-3.6-flash` | no | Primary model. On persistent 5xx, the provider falls back to `gemini-3.5-flash`. |
| `HOST` | `0.0.0.0` | no | uvicorn bind host |
| `PORT` | `8000` | no | uvicorn bind port |
| `OPTIMIZER_TIME_LIMIT_SECONDS` | `10` | no | Wall-clock budget for the CP-SAT solve. |
| `STATIC_LLM_PAYLOAD` | `{"directives":[]}` | only when `LLM_PROVIDER=static` | Pre-canned JSON payload the `StaticProvider` returns without calling an LLM. Useful for offline smoke tests and CI. |

---

## 9. LLM provider & model

The service speaks to Google Gemini through the `google-genai` SDK. The
provider module (`app/llm/provider.py`) does the following:

* Builds a JSON `response_schema` that exactly matches
  `DirectiveInterpretation` so Gemini returns typed JSON we can parse
  directly (`response_mime_type="application/json"`).
* Uses `temperature=0.0` for deterministic output.
* Retries transient `5xx` (server errors) with exponential backoff
  (4 attempts, `1.5 × 2^n` seconds).
* Falls back from the configured primary model to `gemini-3.5-flash` if
  the primary keeps returning 5xx after the retries.
* Logs every call (`model=… notes=…`) and every fallback so production
  behaviour is observable.

The system prompt encodes the six directive types, the start-inclusive /
end-exclusive time-window rule, and the `factor = usable fraction
remaining` semantics for `solar_reduction`. Free-form explanations are
accepted — only the `directive_type`, `applies`, and
`structured_adjustment` shapes are validated deterministically.

---

## 10. Guardrails — fail-closed LLM contract

The LLM is untrusted. After Gemini returns, the payload must clear three
checks before any directive reaches the optimizer:

1. **Structural validation** (`app/guardrails/validator.py:validate_directives`):
   - `directives` is a list of length 1..3
   - Every entry has `note_index ∈ [0, n_notes)` and is unique
   - `directive_type` is one of the six enum values
   - `applies=false ⇔ directive_type=no_op`
   - `structured_adjustment` is `null` iff `no_op`, otherwise has the
     right keys for the chosen type
   - `factor ∈ [0, 1]`; `hours` are unique integers in `[0, 23]`,
     ascending
2. **Range sanity**:
   - `minimum_energy_kwh ≤ battery_capacity_kwh`
   - `max_grid_kwh ≥ 0`
3. **No fabrication**: the guardrail will *not* silently swap a bad
   payload for `no_op`. It raises a typed exception, which the
   orchestrator turns into a `422`. Judges see the failure rather than
   a fake success.

---

## 11. OR-Tools solver

`app/optimizer/solver.py` builds a CP-SAT model with:

* Variables in integer milli-kWh (precision 0.001 kWh, well below the
  0.01 kWh judge tolerance).
* All 24 hours built at once so end-of-day neutrality is a single linear
  equality constraint (`e_after[23] == initial_energy_kwh`).
* Per-hour directive constraints enforced via upper-bound literals on
  the corresponding integer variables.
* Solver wall-clock budget from `OPTIMIZER_TIME_LIMIT_SECONDS` (default
  10 s) — for these 24-hour, 4-variable-per-hour inputs CP-SAT hits
  optimum in well under a second.

The solver returns the integer-valued hourly plan; the final validator
re-derives the totals from the plan and rounds them to 3 decimals so the
response's top-level totals are guaranteed consistent.

---

## 12. Testing

The test suite is in `tests/`. From the repo root:

```bash
uv run pytest                  # full deterministic suite (152 tests)
uv run pytest -q               # quieter
uv run pytest tests/test_public_samples.py -v   # one file
```

Test layout:

| File | Purpose |
|---|---|
| `tests/test_public_samples.py` | **Deterministic round-trip** on every one of the 10 public sample cases. Uses the organizer's reference `directive_interpretation`, then runs the optimizer + every GridWise constraint check + cost-slack check. **No LLM call required.** |
| `tests/test_live_samples.py` | **LLM-driven** round-trip, gated on `GEMINI_API_KEY`. Two paths per case: in-process (`run_optimize`) and HTTP (`POST /optimize-energy` via `TestClient`). Skipped automatically in CI without a key. |
| `tests/test_final_validator.py` | Unit tests for the validator: happy paths, every constraint failure path (negative grid/solar/battery, solar overshoot, battery bounds, rate limits, directive violations, end-of-day mismatch, total mismatches), and an end-to-end "validator passes every public sample" test. |
| `tests/_public_sample_helpers.py` | Shared assertion helpers used by both the deterministic and the live test paths. |

Cost-slack tolerance (judges state "equivalent valid schedules are
accepted"):

* Deterministic test (organizer's reference interpretation): **+5%** of
  reference `total_cost_bdt`.
* Live LLM test (paraphrased notes may yield a slightly suboptimal
  directive set): **+10%** of reference `total_cost_bdt`.

`ABS_TOL = 0.01` is the absolute tolerance for kWh and BDT comparisons,
matching the canonical contract.

---

## 13. Docker

A production-style container is provided in `Dockerfile`:

```bash
docker build -t gridwise:dev .

docker run --rm -p 8000:8000 \
  -e GEMINI_API_KEY="$GEMINI_API_KEY" \
  -e LLM_PROVIDER=gemini \
  -e GEMINI_MODEL=gemini-3.6-flash \
  gridwise:dev
```

Highlights:

* Base: `python:3.11-slim`. Alpine is **not** used (OR-Tools only ships
  manylinux wheels).
* Dependencies installed via `uv sync --frozen` from `uv.lock`, so
  installs are byte-deterministic across machines.
* Runtime user is **non-root** (`appuser`, uid `10001`) — matches
  OpenShift / arbitrary-uid convention.
* **No `.env` is copied into the image.** Secrets are supplied at runtime
  via `-e` or `--env-file`. The `RUN python -c "from app.main import app"`
  sanity check fails the build at image-construction time if imports
  break.
* `HEALTHCHECK` hits `/health` every 30 s.
* `CMD` starts `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}`.

To reproduce the deterministic tests inside the container:

```bash
docker run --rm gridwise:dev uv run pytest -q
```

---

## 14. Deployment

The submission is deployed on **Render**:

* Base URL: **https://smart-campus-energy-optimizer-2ip5.onrender.com**
* Health probe (live-tested during submission):  
  `GET https://smart-campus-energy-optimizer-2ip5.onrender.com/health` → `{"status":"ok"}` 200
* Optimizer endpoint:  
  `POST https://smart-campus-energy-optimizer-2ip5.onrender.com/optimize-energy`

`GEMINI_API_KEY` is configured as a secret in the Render dashboard and
is **not** present in this repository or in the Docker image. On Render
free-tier, the instance may cold-start after inactivity; the first
`/optimize-energy` call after a cold start may take ~10–20 s while
uvicorn imports the app.

> **Note on live POST testing.** During submission preparation, the
> deployed `/health` endpoint was probed and returned `200`. The full
> `POST /optimize-energy` path was exercised end-to-end through the
> local test suite (`tests/test_live_samples.py`, gated on
> `GEMINI_API_KEY`) and via Docker locally, but was **not** smoke-tested
> against the deployed Render URL as part of the submission prep window.

---

## 15. Frontend integration

See [`FRONTEND_API_INTEGRATION.md`](./FRONTEND_API_INTEGRATION.md) for
the dedicated integration guide. Quick pointers:

* No CORS middleware is installed in this repo. If you embed the API on
  a different origin (frontend on `example.com`, API on
  `*.onrender.com`), the browser will block cross-origin requests
  unless you add a `CORSMiddleware` to `app/main.py` *or* put the
  frontend behind a same-origin reverse proxy. This is a deliberate
  TODO, not an oversight — for the hackathon judges (same machine,
  server-side) CORS does not matter.
* Request/response bodies are exactly the Pydantic models; no extra
  wrapping is needed.
* The `plan_summary` field is plain English and is safe to surface
  directly to the operator.

---

## 16. Dependencies

Pinned in `pyproject.toml` + `uv.lock`. Runtime only:

| Package | Why |
|---|---|
| `fastapi` | HTTP framework |
| `pydantic` (v2) | Request/response models (`extra="forbid"`) |
| `uvicorn[standard]` | ASGI server |
| `google-genai` | Gemini SDK |
| `httpx` | Used by the FastAPI test client |
| `ortools` | CP-SAT solver |

Dev only:

| Package | Why |
|---|---|
| `pytest` | Test runner |

Python `>=3.11` is required (per `pyproject.toml`'s
`requires-python`).

---

## 17. Known limitations

* **Single 24-hour horizon.** The model has no rolling lookahead or
  day-to-day state. The end-of-day neutrality constraint forces the
  battery back to its initial state.
* **No demand-side flexibility.** The model only shifts energy
  *supply* (grid ↔ battery); it cannot defer load.
* **No uncertainty modelling.** Solar, demand, and tariff are taken as
  exact point forecasts.
* **No CORS middleware.** See §15.
* **Gemini only at runtime.** `LLM_PROVIDER=static` exists for tests
  but is not a production path.
* **Render cold-start.** First request after the instance sleeps may
  take ~10–20 s.

---

## 18. Security & data policy

* `GEMINI_API_KEY` is **never** baked into the Docker image, the source
  tree, or the README. It is supplied at runtime.
* The container runs as a non-root user (`uid 10001`).
* No operator note content is persisted by the service. Each request is
  stateless: it is interpreted, scheduled, validated, returned, and
  forgotten.
* The 10 public sample cases are stored under `tests/data/` for
  reproducibility; they are organiser-provided, not user data.
* The service does not log `GEMINI_API_KEY`, full request bodies, or
  full response bodies at INFO level; only `scenario_id`, `notes` count,
  and solver metadata.

---

## 19. Submission & reproducibility checklist

- [x] `GET /health` returns `{"status":"ok"}` 200 — tested live on Render.
- [x] `POST /optimize-energy` returns a response that satisfies every
      GridWise constraint for the 10 public sample cases
      (`tests/test_public_samples.py`, 10 parametrized cases + sanity tests).
- [x] `tests/test_live_samples.py` exercises the LLM-driven end-to-end
      pipeline on every public case when `GEMINI_API_KEY` is set.
- [x] `tests/test_final_validator.py` covers every constraint failure
      path.
- [x] `Dockerfile` builds cleanly, runs as non-root, exposes 8000, has a
      `/health` probe, and runs the deterministic test suite in-container.
- [x] `pyproject.toml` + `uv.lock` pin every dependency.
- [x] `.env.example` documents every environment variable and **does
      not** contain a real key.
- [x] `FRONTEND_API_INTEGRATION.md` covers the frontend integration
      guide (request/response shape, complete SAMPLE-01 example, jq
      smoke-test).
- [x] No `GEMINI_API_KEY` in the repo, no `.env` in the repo.
- [x] End-of-day battery neutrality enforced.
- [x] Fail-closed contract: LLM failures produce clean HTTP errors,
      never silent `no_op` substitution.

---

**Submission URL:** https://smart-campus-energy-optimizer-2ip5.onrender.com
**Repository:** this directory
