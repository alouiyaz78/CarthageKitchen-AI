import os
import uuid
import logging
from dotenv import load_dotenv
import gradio as gr

# Crew imports
from src.crew import NourishBotRecipeCrew, NourishBotAnalysisCrew
# Dans app.py, ligne 9 environ
from src.crew import NourishBotRecipeCrew, NourishBotAnalysisCrew

# Forcer le chargement des variables d'environnement
load_dotenv(override=True)

# Product Analytics optionnel via PostHog
POSTHOG_KEY = os.getenv("POSTHOG_KEY")
posthog_client = None
if POSTHOG_KEY:
    try:
        from posthog import Posthog
        posthog_client = Posthog(
            project_api_key=POSTHOG_KEY, 
            host=os.getenv("POSTHOG_HOST", "https://us.i.posthog.com")
        )
    except Exception as e:
        logging.warning(f"Could not initialize PostHog: {e}")

def split_recipe_workflow_output(crew_output):
  """Sépare la sortie de la Crew en deux flux distincts :

  1. Recette culinaire pure (avec ingrédients complets et étapes pour cuisiner).
  2. Guide de courses sous forme de check-list interactive et adresses locales.
  """
  recipe_md = "## 🇹🇳 Fiche Recette — Atelier Culinaire Tunisien\n\n"
  shopping_md = "## 🛒 Liste de Courses & Guide d'Achat\n\n"

  recipes = []
  sourcing_raw = ""

  # Extraction ciblée via les sorties de tâches individuelles
  if hasattr(crew_output, "tasks_output"):
    for task_out in crew_output.tasks_output:
      if task_out.name == "recipe_suggestion_task":
        if hasattr(task_out, "pydantic") and task_out.pydantic:
          pyd = task_out.pydantic
          recipes = getattr(pyd, "recipes", [pyd])
        elif hasattr(task_out, "json_dict") and task_out.json_dict:
          recipes = task_out.json_dict.get("recipes", [task_out.json_dict])
      elif task_out.name == "ingredient_sourcing_task":
        sourcing_raw = str(task_out.raw)

  if not recipes and isinstance(crew_output, dict):
    if "recipes" in crew_output:
      recipes = crew_output["recipes"]
    elif "title" in crew_output:
      recipes = [crew_output]

  # Formatage de l'onglet Recette (Vue Prête à Cuisiner & Imprimer)
  if recipes:
    for idx, recipe in enumerate(recipes, 1):
      if hasattr(recipe, "model_dump"):
        r = recipe.model_dump()
      elif hasattr(recipe, "dict"):
        r = recipe.dict()
      elif isinstance(recipe, dict):
        r = recipe
      else:
        r = {}

      title = r.get("title", f"Recette {idx}")
      desc = r.get("description", "")
      prep = r.get("prep_time", "N/A")
      cook = r.get("cook_time", "N/A")

      recipe_md += f"### {idx}. 🍽️ {title}\n"
      if desc:
        recipe_md += f"*{desc}*\n\n"
      recipe_md += f"⏱️ **Préparation :** {prep} | **Cuisson :** {cook}\n\n"

      # --- INCLURE LES INGRÉDIENTS DANS LA FICHE RECETTE ---
      base_ing = r.get("base_ingredients", [])
      missing_ing = r.get("missing_items_to_grab", [])
      pantry_ing = r.get("pantry_staples", [])

      recipe_md += "#### 🥗 Ingrédients nécessaires\n"
      if base_ing:
        for item in base_ing:
          recipe_md += f"- {item}\n"
      if missing_ing:
        for item in missing_ing:
          recipe_md += f"- {item} *(à prévoir)*\n"
      if pantry_ing:
        recipe_md += (
            f"\n*Fond de placard requis :* {', '.join(pantry_ing)}\n\n"
        )
      else:
        recipe_md += "\n"

      # Instructions de cuisson pas à pas
      recipe_md += "#### 🍳 Étapes de préparation\n"
      instructions = r.get("instructions", [])
      if isinstance(instructions, list):
        for step_num, step in enumerate(instructions, 1):
          recipe_md += f"{step_num}. {step}\n"
      else:
        recipe_md += f"{instructions}\n"
      recipe_md += "\n"

      # Conseil du Chef
      if tips := r.get("chef_tips"):
        recipe_md += f"> 💡 **L'Astuce du Chef :** {tips}\n\n"

      recipe_md += "---\n\n"

      # Check-list interactive pour l'onglet Courses
      shopping_md += f"### 📋 Check-list pour : {title}\n\n"
      if missing_ing:
        shopping_md += (
            "*(Cochez les éléments au fur et à mesure de vos achats)*\n\n"
        )
        for item in missing_ing:
          shopping_md += f"- [ ] **{item}**\n"
        shopping_md += "\n"
      else:
        shopping_md += (
            "✅ *Tous les ingrédients principaux sont déjà dans votre cuisine"
            " !*\n\n"
        )

      if pantry_ing:
        shopping_md += (
            "**Fond de placard requis :** " + ", ".join(pantry_ing) + "\n\n"
        )

    if sourcing_raw:
      shopping_md += "---\n\n" + sourcing_raw
  else:
    fallback_text = getattr(
        crew_output, "raw", "Aucune recette structurée générée."
    )
    recipe_md += fallback_text
    shopping_md += "Aucun élément à acheter répertorié."

  return recipe_md, shopping_md

def format_analysis_output(final_output) -> str:
    """Formatage du diagnostic clinique et métabolique."""
    output = "## 🥗 Analyse Nutritionnelle & Métabolique\n\n"

    if hasattr(final_output, "raw"):
        return f"## 🥗 Rapport Clinique\n\n{final_output.raw}"

    if not isinstance(final_output, dict):
        return str(final_output)

    total_cal = final_output.get("total_calories", final_output.get("estimated_calories", "Calcul en cours"))
    output += f"**Énergie Totale Estimée :** {total_cal} kcal\n\n"

    if items := final_output.get("items"):
        output += "### 🍽 Portions & Aliments Détectés\n"
        output += "| Ingrédient | Portion Estimée | Calories |\n|---|---|---|\n"
        for item in items:
            output += f"| {item.get('food_item', 'Item')} | {item.get('portion_size', 'Standard')} | {item.get('calories', '-')} kcal |\n"
        output += "\n"

    macros = final_output.get("macronutrients", final_output.get("nutrients", {}))
    if macros:
        output += "### ⚖️ Répartition des Macronutriments\n"
        output += "| Nutriments | Quantité |\n|---|---|\n"
        for m in ["protein_g", "carbs_g", "fats_g", "fiber_g", "sodium_mg"]:
            if val := macros.get(m):
                label = m.replace("_g", " (g)").replace("_mg", " (mg)").replace("_", " ").capitalize()
                output += f"| **{label}** | {val} |\n"
        output += "\n"

    if health_eval := final_output.get("health_evaluation"):
        output += f"### 🩺 Évaluation Clinique\n{health_eval}\n\n"

    if disclaimer := final_output.get("disclaimer"):
        output += f"*{disclaimer}*\n"

    return output


def consolidate_dietary_restrictions(selected_list, custom_text) -> str:
    """Agrège cases à cocher et texte libre pour les restrictions."""
    items = list(selected_list) if selected_list else []
    if custom_text and custom_text.strip():
        items.append(custom_text.strip())
    return ", ".join(items) if items else "None"


def run_pipeline(
    image_files, 
    manual_text, 
    dietary_selected, 
    dietary_custom, 
    target_city, 
    workflow_type,
    custom_api_key=None,
    progress=gr.Progress(track_tqdm=True)
):
    """Orchestrateur principal acceptant une liste de photos."""
    session_id = str(uuid.uuid4())
    
    # Gestion multi-photos via gr.File
    has_images = bool(image_files and len(image_files) > 0)
    has_text = bool(manual_text and manual_text.strip())

    if not has_images and not has_text:
        warning_msg = "⚠️ **Action requise :** Veuillez téléverser au moins une photo ou saisir vos ingrédients."
        return warning_msg, "", ""

    if has_images:
        images_arg = ",".join([f.name if hasattr(f, "name") else str(f) for f in image_files])
    else:
        images_arg = "None"

    if custom_api_key and custom_api_key.strip():
        key = custom_api_key.strip()
        if key.startswith("AIza"):
            os.environ["GEMINI_API_KEY"] = key
        elif key.startswith("sk-ant"):
            os.environ["ANTHROPIC_API_KEY"] = key
        elif key.startswith("sk-"):
            os.environ["OPENAI_API_KEY"] = key

    dietary_restrictions = consolidate_dietary_restrictions(dietary_selected, dietary_custom)

    inputs = {
        "uploaded_image": images_arg,
        "manual_ingredients": manual_text if has_text else "None",
        "dietary_restrictions": dietary_restrictions,
        "target_city": target_city
    }

    if posthog_client:
        try:
            posthog_client.capture(
                distinct_id=session_id,
                event="food_analysis_started",
                properties={
                    "workflow": workflow_type,
                    "city": target_city,
                    "image_count": len(image_files) if has_images else 0,
                    "has_text": has_text,
                    "dietary": dietary_restrictions
                }
            )
        except Exception:
            pass

    try:
        if workflow_type == "recipe":
            crew = NourishBotRecipeCrew(
                image_data=images_arg,
                manual_ingredients=manual_text,
                dietary_restrictions=dietary_restrictions,
                target_city=target_city
            ).crew()
            raw_result = crew.kickoff(inputs=inputs)
            
            recipe_md, shopping_md = split_recipe_workflow_output(raw_result)
            analysis_md = "💡 *Basculez sur le mode 'Analyse Nutritionnelle' pour obtenir l'évaluation métabolique de votre repas.*"
            return recipe_md, shopping_md, analysis_md

        else:
            crew = NourishBotAnalysisCrew(
                image_data=images_arg,
                manual_ingredients=manual_text,
                dietary_restrictions=dietary_restrictions
            ).crew()
            raw_result = crew.kickoff(inputs=inputs)
            dict_result = raw_result.to_dict() if hasattr(raw_result, "to_dict") else raw_result
            
            recipe_md = "ℹ️ *Mode Analyse Métabolique actif.*"
            shopping_md = "ℹ️ *Aucune liste de courses requise pour une analyse nutritionnelle.*"
            analysis_md = format_analysis_output(dict_result)
            return recipe_md, shopping_md, analysis_md

    except Exception as err:
        logging.error(f"Execution failed: {err}")
        err_msg = f"❌ **Une erreur est survenue pendant le traitement :**\n\n```text\n{str(err)}\n```"
        return err_msg, "", ""


# ---------------------------------------------------------------------------
# Style CSS et règles d'impression PDF
# ---------------------------------------------------------------------------
css = """
.main-title { font-size: 1.8rem !important; font-weight: 700 !important; text-align: center; color: #d97706; }
.sub-title { text-align: center; font-size: 1rem; margin-bottom: 1.5rem; color: #4b5563; }
.category-header { font-weight: 600; color: #b45309; margin-top: 0.5rem; }

/* Impression PDF propre et complète */
@media print {
    /* Masquer les formulaires d'entrée, boutons, navigation et onglets inutiles */
    button, 
    .tab-nav,
    .tabs > .tab-nav,
    .gradio-container > .main > .row > div:first-child,
    .category-header,
    input,
    textarea {
        display: none !important;
    }

    /* Déployer la zone de contenu recette en pleine page */
    body, html, .gradio-container {
        background: white !important;
        color: black !important;
        margin: 0 !important;
        padding: 0 !important;
        width: 100% !important;
    }

    #printable-recipe-card {
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
        display: block !important;
        visibility: visible !important;
        page-break-inside: auto;
    }

    #printable-recipe-card * {
        visibility: visible !important;
        color: black !important;
    }
}
"""

with gr.Blocks(theme=gr.themes.Citrus(), css=css, title="NourishBot Tunisie") as demo:
    gr.Markdown("# 🇹🇳 NourishBot AI — Atelier Culinaire Tunisien & Coaching Santé", elem_classes="main-title")
    gr.Markdown(
        "Transformez le contenu de votre réfrigérateur en plats tunisiens authentiques, sains et traditionnels, "
        "avec carnet d'adresses d'épiceries locales à **Ottawa** et **Montréal**.",
        elem_classes="sub-title"
    )

    with gr.Row():
        # COLONNE DE GAUCHE : Entrées
        with gr.Column(scale=5, min_width=360):
            with gr.Tabs():
                with gr.TabItem("📸 Photos des Ingrédients"):
                    image_files_input = gr.File(
                        file_count="multiple",
                        file_types=["image"],
                        type="filepath",
                        label="Téléversez 1 ou plusieurs photos (Frigo, Placard, Table...)"
                    )
                with gr.TabItem("✍️ Saisie Texte"):
                    manual_text_input = gr.Textbox(
                        label="Ingrédients disponibles", 
                        placeholder="Ex: 2 tomates, 3 poivrons, 1 aubergine, ail, couscous, concentré de tomate...",
                        lines=3
                    )

            gr.Markdown("#### 🥗 Préférences & Allergies", elem_classes="category-header")
            dietary_checks = gr.CheckboxGroup(
                choices=[
                    "Gluten-Free (Sans gluten)", 
                    "Vegetarian (Végétarien)", 
                    "Vegan", 
                    "Diabetic / Low Glycemic", 
                    "Low Sodium (Hypertension)"
                ],
                label="Profils diététiques",
                value=[]
            )
            dietary_free_text = gr.Textbox(
                label="Exclusions personnalisées", 
                placeholder="Ex: Pas de piquant, allergie coriandre..."
            )

            with gr.Row():
                city_selector = gr.Dropdown(
                    choices=["Ottawa / Gatineau", "Montreal"], 
                    value="Ottawa / Gatineau", 
                    label="🇨🇦 Ville pour le sourcing"
                )
                workflow_selector = gr.Radio(
                    choices=[("Studio Recette", "recipe"), ("Analyse Nutritionnelle", "analysis")],
                    value="recipe", 
                    label="Mode d'exécution"
                )

            with gr.Accordion("⚙️ Clé API Personnalisée (Optionnel)", open=False):
                api_key_input = gr.Textbox(
                    label="Clé API (BYOK)", 
                    type="password", 
                    placeholder="sk-ant-... ou sk-..."
                )

            submit_btn = gr.Button("🚀 Générer la Recette & le Guide", variant="primary", size="lg")

        # COLONNE DE DROITE : Sorties modulaires en 3 onglets
        with gr.Column(scale=7, min_width=520):
            with gr.Tabs():
                with gr.TabItem("🍽️ 1. En Cuisine (Fiche Recette)"):
                    with gr.Row():
                        gr.Markdown("Visualisez vos instructions de cuisson sans distraction.")
                        pdf_btn = gr.Button("🖨️ Imprimer / PDF", size="sm", variant="secondary")
                    
                    recipe_box = gr.Markdown(
                        "<div style='border: 2px dashed #f59e0b; border-radius: 8px; padding: 2rem; text-align: center; color: #78716c;'>"
                        "🍳 <b>Votre fiche recette prête à cuisiner apparaîtra ici.</b></div>",
                        elem_id="printable-recipe-card"
                    )

                with gr.TabItem("🛒 2. Liste de Courses & Marché"):
                    shopping_box = gr.Markdown(
                        "<div style='border: 2px dashed #d97706; border-radius: 8px; padding: 2rem; text-align: center; color: #78716c;'>"
                        "🛍️ <b>La check-list interactive des ingrédients manquants et les adresses locales apparaîtront ici.</b></div>"
                    )

                with gr.TabItem("🔬 3. Diagnostic & Nutrition"):
                    analysis_box = gr.Markdown(
                        "<div style='border: 2px dashed #10b981; border-radius: 8px; padding: 2rem; text-align: center; color: #78716c;'>"
                        "📊 <b>Le rapport nutritionnel et métabolique s'affichera ici.</b></div>"
                    )

    # Action du bouton d'impression PDF
    pdf_btn.click(fn=None, js="() => { window.print(); }")

    # Déclencheur du pipeline
    submit_btn.click(
        fn=run_pipeline,
        inputs=[
            image_files_input, 
            manual_text_input, 
            dietary_checks, 
            dietary_free_text, 
            city_selector, 
            workflow_selector, 
            api_key_input
        ],
        outputs=[recipe_box, shopping_box, analysis_box]
    )

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860
    )