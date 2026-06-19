# 📚 Recipe Digitizer

Turn photos of cookbook pages into structured, searchable recipes — stored locally and optionally pushed to a [Mealie](https://mealie.io) instance for meal planning and a polished mobile UI.

Each page is run through OCR, parsed into structured fields by GPT-4o (using the photo *and* the OCR text), de-duplicated, saved to a local SQLite database, exported as Markdown, and — if you want — synced to Mealie.

---

## ✨ Features

- **OCR + AI extraction** — Apple Vision (macOS) or Tesseract (Linux/Raspberry Pi), then GPT-4o turns the text + image into a clean recipe (ingredients, steps, times, servings, tags, background notes).
- **Per-cookbook configuration** — an AI wizard analyses a sample page and writes a `config.json` describing the cookbook's layout/language, which sharpens extraction.
- **Deduplication** — every image is SHA-256 hashed; re-processing the same photo is skipped automatically.
- **Local-first storage** — everything lives in `data/recipes.db` plus Markdown exports. No cloud lock-in.
- **Mealie integration** — one-click or bulk sync, change detection so only updated recipes are re-pushed, and a delete-all option. Every synced recipe is tagged `recipe_digitizer`.
- **Two interfaces** — a Streamlit web app and a `click` CLI.

---

## 🧭 How it works

```
 Photo ─▶ OCR (Apple Vision / Tesseract) ─▶ GPT-4o parsing ─▶ SQLite + Markdown ─▶ (optional) Mealie
            │                                  │
            └─ confidence score                └─ guided by the cookbook's config.json
```

1. **Hash & dedupe** — SHA-256 of the image is checked against the DB.
2. **OCR** — the best available backend extracts text + a confidence score.
3. **Parse** — GPT-4o receives the OCR text (primary source) and the image (for layout/handwriting) plus cookbook hints, and returns structured JSON.
4. **Store** — saved to SQLite and exported to `cookbooks/<name>/extracted/<Recipe>.md`.
5. **Sync (optional)** — pushed to Mealie via its REST API; the Mealie slug is recorded back in the DB.

---

## 📁 Project structure

```
recipe-manager/
├── recipe_app.py                    # Streamlit web interface
├── recipe_cli.py                    # Command-line interface (click)
├── recipe_processor_integrated.py   # Core pipeline (OCR → AI → DB → Markdown → Mealie)
├── ocr_backends.py                  # OCR abstraction: Apple Vision + Tesseract, auto-detect
├── apple_ocr.swift                  # Apple Vision OCR (macOS), called as a subprocess
├── database.py                      # SQLite manager + Recipe/Cookbook dataclasses
├── mealie_client.py                 # Mealie REST client
├── cookbook_config.py               # AI-powered cookbook config wizard
├── requirements.txt
├── Dockerfile                       # Container image (Tesseract + app)
├── docker-compose.yml               # Service definition for the Pi
├── .dockerignore
├── config/
│   ├── settings.yaml                # Global settings (optional)
│   ├── openai_config.json           # OpenAI API key (gitignored)
│   └── mealie_config.json           # Mealie URL + API token (gitignored)
├── data/
│   └── recipes.db                   # SQLite database
└── cookbooks/
    └── <cookbook-name>/
        ├── config.json              # Per-cookbook extraction config
        ├── images/                  # Source page photos
        └── extracted/               # Markdown exports
```

> The `data/`, `cookbooks/`, and `config/` folders are gitignored — they hold your personal recipes and credentials.

---

## 🚀 Installation

### 1. Dependencies

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 2. OCR backend

The app auto-selects an OCR backend at runtime — Apple Vision on macOS, Tesseract elsewhere.

- **macOS** — Apple Vision works out of the box (needs Xcode command-line tools: `xcode-select --install`).
- **Linux / Raspberry Pi** — install Tesseract:
  ```bash
  sudo apt install tesseract-ocr
  sudo apt install tesseract-ocr-deu     # add language packs as needed (deu, fra, ita, …)
  pip install pytesseract
  ```
  Tesseract is lightweight and ARM-friendly; combined with GPT-4o's image understanding it gives good results on clean cookbook print.

### 3. OpenAI API key

Create `config/openai_config.json` with your key — this is the single source of truth (the file is gitignored):

```json
{
  "api_key": "sk-..."
}
```

The app reads this file fresh before every AI call, so you can rotate the key by editing the file without restarting. There is no environment-variable or sidebar fallback.

> The **CLI** (`recipe_cli.py`) is the exception — it takes the key from the `--openai-key` flag or the `OPENAI_API_KEY` environment variable instead. See [CLI](#-cli).

---

## ⚙️ Configuration

### Global settings — `config/settings.yaml` (optional)

```yaml
database_path: "data/recipes.db"
output_format: "markdown"
skip_duplicates: true
confidence_threshold: 0.7

openai_model: "gpt-4o"
openai_temperature: 0.1

mealie_enabled: true
mealie_auto_sync: false
```

### Mealie credentials — `config/mealie_config.json`

Mealie connection details are read from this file (so you don't re-enter them each session):

```json
{
  "base_url": "http://mealie.home",
  "api_token": "your-mealie-api-token"
}
```

Generate the token in Mealie under **Profile → API Tokens**. This file is gitignored — keep your token out of version control.

### Cookbook configuration — `cookbooks/<name>/config.json`

Each cookbook can carry a config that tells the parser about its layout, language, and quirks. The easiest way to create one is the **AI wizard** (see below). A config looks like:

```json
{
  "cookbook": {
    "name": "Jerusalem",
    "authors": ["Yotam Ottolenghi", "Sami Tamimi"],
    "language": "en",
    "cuisine": "Middle Eastern"
  },
  "layout": {
    "typical_columns": 2,
    "title_position": "top",
    "has_background_stories": true,
    "ingredients_side": "left-column",
    "instructions_side": "right-column"
  },
  "extraction_hints": {
    "description": "Background stories at the top, separate from cooking steps.",
    "special_instructions": "Put intro text in background_info, numbered steps in instructions.",
    "common_headings": {
      "ingredients": ["Ingredients", "Zutaten"],
      "instructions": ["Method", "Zubereitung"]
    },
    "language_specific": { "output_language": "en", "do_not_translate": false }
  },
  "default_tags": ["middle-eastern", "ottolenghi"]
}
```

Both the nested format above and an older flat format (`book_name`, `layout_hints`, `extraction_instructions`) are supported.

#### Config field reference

| Field | Type | Description |
|-------|------|-------------|
| `cookbook.name` | string | Cookbook display name |
| `cookbook.authors` | array | Author names |
| `cookbook.language` | string | ISO code (`en`, `de`, `fr`, `es`, `it`) — also drives the Tesseract language pack |
| `cookbook.cuisine` | string | Cuisine, used for Mealie category |
| `layout.typical_columns` | int | 1, 2, or 3 |
| `layout.title_position` | string | `top`, `center`, `left-column`, `right-column` |
| `layout.has_background_stories` | bool | Does it mix story text with recipes? |
| `layout.ingredients_side` / `instructions_side` | string | Column positions for multi-column books |
| `layout.has_handwritten_notes` | bool | Are handwritten notes common? |
| `extraction_hints.description` | string | Short description of the book's style |
| `extraction_hints.special_instructions` | string | Detailed parsing guidance for the AI |
| `extraction_hints.common_headings` | object | Language-specific heading words |
| `extraction_hints.language_specific.do_not_translate` | bool | Keep original language (true for non-English) |
| `default_tags` | array | Tags applied to all recipes from this cookbook |

---

## 🐳 Docker (Raspberry Pi deployment)

The repo ships a `Dockerfile` and `docker-compose.yml` so the app can run as a long-lived service on a Raspberry Pi — sitting nicely alongside a Dockerized Mealie. The image bundles Tesseract (with German/French/Italian/Spanish language packs), so OCR works without any macOS dependency; the app auto-selects Tesseract inside the container.

### Prerequisites

- **64-bit Raspberry Pi OS (arm64).** `streamlit` pulls in `pandas`/`pyarrow`, which have prebuilt arm64 wheels — on 32-bit OS there are no `pyarrow` wheels and the build will fail.
- Docker + the Compose plugin installed (`curl -fsSL https://get.docker.com | sh`).
- A Pi 4/5 with **4 GB+ RAM** is comfortable (2 GB is tight during the build).

### Step-by-step setup

Your recipes (`data/recipes.db`), cookbook images, and credentials (`config/mealie_config.json`, the OpenAI key) are **gitignored**, so they must be placed on the Pi separately from the code. The steps below include migrating your existing data. Replace `pi@raspberrypi.local` with your Pi's user@host.

**1. Confirm 64-bit OS** — on the Pi:
```bash
uname -m        # aarch64 = good. armv7l = 32-bit → reflash 64-bit Raspberry Pi OS first
```

**2. Install Docker** — on the Pi:
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
sudo systemctl enable docker        # start Docker (and the app) on boot
# log out/in (or: newgrp docker), then verify:
docker version && docker compose version
```

**3. Copy the project + existing recipes** — from your Mac. `rsync` brings the code *and* the gitignored data/config in one shot:
```bash
rsync -av --exclude venv --exclude .git --exclude __pycache__ --exclude .DS_Store \
  ~/Dropbox/Projekte/recipe-manager/ pi@raspberrypi.local:~/recipe-manager/
```
*(Alternatively `git clone` the repo on the Pi, then `scp` `config/mealie_config.json` and `rsync` `data/` + `cookbooks/` over separately.)*

**4. Set the OpenAI key** — on the Pi (`config/openai_config.json` must exist before starting):
```bash
cd ~/recipe-manager
nano config/openai_config.json      # {"api_key": "sk-..."}
cat config/mealie_config.json       # confirm the Mealie URL + token came across
```

**5. Build and start** — on the Pi (first build takes a few minutes):
```bash
docker compose up -d --build
```

**6. Verify** — on the Pi:
```bash
docker compose ps                                # State: running (healthy)
docker compose logs -f                           # watch startup (Ctrl-C to stop)
curl -fsS http://localhost:8501/_stcore/health   # prints "ok"
```
Then open **`http://raspberrypi.local:8501`** (or `http://<pi-ip>:8501`) in a browser.

**7. Confirm Mealie is reachable from the container** — see [Reaching Mealie](#reaching-mealie-from-the-container) below.

`restart: always` plus the enabled Docker service means the container auto-starts after a reboot — no systemd unit needed. Updating later: `git pull` (or re-run the rsync), then `docker compose up -d --build` (see [Everyday commands](#everyday-commands)).

### What persists

`docker-compose.yml` mounts three host folders into the container, so nothing is lost on rebuild or restart:

| Host path | Purpose |
|-----------|---------|
| `./data` | `recipes.db` (the database) |
| `./cookbooks` | source images + Markdown exports |
| `./config` | `openai_config.json` (API key) + `mealie_config.json` (Mealie URL + token) |

The OpenAI key comes from `config/openai_config.json`; `config/` is mounted, not baked into the image (see `.dockerignore`).

### Everyday commands

```bash
docker compose logs -f                  # follow logs
docker compose restart                  # restart
docker compose pull && docker compose up -d --build   # update after `git pull`
docker compose down                     # stop & remove the container
```

### Reaching Mealie from the container

The app connects to Mealie using the `base_url` in `config/mealie_config.json` (e.g. `http://mealie.home`). Docker forwards DNS to the host's resolver, so a Pi-hole hostname normally resolves inside the container. If it doesn't, pin it in `docker-compose.yml`:

```yaml
    extra_hosts:
      - "mealie.home:192.168.1.50"   # your Pi's LAN IP
```

> Note: HEIC photos (e.g. straight from an iPhone) are supported in the container via `pillow-heif`, which is included in `requirements.txt`.

---

## 🖥️ Streamlit web app

```bash
streamlit run recipe_app.py
```

The sidebar shows whether the OpenAI key was loaded (from `config/openai_config.json`), the Mealie integration (auto-loaded from `config/mealie_config.json`), and a **Sync Database** section. The main area has five tabs:

| Tab | What it does |
|-----|--------------|
| **📖 Recipes** | Sortable table of every recipe (title, cookbook, tags, ingredient/step counts, time, servings, sync status). Click a column header to sort, click a row to open a detail panel with ingredients, instructions, the source image, and actions (Edit, Sync, Download MD, Delete). Filter by cookbook and sync status. |
| **📚 Cookbooks** | Manage existing cookbooks (edit config, **regenerate config from a sample page via AI**, view recipes, **delete**) and create new ones with the AI config wizard. Regenerate is available even after a cookbook exists, so you can recover one whose config fell back to default values when AI generation failed at creation time. Deleting a cookbook removes all its recipes — including their Mealie copies (when Mealie is enabled) — and can optionally delete the cookbook's folder from disk. |
| **📤 Upload** | Drag-and-drop recipe photos, pick a cookbook, and process them (with optional Mealie sync). |
| **🔍 Search** | Search recipes by title, ingredient, or tag. |
| **📊 Statistics** | Totals, processing status, Mealie sync counts, and per-cookbook breakdown. |

### Sidebar — Sync Database

- **🆕 / ✏️ / ✅ counts** — shows how many recipes are new, changed since last sync, or up to date. Change detection uses a content fingerprint, so only genuinely-edited recipes are re-pushed.
- **☁️ Sync All to Mealie** — creates new recipes and updates changed ones; unchanged recipes are skipped. Deleted-in-Mealie recipes are automatically recreated.
- **⚠️ Danger zone → 🗑️ Delete All from Mealie** — removes every recipe this app synced (those tagged `recipe_digitizer`) and clears the local sync state. Recipes you added to Mealie by other means are left untouched. Gated behind a confirmation checkbox.

---

## 🧰 CLI

```bash
# Process a single image (cookbook defaults to the parent folder name)
python recipe_cli.py process image.jpg --cookbook "Jerusalem"

# Process an entire folder (uses the folder's config.json if present)
python recipe_cli.py process cookbooks/jerusalem/images/

# Process and sync to Mealie in one go
python recipe_cli.py process cookbooks/jerusalem/images/ --sync-mealie

# Re-process, ignoring the dedupe check
python recipe_cli.py process image.jpg --cookbook "Jerusalem" --no-skip-duplicates

# Database
python recipe_cli.py stats
python recipe_cli.py list --cookbook "Jerusalem" --limit 10
python recipe_cli.py search "chicken"

# Sync existing recipes to Mealie
python recipe_cli.py sync --all
python recipe_cli.py sync --cookbook "Jerusalem"

# Create a new cookbook (AI analysis optional)
python recipe_cli.py init-cookbook "Ottolenghi Simple" \
  --authors "Yotam Ottolenghi" --language en --cuisine Mediterranean \
  --sample-page cookbooks/ottolenghi-simple/images/page1.jpg

# Interactive cookbook wizard
python recipe_cli.py init-cookbook --interactive
```

The OpenAI key for the CLI comes from the `--openai-key` flag or the `OPENAI_API_KEY` environment variable (the CLI does **not** read `config/openai_config.json` — that file is the web app's source). Mealie URL/token for the CLI come from `--mealie-url` / `--mealie-token` flags or the `MEALIE_URL` / `MEALIE_TOKEN` environment variables.

---

## 🤖 AI cookbook wizard

Instead of writing `config.json` by hand, upload one representative page and GPT-4o Vision detects the layout for you.

**In Streamlit:** Cookbooks tab → Create New → fill in basics → upload a sample page → **Analyze & Create**. Review the detected structure, edit if needed (Pretty View form or raw JSON), and save.

**In the CLI:** use `init-cookbook` with `--sample-page` (see above), or `--interactive` for guided prompts.

The wizard detects language, column count, title/ingredient/instruction positions, background stories vs. steps, handwritten-note locations, and common headings — then writes a config tuned to that book. Cost is roughly **$0.01–0.02 per analysis**.

**Tips**
- Pick a *typical, complete* recipe page — not a title page or index.
- Always review the detected language for non-English books.
- If a book has inconsistent layouts, configure for the most common one and describe variations in `extraction_hints.special_instructions`.
- After changing a config, reprocess with `--no-skip-duplicates` to apply it.

---

## ☁️ Mealie integration

[Mealie](https://mealie.io) is a separate, self-hosted recipe manager with a polished mobile UI, meal planning, and shopping lists. **It is optional** — this app works fully without it. When enabled, the app pushes recipes to Mealie via its REST API; the two databases stay separate and updates flow one way (this app → Mealie).

### Run Mealie with Docker (e.g. on a Raspberry Pi)

```yaml
# ~/mealie/docker-compose.yml
services:
  mealie:
    image: ghcr.io/mealie-recipes/mealie:latest
    container_name: mealie
    restart: always
    ports:
      - "9000:9000"
    environment:
      PUID: 1000
      PGID: 1000
      TZ: Europe/Berlin
      DB_ENGINE: sqlite
      ALLOW_SIGNUP: "false"
      BASE_URL: http://mealie.home
    volumes:
      - ./data:/app/data
```

```bash
cd ~/mealie && docker compose up -d        # start
docker compose logs -f                      # logs
docker compose pull && docker compose up -d # update
tar -czf mealie-backup-$(date +%Y%m%d).tar.gz ~/mealie/data/  # backup
```

Then open `http://<host>:9000`, create your account, and generate an API token under **Profile → API Tokens**. Put the URL and token in `config/mealie_config.json` (see Configuration above) and use **Test Connection** in the sidebar to verify.

### How sync behaves

- **Create** uses Mealie's two-step flow (create by name → populate via round-trip update), so ingredients/instructions/tags all land correctly.
- **Tags & categories** are resolved (get-or-create) to real Mealie objects, and every recipe gets the `recipe_digitizer` tag so app-synced recipes are identifiable.
- **Change detection** stores a content fingerprint per recipe; bulk sync only re-pushes recipes whose content actually changed.

---

## 🔤 OCR backends

| Backend | Platform | Notes |
|---------|----------|-------|
| **Apple Vision** | macOS | Default on macOS; high accuracy, multi-language, no extra install (uses `apple_ocr.swift`). |
| **Tesseract** | Linux / Raspberry Pi / Windows | Lightweight and ARM-friendly. Pillow preprocessing (grayscale, contrast, sharpen) improves results. Language follows the cookbook's config. |

`ocr_backends.py` exposes a common `OCRBackend` interface and an `auto_detect_backend()` that prefers Apple Vision and falls back to Tesseract. You can also pass an explicit backend to `IntegratedRecipeProcessor`.

---

## 🗄️ Database

SQLite at `data/recipes.db`, with three tables:

- **cookbooks** — name, authors, language, cuisine, config path.
- **recipes** — title, page, image hash (unique, for dedupe), ingredients/instructions (JSON), times, servings, tags, Markdown path, Mealie id + sync timestamp + sync fingerprint, OCR confidence.
- **processing_log** — every attempt with status (`success` / `failed` / `duplicate` / `skipped`) and any error.

The schema self-migrates on startup (e.g. adding the Mealie sync-hash column to older databases).

---

## 🐛 Troubleshooting

**OpenAI errors** — confirm `config/openai_config.json` exists and contains a valid `api_key`. The sidebar shows whether the key was loaded.

**OCR fails (macOS)** — run `swift apple_ocr.swift test.jpg` directly to see the error; ensure Xcode CLT is installed.

**OCR fails (Linux/Pi)** — confirm `tesseract --version` works and `pip show pytesseract` is installed; install the right language pack (`tesseract-ocr-deu`, etc.).

**Mealie connection fails** — check the instance is up (`curl http://<host>:9000/api/app/about`), the URL/token in `config/mealie_config.json` are correct, and the token hasn't expired.

**Recipe syncs but looks empty / "Recipe already exists"** — these were Mealie v1 API quirks (create accepts only a name; full content needs a round-trip update; tags/categories must carry their real ids). The client handles all of this; if you see it, make sure you're on the current `mealie_client.py`.

**"No config found" when processing** — generate one via the Cookbooks tab or `init-cookbook --sample-page`. Processing still works without a config, just with generic extraction.

**Database locked** — close other processes using it: `lsof data/recipes.db`.

---

## ❓ FAQ

**Do I need a config for every cookbook?** No, but it noticeably improves accuracy. Without one, generic extraction is used.

**Does the AI analysis cost money?** Yes — about $0.01–0.02 per sample-page analysis (GPT-4o Vision).

**Can I run this without Mealie?** Yes. Mealie is an optional enhancement; the app stores and exports recipes on its own.

**My uploaded recipe has no source image in the detail view.** Web uploads are processed from a temporary file that's deleted afterward, so only folder/CLI-processed recipes keep a persistent image path.

**Can I share a config between similar cookbooks?** Yes — copy the `config.json` and edit the name/authors. Handy for book series.

---

*Powered by Apple Vision / Tesseract OCR + OpenAI GPT-4o, with optional Mealie sync.*
