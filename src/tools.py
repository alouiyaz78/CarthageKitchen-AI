import base64
from concurrent.futures import ThreadPoolExecutor
import logging
import os
from pathlib import Path
import re
from typing import List, Union
from crewai.tools import BaseTool, tool
from dotenv import load_dotenv
from fastembed import TextEmbedding
from litellm import completion
import psycopg2
from pydantic import BaseModel, Field
import requests

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

DATABASE_URL = os.getenv("DATABASE_URL")

# Loaded lazily: the first call downloads the model.
_embedder = None


def get_embedder() -> TextEmbedding:
  global _embedder
  if _embedder is None:
    _embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
  return _embedder


def encode_image_to_base64(path: str) -> str:
  """Read an image file and return it as a base64 string."""
  with open(path, "rb") as image_file:
    return base64.b64encode(image_file.read()).decode("utf-8")


@tool("extract_ingredients_from_image_and_text")
def extract_ingredients_from_image_and_text(
    image_input: str = "None", manual_input: str = "None"
) -> str:
  """Extract the ingredients visible in one or more images and merge them with
  the ingredients typed by the user."""
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
  """Normalize a raw ingredient string into a de-duplicated list."""
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
  """Remove ingredients that conflict with the given dietary restrictions."""
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


@tool("search_tunisian_recipes_tool")
def search_tunisian_recipes_tool(query: str) -> str:
  """Search the pgvector recipe store built from the Tunisian cookbooks.

  Returns the closest traditional recipes with their ingredients and
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

  return "\n---\n".join(
      format_recipe(row[0], row[1], row[2], row[3], score=row[4])
      for row in rows
  )


YOUTUBE_VIDEO_URL = re.compile(
    r"^https?://(www\.|m\.)?(youtube\.com/(watch|shorts/)|youtu\.be/)"
)


def youtube_channel(url: str) -> str | None:
  """Return the channel that published a video, or None if it is unavailable."""
  try:
    resp = requests.get(
        "https://www.youtube.com/oembed",
        params={"url": url, "format": "json"},
        timeout=4,
    )
    if resp.ok:
      return resp.json().get("author_name")
  except requests.RequestException:
    pass
  return None


class ChefVideoSearchInput(BaseModel):
  query: str = Field(description="Google search query for YouTube videos.")


class ChefVideoSearchTool(BaseTool):
  """Serper search limited to YouTube videos, with the real channel name.

  Serper snippets for YouTube pages mix in names from the recommended videos
  sidebar, so the channel is looked up with YouTube oEmbed instead.
  """

  name: str = "search_tunisian_chef_videos"
  description: str = (
      "Search YouTube videos of Tunisian chefs. For each video, returns its"
      " title, the channel that published it, its URL and a search snippet."
  )
  args_schema: type[BaseModel] = ChefVideoSearchInput

  def _run(self, query: str) -> str:
    # Keep Moroccan and Algerian versions of the same dish out of the results.
    if "tunis" not in query.lower():
      query = f"{query} tunisien"
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
      return "Error: SERPER_API_KEY is missing."
    try:
      resp = requests.post(
          "https://google.serper.dev/search",
          headers={"X-API-KEY": api_key},
          json={"q": query, "num": 5},
          timeout=10,
      )
      resp.raise_for_status()
    except requests.RequestException as e:
      logging.error(f"Serper search failed: {e}")
      return f"Error: web search failed ({e})."

    videos = [
        r
        for r in resp.json().get("organic", [])
        if YOUTUBE_VIDEO_URL.match(r.get("link", ""))
    ]
    with ThreadPoolExecutor(max_workers=5) as pool:
      channels = list(pool.map(youtube_channel, [v["link"] for v in videos]))

    # Videos that oEmbed cannot resolve are private or removed: skip them.
    lines = [
        f"- Title: {v.get('title', '')}\n"
        f"  Channel: {channel}\n"
        f"  URL: {v['link']}\n"
        f"  Snippet: {v.get('snippet', '')}"
        for v, channel in zip(videos, channels)
        if channel
    ]
    if not lines:
      return "No YouTube video found for this query."
    return (
        "The Channel line is the real publisher of each video. Names inside"
        " snippets often belong to other recommended videos.\n"
        + "\n".join(lines)
    )


def format_recipe(dish_name, page, ingredients, instructions, score=None) -> str:
  score_tag = f" [Score: {score:.2f}]" if score is not None else ""
  return (
      f"=== RECETTE : {dish_name} (Page {page}){score_tag} ===\n"
      f"INGRÉDIENTS D'ORIGINE :\n{ingredients}\n\n"
      f"PRÉPARATION AUTHENTIQUE :\n{instructions}\n"
  )


def get_recipe_by_name(dish_name: str) -> str | None:
  """Fetch the stored recipe whose dish_name matches exactly.

  Used when the user picks a dish from the dropdown, so the chef works from
  that exact recipe instead of whatever the semantic search returns.
  Returns None if the dish is not found or the database is unreachable.
  """
  if not DATABASE_URL or not dish_name:
    return None
  try:
    conn = psycopg2.connect(DATABASE_URL)
    try:
      with conn.cursor() as cur:
        cur.execute(
            "SELECT dish_name, page_number, ingredients, instructions"
            " FROM tunisian_recipes WHERE dish_name = %s LIMIT 1;",
            (dish_name,),
        )
        row = cur.fetchone()
    finally:
      conn.close()
  except psycopg2.Error as err:
    logging.error(f"Recipe lookup failed for {dish_name!r}: {err}")
    return None
  return format_recipe(*row) if row else None