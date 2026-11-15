# Corvid

Corvid is an evidence-first drawing assistant. Upload a PDF, PNG or JPEG, select a page, and ask a question. Answers link to source regions that you can inspect in the drawing viewer.

## What it does

- Extracts printed room-area measurements and adds supported operands using Decimal arithmetic.
- Resolves explicit room identifiers and unique source room names; ambiguous names require clarification.
- Measures eligible native PDF room polygons using a validated graphic scale.
- Displays rectangles, room boundaries, source labels and scale evidence in one coordinate system.
- Supports optional model-based visual questions, with explicit review status, cost reporting and a durable spending ledger.

Corvid is a bounded prototype, not a universal room detector. Native extraction requires suitable PDF content. Model-proposed regions are not independently verified. An experimental doorway prompt did not pass its development gate and is not included in the current runtime. No unseen-drawing generalization claim is made.

## Run locally

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --frozen
STOA_ENABLE_PAID_API=0 uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/ . Paid inference is disabled by default. Printed-area and eligible geometry routes work without API credentials. Uploads, generated images and SQLite state are created locally at runtime and must remain ignored.

The UI is plain HTML/CSS/JavaScript and SVG; no frontend build step, npm packages, external fonts or CDNs are required.

## Public examples

Three small, explicitly licensed development PDFs are included solely as runnable examples and regression fixtures, not a dataset release. Two are also linked in the demo guide:

- `site1000_bldg2082_floor9385.pdf`: ask “Could you add the areas of rooms 2.01 and 2.02 in sqm, please?” The printed sum is 27.66 m².
- `site2293_bldg3380_floor15055.pdf`: ask “What is the area of room 4.23?” Inspect its polygon and scale evidence.
- `site4085_bldg6548_floor26706.pdf`: a separate development source for name-resolution regression checks.

Original Swiss Dwellings attribution and CC BY 4.0 terms are retained in the adjacent `LICENSE.md` files. See [the original dataset](https://doi.org/10.5281/zenodo.7788422). No overall software license is asserted by this export; select a software license before representing the code as licensed open source.

## Tests

```sh
STOA_ENABLE_PAID_API=0 uv run pytest -q
```

Runtime tests mock provider access and use temporary storage. Pure scoring/payload helpers are included without the private evaluation runner. One historical evaluation-membership test is skipped because evaluation metadata is intentionally excluded. This is distinct from the private answer data, which is never included.

Deployment tests are separate and require the isolated Modal SDK, not the normal local test environment:

```sh
uv tool run --from modal==1.6.4 --with-requirements deployment/requirements.txt --with httpx==0.28.1 python -m unittest discover -s deployment/tests -v
```

## Technology

Python 3.12; FastAPI/Starlette; Pydantic; PyMuPDF; Pillow; Shapely; SQLite; OpenAI Responses API for optional visual queries; vanilla browser JavaScript and SVG; Modal CPU hosting with a persistent Volume.

## Deployment and credentials

`modal_app.py` contains the CPU adapter: 1 CPU, 2048 MiB RAM, no GPU, one web container, a 180-second timeout and persistent SQLite/document storage. Use the `recreate` strategy to avoid overlapping writers.

This public copy uses separate `corvid-public-*` Modal resource names rather than targeting the existing production resources. It contains no keys, dotenv files, account configuration, database, ledger transfer or cloud credentials.

Paid activation deliberately remains gated. Historical private release/ledger artifacts are omitted, so enabling paid deployment requires an independently verified release and a safe ledger initialization procedure. Do not bypass those guards, reset production spending, or import an obsolete ledger. The existing cumulative cap is $2; unknown reservations must remain reserved.

For local use, keep `STOA_ENABLE_PAID_API=0`. If configuring optional paid access later, provide `OPENAI_API_KEY`, `STOA_ENABLE_PAID_API`, and `STOA_API_BALANCE_VERIFIED` through a local ignored secret file or a scoped Modal Secret. Never place credential values in frontend code or commit them.

## Public-export contents

Included: backend, frontend, tests, deployment source, pinned dependencies, API contracts and the three licensed public PDF fixtures.

Excluded: all real credentials and dotenv files; private evaluation questions/answers and membership; historical model responses; spend records and transfer files; databases; full datasets; caches; build outputs; screenshots; logs; Git metadata; and rollback archives.

See `PUBLIC_EXPORT_AUDIT.json` for the per-file scan inventory and verification limits. No model calls, publishing or deployment were performed to prepare this folder.
