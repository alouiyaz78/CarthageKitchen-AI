# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

CarthageKitchen AI (repo/package name: NourishBot) is a Gradio app. The README front-matter is set up for a Hugging Face Space, but the project is still in testing and has not been deployed yet. It uses a CrewAI multi-agent pipeline to turn pantry photos or typed ingredients into authentic Tunisian recipes. It also produces a local grocery sourcing guide (Ottawa/Gatineau, Montreal) and a nutrition analysis. Recipe suggestions draw on a RAG store built from scanned Tunisian cookbooks.

## Commands

```bash
source .venv/bin/activate
uv pip install -r requirements.txt   # .venv is managed by uv and has no pip
python app.py                 # Gradio UI on http://0.0.0.0:7860
ruff check .                  # ruff is pinned in requirements.txt
```

- There is no `pyproject.toml`, so the README's `uv sync` does not work. Use `uv pip` with `requirements.txt`.
- `requirements.txt` lists only direct dependencies, pinned to the versions tested in `.venv` (crewai 1.15.22, gradio 6.28.0). Check changes with `uv pip compile requirements.txt`.
- Gradio version mismatch: the README Space front-matter still says `sdk_version: 5.12.0`, while `requirements.txt` and `.venv` use Gradio 6.28. In 6.x, passing `theme`/`css`/`js`/`head` to `gr.Blocks` logs a deprecation warning but still works. `app.py` keeps them on `gr.Blocks` so it runs on both versions.
- There is no test suite. `test_claude_vision_109.py` is not a pytest file: it is an ingestion script that writes to the production database.

## Environment

The app reads a `.env` file. `src/crew.py` looks for `src/.env` first and falls back to the root `.env`. `src/tools.py`, `app.py`, and the ingestion scripts only read the root `.env`.

- `ANTHROPIC_API_KEY`: required. `src/crew.py` raises an error at import time if it is missing.
- `DATABASE_URL`: Neon Postgres with pgvector. Without it, the dish dropdown shows only "Auto-detect" and the RAG tool returns an error string.
- `VISION_MODEL`: optional. Sets the model used for image ingredient extraction in `src/tools.py`.
- `MODEL_NAME` appears in the README but is **ignored**. The crew LLM is hardcoded in `src/crew.py` (`anthropic/claude-haiku-4-5-20251001`, temperature 0.2).

## Architecture

**Request flow:** `app.py:run_pipeline` builds an `inputs` dict and calls `.crew().kickoff(inputs=inputs)` on one of two crews in `src/crew.py`:
- `NourishBotRecipeCrew`: five sequential tasks, in this order: detect ingredients → dietary filter → heritage recipe (RAG) → local sourcing → nutrition.
- `NourishBotAnalysisCrew`: `detect_ingredients_task` (only when there are images or typed ingredients), then `analyze_meal_task`.

**Prompts live in YAML.** `src/config/agents.yaml` and `src/config/tasks.yaml` are loaded when the module is imported. CrewAI fills the `{placeholders}` in the YAML from the `kickoff(inputs=...)` keys: `image_paths`, `manual_input`, `selected_dish`, `heritage_recipe`, `meal_preference`, `dietary_restrictions`, `target_city`. If you add a placeholder, you must add the matching key in `app.py`, otherwise CrewAI raises a KeyError. Empty inputs are passed as the string `"None"`.

**Selected dish.** When the user picks a dish, `app.py` fetches it by exact name with `get_recipe_by_name()` (`src/tools.py`) and passes it as `heritage_recipe`. The chef task is told to cook exactly that dish from that reference instead of running the semantic search.

**UI output depends on task position.** `app.py:dispatch_outputs_to_tabs` reads `tasks_output[2]`, `[3]`, and `[4]` to fill the Recipe, Shopping, and Nutrition tabs. If you reorder, add, or remove tasks in `NourishBotRecipeCrew.crew()`, you must update this function too.

**`src/models.py`** defines Pydantic output schemas (`RecipeOutput`, `NutrientAnalysisOutput`), but no task uses them yet (there is no `output_pydantic`). Task outputs are raw markdown text.

**Tools (`src/tools.py`, CrewAI `@tool` functions):**
- `extract_ingredients_from_image_and_text`: takes comma-separated image paths, base64-encodes the images, and sends them in a LiteLLM `completion` call to Anthropic.
- `filter_ingredients_list` and `filter_based_on_dietary_restrictions`: rule-based. The keyword lists are mostly in French (e.g. `végétarien`, `semoule`).
- `search_tunisian_recipes_tool`: RAG search. It embeds the query with fastembed `BAAI/bge-small-en-v1.5` (384 dimensions), then runs a cosine search on the `tunisian_recipes` table with a similarity threshold of ≥ 0.55 and a limit of 2 results.

**`app.py` queries the database at import time.** It loads the list of dish names from `tunisian_recipes` when the module is imported, to fill the dropdown.

## RAG ingestion (root-level scripts, run manually)

The scripts read the cookbook PDFs in `Doc/` (gitignored) and fill `tunisian_recipes`. Every script must use the same embedding model as `src/tools.py`, otherwise the stored vectors will not match the query vectors.

- `ingest_with_claude_vision.py`: the main pipeline. It renders each page of `Doc/52687157-Traditions-Culinaires-de-Tunisie.pdf` and sends it to Claude Vision for structured JSON extraction. Results are cached in `Doc/recipes_json_cache/`.
- `fix_failed_pages.py`: re-runs extraction for a hardcoded `FAILED_PAGES` list, with more tolerant JSON parsing.
- `test_claude_vision_109.py`: ingests the text-native `Atelier-Cuisine-Tunisienne` PDF.
- `ingest_recipes.py` and `inspect_books.py` use `CREATE TABLE IF NOT EXISTS`. Their `DROP TABLE` line is commented out on purpose to protect the production table, so re-running them appends rows (which can create duplicates) instead of replacing the data.

## UI theme

The theme is defined in `app.py`: a custom `gr.themes.Soft` (Sidi Bou Saïd palette), a `css` string, and a Google Font loaded through `head` (Gradio 6 drops `@import` rules in `css`). The output tabs get their accent colors from their `elem_id`s: Gradio renders each tab button as `#<elem_id>-button`, and the CSS styles those ids. Keep the ids `ck-tab-recipe`, `ck-tab-shopping`, `ck-tab-nutrition` and `ck-output-tabs` stable.

The background mosaic and the hero photos come from `assets/ui/`. They are served with `gr.set_static_paths`, which lists the individual files (`MOSAIC_FILE`, `VIGNETTES`) rather than the whole directory, so other files there stay private. To add an image, add it to those lists; the URL is built by `ui_asset_url()` as `/gradio_api/file=<absolute path>`. Missing files are skipped. `assets/ui/` must be committed for the images to show up once the app is deployed.

## Conventions

- Code in `src/` and `app.py` uses 2-space indentation. `models.py` and some scripts use 4 spaces. Match the file you are editing.
- Comments, docstrings, log/print messages, and commit messages are in English. User-facing UI text is in French. LLM prompts that target the French cookbooks stay in French.
- No emoji in UI text, print/log output, or commit messages. Keep comments short and plain: no banner blocks, no comments that restate the code.
