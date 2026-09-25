import logging
import os
from pathlib import Path
import uuid
from dotenv import load_dotenv
import gradio as gr
import psycopg2
from src.crew import NourishBotAnalysisCrew, NourishBotRecipeCrew

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
    logging.error(f"Erreur Neon : {e}")
    return default_choice


DISH_CHOICES = get_heritage_recipes_from_neon()


# ==============================================================================
# SÉPARATION STRICTE DES CONTENUS PAR ONGLET
# ==============================================================================
def dispatch_outputs_to_tabs(crew_output):
  """Isole chaque tâche pour la restituer exclusivement dans son onglet dédié."""
  recipe_md = "## 🇹🇳 Fiche Recette Patrimoniale\n\n"
  shopping_md = "## 🛒 Guide des Courses & Marchés Locaux\n\n"
  nutrition_md = "## 🔬 Bilan Nutritionnel & Recommandations Cliniques\n\n"

  tasks_out = getattr(crew_output, "tasks_output", [])

  if len(tasks_out) >= 5:
    # 1. Onglet Recette (Sortie de suggest_heritage_recipe_task)
    recipe_raw = str(tasks_out[2].raw).strip()
    recipe_md += recipe_raw

    # 2. Onglet Épicerie & Sourcing (Sortie de source_ingredients_task)
    sourcing_raw = str(tasks_out[3].raw).strip()
    shopping_md += sourcing_raw

    # 3. Onglet Nutrition (Sortie de analyze_nutrition_task)
    nutrition_raw = str(tasks_out[4].raw).strip()
    nutrition_md += nutrition_raw

  elif tasks_out:
    # Fallback pour le mode Nutrition seule
    nutrition_md += str(tasks_out[-1].raw)
    recipe_md = (
        "ℹ️ *Mode Évaluation Nutritionnelle actif. Aucune recette générée.*"
    )
    shopping_md = "ℹ️ *Aucune liste de courses requise dans ce mode.*"
  else:
    recipe_md += getattr(crew_output, "raw", "Aucun résultat généré.")

  return recipe_md, shopping_md, nutrition_md


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
        "⚠️ **Action requise :** Veuillez charger une photo, saisir des"
        " ingrédients ou choisir un plat dans le menu.",
        "",
        "",
    )

  images_arg = (
      ",".join([f.name if hasattr(f, "name") else str(f) for f in image_files])
      if has_images
      else "None"
  )

  diet_items = list(dietary_selected) if dietary_selected else []
  if dietary_custom and dietary_custom.strip():
    diet_items.append(dietary_custom.strip())
  dietary_restrictions = ", ".join(diet_items) if diet_items else "None"

  inputs = {
      "image_paths": images_arg,
      "manual_input": manual_text if has_text else "None",
      "selected_dish": selected_dish,
      "meal_preference": user_cravings.strip() if user_cravings else "None",
      "dietary_restrictions": dietary_restrictions,
      "target_city": target_city,
  }

  try:
    if workflow_type == "recipe":
      crew = NourishBotRecipeCrew(
          image_data=images_arg,
          manual_ingredients=manual_text if has_text else "None",
          dietary_restrictions=dietary_restrictions,
          target_city=target_city,
          selected_dish=selected_dish,
          user_cravings=user_cravings,
      ).crew()
      raw_result = crew.kickoff(inputs=inputs)
      return dispatch_outputs_to_tabs(raw_result)
    else:
      crew = NourishBotAnalysisCrew(
          image_data=images_arg,
          manual_ingredients=manual_text if has_text else "None",
          dietary_restrictions=dietary_restrictions,
      ).crew()
      raw_result = crew.kickoff(inputs=inputs)
      return dispatch_outputs_to_tabs(raw_result)

  except Exception as err:
    logging.error(f"Erreur : {err}")
    return f"❌ **Erreur d'exécution :**\n\n```text\n{str(err)}\n```", "", ""


# ==============================================================================
# INTERFACE GRADIO
# ==============================================================================
css = """
.main-title { font-size: 1.8rem !important; font-weight: 700 !important; text-align: center; color: #d97706; }
.sub-title { text-align: center; font-size: 1rem; margin-bottom: 1.5rem; color: #4b5563; }
.category-header { font-weight: 600; color: #b45309; margin-top: 0.5rem; }
"""

with gr.Blocks(
    title="NourishBot — CarthageKitchen AI", theme=gr.themes.Citrus(), css=css
) as demo:
  gr.Markdown(
      "# 🇹🇳 CarthageKitchen AI — Studio Culinaire Tunisien & Nutrition",
      elem_classes="main-title",
  )
  gr.Markdown(
      "Recettes patrimoniales authentiques, approvisionnement local à"
      " **Ottawa/Gatineau** et **Montréal**, et évaluation diététique"
      " complète.",
      elem_classes="sub-title",
  )

  with gr.Row():
    with gr.Column(scale=5, min_width=360):
      with gr.Tabs():
        with gr.TabItem("📸 Photos des Ingrédients"):
          image_files_input = gr.File(
              file_count="multiple",
              file_types=["image"],
              type="filepath",
              label="Photos du frigo, placard ou ingrédients",
          )
        with gr.TabItem("✍️ Ingrédients en Texte"):
          manual_text_input = gr.Textbox(
              label="Ingrédients disponibles",
              placeholder="Ex: 2 tomates, piments, ail, huile d'olive, carvi...",
              lines=3,
          )

      gr.Markdown(
          "#### 🍲 Choix Direct d'une Recette du Patrimoine",
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
          "#### 🥗 Préférences & Restrictions Santé",
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
            label="🇨🇦 Ville de Sourcing",
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
          "🚀 Générer le Plan Authentique & les Courses",
          variant="primary",
          size="lg",
      )

    with gr.Column(scale=7, min_width=520):
      with gr.Tabs():
        with gr.TabItem("🍽️ 1. En Cuisine (Fiche Recette)"):
          recipe_box = gr.Markdown(
              "<div style='border: 2px dashed #f59e0b; border-radius: 8px;"
              " padding: 2rem; text-align: center; color: #78716c;'>🍳 <b>La"
              " fiche recette détaillée s'affichera ici.</b><br>Instructions pas"
              " à pas et techniques traditionnelles.</div>"
          )

        with gr.TabItem("🛒 2. Liste d'Épicerie & Marchés"):
          shopping_box = gr.Markdown(
              "<div style='border: 2px dashed #d97706; border-radius: 8px;"
              " padding: 2rem; text-align: center; color: #78716c;'>🛍️ <b>La"
              " liste des courses et les adresses locales"
              " s'afficheront ici.</b><br>Épiceries recommandées à"
              " Ottawa/Gatineau et Montréal.</div>"
          )

        with gr.TabItem("🔬 3. Diagnostic & Nutrition"):
          analysis_box = gr.Markdown(
              "<div style='border: 2px dashed #10b981; border-radius: 8px;"
              " padding: 2rem; text-align: center; color: #78716c;'>📊 <b>Le"
              " bilan nutritionnel et métabolique s'affichera ici.</b><br>Macros,"
              " calories et conseils de santé.</div>"
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