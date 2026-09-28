"""Quality check of the recipe pipeline on 4 real cases, free service pool only.

Runs app.run_pipeline end to end (LLM, RAG, web search, Python nutrition) and
checks the title, the nutrition parsing rate, the Toronto stores and the
gluten-free adaptation. Paid LLM keys are removed from the environment before
the app is imported, so only Groq and Gemini can be used.

Usage: python scripts/test_quality_eval.py
"""

import logging
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Import the app first (it loads .env with override=True), then drop the paid
# keys, so neither the crew nor LiteLLM can fall back on them.
import app  # noqa: E402
from src.nutrition import (  # noqa: E402
    TO_TASTE,
    TO_TASTE_FOODS,
    clean_item,
    ingredient_lines,
    match_food,
    normalize,
    quantity_grams,
)

PAID_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")
for key in PAID_KEYS:
    os.environ.pop(key, None)

LANGUAGE = "Français"
MIN_PARSED = 0.75
TORONTO_STORES = ("Adonis", "Arz", "Iqbal", "FreshCo", "No Frills")
GLUTEN_FREE = re.compile(
    r"gluten|sans ble|millet|sorgho|quinoa|sarrasin|\bmais\b|adapt"
)

CASES = [
    {
        "label": "Kafteji",
        "dish": "Kafteji",  # not in the database: the chef searches for it
        "title_words": ("kafteji", "kaftaji", "kefteji"),
        "style": "classic",
        "city": "Ottawa / Gatineau",
        "diet": [],
    },
    {
        "label": "Kousksi (sans gluten)",
        "dish": "Couscous aux Légumes (Kousksi bil Khodhra)",
        "title_words": ("couscous", "kousksi"),
        "style": "classic",
        "city": "Montreal",
        "diet": ["Gluten-Free"],
    },
    {
        "label": "Tajine Malsouka",
        "dish": "Tajine aux Feuilles de Brik - Tajine Malsouka",
        "title_words": ("tajine", "malsouka"),
        "style": "classic",
        "city": "Toronto",
        "diet": [],
    },
    {
        "label": "Calmars Farcis",
        "dish": "Calmars Farcis / Kalmars Mihchi",
        "title_words": ("calmar", "kalmar"),
        "style": "comparison",
        "city": "Ottawa / Gatineau",  # Gatineau
        "diet": [],
    },
]


class FallbackWatcher(logging.Handler):
    """Notes when run_pipeline moves from Groq to Gemini."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.fell_back = False

    def emit(self, record):
        if "trying the next model" in record.getMessage():
            self.fell_back = True


def run_recipe_crew(case: dict, user_api_key=None) -> tuple[str, str, str]:
    """One pipeline run. user_api_key stays None: free service pool only."""
    return app.run_pipeline(
        None,  # no photos
        "",  # no typed ingredients
        case["dish"],
        "",
        case["diet"],
        "",
        case["city"],
        "recipe",
        case["style"],
        LANGUAGE,
        user_api_key,
    )


def recipe_title(recipe_md: str) -> str:
    """The card's own heading: the first heading after the app's tab title."""
    headings = [line for line in recipe_md.splitlines() if line.startswith("#")]
    return headings[1] if len(headings) > 1 else ""


def nutrition_parsing(recipe_md: str) -> tuple[int, int]:
    """(parsed, total) ingredient lines, with the rules of src/nutrition.py.

    A seasoning listed without a quantity ("sel, poivre") is skipped on
    purpose by the nutrition module, so it counts as handled.
    """
    lines = [clean_item(line) for line in ingredient_lines(recipe_md)]
    parsed = 0
    for line in lines:
        text = normalize(line)
        food = match_food(text)
        if food and quantity_grams(text, food) is not None:
            parsed += 1
        elif food and (food.name in TO_TASTE_FOODS or TO_TASTE.search(text)):
            parsed += 1
    return parsed, len(lines)


def evaluate(case: dict) -> dict:
    watcher = FallbackWatcher()
    logging.getLogger().addHandler(watcher)
    start = time.time()
    try:
        recipe_md, shopping_md, _ = run_recipe_crew(case, user_api_key=None)
    finally:
        logging.getLogger().removeHandler(watcher)
    seconds = time.time() - start

    checks, notes = {}, []
    title = recipe_title(recipe_md)
    checks["title"] = any(word in normalize(title) for word in case["title_words"])
    if not checks["title"]:
        notes.append(f"title: {title or recipe_md[:80]!r}")

    parsed, total = nutrition_parsing(recipe_md)
    checks["nutrition"] = total > 0 and parsed / total >= MIN_PARSED
    if not checks["nutrition"]:
        notes.append(f"nutrition: {parsed}/{total} parsed")

    stores = []
    if case["city"] == "Toronto":
        stores = [s for s in TORONTO_STORES if s.lower() in shopping_md.lower()]
        checks["stores"] = bool(stores)
        if not stores:
            notes.append("no Toronto store in the shopping list")

    if "Gluten-Free" in case["diet"]:
        checks["gluten_free"] = bool(GLUTEN_FREE.search(normalize(recipe_md)))
        if not checks["gluten_free"]:
            notes.append("no gluten-free adaptation mentioned")

    return {
        "label": case["label"],
        "seconds": seconds,
        "model": "Gemini (fallback)" if watcher.fell_back else "Groq",
        "parsed": f"{parsed}/{total}",
        "stores": ", ".join(stores) if case["city"] == "Toronto" else "-",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "notes": notes,
        "recipe": recipe_md,
    }


def main():
    # The root logger lets warnings through so FallbackWatcher sees them; the
    # console handler only prints errors.
    logging.basicConfig(level=logging.WARNING)
    for handler in logging.getLogger().handlers:
        handler.setLevel(logging.ERROR)
    if not any(os.getenv(k) for k in ("GROQ_API_KEY", "GEMINI_API_KEY")):
        sys.exit("No GROQ_API_KEY or GEMINI_API_KEY: the free pool is not configured.")

    results = []
    for case in CASES:
        print(f"Running: {case['label']} ...", flush=True)
        results.append(evaluate(case))

    header = ("Plat", "Temps (s)", "Modèle", "Ingrédients parsés", "Magasins trouvés", "Statut")
    rows = [
        (r["label"], f"{r['seconds']:.0f}", r["model"], r["parsed"], r["stores"], r["status"])
        for r in results
    ]
    widths = [max(len(str(row[i])) for row in [header, *rows]) for i in range(len(header))]
    line = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    print("\n" + line)
    print("| " + " | ".join(h.ljust(w) for h, w in zip(header, widths)) + " |")
    print(line)
    for row in rows:
        print("| " + " | ".join(str(c).ljust(w) for c, w in zip(row, widths)) + " |")
    print(line)

    for r in results:
        for note in r["notes"]:
            print(f"- {r['label']}: {note}")
    failed = [r for r in results if r["status"] == "FAIL"]
    print(f"\n{len(results) - len(failed)}/{len(results)} PASS")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
