# Genie Agent — "RNI Inventory Intelligence Agent"

- **Space id:** `01f1d4e83ebe1ea089da3d55bd01592f`, warehouse `6674ed0664e1e8a3`. Created through the Genie API by
  `scripts/setup_genie.py`.
- **Tables:** 12 approved Gold objects only (`src/genie/space_config.py::GENIE_TABLES`). No bronze, silver or ml
  tables are attached.
- **Business definitions:** PAR, mandatory minimum, on-hand, shipped vs consumed, return rate, excess, expiration
  risk, inventory exposure, forecast demand, recommended quantity, and an as-of date rule.
- **Verified example SQL:** 8 statements, each executed on the warehouse before upload.
- **Benchmarks:** the same 8 questions are uploaded as Genie benchmarks.

## Live validation (Genie Conversation API, rerun 2026-11-01 after renaming Hospital A / Product A)

Each question was asked through `start_conversation`. The result rows were fetched with
`get_message_attachment_query_result` and compared with the verified SQL result by matching numeric column totals.

| # | Question | Answered by Genie | Matches verified SQL | Rows | Latency |
|---|---|---|---|---|---|
| 1 | Which customers have the highest excess inventory exposure? | yes | yes | 10 | 20.0 s |
| 2 | Which products have the highest return rates? | yes | yes | 10 | 25.8 s |
| 3 | Why was Desert Crest's shipment request flagged? | yes | yes | 1 | 14.8 s |
| 4 | Which products may expire in the next 60 days? | yes | yes | 6 | 20.1 s |
| 5 | Which customers have the highest shipments relative to usage? | yes | **no** | 11 | 20.2 s |
| 6 | How much was returned during the last 12 months? | yes | yes | 1 | 14.9 s |
| 7 | Which shipment requests need review and what is the potential exposure? | yes | yes | 24 | 14.9 s |
| 8 | What is our total inventory deployed and how much is approaching expiration? | yes | yes | 1 | 14.8 s |

Result: 8/8 answered live by Genie; 7/8 matched the verified SQL exactly. Q5 did not: Genie ranked with `RANK() <= 10`, and a tie at 10th place returned 11 customers instead of 10. This is a tie-handling difference in the SQL Genie wrote, unrelated to the rename. The first run (2026-10-31) matched 8/8.

The raw results are in `docs/genie_benchmark_results.json`. To rerun:
`python scripts/setup_genie.py --warehouse-id <id> --space-id <id>`.

## Expected answers (synthetic data, as of 2026-10-30)

- **Q3:** Desert Crest Medical Center / Hyperimmune Globulin 1,500 IU — requested 500, recommended 15, PAR-only baseline 35, on hand 25, PAR 60,
  minimum 40, consumed 1 in 120 days, EXCESSIVE_REQUEST, potential exposure ≈ $436,500.
- **Q6:** returns over the last 12 months ≈ $4.83M of returned inventory value, with ≈ $131K of return logistics
  cost.
- **Q8:** inventory deployed ≈ $3.42M; approaching expiration ≈ $90K; potential excess exposure ≈ $1.42M.

## App integration and fallback

The App's **Ask RNI AI** screen calls the same space through `src/genie/client.py`:

- polling with backoff
- retry on 429 and 5xx responses
- a 120-second timeout
- friendly error text instead of raw errors

If Genie is unavailable, the screen answers the prevalidated questions with fixed, verified SQL. Those answers are
badged **"Curated SQL fallback — not a Genie response"**.
