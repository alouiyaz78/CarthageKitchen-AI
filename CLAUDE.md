# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

CarthageKitchen AI (repo/package name: NourishBot) is a Gradio app. The README front-matter is set up for a Hugging Face Space, but the project is still in testing and has not been deployed yet. It uses a CrewAI multi-agent pipeline to turn pantry photos or typed ingredients into authentic Tunisian recipes. It also produces a local grocery sourcing guide (Ottawa/Gatineau, Montreal, Quebec City, Toronto) and a nutrition analysis. Recipe suggestions draw on a RAG store built from scanned Tunisian cookbooks.

## Commands

```bash
source .venv/bin/activate
uv pip install -r requirements.txt   # .venv is managed by uv and has no pip
python app.py                 # Gradio UI on http://0.0.0.0:7860
ruff check .                  # ruff is pinned in requirements.txt
```

- There is no `pyproject.toml`, so the README's `uv sync` does not work. Use `uv pip` with `requirements.txt`.
- `requirements.txt` lists only direct dependencies, pinned to the versions tested in `.venv` (crewai 1.15.22, gradio 6.28.0). Check changes with `uv pip compile requirements.txt`.
- Gradio 6.28.0 everywhere: `.venv`, `requirements.txt` and the README Space front-matter (`sdk_version`, with `python_version: "3.12"`). Keep the three in sync when upgrading. In 6.x, passing `theme`/`css`/`js`/`head` to `gr.Blocks` logs a deprecation warning but still works. `app.py` keeps them on `gr.Blocks` so it runs on both versions.
- There is no test suite. `test_claude_vision_109.py` is not a pytest file: it is an ingestion script that writes to the production database.

## Environment

The app reads a `.env` file. `src/crew.py` looks for `src/.env` first and falls back to the root `.env`. `src/tools.py`, `app.py`, and the ingestion scripts only read the root `.env`.

- `GROQ_API_KEY` and `GEMINI_API_KEY` (or `GOOGLE_API_KEY`): the free service pool used when the user gives no key of their own. Groq runs first, Gemini takes over if the Groq run fails. With neither, users must enter their own key.
- `ANTHROPIC_API_KEY`: optional. Only used for vision if `VISION_MODEL` is an Anthropic model.
- `GROQ_MODEL`, `GEMINI_MODEL`, `ANTHROPIC_MODEL`, `OPENAI_MODEL`: optional overrides of the model per provider (`PROVIDER_MODELS` in `src/crew.py`: `groq/openai/gpt-oss-120b`, `gemini/gemini-3.5-flash-lite`, `anthropic/claude-haiku-4-5-20251001`, `openai/gpt-4o-mini`). Providers retire models often: `llama-3.3-70b-versatile` (Groq), `gemini-1.5-flash` and `claude-3-5-haiku-20241022` no longer answer.
- `SERPER_API_KEY`: optional. Enables the chef search (`ChefSearchTool` in `src/tools.py`: written recipes and YouTube videos) for the modern chef recipe styles. Without it, those styles fall back to the classic recipe with a notice.
- `DATABASE_URL`: Neon Postgres with pgvector. Without it, the dish dropdown shows only "Auto-detect" and the RAG tool returns an error string.
- `VISION_MODEL`: optional. LiteLLM model for image ingredient extraction on service keys (default: the Gemini model).
- `MODEL_NAME` (README) and `TEXT_MODEL` are **ignored**. The crew LLM comes from `get_llm_from_user_key()` in `src/crew.py` (temperature 0.2).

**Personal keys (BYOK).** The advanced settings accordion has a password field for the user's own key. `key_provider()` picks the provider from the prefix (`gsk_` Groq, `AIza` or `AQ.` Gemini, `sk-ant-` Anthropic, `sk-` OpenAI; unknown prefixes get an error message). A user key is passed to that user's LLM and vision tool only, never put in `os.environ` (shared by every request), and it is replaced by `***` in displayed and logged errors. Vision uses the user key only for Gemini and Anthropic keys (`vision_tool_for()`); otherwise `VISION_MODEL` on service keys. `IngredientVisionTool` is created per crew and keeps the key in a private attribute, out of its repr. Groq runs through CrewAI's native OpenAI client on Groq's OpenAI compatible endpoint (`make_llm()`): on the LiteLLM route, CrewAI 1.15 leaves its `cache_breakpoint` flag in the messages and Groq rejects them. Gemini needs `google-genai` (CrewAI's native Gemini provider).

## Architecture

**Request flow:** `app.py:run_pipeline` builds an `inputs` dict and calls `.crew().kickoff(inputs=inputs)` on one of two crews in `src/crew.py`:
- `NourishBotRecipeCrew`: detect ingredients (only with photos) → dietary filter (only with photos or typed ingredients) → heritage recipe (RAG) → local sourcing. Typed ingredients reach the filter through `{manual_input}` without a vision call. Sourcing gets `context=[recipe_task]` only, not the whole history. Nutrition is not a crew task: `app.py` computes it from the recipe card with `src/nutrition.py`.
- `NourishBotAnalysisCrew`: `detect_ingredients_task` (only with photos), then `analyze_meal_task`.
- Agent and crew logs are off; set `CREW_VERBOSE=1` to turn them on.

**Prompts live in YAML.** `src/config/agents.yaml` and `src/config/tasks.yaml` are loaded when the module is imported. CrewAI fills the `{placeholders}` in the YAML from the `kickoff(inputs=...)` keys: `image_paths`, `manual_input`, `selected_dish`, `heritage_recipe`, `has_pantry` (`yes`/`no`: did the user give photos or ingredients), `meal_preference`, `dietary_restrictions`, `target_city`, `language` (`English` or `French`, from the UI language switch), `recipe_style` (`classic`, `chefs_variants` or `comparison`). If you add a placeholder, you must add the matching key in `app.py`, otherwise CrewAI raises a KeyError. Empty inputs are passed as the string `"None"`.

**Dish types.** `src/dish_categories.py` maps each exact `dish_name` to a type (main, starter, soup, bread, sweet, drink, sauce). The UI has a type filter above the dish dropdown; the full list is grouped by type with a short text prefix in the label (the value stays the plain dish name). Dishes missing from the map show up under "Other", so add new ingestions to the map.

**Selected dish.** When the user picks a dish, `app.py` fetches it by exact name with `get_recipe_by_name()` (`src/tools.py`) and passes it as `heritage_recipe`. The chef task is told to cook exactly that dish from that reference instead of running the semantic search.

**Recipe style.** In `classic` style the chef only has the Neon RAG tool. In `chefs_variants` and `comparison` it also gets `ChefSearchTool` (`find_tunisian_chef_versions`, one call at most, one new instance per crew because the usage count lives on the instance). The model passes simple dish names (plain French name, then Tunisian spellings), not a query: Google returns nothing for long boolean queries. The tool runs two searches in parallel and returns both, so the video fallback does not depend on a second tool call (Haiku often skipped it):
- Written recipes: Serper `<name> recette tunisienne`, social sites and Moroccan/Algerian pages dropped, then each page's schema.org `Recipe` JSON-LD is read. Only complete recipes (3+ ingredients, 2+ steps) are kept. `source_rank()` sorts them: Tunisian chefs and sites (`TUNISIAN_SITES` on the domain, `TUNISIAN_CHEFS` on the author with full or distinctive names only, since a bare first name such as Samar is too common, or a `.tn` domain), then independent authors (a named person on an unknown site), then food portals and general blogs (`FOOD_PORTALS`, no author, or a non-Tunisian Maghrebi blog: `MAGHREB_BLOGS`, `.dz`, `.ma`), then food brands (`FOOD_BRANDS`, or an `Organization` author). The Maghrebi blog check runs before the Tunisian one, and `matches()` ignores spaces and hyphens, so keys in these lists must not contain them. Portal and brand pages are ranked only to be dropped: the tool returns at most one recipe, by a Tunisian chef or an independent author, and none otherwise, so the model falls back to a Tunisian chef's video. `condense_steps()` merges neighbouring steps down to 10 at most instead of cutting the end. The recipe comes with a `Source type` and a `Credit` (the person, or the site) that the model copies into the `CHEF:` line. Unknown brands only count as brands if the page names an `Organization` author: add them to `FOOD_BRANDS`. Pages rendered by JavaScript (Nessma Cuisine) have no JSON-LD and are skipped. If one is the same dish and Tunisian, the card follows it (ingredients, quantities, steps) and ends with a `CHEF:` line; `comparison` adds "What the chef changes" against the heritage recipe.
- Videos (fallback): Serper `site:youtube.com <name> tunisien`, with each video's real channel from YouTube oEmbed (Serper snippets contain names from the recommended videos sidebar, which led the model to credit the wrong chef). Unresolvable videos are dropped, Teyssir Ksouri and Hendati are listed first. The card is then the heritage recipe plus a `VIDEO:` line.
`names_other_dish()` drops recipes and videos whose title names a base the request does not (riz, couscous, boulgour, pâtes...), so "riz aux calamars farcis" never reaches the model for "calmars farcis": Haiku accepted it despite the prompt. Other mismatches are still left to the model, and the "What the chef changes" bullets can still contain an invented difference.

**UI output is matched by task name.** The number of tasks varies with the inputs, so `app.py:dispatch_outputs_to_tabs` looks outputs up by `TaskOutput.name` (`RECIPE_TASK`, `SOURCING_TASK`, `MEAL_ANALYSIS_TASK` in `src/crew.py`). Tasks must be created with `make_task()`, which sets `name=`. It also strips emoji from the LLM output. The recipe output also goes through `drop_preamble()` (drops any text before the first markdown heading) because the model does not always follow that rule, and through `render_source_lines()`: the chef writes external sources as `VIDEO: channel | title | url` (a video to watch, never the source of the written recipe) or `CHEF: name | title | url` (the card follows that written recipe), and the app turns them into a sentence in the UI language. The recipe tab title comes from `recipe_heading()`: the heritage title only in `classic` style, the comparison title in `comparison`; in `chefs_variants`, traditional recipe and chef video for a `VIDEO:` line, contemporary card otherwise (including a missing or malformed `CHEF:` line).

**`src/models.py`** defines Pydantic output schemas (`RecipeOutput`, `NutrientAnalysisOutput`), but no task uses them yet (there is no `output_pydantic`). Task outputs are raw markdown text.

**Tools (`src/tools.py`, CrewAI `@tool` functions):**
- `IngredientVisionTool` (`extract_ingredients_from_image_and_text`): takes comma-separated image paths, base64-encodes the images, and sends them in a LiteLLM `completion` call to the vision model.
- `filter_ingredients_list` and `filter_based_on_dietary_restrictions`: rule-based. The keyword lists are mostly in French (e.g. `végétarien`, `semoule`).
- `search_tunisian_recipes_tool`: RAG search. It embeds the query with fastembed `BAAI/bge-small-en-v1.5` (384 dimensions), then runs a cosine search on the `tunisian_recipes` table with a similarity threshold of ≥ 0.55 and a limit of 2 results.

**`app.py` queries the database at import time.** It loads the list of dish names from `tunisian_recipes` when the module is imported, to fill the dropdown.

**Nutrition (`src/nutrition.py`, no LLM).** `nutrition_report()` reads the ingredient bullets of the recipe card (the section under an ingredient, pantry or add-on heading, up to the steps; otherwise every bullet before the first numbered step) and the servings count (default 4). `calculate_recipe_nutrition()` parses each quantity (g, kg, ml, dl, cl, l, c. à soupe/tbsp = 15 ml, c. à café/tsp = 5 ml, gousse, botte, pincée, or a count times `Food.piece`), matches the line against `FOODS` (per 100 g raw or dry, rounded from Ciqual and USDA; the first matching regex wins, so specific entries come before generic ones) and sums per serving. Volumes use `Food.density`; frying oil counts for 10%. The tips are fixed rules in `nutrition_tips()` (sodium, oil over 50 ml per serving, carbohydrates with a lower threshold for the diabetic profile, calories, fiber, protein), 3 at most. Every visible string is a `nut_*` key in `UI_TEXT`. Lines with no usable quantity or an unknown ingredient are listed as not counted, so add missing Tunisian ingredients to `FOODS`. The recipe task asks for one quantified ingredient per bullet for this parser. The meal analysis mode (`analyze_meal_task`) still uses the LLM.

## RAG ingestion (root-level scripts, run manually)

The scripts read the cookbook PDFs in `Doc/` (gitignored) and fill `tunisian_recipes`. Every script must use the same embedding model as `src/tools.py`, otherwise the stored vectors will not match the query vectors.

- `ingest_with_claude_vision.py`: the main pipeline. It renders each page of `Doc/52687157-Traditions-Culinaires-de-Tunisie.pdf` and sends it to Claude Vision for structured JSON extraction. Results are cached in `Doc/recipes_json_cache/`.
- `fix_failed_pages.py`: re-runs extraction for a hardcoded `FAILED_PAGES` list, with more tolerant JSON parsing.
- `test_claude_vision_109.py`: ingests the text-native `Atelier-Cuisine-Tunisienne` PDF.
- `ingest_recipes.py` and `inspect_books.py` use `CREATE TABLE IF NOT EXISTS`. Their `DROP TABLE` line is commented out on purpose to protect the production table, so re-running them appends rows (which can create duplicates) instead of replacing the data.

## UI theme

The theme is defined in `app.py`: a custom `gr.themes.Soft` (Sidi Bou Saïd palette), a `css` string, and a Google Font loaded through `head` (Gradio 6 drops `@import` rules in `css`). The output tabs get their accent colors from their `elem_id`s: Gradio renders each tab button as `#<elem_id>-button`, and the CSS styles those ids. Keep the ids `ck-tab-recipe`, `ck-tab-shopping`, `ck-tab-nutrition` and `ck-output-tabs` stable.

The recipe and shopping tabs each have a print button (`print_js()`). It copies the box content into a `#ck-print-sheet` div, and `PRINT_CSS` hides the rest of the page while printing. `PRINT_CSS` is injected through `head`, not `css`, because Gradio prefixes every selector in `css` (including inside `@media`) with its container class, so rules on `body` never match. The Markdown ids `ck-recipe-md` and `ck-shopping-md` must stay stable.

The background mosaic and the hero photos come from `assets/ui/`. They are served with `gr.set_static_paths`, which lists the individual files (`MOSAIC_FILE`, `VIGNETTES`) rather than the whole directory, so other files there stay private. To add an image, add it to those lists; the URL is built by `ui_asset_url()` as `/gradio_api/file=<absolute path>`. Missing files are skipped. `assets/ui/` must be committed for the images to show up once the app is deployed.

## Conventions

- Code in `src/` and `app.py` uses 2-space indentation. `models.py` and some scripts use 4 spaces. Match the file you are editing.
- Comments, docstrings, log/print messages, and commit messages are in English. The UI is bilingual (English by default, French via the switch in the header): every visible string lives in `UI_TEXT` in `app.py` and must be added in both languages, and `translate_ui()` must list any new component. Values sent to the crew (dietary profiles, cities, mode) stay in English; only their labels are translated. LLM prompts that target the French cookbooks stay in French.
- No emoji in UI text, print/log output, or commit messages. Keep comments short and plain: no banner blocks, no comments that restate the code.

## Next steps

**Nutrition, next steps.** Recipe nutrition is now computed in Python (see above). Still open: meal analysis mode is estimated by the LLM in `analyze_meal_task` and its numbers are not reliable; a structured ingredient list from the recipe task (`output_pydantic`) would be sturdier than parsing markdown bullets; `FOODS` could be replaced by the full Ciqual table.

**Before public deployment.** Replace the images whose rights are unclear or that carry a watermark: `assets/ui/tajine.jpg` shows a "Marie N Guérin" watermark. The other committed images have no visible watermark, but their source still needs checking before publishing.
