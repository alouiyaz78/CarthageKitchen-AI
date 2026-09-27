import logging
import os
from pathlib import Path
import re
from urllib.parse import quote
from dotenv import load_dotenv
import gradio as gr
import psycopg2
from src.crew import (
    CLASSIC_STYLE,
    MEAL_ANALYSIS_TASK,
    NUTRITION_TASK,
    RECIPE_STYLES,
    RECIPE_TASK,
    SOURCING_TASK,
    WEB_SEARCH_AVAILABLE,
    NourishBotAnalysisCrew,
    NourishBotRecipeCrew,
)
from src.tools import get_recipe_by_name

CURRENT_DIR = Path(__file__).resolve().parent
ENV_FILE = CURRENT_DIR / ".env"
if not ENV_FILE.exists():
  ENV_FILE = CURRENT_DIR / "src" / ".env"
load_dotenv(dotenv_path=ENV_FILE, override=True)

DATABASE_URL = os.getenv("DATABASE_URL")


AUTO_DETECT = "Auto-detect"


def load_dish_names() -> list[str]:
  if not DATABASE_URL:
    return []
  try:
    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor() as cur:
      cur.execute(
          "SELECT DISTINCT dish_name FROM tunisian_recipes ORDER BY dish_name"
          " ASC;"
      )
      rows = cur.fetchall()
    conn.close()
    return [row[0] for row in rows if row[0]]
  except Exception as e:
    logging.error(f"Could not load dish names from Neon: {e}")
    return []


DISH_NAMES = load_dish_names()

# Radio label -> language code. The agents get the full language name.
LANGUAGES = {"English": "en", "Français": "fr"}
DEFAULT_LANGUAGE = "English"
CREW_LANGUAGE = {"en": "English", "fr": "French"}

# Values sent to the crew stay in English whatever the UI language; only the
# labels shown next to them are translated.
DIETARY_PROFILES = [
    "Gluten-Free",
    "Vegetarian",
    "Vegan",
    "Diabetic / Low Glycemic",
    "Low Sodium (Hypertension)",
]
CITIES = ["Ottawa / Gatineau", "Montreal", "Quebec City"]

UI_TEXT = {
    "en": {
        "tagline": "Tunisian Culinary Studio &amp; Nutrition",
        "subtitle": (
            "Authentic heritage recipes, local sourcing in"
            " <b>Ottawa/Gatineau</b>, <b>Montreal</b> and <b>Quebec City</b>,"
            " and a full dietary assessment."
        ),
        "tab_photos": "Ingredient Photos",
        "tab_text": "Ingredients Input",
        "upload_label": "Photos of your fridge, pantry or ingredients",
        "manual_label": "Available ingredients",
        "manual_placeholder": (
            "e.g. 2 tomatoes, chili peppers, garlic, olive oil, caraway..."
        ),
        "dish_header": "#### Heritage Recipe Choice",
        "dish_label": "Heritage recipes ({count} dishes)",
        "auto_detect": "Auto-detect / Recipe from my ingredients",
        "style_label": "Recipe style",
        "style_choices": [
            "Classic Heritage (Books & Neon RAG)",
            "Modern Chefs & Creators (YouTube: Teyssir, Hendati...)",
            "Heritage vs Modern Comparison",
        ],
        "msg_web_unavailable": (
            "*Web search is not configured (SERPER_API_KEY missing), so this"
            " is the classic heritage recipe.*"
        ),
        "cravings_label": "Cravings or variations (optional)",
        "cravings_placeholder": "e.g. fish dish, spicy, family-style...",
        "diet_header": "#### Dietary Preferences & Health",
        "diet_label": "Dietary profiles",
        "diet_choices": [
            "Gluten-free",
            "Vegetarian",
            "Vegan",
            "Diabetic / Low glycemic",
            "Low sodium (hypertension)",
        ],
        "allergies_label": "Allergies and exclusions",
        "allergies_placeholder": "e.g. no coriander, very mild chili...",
        "city_label": "Sourcing city",
        "city_choices": [
            "Ottawa / Gatineau",
            "Montreal (Greater Montreal)",
            "Quebec City",
        ],
        "mode_label": "Mode",
        "mode_recipe": "Full culinary studio",
        "mode_analysis": "Dietary analysis only",
        "submit": "Generate Recipe & Shopping List",
        "out_recipe": "1. In the Kitchen",
        "out_shopping": "2. Grocery & Markets",
        "out_nutrition": "3. Nutrition",
        "print_recipe": "Print recipe",
        "print_shopping": "Print shopping list",
        "ph_recipe": (
            "Your recipe will appear here.",
            "Step-by-step instructions and traditional techniques.",
        ),
        "ph_shopping": (
            "Your shopping list and local stores will appear here.",
            "Recommended grocers in Ottawa/Gatineau, Montreal and Quebec City.",
        ),
        "ph_nutrition": (
            "Your nutrition report will appear here.",
            "Macros, calories and health tips.",
        ),
        "head_recipe": "Heritage Recipe",
        "head_shopping": "Shopping Guide & Local Markets",
        "head_nutrition": "Nutrition Report & Recommendations",
        "msg_missing_input": (
            "**Action needed:** upload a photo, type some ingredients or pick"
            " a dish from the menu."
        ),
        "msg_analysis_recipe": "*Dietary analysis mode: no recipe generated.*",
        "msg_analysis_shopping": "*No shopping list in this mode.*",
        "msg_error": "**Something went wrong:**",
        "msg_no_output": "No result was generated.",
    },
    "fr": {
        "tagline": "Studio Culinaire Tunisien &amp; Nutrition",
        "subtitle": (
            "Recettes patrimoniales authentiques, approvisionnement local à"
            " <b>Ottawa/Gatineau</b>, <b>Montréal</b> et <b>Québec</b>, et évaluation"
            " diététique complète."
        ),
        "tab_photos": "Photos des ingrédients",
        "tab_text": "Ingrédients en texte",
        "upload_label": "Photos du frigo, placard ou ingrédients",
        "manual_label": "Ingrédients disponibles",
        "manual_placeholder": (
            "Ex : 2 tomates, piments, ail, huile d'olive, carvi..."
        ),
        "dish_header": "#### Choix d'une recette du patrimoine",
        "dish_label": "Recettes patrimoniales ({count} plats)",
        "auto_detect": "Détection auto / Recette selon mes ingrédients",
        "style_label": "Style de recette",
        "style_choices": [
            "Patrimoine classique (livres et base Neon)",
            "Chefs et créateurs modernes (YouTube : Teyssir, Hendati...)",
            "Comparaison patrimoine / moderne",
        ],
        "msg_web_unavailable": (
            "*La recherche web n'est pas configurée (SERPER_API_KEY absente) :"
            " voici la recette patrimoniale classique.*"
        ),
        "cravings_label": "Envies ou variantes (optionnel)",
        "cravings_placeholder": "Ex : plat au poisson, bien piquant, familial...",
        "diet_header": "#### Préférences et restrictions santé",
        "diet_label": "Profils diététiques",
        "diet_choices": [
            "Sans gluten",
            "Végétarien",
            "Végétalien",
            "Diabétique / IG bas",
            "Pauvre en sel (hypertension)",
        ],
        "allergies_label": "Allergies et exclusions",
        "allergies_placeholder": "Ex : sans coriandre, piment très doux...",
        "city_label": "Ville de sourcing",
        "city_choices": [
            "Ottawa / Gatineau",
            "Montréal (Grand Montréal)",
            "Québec (Ville de Québec)",
        ],
        "mode_label": "Mode",
        "mode_recipe": "Studio culinaire complet",
        "mode_analysis": "Analyse diététique seule",
        "submit": "Générer la recette et la liste de courses",
        "out_recipe": "1. En cuisine",
        "out_shopping": "2. Épicerie et marchés",
        "out_nutrition": "3. Nutrition",
        "print_recipe": "Imprimer la recette",
        "print_shopping": "Imprimer la liste de courses",
        "ph_recipe": (
            "La fiche recette détaillée s'affichera ici.",
            "Instructions pas à pas et techniques traditionnelles.",
        ),
        "ph_shopping": (
            "La liste des courses et les adresses locales s'afficheront ici.",
            "Épiceries recommandées à Ottawa/Gatineau, Montréal et Québec.",
        ),
        "ph_nutrition": (
            "Le bilan nutritionnel s'affichera ici.",
            "Macros, calories et conseils de santé.",
        ),
        "head_recipe": "Fiche recette patrimoniale",
        "head_shopping": "Guide des courses et marchés locaux",
        "head_nutrition": "Bilan nutritionnel et recommandations",
        "msg_missing_input": (
            "**Action requise :** chargez une photo, saisissez des ingrédients"
            " ou choisissez un plat dans le menu."
        ),
        "msg_analysis_recipe": (
            "*Mode analyse diététique : aucune recette générée.*"
        ),
        "msg_analysis_shopping": "*Pas de liste de courses dans ce mode.*",
        "msg_error": "**Erreur d'exécution :**",
        "msg_no_output": "Aucun résultat généré.",
    },
}


def ui_text(language: str) -> dict:
  return UI_TEXT[LANGUAGES.get(language, "en")]


def placeholder_html(lines: tuple[str, str]) -> str:
  title, detail = lines
  return f"<div class='ck-placeholder'><b>{title}</b><br>{detail}</div>"


def dish_choices(t: dict) -> list[tuple[str, str]]:
  return [(t["auto_detect"], AUTO_DETECT)] + [(n, n) for n in DISH_NAMES]


# The prompts ask for no emoji, but the model still slips in symbols like
# check marks and warning signs now and then.
EMOJI_PATTERN = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]"
)


def strip_emoji(text: str) -> str:
  return EMOJI_PATTERN.sub("", text)


def dispatch_outputs_to_tabs(crew_output, t: dict):
  """Split the crew output into the recipe, shopping and nutrition tabs.

  Outputs are matched by task name, since the number of tasks that run
  depends on the inputs (no vision step without photos, for example).
  """
  outputs = {
      o.name: strip_emoji(str(o.raw)).strip()
      for o in getattr(crew_output, "tasks_output", [])
  }

  if MEAL_ANALYSIS_TASK in outputs:
    return (
        t["msg_analysis_recipe"],
        t["msg_analysis_shopping"],
        f"## {t['head_nutrition']}\n\n{outputs[MEAL_ANALYSIS_TASK]}",
    )

  if RECIPE_TASK not in outputs:
    raw = getattr(crew_output, "raw", "") or t["msg_no_output"]
    return f"## {t['head_recipe']}\n\n{raw}", "", ""

  return (
      f"## {t['head_recipe']}\n\n{outputs[RECIPE_TASK]}",
      f"## {t['head_shopping']}\n\n{outputs.get(SOURCING_TASK, '')}",
      f"## {t['head_nutrition']}\n\n{outputs.get(NUTRITION_TASK, '')}",
  )


def run_pipeline(
    image_files,
    manual_text,
    selected_dish,
    user_cravings,
    dietary_selected,
    dietary_custom,
    target_city,
    workflow_type,
    recipe_style,
    language,
    progress=gr.Progress(track_tqdm=True),
):
  t = ui_text(language)
  # Without a Serper key the web styles cannot work: fall back to classic and
  # say so above the recipe.
  web_fallback = recipe_style != CLASSIC_STYLE and not WEB_SEARCH_AVAILABLE
  if web_fallback:
    recipe_style = CLASSIC_STYLE
  has_images = bool(image_files and len(image_files) > 0)
  has_text = bool(manual_text and manual_text.strip())
  has_dish = bool(selected_dish) and selected_dish != AUTO_DETECT

  if not has_images and not has_text and not has_dish:
    return t["msg_missing_input"], "", ""

  images_arg = (
      ",".join([f.name if hasattr(f, "name") else str(f) for f in image_files])
      if has_images
      else "None"
  )
  manual_arg = manual_text.strip() if has_text else "None"

  diet_items = list(dietary_selected) if dietary_selected else []
  if dietary_custom and dietary_custom.strip():
    diet_items.append(dietary_custom.strip())
  dietary_restrictions = ", ".join(diet_items) if diet_items else "None"

  # Look the dish up by its exact name so the chef works from that recipe.
  heritage_recipe = get_recipe_by_name(selected_dish) if has_dish else None

  inputs = {
      "image_paths": images_arg,
      "manual_input": manual_arg,
      "selected_dish": selected_dish if has_dish else "None",
      "heritage_recipe": heritage_recipe or "None",
      "has_pantry": "yes" if has_images or has_text else "no",
      "meal_preference": (user_cravings or "").strip() or "None",
      "dietary_restrictions": dietary_restrictions,
      "target_city": target_city,
      "language": CREW_LANGUAGE[LANGUAGES.get(language, "en")],
      "recipe_style": recipe_style,
  }

  if workflow_type == "recipe":
    crew_builder = NourishBotRecipeCrew(
        image_data=images_arg,
        manual_ingredients=manual_arg,
        recipe_style=recipe_style,
    )
  else:
    crew_builder = NourishBotAnalysisCrew(
        image_data=images_arg, manual_ingredients=manual_arg
    )
  try:
    recipe_md, shopping_md, nutrition_md = dispatch_outputs_to_tabs(
        crew_builder.crew().kickoff(inputs=inputs), t
    )
    if web_fallback and workflow_type == "recipe":
      recipe_md = f"{t['msg_web_unavailable']}\n\n{recipe_md}"
    return recipe_md, shopping_md, nutrition_md
  except Exception as err:
    logging.exception(f"Pipeline failed: {err}")
    return f"{t['msg_error']}\n\n```text\n{err}\n```", "", ""


# UI theme: colors taken from the mosaic background and Sidi Bou Said blue.
sidi_bou_said = gr.themes.Color(
    c50="#eef4fa",
    c100="#d6e4f2",
    c200="#adc9e5",
    c300="#7ea8d3",
    c400="#4d84bd",
    c500="#1e5f9e",
    c600="#1a5289",
    c700="#174572",
    c800="#14395e",
    c900="#122f4d",
    c950="#0b1f35",
    name="sidi_bou_said",
)

theme = gr.themes.Soft(
    primary_hue=sidi_bou_said,
    secondary_hue=gr.themes.colors.amber,
    neutral_hue=gr.themes.colors.stone,
    font=[gr.themes.GoogleFont("Nunito Sans"), "ui-sans-serif", "sans-serif"],
    radius_size=gr.themes.sizes.radius_lg,
).set(
    body_background_fill="transparent",
    block_background_fill="rgba(255, 253, 248, 0.6)",
    background_fill_secondary="rgba(255, 250, 240, 0.55)",
    block_border_color="rgba(201, 138, 43, 0.22)",
    # Field labels: linen background with brown text instead of light blue.
    block_label_background_fill="#f6ecdb",
    block_label_border_color="rgba(201, 138, 43, 0.35)",
    block_label_text_color="#8a4a1f",
    block_title_text_color="#8a4a1f",
    color_accent_soft="#f7efe1",
    border_color_accent="#e3c9a0",
    input_background_fill="rgba(255, 255, 255, 0.94)",
    button_primary_background_fill="linear-gradient(135deg, #1e5f9e, #1b2f6e)",
    button_primary_background_fill_hover="linear-gradient(135deg, #2a6fb0, #22397f)",
    button_primary_text_color="#ffffff",
    checkbox_background_color_selected="#1e5f9e",
)

# Only the files listed here are served by Gradio, not the whole folder.
UI_ASSETS_DIR = CURRENT_DIR / "assets" / "ui"
MOSAIC_FILE = UI_ASSETS_DIR / "mosaique_Tunisienne.jpg"
# (file, object-position, captions)
VIGNETTES = [
    ("couscous.jpeg.webp", "center",
     {"en": "Fish couscous", "fr": "Couscous au poisson"}),
    ("Ojja_bel_mregez.jpg", "center 70%",
     {"en": "Ojja with merguez", "fr": "Ojja merguez"}),
    ("tajine.jpg", "center", {"en": "Tunisian tajine", "fr": "Tajine tunisien"}),
    ("brick.jpg", "60% center", {"en": "Egg brik", "fr": "Brick à l'œuf"}),
    ("fricasse.jpg", "center",
     {"en": "Tunisian fricassé", "fr": "Fricassé tunisien"}),
]
# Empty Nabeul plate, used as a corner decoration rather than a dish photo.
CORNER_PLATE = UI_ASSETS_DIR / "assiette-tunisienne-145-p.jpg"
_ui_files = (
    [MOSAIC_FILE, CORNER_PLATE]
    + [UI_ASSETS_DIR / name for name, _, _ in VIGNETTES]
)
gr.set_static_paths(paths=[p for p in _ui_files if p.exists()])


def ui_asset_url(path: Path) -> str:
  return f"/gradio_api/file={path.as_posix()}"


# Small SVG icons shown above the title: chili, couscoussier, mortar.
ICON_CHILI = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
    "<path d='M41 15c-2-4-1-8 3-10' stroke='#2e7d32' stroke-width='3.5'"
    " fill='none' stroke-linecap='round'/>"
    "<path d='M38 16c9 2 13 10 9 21-5 12-19 22-33 23-3 0-4-3-1-4"
    " 12-5 19-14 20-26 1-8 0-13 5-14z' fill='#d4382c'/>"
    "<path d='M37 20c4 1 6 4 5 9' stroke='#fff' stroke-opacity='.5'"
    " stroke-width='2.5' fill='none' stroke-linecap='round'/></svg>"
)
ICON_COUSCOUSSIER = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
    "<path d='M24 13c-2-3 2-5 0-8M32 13c-2-3 2-5 0-8M40 13c-2-3 2-5 0-8'"
    " stroke='#7fa9c9' stroke-width='2.2' fill='none' stroke-linecap='round'/>"
    "<path d='M22 20a10 5 0 0 1 20 0z' fill='#f0a53a'/>"
    "<path d='M17 20h30l-3 12H20z' fill='#c98a2b'/>"
    "<g fill='#fff8e8'><circle cx='25' cy='26' r='1.4'/><circle cx='32' cy='26'"
    " r='1.4'/><circle cx='39' cy='26' r='1.4'/></g>"
    "<rect x='9' y='31' width='46' height='4' rx='2' fill='#1b2f6e'/>"
    "<path d='M12 35h40c0 12-8 21-20 21S12 47 12 35z' fill='#233a7a'/>"
    "<path d='M8 40h5M51 40h5' stroke='#1b2f6e' stroke-width='3'"
    " stroke-linecap='round'/>"
    "<path d='M20 42c2 4 6 7 11 8' stroke='#fff' stroke-opacity='.35'"
    " stroke-width='2.5' fill='none' stroke-linecap='round'/></svg>"
)
ICON_MAHREZ = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
    "<rect x='36' y='3' width='6' height='30' rx='3'"
    " transform='rotate(25 39 18)' fill='#8d6e3f'/>"
    "<path d='M12 28h40c0 12-8 20-20 20S12 40 12 28z' fill='#c98a2b'/>"
    "<rect x='10' y='25' width='44' height='5' rx='2.5' fill='#e6b95c'/>"
    "<path d='M24 48h16l3 8H21z' fill='#a8762a'/>"
    "<path d='M18 34c3 6 8 9 14 9' stroke='#fff' stroke-opacity='.4'"
    " stroke-width='2.5' fill='none' stroke-linecap='round'/></svg>"
)


def svg_data_uri(svg: str) -> str:
  return "data:image/svg+xml," + quote(svg)


def build_hero_html(language: str) -> str:
  code = LANGUAGES.get(language, "en")
  t = UI_TEXT[code]
  vignettes = "".join(
      f"<figure class='ck-vignette'><img src='{ui_asset_url(UI_ASSETS_DIR / name)}'"
      f" alt=\"{captions[code]}\" loading='lazy' style='object-position:{pos}'>"
      f"<figcaption>{captions[code]}</figcaption></figure>"
      for name, pos, captions in VIGNETTES
      if (UI_ASSETS_DIR / name).exists()
  )
  corner_plate = (
      "<span class='ck-corner-plate' aria-hidden='true'"
      f" style=\"background-image:url('{ui_asset_url(CORNER_PLATE)}')\"></span>"
      if CORNER_PLATE.exists()
      else ""
  )
  ornaments = "".join(
      f"<span class='ck-ornament' title=\"{label}\""
      f" style=\"background-image:url('{svg_data_uri(svg)}')\"></span>"
      for svg, label in [
          (ICON_CHILI, "Piment"),
          (ICON_COUSCOUSSIER, "Couscoussier"),
          (ICON_MAHREZ, "Mahrez"),
      ]
  )
  return (
      "<div class='ck-hero'><div class='ck-band'></div>"
      f"<div class='ck-hero-body'>{corner_plate}"
      "<div class='ck-hero-text'>"
      f"<div class='ck-ornaments'>{ornaments}</div>"
      "<h1>Carthage<span> Kitchen</span> </h1>"
      f"<p class='ck-tagline'>{t['tagline']}</p>"
      f"<p class='ck-sub'>{t['subtitle']}</p>"
      "</div>"
      f"<div class='ck-vignettes'>{vignettes}</div>"
      "</div><div class='ck-band'></div></div>"
  )


# The styling assumes a light background, so force Gradio's light mode.
force_light_js = """
() => {
  const url = new URL(window.location);
  if (url.searchParams.get('__theme') !== 'light') {
    url.searchParams.set('__theme', 'light');
    window.location.replace(url.href);
  }
}
"""


def print_js(box_id: str) -> str:
  """Print one output box on its own.

  The box content is copied into a sheet at the top of <body>; the print CSS
  hides everything else while body has the ck-printing class.
  """
  return f"""
() => {{
  const box = document.getElementById('{box_id}');
  if (!box || box.querySelector('.ck-placeholder')) return;
  const sheet = document.createElement('div');
  sheet.id = 'ck-print-sheet';
  sheet.innerHTML = (box.querySelector('.prose') || box).innerHTML;
  document.body.prepend(sheet);
  document.body.classList.add('ck-printing');
  window.addEventListener('afterprint', () => {{
    sheet.remove();
    document.body.classList.remove('ck-printing');
  }}, {{once: true}});
  window.print();
}}
"""


# Gradio 6 drops @import rules from css, so the title font is loaded in <head>.
head = (
    "<link rel='stylesheet' href='https://fonts.googleapis.com/css2?"
    "family=Playfair+Display:wght@600;700&display=swap'>"
)

# Print styles go in <head> because Gradio prefixes every selector in css
# with its container class, and these must target body.
PRINT_CSS = """
#ck-print-sheet { display: none; }
@media print {
  body.ck-printing { background: #fff !important; }
  body.ck-printing > :not(#ck-print-sheet) { display: none !important; }
  body.ck-printing #ck-print-sheet {
    display: block;
    color: #1c1917;
    font: 11pt/1.5 Georgia, serif;
  }
  #ck-print-sheet h2, #ck-print-sheet h3 {
    font-family: 'Playfair Display', Georgia, serif;
    color: #233a7a;
    break-after: avoid;
  }
  #ck-print-sheet table { border-collapse: collapse; width: 100%; }
  #ck-print-sheet th, #ck-print-sheet td { border: 1px solid #d6d3d1; padding: 4px 8px; }
  #ck-print-sheet tr, #ck-print-sheet li { break-inside: avoid; }
  #ck-print-sheet a { color: inherit; }
}
"""
head += f"<style>{PRINT_CSS}</style>"

css = """
:root {
  --ck-blue: #1e5f9e;        /* Sidi Bou Said blue */
  --ck-amber: #d97706;       /* tab accent */
  --ck-sand: #e3c9a0;
  --ck-linen: #f6ecdb;
  --ck-spice: #8a4a1f;
  --ck-indigo: #1b2f6e;
  --ck-cobalt: #233a7a;      /* mosaic cobalt */
  --ck-chaux: #fbf6ec;       /* warm whitewash */
  --ck-saffron: #f0a53a;
  --ck-ochre: #c98a2b;
  --ck-terracotta: #d4572e;
  --ck-emerald: #1f6b4a;
  --ck-olive: #5f7a3a;
  --ck-harissa: #c0392b;
  --ck-ink: #2b2a33;
  --ck-mosaic: url('__MOSAIC_URL__');
  --ck-card-border: 1px solid rgba(201, 138, 43, 0.45);
  --ck-card-shadow: 0 18px 44px -20px rgba(80, 40, 10, 0.45),
                    0 2px 6px -2px rgba(27, 47, 110, 0.12),
                    inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

/* Mosaic background, faded toward the center so text stays readable. */
body {
  background-color: var(--ck-chaux) !important;
  background-image:
    radial-gradient(ellipse 75% 70% at 50% 42%,
      rgba(251, 246, 236, 0.94) 0%,
      rgba(251, 246, 236, 0.86) 45%,
      rgba(251, 240, 222, 0.55) 80%,
      rgba(240, 165, 58, 0.18) 100%),
    var(--ck-mosaic),
    linear-gradient(180deg, #fbf1de 0%, #f6e6cc 100%) !important;
  background-size: auto, 237px auto, auto !important;
  background-attachment: fixed !important;
}
gradio-app, .gradio-container { background: transparent !important; }
gradio-app { position: relative; z-index: 1; }
.gradio-container { color: var(--ck-ink); }

/* Mosaic strips on the sides, wide screens only. */
@media (min-width: 1380px) {
  body::before, body::after {
    content: "";
    position: fixed;
    top: 0;
    bottom: 0;
    width: 58px;
    z-index: 0;
    pointer-events: none;
    background-image: var(--ck-mosaic);
    background-size: 58px auto;
    background-repeat: repeat-y;
    box-shadow: 0 0 24px rgba(80, 40, 10, 0.25);
  }
  body::before { left: 0; border-right: 3px solid var(--ck-saffron); }
  body::after { right: 0; border-left: 3px solid var(--ck-saffron); }
}

/* Language switch, pinned to the top-right corner of the header. */
#ck-header { position: relative; gap: 0 !important; }
#ck-lang {
  position: absolute;
  top: 24px;
  right: 22px;
  z-index: 5;
  width: auto !important;
  min-width: 0 !important;
  flex: none !important;
}
#ck-lang .wrap { gap: 0 !important; flex-wrap: nowrap; }
#ck-lang label {
  margin: 0 !important;
  padding: 0.2rem 0.7rem !important;
  font-size: 0.75rem !important;
  font-weight: 700;
  letter-spacing: 0.03em;
  color: var(--ck-spice) !important;
  background: rgba(246, 236, 219, 0.9) !important;
  border: 1px solid rgba(201, 138, 43, 0.45) !important;
  box-shadow: none !important;
  border-radius: 0 !important;
  cursor: pointer;
}
#ck-lang label:first-child { border-radius: 999px 0 0 999px !important; }
#ck-lang label:last-child { border-radius: 0 999px 999px 0 !important; border-left: none !important; }
#ck-lang label.selected, #ck-lang label:has(input:checked) {
  color: #fff !important;
  background: var(--ck-blue) !important;
  border-color: var(--ck-blue) !important;
}
#ck-lang input[type="radio"] { display: none; }

/* Header */
.ck-hero {
  position: relative;
  overflow: hidden;
  border-radius: 22px;
  background: rgba(255, 252, 245, 0.8);
  backdrop-filter: blur(14px) saturate(150%);
  -webkit-backdrop-filter: blur(14px) saturate(150%);
  border: var(--ck-card-border);
  box-shadow: var(--ck-card-shadow);
}
.ck-band {
  height: 14px;
  background-image: var(--ck-mosaic);
  background-size: 42px auto;
  background-repeat: repeat-x;
  background-position: center;
  border-top: 1px solid rgba(201, 138, 43, 0.6);
  border-bottom: 1px solid rgba(201, 138, 43, 0.6);
}
.ck-hero-body {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.5rem;
  padding: 1.2rem 1.8rem;
  background:
    radial-gradient(circle at 0% 50%, rgba(240, 165, 58, 0.14), transparent 45%),
    radial-gradient(circle at 100% 50%, rgba(212, 87, 46, 0.1), transparent 45%);
}
.ck-hero-text { flex: 1 1 auto; min-width: 280px; position: relative; z-index: 1; }

/* Plate peeking out of the bottom-right corner. */
.ck-corner-plate {
  position: absolute;
  right: -62px;
  bottom: -62px;
  width: 150px;
  height: 150px;
  border-radius: 50%;
  background-size: 108% auto;
  background-position: center;
  background-repeat: no-repeat;
  opacity: 0.4;
  transform: rotate(-12deg);
  pointer-events: none;
  z-index: 0;
}
.ck-ornaments { display: flex; gap: 0.35rem; margin-bottom: 0.3rem; }
.ck-ornament {
  width: 30px;
  height: 30px;
  background-size: contain;
  background-repeat: no-repeat;
  filter: drop-shadow(0 2px 2px rgba(80, 40, 10, 0.25));
}
.ck-hero h1 {
  font-family: 'Playfair Display', Georgia, serif !important;
  font-size: 2.3rem !important;
  font-weight: 700 !important;
  margin: 0 !important;
  color: var(--ck-cobalt) !important;
  letter-spacing: 0.01em;
}
.ck-hero h1 span { color: var(--ck-terracotta); }
.ck-tagline {
  margin: 0.2rem 0 0.5rem !important;
  font-size: 0.82rem;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: var(--ck-emerald) !important;
  font-weight: 800;
}
.ck-sub { margin: 0 !important; color: #57534e !important; font-size: 0.98rem; }
.ck-sub b { color: var(--ck-blue); }

.ck-vignettes {
  display: flex;
  align-items: center;
  flex: 0 0 auto;
  position: relative;
  z-index: 1;
  padding-bottom: 0.6rem;
}
.ck-vignette { margin: 0 0 0 -14px; position: relative; text-align: center; }
.ck-vignette:first-child { margin-left: 0; }
.ck-vignette img {
  width: 92px;
  height: 92px;
  object-fit: cover;
  border-radius: 50%;
  border: 3px solid #fffaf0;
  outline: 2px solid var(--ck-saffron);
  box-shadow: 0 8px 18px -8px rgba(80, 40, 10, 0.55);
  transition: transform 0.25s ease;
}
.ck-vignette:nth-child(even) img { outline-color: var(--ck-cobalt); transform: translateY(8px); }
.ck-vignette:hover img { transform: translateY(-4px) scale(1.06); z-index: 2; position: relative; }
.ck-vignette figcaption {
  position: absolute;
  left: 50%;
  bottom: -1.4rem;
  transform: translateX(-50%);
  white-space: nowrap;
  font-size: 0.7rem;
  font-weight: 700;
  color: var(--ck-cobalt);
  opacity: 0;
  transition: opacity 0.2s;
}
.ck-vignette:hover figcaption { opacity: 1; }

/* Cards */
.ck-glass {
  background: rgba(255, 252, 245, 0.8) !important;
  backdrop-filter: blur(14px) saturate(150%);
  -webkit-backdrop-filter: blur(14px) saturate(150%);
  border: var(--ck-card-border) !important;
  border-radius: 22px !important;
  box-shadow: var(--ck-card-shadow);
  padding: 1.25rem !important;
}

.category-header h4 {
  display: inline-block;
  font-family: 'Playfair Display', Georgia, serif !important;
  color: var(--ck-spice) !important;
  background: var(--ck-linen);
  border: 1px solid rgba(201, 138, 43, 0.35);
  border-left: 4px solid var(--ck-amber);
  border-radius: 10px;
  padding: 0.3rem 0.8rem 0.3rem 0.6rem;
  margin: 0.6rem 0 0 !important;
}

/* Upload area */
.ck-upload {
  border: 2px dashed var(--ck-sand) !important;
  background: rgba(251, 246, 236, 0.7) !important;
  transition: border-color 0.2s;
}
.ck-upload:hover { border-color: var(--ck-blue) !important; }
.ck-upload [class*="icon-wrap"] { color: var(--ck-blue) !important; }

/* Input tabs (left column) */
.ck-input-tabs { --color-accent: var(--ck-blue); }

#ck-submit {
  font-weight: 700;
  letter-spacing: 0.02em;
  box-shadow: 0 10px 24px -10px rgba(27, 47, 110, 0.6);
  border-bottom: 3px solid var(--ck-saffron);
}

/* Output tabs: shared amber underline, one text accent per tab. */
#ck-output-tabs { --color-accent: var(--ck-amber); }
#ck-tab-recipe-button, #ck-tab-recipe {
  --ck-accent: #b45309;      /* darker amber, readable on cream */
  --ck-accent-soft: rgba(217, 119, 6, 0.08);
}
#ck-tab-shopping-button, #ck-tab-shopping {
  --ck-accent: var(--ck-emerald);
  --ck-accent-soft: rgba(31, 107, 74, 0.08);
}
#ck-tab-nutrition-button, #ck-tab-nutrition {
  --ck-accent: var(--ck-blue);
  --ck-accent-soft: rgba(31, 111, 191, 0.08);
}

#ck-output-tabs button[role="tab"] {
  font-weight: 700;
  color: #78716c;
  border-radius: 12px 12px 0 0;
  transition: color 0.2s, background 0.2s;
}
#ck-output-tabs button[role="tab"]:hover { color: var(--ck-accent); }
#ck-output-tabs button[role="tab"][aria-selected="true"] {
  color: var(--ck-accent) !important;
  background: var(--ck-accent-soft);
}
#ck-output-tabs button[role="tab"][aria-selected="true"]::after {
  background-color: var(--ck-amber) !important;
  height: 3px;
}

#ck-tab-recipe, #ck-tab-shopping, #ck-tab-nutrition {
  border-top: 3px solid var(--ck-amber);
  border-radius: 0 0 16px 16px;
  background: linear-gradient(180deg, var(--ck-accent-soft), rgba(255, 255, 255, 0.5) 160px);
  padding: 1.25rem !important;
  min-height: 460px;
}
#ck-output-tabs .prose h2 {
  font-family: 'Playfair Display', Georgia, serif !important;
  color: var(--ck-accent) !important;
  border-bottom: 1px solid var(--ck-accent-soft);
  padding-bottom: 0.4rem;
}
#ck-output-tabs .prose h3, #ck-output-tabs .prose strong { color: var(--ck-cobalt); }
#ck-output-tabs .prose li::marker { color: var(--ck-accent); }
#ck-output-tabs .prose table { border-radius: 10px; overflow: hidden; }
#ck-output-tabs .prose th { background: var(--ck-accent-soft); color: var(--ck-cobalt); }
#ck-output-tabs .prose blockquote {
  border-left: 4px solid var(--ck-saffron);
  background: rgba(240, 165, 58, 0.1);
  border-radius: 0 10px 10px 0;
}

.ck-placeholder {
  border: 2px dashed var(--ck-accent);
  border-radius: 16px;
  padding: 2.5rem 1.5rem;
  text-align: center;
  color: #78716c;
  background: rgba(255, 255, 255, 0.65);
}
.ck-placeholder b { color: var(--ck-accent); }

.ck-print-btn { margin-top: 1rem; align-self: flex-end; }

@media (max-width: 900px) {
  #ck-lang { top: 20px; right: 14px; }
  .ck-hero-body { flex-direction: column; text-align: center; }
  .ck-ornaments { justify-content: center; }
  .ck-vignette img { width: 64px; height: 64px; }
  .ck-corner-plate { display: none; }
}
@media (max-width: 768px) {
  .ck-hero h1 { font-size: 1.6rem !important; }
  .ck-glass { padding: 0.8rem !important; }
}
""".replace("__MOSAIC_URL__", ui_asset_url(MOSAIC_FILE))

# Placeholders in every language, so a language switch only replaces an
# output box that still shows its placeholder, never a generated result.
OUTPUT_PLACEHOLDERS = {
    key: {placeholder_html(t[key]) for t in UI_TEXT.values()}
    for key in ("ph_recipe", "ph_shopping", "ph_nutrition")
}


def translate_ui(language, recipe_md, shopping_md, nutrition_md):
  t = ui_text(language)

  def placeholder_update(current, key):
    if current in OUTPUT_PLACEHOLDERS[key]:
      return gr.update(value=placeholder_html(t[key]))
    return gr.update()

  return [
      gr.update(value=build_hero_html(language)),
      gr.update(label=t["tab_photos"]),
      gr.update(label=t["upload_label"]),
      gr.update(label=t["tab_text"]),
      gr.update(label=t["manual_label"], placeholder=t["manual_placeholder"]),
      gr.update(value=t["dish_header"]),
      gr.update(
          label=t["dish_label"].format(count=len(DISH_NAMES)),
          choices=dish_choices(t),
      ),
      gr.update(
          label=t["style_label"], choices=list(zip(t["style_choices"], RECIPE_STYLES))
      ),
      gr.update(label=t["cravings_label"], placeholder=t["cravings_placeholder"]),
      gr.update(value=t["diet_header"]),
      gr.update(
          label=t["diet_label"],
          choices=list(zip(t["diet_choices"], DIETARY_PROFILES)),
      ),
      gr.update(
          label=t["allergies_label"], placeholder=t["allergies_placeholder"]
      ),
      gr.update(label=t["city_label"], choices=list(zip(t["city_choices"], CITIES))),
      gr.update(
          label=t["mode_label"],
          choices=[(t["mode_recipe"], "recipe"), (t["mode_analysis"], "analysis")],
      ),
      gr.update(value=t["submit"]),
      gr.update(label=t["out_recipe"]),
      gr.update(label=t["out_shopping"]),
      gr.update(label=t["out_nutrition"]),
      gr.update(value=t["print_recipe"]),
      gr.update(value=t["print_shopping"]),
      placeholder_update(recipe_md, "ph_recipe"),
      placeholder_update(shopping_md, "ph_shopping"),
      placeholder_update(nutrition_md, "ph_nutrition"),
  ]


T = ui_text(DEFAULT_LANGUAGE)

with gr.Blocks(
    title="NourishBot — Carthage Kitchen ",
    theme=theme,
    css=css,
    js=force_light_js,
    head=head,
) as demo:
  with gr.Column(elem_id="ck-header"):
    hero_html = gr.HTML(build_hero_html(DEFAULT_LANGUAGE))
    language_selector = gr.Radio(
        choices=list(LANGUAGES),
        value=DEFAULT_LANGUAGE,
        show_label=False,
        container=False,
        elem_id="ck-lang",
    )

  with gr.Row():
    with gr.Column(scale=5, min_width=360, elem_classes="ck-glass"):
      with gr.Tabs(elem_classes="ck-input-tabs"):
        with gr.TabItem(T["tab_photos"]) as photos_tab:
          image_files_input = gr.File(
              file_count="multiple",
              file_types=["image"],
              type="filepath",
              label=T["upload_label"],
              elem_classes="ck-upload",
          )
        with gr.TabItem(T["tab_text"]) as text_tab:
          manual_text_input = gr.Textbox(
              label=T["manual_label"],
              placeholder=T["manual_placeholder"],
              lines=3,
          )

      dish_header = gr.Markdown(T["dish_header"], elem_classes="category-header")
      dish_dropdown = gr.Dropdown(
          choices=dish_choices(T),
          value=AUTO_DETECT,
          label=T["dish_label"].format(count=len(DISH_NAMES)),
          interactive=True,
      )

      style_selector = gr.Radio(
          choices=list(zip(T["style_choices"], RECIPE_STYLES)),
          value=CLASSIC_STYLE,
          label=T["style_label"],
      )

      cravings_input = gr.Textbox(
          label=T["cravings_label"],
          placeholder=T["cravings_placeholder"],
          lines=1,
      )

      diet_header = gr.Markdown(T["diet_header"], elem_classes="category-header")
      dietary_checks = gr.CheckboxGroup(
          choices=list(zip(T["diet_choices"], DIETARY_PROFILES)),
          label=T["diet_label"],
          value=[],
      )
      dietary_free_text = gr.Textbox(
          label=T["allergies_label"],
          placeholder=T["allergies_placeholder"],
      )

      with gr.Row():
        city_selector = gr.Dropdown(
            choices=list(zip(T["city_choices"], CITIES)),
            value=CITIES[0],
            label=T["city_label"],
        )
        workflow_selector = gr.Radio(
            choices=[(T["mode_recipe"], "recipe"), (T["mode_analysis"], "analysis")],
            value="recipe",
            label=T["mode_label"],
        )

      submit_btn = gr.Button(
          T["submit"],
          variant="primary",
          size="lg",
          elem_id="ck-submit",
      )

    with gr.Column(scale=7, min_width=520, elem_classes="ck-glass"):
      with gr.Tabs(elem_id="ck-output-tabs"):
        with gr.TabItem(T["out_recipe"], elem_id="ck-tab-recipe") as recipe_tab:
          recipe_box = gr.Markdown(
              placeholder_html(T["ph_recipe"]), elem_id="ck-recipe-md"
          )
          print_recipe_btn = gr.Button(
              T["print_recipe"], size="sm", elem_classes="ck-print-btn"
          )

        with gr.TabItem(
            T["out_shopping"], elem_id="ck-tab-shopping"
        ) as shopping_tab:
          shopping_box = gr.Markdown(
              placeholder_html(T["ph_shopping"]), elem_id="ck-shopping-md"
          )
          print_shopping_btn = gr.Button(
              T["print_shopping"], size="sm", elem_classes="ck-print-btn"
          )

        with gr.TabItem(
            T["out_nutrition"], elem_id="ck-tab-nutrition"
        ) as nutrition_tab:
          analysis_box = gr.Markdown(placeholder_html(T["ph_nutrition"]))

  language_selector.change(
      fn=translate_ui,
      inputs=[language_selector, recipe_box, shopping_box, analysis_box],
      outputs=[
          hero_html,
          photos_tab,
          image_files_input,
          text_tab,
          manual_text_input,
          dish_header,
          dish_dropdown,
          style_selector,
          cravings_input,
          diet_header,
          dietary_checks,
          dietary_free_text,
          city_selector,
          workflow_selector,
          submit_btn,
          recipe_tab,
          shopping_tab,
          nutrition_tab,
          print_recipe_btn,
          print_shopping_btn,
          recipe_box,
          shopping_box,
          analysis_box,
      ],
  )

  print_recipe_btn.click(fn=None, js=print_js("ck-recipe-md"))
  print_shopping_btn.click(fn=None, js=print_js("ck-shopping-md"))

  submit_btn.click(
      fn=run_pipeline,
      inputs=[
          image_files_input,
          manual_text_input,
          dish_dropdown,
          cravings_input,
          dietary_checks,
          dietary_free_text,
          city_selector,
          workflow_selector,
          style_selector,
          language_selector,
      ],
      outputs=[recipe_box, shopping_box, analysis_box],
  )

if __name__ == "__main__":
  demo.launch(server_name="0.0.0.0", server_port=7860)
