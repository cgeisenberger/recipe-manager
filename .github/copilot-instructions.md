# Copilot / AI agent instructions — Recipe Manager

Purpose: make code changes quickly and safely by highlighting the repository's architecture, conventions, and concrete edit points.

Big picture
- **UI**: Streamlit web app at [recipe_app.py](recipe_app.py) — session-managed, uses `IntegratedRecipeProcessor` and `DatabaseManager`.
- **CLI**: [recipe_cli.py](recipe_cli.py) — `click` commands wrap the same processor for batch runs (process, stats, sync, init_cookbook).
- **Processing core**: [recipe_processor_integrated.py](recipe_processor_integrated.py) — runs Apple Vision OCR (`apple_ocr.swift`), calls OpenAI to parse, stores results via [database.py](database.py), and optionally syncs to Mealie via [mealie_client.py](mealie_client.py).
- **Data layout**: per-cookbook folders under `cookbooks/<name>/` with `images/` and `extracted/` Markdown outputs. Cookbooks may include `config.json` with extraction hints (see [cookbooks/jerusalem/config.json](cookbooks/jerusalem/config.json)).

Key developer workflows (concrete)
- Install deps: `pip install -r requirements.txt`.
- Run UI: `streamlit run recipe_app.py`.
- Run CLI examples:
```
python3 recipe_cli.py process cookbooks/jerusalem/images/ -c jerusalem
python3 recipe_cli.py stats
python3 recipe_cli.py sync --mealie-url $MEALIE_URL --mealie-token $MEALIE_TOKEN
```
- Database: default path is `data/recipes.db` (config in `config/settings.yaml`). Duplicate detection uses SHA256 image hashes and the `image_hash` unique constraint in `recipes` table (see [database.py](database.py)).

Project-specific conventions and constraints
- OpenAI parsing: the system/user prompt in `_parse_with_openai` expects a precise JSON shape (title, ingredients, instructions, handwritten_notes, background_info, prep_time, cook_time, total_time, servings, tags). When changing parsers, preserve exact field names and the rule: instructions must be paragraph-based (not sentence-split).
- OCR vs text: OCR output (Apple Vision) is the primary source; the image is supplemental for layout/handwritten notes. See `recipe_processor_integrated.py` for the exact instruction text used to prompt the model.
- Markdown export: titles are sanitized and truncated to 50 chars and written to `cookbooks/<name>/extracted/<safe_title>.md` (see `_export_markdown`). Keep export format when modifying storage or filenames to preserve downstream consumers.
- Cookbook config: `cookbooks/<name>/config.json` contains `extraction_hints` and `output_dir`. Use these hints to adapt parser/system messages for a cookbook.

Integration points and external dependencies
- Apple Vision OCR: `apple_ocr.swift` invoked via `swift` CLI. Ensure Swift is available on the runner when editing OCR behavior.
- OpenAI: reads `OPENAI_API_KEY` env or UI-provided key; model configured in `config/settings.yaml` (`gpt-4o` by default).
- Mealie: optional integration via `mealie_client.py`; credentials come from env vars or `config/mealie_config.json`.
- Requirements: `requirements.txt` — update when adding Python deps and run `pip install -r requirements.txt` in CI/dev.

Editing guidance (where to make changes)
- Change UI behavior: edit [recipe_app.py](recipe_app.py) and use `st.session_state.processor` initialization as pattern.
- Change parsing / prompts or model behavior: edit `_parse_with_openai` and `_build_system_message` in [recipe_processor_integrated.py](recipe_processor_integrated.py). Keep the JSON output schema stable.
- Change OCR logic: edit `apple_ocr.swift` and `_run_apple_ocr` call sites (timeout and error handling live in the processor).
- Change data model / DB schema: edit [database.py](database.py) and update `init_database()` — migrations are manual; be careful to preserve `image_hash` uniqueness and JSON serialization of `ingredients`/`instructions`.

Examples & places to inspect
- Sample extracted recipe: [cookbooks/jerusalem/extracted/Auberginen_mit_Chermoula_Bulgur__Joghurt.md](cookbooks/jerusalem/extracted/Auberginen_mit_Chermoula_Bulgur__Joghurt.md)
- Cookbook hints example: [cookbooks/jerusalem/config.json](cookbooks/jerusalem/config.json)
- Config flags: [config/settings.yaml](config/settings.yaml)

Do's and don'ts (practical)
- Do: preserve the exact OpenAI JSON keys when making parser changes. Tests and downstream export expect them.
- Do: run `streamlit run recipe_app.py` or `python3 recipe_cli.py process ...` to validate end-to-end changes (OCR -> parse -> DB -> markdown).
- Don't: change markdown filename logic or DB column names without updating the CLI/UI and Mealie sync code.

If something is unclear or you want me to expand any section (examples, CI, or a test harness), tell me which area to deepen.
