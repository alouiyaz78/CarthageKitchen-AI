import base64
import os
from pathlib import Path
from typing import List, Union
from crewai.tools import tool
from dotenv import load_dotenv
from fastembed import TextEmbedding
from litellm import completion
import psycopg2

# 1. Chargement de la configuration
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

DATABASE_URL = os.getenv("DATABASE_URL")

# Modèle d'embedding mis en cache local
_embedder = None


def get_embedder() -> TextEmbedding:
  global _embedder
  if _embedder is None:
    _embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
  return _embedder


def encode_image_to_base64(path: str) -> str:
  """Lit un fichier image et le convertit en chaîne Base64."""
  with open(path, "rb") as image_file:
    return base64.b64encode(image_file.read()).decode("utf-8")


# ==============================================================================
# 1. OUTILS D'INSPECTION DU FRIGO & RESTRICTIONS (EXISTANTS)
# ==============================================================================


@tool("extract_ingredients_from_image_and_text")
def extract_ingredients_from_image_and_text(
    image_input: str = "None", manual_input: str = "None"
) -> str:
  """Extrait et fusionne les ingrédients visibles sur une ou plusieurs images avec les ingrédients saisis manuellement au format texte."""
  content = []

  if image_input and image_input not in ["None", "null", ""]:
    raw_paths = [p.strip() for p in image_input.split(",") if p.strip()]
    valid_paths = [p for p in raw_paths if os.path.exists(p)]

    for path in valid_paths:
      try:
        b64_img = encode_image_to_base64(path)
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"},
        })
      except Exception:
        continue

    if valid_paths:
      content.append({
          "type": "text",
          "text": (
              "Identifie avec précision tous les ingrédients comestibles,"
              " légumes, fruits, protéines, condiments, boîtes de conserve et"
              " épices visibles sur ces photographies. Renvoie uniquement la"
              " liste de ces ingrédients séparés par des virgules."
          ),
      })

  if manual_input and manual_input not in ["None", "null", ""]:
    content.append({
        "type": "text",
        "text": (
            "Prends également en compte ces ingrédients saisis manuellement :"
            f" {manual_input}"
        ),
    })

  if not content:
    return "Aucun ingrédient détecté ni renseigné."

  # Modèle actif validé sur votre compte
  vision_model = os.getenv("VISION_MODEL", "claude-haiku-4-5-20251001")
  clean_model = vision_model.replace("anthropic/", "")
  litellm_model = f"anthropic/{clean_model}"

  try:
    response = completion(
        model=litellm_model,
        messages=[{"role": "user", "content": content}],
        api_key=os.getenv("ANTHROPIC_API_KEY"),
    )
    return response.choices[0].message.content
  except Exception as err:
    return f"Erreur lors de la détection visuelle : {str(err)}"


@tool("filter_ingredients_list")
def filter_ingredients_list(raw_ingredients: str) -> List[str]:
  """Nettoie, standardise et dé-duplique une chaîne d'ingrédients bruts pour renvoyer une liste Python propre."""
  if not raw_ingredients or raw_ingredients in ["None", "null"]:
    return []

  cleaned = (
      raw_ingredients.replace("\n", ",")
      .replace("-", ",")
      .replace("*", "")
      .replace(";", ",")
  )
  items = [item.strip().lower() for item in cleaned.split(",") if item.strip()]
  return list(dict.fromkeys(items))


@tool("filter_based_on_dietary_restrictions")
def filter_based_on_dietary_restrictions(
    ingredients: Union[List[str], str], dietary_restrictions: str = "None"
) -> List[str]:
  """Filtre les ingrédients selon les intolérances et régimes spécifiés."""
  if isinstance(ingredients, str):
    ing_list = [i.strip().lower() for i in ingredients.split(",") if i.strip()]
  else:
    ing_list = [str(i).strip().lower() for i in ingredients]

  if (
      not dietary_restrictions
      or dietary_restrictions.lower() in ["none", "standard", ""]
  ):
    return ing_list

  restrictions_lower = dietary_restrictions.lower()
  filtered = []

  gluten_items = [
      "couscous",
      "farine",
      "pain",
      "pâtes",
      "semoule",
      "orzo",
      "frik",
      "malsouka",
      "brik",
  ]
  meat_items = [
      "viande",
      "foie",
      "poulet",
      "boeuf",
      "agneau",
      "merguez",
      "veau",
      "thon",
      "poisson",
      "crevette",
  ]
  animal_items = meat_items + ["oeuf", "oeufs", "lait", "fromage", "beurre"]

  for item in ing_list:
    exclude = False
    if "gluten" in restrictions_lower and any(g in item for g in gluten_items):
      exclude = True
    if "végétarien" in restrictions_lower or "vegetarian" in restrictions_lower:
      if any(m in item for m in meat_items):
        exclude = True
    if "vegan" in restrictions_lower:
      if any(a in item for a in animal_items):
        exclude = True

    if not exclude:
      filtered.append(item)

  return filtered


# ==============================================================================
# 2. NOUVEL OUTIL RAG : RECHERCHE DANS LA BASE PATRIMONIALE NEON
# ==============================================================================


@tool("search_tunisian_recipes_tool")
def search_tunisian_recipes_tool(query: str) -> str:
  """Interroge la base Neon pgvector contenant le livre 'Traditions Culinaires de Tunisie'.

  Renvoie les recettes traditionnelles les plus proches avec ingrédients et
  instructions.
  """
  if not DATABASE_URL:
    return "Erreur : DATABASE_URL manquante."

  embedder = get_embedder()
  query_vec = list(embedder.embed([query]))[0].tolist()

  conn = psycopg2.connect(DATABASE_URL)
  with conn.cursor() as cur:
    cur.execute(
        """
            SELECT dish_name, page_number, ingredients, instructions,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM tunisian_recipes
            WHERE 1 - (embedding <=> %s::vector) >= 0.55
            ORDER BY embedding <=> %s::vector
            LIMIT 2;
        """,
        (query_vec, query_vec, query_vec),
    )
    rows = cur.fetchall()
  conn.close()

  if not rows:
    return (
        "Aucune recette traditionnelle correspondante trouvée dans le livre."
    )

  output = []
  for row in rows:
    output.append(
        f"=== RECETTE : {row[0]} (Page {row[1]}) [Score: {row[4]:.2f}] ===\n"
        f"INGRÉDIENTS D'ORIGINE :\n{row[2]}\n\n"
        f"PRÉPARATION AUTHENTIQUE :\n{row[3]}\n"
    )
  return "\n---\n".join(output)