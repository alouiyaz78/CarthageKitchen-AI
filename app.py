import logging
import os
from pathlib import Path
from urllib.parse import quote
from dotenv import load_dotenv
import gradio as gr
import psycopg2
from src.crew import (
    MEAL_ANALYSIS_TASK,
    NUTRITION_TASK,
    RECIPE_TASK,
    SOURCING_TASK,
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


def get_heritage_recipes_from_neon() -> list[str]:
  default_choice = ["Auto-detect / Recipe from my ingredients"]
  if not DATABASE_URL:
    return default_choice
  try:
    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor() as cur:
      cur.execute(
          "SELECT DISTINCT dish_name FROM tunisian_recipes ORDER BY dish_name"
          " ASC;"
      )
      rows = cur.fetchall()
    conn.close()
    return default_choice + [row[0] for row in rows if row[0]]
  except Exception as e:
    logging.error(f"Could not load dish names from Neon: {e}")
    return default_choice


DISH_CHOICES = get_heritage_recipes_from_neon()


def dispatch_outputs_to_tabs(crew_output):
  """Split the crew output into the recipe, shopping and nutrition tabs.

  Outputs are matched by task name, since the number of tasks that run
  depends on the inputs (no vision step without photos, for example).
  """
  recipe_head = "## Fiche recette patrimoniale\n\n"
  shopping_head = "## Guide des courses et marchés locaux\n\n"
  nutrition_head = "## Bilan nutritionnel et recommandations\n\n"

  outputs = {
      o.name: str(o.raw).strip()
      for o in getattr(crew_output, "tasks_output", [])
  }

  if MEAL_ANALYSIS_TASK in outputs:
    return (
        "*Mode analyse nutritionnelle : aucune recette générée.*",
        "*Pas de liste de courses dans ce mode.*",
        nutrition_head + outputs[MEAL_ANALYSIS_TASK],
    )

  if RECIPE_TASK not in outputs:
    raw = getattr(crew_output, "raw", "") or "Aucun résultat généré."
    return recipe_head + raw, "", ""

  return (
      recipe_head + outputs[RECIPE_TASK],
      shopping_head + outputs.get(SOURCING_TASK, ""),
      nutrition_head + outputs.get(NUTRITION_TASK, ""),
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
    progress=gr.Progress(track_tqdm=True),
):
  has_images = bool(image_files and len(image_files) > 0)
  has_text = bool(manual_text and manual_text.strip())
  has_dish = selected_dish and not selected_dish.startswith("Auto-detect")

  if not has_images and not has_text and not has_dish:
    return (
        "**Action requise :** veuillez charger une photo, saisir des"
        " ingrédients ou choisir un plat dans le menu.",
        "",
        "",
    )

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
      "meal_preference": user_cravings.strip() if user_cravings else "None",
      "dietary_restrictions": dietary_restrictions,
      "target_city": target_city,
  }

  crew_class = (
      NourishBotRecipeCrew if workflow_type == "recipe" else NourishBotAnalysisCrew
  )
  try:
    crew = crew_class(image_data=images_arg, manual_ingredients=manual_arg).crew()
    return dispatch_outputs_to_tabs(crew.kickoff(inputs=inputs))
  except Exception as err:
    logging.exception(f"Pipeline failed: {err}")
    return f"**Erreur d'exécution :**\n\n```text\n{str(err)}\n```", "", ""


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
# (file, caption, object-position)
VIGNETTES = [
    ("couscous.jpeg.webp", "Couscous au poisson", "center"),
    ("Ojja_bel_mregez.jpg", "Ojja merguez", "center 70%"),
    ("tajine.jpg", "Tajine tunisien", "center"),
    ("brick.jpg", "Brick à l'œuf", "60% center"),
    ("fricasse.jpg", "Fricassé tunisien", "center"),
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


def build_hero_html() -> str:
  vignettes = "".join(
      f"<figure class='ck-vignette'><img src='{ui_asset_url(UI_ASSETS_DIR / name)}'"
      f" alt=\"{label}\" loading='lazy' style='object-position:{pos}'>"
      f"<figcaption>{label}</figcaption></figure>"
      for name, label, pos in VIGNETTES
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
      "<h1>Carthage<span>Kitchen</span> AI</h1>"
      "<p class='ck-tagline'>Studio Culinaire Tunisien &amp; Nutrition</p>"
      "<p class='ck-sub'>Recettes patrimoniales authentiques, approvisionnement"
      " local à <b>Ottawa/Gatineau</b> et <b>Montréal</b>, et évaluation"
      " diététique complète.</p>"
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

# Gradio 6 drops @import rules from css, so the title font is loaded in <head>.
head = (
    "<link rel='stylesheet' href='https://fonts.googleapis.com/css2?"
    "family=Playfair+Display:wght@600;700&display=swap'>"
)

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

@media (max-width: 900px) {
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

with gr.Blocks(
    title="NourishBot — CarthageKitchen AI",
    theme=theme,
    css=css,
    js=force_light_js,
    head=head,
) as demo:
  gr.HTML(build_hero_html())

  with gr.Row():
    with gr.Column(scale=5, min_width=360, elem_classes="ck-glass"):
      with gr.Tabs(elem_classes="ck-input-tabs"):
        with gr.TabItem("Photos des ingrédients"):
          image_files_input = gr.File(
              file_count="multiple",
              file_types=["image"],
              type="filepath",
              label="Photos du frigo, placard ou ingrédients",
              elem_classes="ck-upload",
          )
        with gr.TabItem("Ingrédients en texte"):
          manual_text_input = gr.Textbox(
              label="Ingrédients disponibles",
              placeholder="Ex: 2 tomates, piments, ail, huile d'olive, carvi...",
              lines=3,
          )

      gr.Markdown(
          "#### Choix direct d'une recette du patrimoine",
          elem_classes="category-header",
      )
      dish_dropdown = gr.Dropdown(
          choices=DISH_CHOICES,
          value="Auto-detect / Recipe from my ingredients",
          label="Répertoire Historique (83 Recettes Neon pgvector)",
          interactive=True,
      )

      cravings_input = gr.Textbox(
          label="Envies spécifiques ou variantes (Optionnel)",
          placeholder="Ex: plat au poisson, bien piquant, familial...",
          lines=1,
      )

      gr.Markdown(
          "#### Préférences et restrictions santé",
          elem_classes="category-header",
      )
      dietary_checks = gr.CheckboxGroup(
          choices=[
              "Gluten-Free",
              "Vegetarian",
              "Vegan",
              "Diabetic / Low Glycemic",
              "Low Sodium (Hypertension)",
          ],
          label="Profils Diététiques",
          value=[],
      )
      dietary_free_text = gr.Textbox(
          label="Allergies & Exclusions spécifiques",
          placeholder="Ex: sans coriandre, piment très doux...",
      )

      with gr.Row():
        city_selector = gr.Dropdown(
            choices=["Ottawa / Gatineau", "Montreal"],
            value="Ottawa / Gatineau",
            label="Ville de sourcing",
        )
        workflow_selector = gr.Radio(
            choices=[
                ("Studio Culinaire Complet", "recipe"),
                ("Analyse Diététique Seule", "analysis"),
            ],
            value="recipe",
            label="Mode d'Exécution",
        )

      submit_btn = gr.Button(
          "Générer la recette et la liste de courses",
          variant="primary",
          size="lg",
          elem_id="ck-submit",
      )

    with gr.Column(scale=7, min_width=520, elem_classes="ck-glass"):
      with gr.Tabs(elem_id="ck-output-tabs"):
        with gr.TabItem(
            "1. En cuisine", elem_id="ck-tab-recipe"
        ):
          recipe_box = gr.Markdown(
              "<div class='ck-placeholder'>"
              "<b>La fiche recette détaillée s'affichera ici.</b><br>"
              "Instructions pas à pas et techniques traditionnelles.</div>"
          )

        with gr.TabItem(
            "2. Épicerie et marchés", elem_id="ck-tab-shopping"
        ):
          shopping_box = gr.Markdown(
              "<div class='ck-placeholder'>"
              "<b>La liste des courses et les adresses locales s'afficheront"
              " ici.</b><br>Épiceries recommandées à Ottawa/Gatineau et"
              " Montréal.</div>"
          )

        with gr.TabItem(
            "3. Nutrition", elem_id="ck-tab-nutrition"
        ):
          analysis_box = gr.Markdown(
              "<div class='ck-placeholder'>"
              "<b>Le bilan nutritionnel et métabolique s'affichera ici.</b><br>"
              "Macros, calories et conseils de santé.</div>"
          )

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
      ],
      outputs=[recipe_box, shopping_box, analysis_box],
  )

if __name__ == "__main__":
  demo.launch(server_name="0.0.0.0", server_port=7860)