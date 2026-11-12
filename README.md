# iimagica Testing Platform (backend-only, no Flutter)

One AI model powers **every** iimagica feature. Models are switched through
`config.yaml` (or a live API call) — **never by editing code**.

## Default model choice (one model for all features)

**`gemini-nano-banana-2.1`** (Gemini "Nano Banana 2.1") — chosen because it is the
only mainstream single model that covers all four AI features:

| iimagica feature (from spec) | Interface method | Covered by model? |
|---|---|---|
| Poster background generation (text-to-image) | `generate_image()` | ✅ image output |
| Poster editing / background replace / logo-safe edit (image-to-image) | `edit_image()` | ✅ text+image→image |
| Logo & image understanding (frame analysis) | `analyze_image()` | ✅ image input |
| Frame design suggestion (JSON) | `suggest_layout()` | ✅ text output |
| Footer design suggestion (JSON) | `suggest_layout()` | ✅ text output |
| Prompt enhancement | `enhance_prompt()` | ✅ text output |
| Brand color extraction | `/colors` (pure code: NumPy k-means) | n/a — code task, no model |
| Background removal / upscaling | `/remove-bg`, `/upscale` (code utilities) | n/a |

Model facts verified from Google AI Studio docs: inputs Text/Image/Video/PDF,
outputs Image + Text, stable model id `gemini-nano-banana-2.1`, image editing by
sending base64 image + text (Interactions API), optional `response_format`
`[{"type":"text"},{"type":"image"}]`.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env            # put your GEMINI_API_KEY / FLUX_API_KEY here
uvicorn app.api:app --reload    # http://127.0.0.1:8000/docs
```

No API key? Everything still runs — the built-in `mock` provider returns
placeholder output so tests and the dashboard work offline.

## Switching models — the core promise

### Option 1: edit `config.yaml` (no code change)

```yaml
default_provider: gemini          # ← change to "mock", "gemini_lite", "flux", ...
providers:
  gemini:
    class: providers.gemini_provider.GeminiProvider
    model_id: gemini-nano-banana-2.1
  gemini_lite:                    # a second real provider, swap-ready
    class: providers.gemini_provider.GeminiProvider
    model_id: gemini-3.1-flash-image
  flux:                           # second model adapter — drop-in file
    class: providers.flux_provider.FluxProvider
    model_id: flux-pro-1.1        # generation via BFL /v1/flux-pro-1.1
    api_key_env: FLUX_API_KEY
features:                          # per-feature override beats default
  generate_image: null             # null → use default_provider
  edit_image: null                 # e.g. edit_image: gemini, generate_image: flux
```

FLUX (Black Forest Labs) is a true drop-in: one file (`providers/flux_provider.py`),
selected purely by the config lines above. It supports `generate_image` and
`edit_image` (via `flux-kontext-pro`); text features are not declared and the
registry rejects them clearly. BFL is credit-based (not free-tier) — reported
honestly by `health_check`.

### Option 2: switch live via API (testing dashboard behaviour)

```bash
curl -X POST localhost:8000/switch -H 'Content-Type: application/json' \
     -d '{"provider": "gemini_lite"}'
curl localhost:8000/models        # see every registered provider + features
```

### Option 3: per-feature selection

`features.edit_image: gemini` + `features.generate_image: gemini_lite` —
different models for different features, exactly as the spec requires.

## API endpoints (one per feature)

| Endpoint | Feature |
|---|---|
| `POST /generate` | poster background generation |
| `POST /edit` | image editing (with optional reference/logo image) |
| `POST /analyze` | logo/image understanding |
| `POST /layout` | frame or footer design suggestion (JSON) |
| `POST /enhance` | prompt enhancement |
| `POST /colors` | brand color extraction (code, no model) |
| `GET /models` | registered providers, capabilities, current selection |
| `POST /switch` | change default provider at runtime |
| `GET /health` | provider health check |
| `POST /remove-bg` | background removal (code, no model) |
| `POST /upscale` | 2-4x Lanczos upscale (code, no model) |
| `POST /compare` | same prompt on many providers: time, errors, images |
| `POST /compare/{id}/rate` | six-criteria rating (1-5) |
| `GET /compare/history`, `GET /leaderboard` | history; success rate, avg time, avg ratings |
| `POST/GET /gallery`, `POST /gallery/{id}/favorite`, `DELETE /gallery/{id}` | save, search (`q`, `favorite`), favourite, delete |

## CLI

```bash
python -m app.cli generate "Diwali sale poster background, marigold theme"
python -m app.cli layout frame --business "Sharma Sweets"
python -m app.cli models
python -m app.cli switch mock
```

## Tests

```bash
pytest -v          # all tests use the mock provider — no API key needed
```

## Adding a brand-new provider (e.g. FLUX on Replicate) tomorrow

1. Create `providers/<name>_provider.py` implementing `BaseProvider` — implement
   only the features you support and list them in `capabilities`.
2. Add a block under `providers:` in `config.yaml` with its class path.
3. `switch` to it (or edit `default_provider`). Zero changes to the engine,
   API, or tests. `providers/flux_provider.py` is the working example.

## v3 additions (studio, lab, platform)

Projects/editor API: `/templates`, `/projects` (create, list, ops, undo, redo, duplicate, favorite, render, per-layer regenerate),
`/brands`, `/qr`, `/festivals`, `/suggestions`, `/languages`, `/captions`, `/layout-suggest`, `/evaluate`, `/brand-check`,
`/replace-background`, `/remove-object`, `/expand`, `/variations` (4-8), `/bulk`, `/jobs/{id}`, `/benchmark`
(generate / edit / text features, repeats), `/reports/benchmark?format=csv|json`, `/quota`, `/errors`, `/backup`, `/restore`, `/campaigns`.

Optional per-provider keys in `config.yaml`: `cost_per_image`, `daily_limit` (used for cost tracking and quota).
Movable festivals (Diwali, Holi, Eid...) return `date_varies: true`: check the year's calendar before publishing.

## v5: editor + gap-fill (open `/editor` after `uvicorn app.api:app`)

- **Editor page** (`/editor`): drag/resize, multi-select (shift), groups, align/distribute, snapping guides + grid, layers panel
  (reorder, lock, hide), properties panel (text, fonts, colours, opacity, rotation, image masks), keyboard shortcuts
  (Ctrl+Z/Y/D/C/V/A/G, Delete, arrows), AI background, brand apply, footer designer, PNG/JPG/PDF export (transparent option).
- **New layer ops** via `POST /projects/{id}/ops`: `batch`, `group`, `ungroup`, `align`, `distribute`, `paste`. New layer types: `polygon`, `wave`, `frame`; image `mask`; text `font`.
- **Dashboard**: `/dashboard` (search, sort, folder, favourite), `/folders`, `/projects/{id}/meta|thumbnail|bg|versions|restore`.
- **Fonts**: `GET/POST /fonts` (upload .ttf/.otf, then set a layer's `font`).
- **Brand + footer**: `/projects/{id}/apply-brand`, `/projects/{id}/footer`, `/footer-presets`.
- **Sizes**: `/projects/{id}/resize`, `/convert` (festival x language x size), `/campaign-set`, `/export/batch` (zip).
- **AI editing**: `/region-edit` (inpaint/remove/edit a box only), `/style-transfer`, `/expand` with `"ai": true`, `/replace-subject-bg`.
- **Text**: `/proofread` (rules; `use_ai` optional), `/translate`, `/projects/{id}/translate`, `/recommend-model`.

## v6: design intelligence, workflow safety, India support
- **Checks:** `GET /projects/{id}/check?margin_pct=3&bleed_mm=3` (contrast, overlaps, safe margin/bleed, alignment, low-res, balance, score);
  `POST /projects/{id}/fix` applies safe fixes as one undoable version (skips locked layers); `POST /projects/{id}/message-check` (AI reads the render).
- **Compare** versions side by side: `GET /projects/{id}/compare?a=0&b=-1`. **Fonts:** `/fonts/search?q=`, `/font-pairing?lang=hi` (bundled fonts only).
- **AI workflow:** `/prompts` (save/search/delete), `/assets` (icons, stickers, illustrations, references, logos; searchable), `POST /generate/fallback`
  (opt-in provider order; response names the provider used), `GET /jobs` (find jobs after a refresh), duplicate-request guard (409 while an identical call runs).
- **India:** `/format-in` (₹12,34,567, Hindi dates, Devanagari digits), `/print-sizes` (A3/A5/A6/DL/visiting card/12x18 with 3 mm bleed), `/business-categories`,
  `POST /projects/from-category`, `/recommend-design`, `/festivals/verified` (sourced dates only).
- **Safety/reliability:** uploads to `/assets`, `/projects/{id}/bg` and `/fonts` are validated and images re-encoded; `POST /storage/cleanup` (dry run by default);
  `/usage/summary`; automatic backups every `auto_backup_hours` (config.yaml). Editor: paste or drop an image to add it.

## v7: Model Lab (benchmark and production selection)
Open `/model-lab` after `uvicorn app.api:app`. API under `/model-lab/*` (providers, test-connection, dataset, benchmark, results, rate, leaderboard, report, select-winner, selection).
- **New providers** (one file each, drop-in via `config.yaml`): `cloudflare_provider` (needs `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`), `huggingface_provider` (`HF_TOKEN`), `pollinations_provider`.
  Their request formats were written from provider docs and are **unverified until you press "Live test"**. The FLUX.2 multipart format on Cloudflare is the least certain.
- **Dataset:** `benchmark_data/prompts/poster_prompts.json` (10 generation prompts + 2 logo/reference tests that need an uploaded image). Don't edit entries between runs.
- **Money rules:** each provider has `billing` in `config.yaml` (`free`, `free_tier`, `credit`, `unverified`, `unknown`). Anything not free needs `approve_paid` AND `budget > 0` AND `cost_per_image`.
  Set `daily_limit` per provider to your safe number of calls; a quota/429/credit error stops that provider for the rest of the run. There is no paid fallback.
- **Scores:** human ratings (9 criteria incl. text accuracy and logo preservation) drive the leaderboard. Automated estimates (size/aspect, blank check, heuristic design score,
  OCR text match if `pytesseract` is installed) are listed separately and never counted as ratings.
- **Production model:** `POST /model-lab/select-winner` saves to `outputs/model_selection.json`; existing endpoints then use it with no code change.

### Manual testing guide
1. Fill `.env` (see `.env.example`), start the server, open `/model-lab`.
2. Press **Check** on each provider, then **Live test** (one 512px image) for those you want. Fix any `missing key` or HTTP errors first.
3. Set `daily_limit` for free-tier providers, tick them, run one category with repeats = 1, and look at the images.
4. Rate results (especially Hindi text and logos), then run everything with repeats = 3 until you have 50 to 100 comparable samples.
5. Read the leaderboard by category, download the CSV, then **Use** the winner for each feature.
