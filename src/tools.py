import base64
import html
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
from pathlib import Path
import re
from typing import List, Union
from urllib.parse import urlparse
from crewai.tools import BaseTool, tool
from dotenv import load_dotenv
from fastembed import TextEmbedding
from litellm import completion
import psycopg2
from pydantic import BaseModel, Field, PrivateAttr
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


def extract_ingredients(
    image_input: str, manual_input: str, model: str, api_key: str | None
) -> str:
  """Extract the ingredients visible in one or more images and merge them with
  the ingredients typed by the user. Without an api_key, LiteLLM reads the
  service key of the model's provider from the environment."""
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

  try:
    response = completion(
        model=model,
        messages=[{"role": "user", "content": content}],
        api_key=api_key,
    )
    return response.choices[0].message.content
  except Exception as err:
    message = str(err).replace(api_key, "***") if api_key else str(err)
    return f"Erreur lors de la détection visuelle : {message}"


class VisionInput(BaseModel):
  image_input: str = Field("None", description="Comma-separated image paths.")
  manual_input: str = Field("None", description="Ingredients typed by the user.")


class IngredientVisionTool(BaseTool):
  """One instance per crew, so a user's own key never leaves their request."""

  name: str = "extract_ingredients_from_image_and_text"
  description: str = (
      "Extract the ingredients visible in one or more images and merge them"
      " with the ingredients typed by the user."
  )
  args_schema: type[BaseModel] = VisionInput
  model: str
  # Private, so the key stays out of the tool's repr and any logged schema.
  _api_key: str | None = PrivateAttr(default=None)

  def __init__(self, model: str, api_key: str | None = None, **kwargs):
    super().__init__(model=model, **kwargs)
    self._api_key = api_key

  def _run(self, image_input: str = "None", manual_input: str = "None") -> str:
    return extract_ingredients(image_input, manual_input, self.model, self._api_key)


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


SERPER_URL = "https://google.serper.dev/search"
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
# Pages about the Moroccan or Algerian version of a dish.
NEIGHBOR_CUISINE = re.compile(r"maroc|morocc|alg[ée]r", re.I)
# Tunisian chefs whose videos are listed first.
PREFERRED_CHANNELS = ("teyssir", "hendati")


# A result titled "riz aux calamars farcis" is another dish than "calmars
# farcis": drop results whose title names a base the request does not.
BASE_STARCHES = {
    "riz": ("riz", "rouz"),
    "couscous": ("couscous", "kousksi", "kouski", "kesksi"),
    "boulgour": ("boulgour", "borghol", "burghul", "bulgur"),
    "pâtes": ("pâtes", "pates", "macaroni", "spaghetti", "nwasser", "rechta"),
    "frik": ("frik", "chorba", "soupe"),
    "mhamsa": ("mhamsa", "mhamssa"),
}


def names_other_dish(title: str, names: list[str]) -> bool:
  title, wanted = title.lower(), " ".join(names).lower()
  for words in BASE_STARCHES.values():
    in_title = any(re.search(rf"\b{w}\b", title) for w in words)
    if in_title and not any(re.search(rf"\b{w}\b", wanted) for w in words):
      return True
  return False


def split_dish_names(dish_names: str) -> list[str]:
  names = [n.strip().strip('"') for n in dish_names.split(",")]
  return [n for n in dict.fromkeys(names) if n][:3]


def serper_search(query: str) -> list[dict]:
  """Return Serper's organic results, or an empty list if the search fails."""
  api_key = os.getenv("SERPER_API_KEY")
  if not api_key:
    return []
  try:
    resp = requests.post(
        SERPER_URL,
        headers={"X-API-KEY": api_key},
        json={"q": query, "num": 10, "gl": "fr", "hl": "fr"},
        timeout=10,
    )
    resp.raise_for_status()
  except requests.RequestException as e:
    logging.error(f"Serper search failed for {query!r}: {e}")
    return []
  return resp.json().get("organic", [])


YOUTUBE_VIDEO_URL = re.compile(
    r"^https?://(www\.|m\.)?(youtube\.com/(watch|shorts/)|youtu\.be/)"
)
SOCIAL_URL = re.compile(
    r"youtube\.com|youtu\.be|facebook\.com|instagram\.com|tiktok\.com"
    r"|pinterest\.|twitter\.com|x\.com/"
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


class DishNamesInput(BaseModel):
  dish_names: str = Field(
      description=(
          "Comma-separated names of the dish as people write them today: the"
          " plain French name first, then common Tunisian spellings. Example:"
          " 'calmars farcis, kalamar mahchi'."
      )
  )


def clean_text(value) -> str:
  text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
  return re.sub(r"\s+", " ", text).strip()


def find_recipe_nodes(node):
  """Yield the schema.org Recipe objects found in a JSON-LD document."""
  if isinstance(node, list):
    for item in node:
      yield from find_recipe_nodes(item)
  elif isinstance(node, dict):
    types = node.get("@type")
    if "Recipe" in (types if isinstance(types, list) else [types]):
      yield node
    for key in ("@graph", "mainEntity"):
      if key in node:
        yield from find_recipe_nodes(node[key])


def recipe_steps(instructions) -> list[str]:
  """Flatten recipeInstructions: plain text, HowToStep or HowToSection."""
  if isinstance(instructions, str):
    return [s for s in (clean_text(x) for x in instructions.split("\n")) if s]
  steps = []
  for item in instructions or []:
    if isinstance(item, str):
      steps.append(clean_text(item))
    elif isinstance(item, dict):
      if "itemListElement" in item:
        steps.extend(recipe_steps(item["itemListElement"]))
      else:
        steps.append(clean_text(item.get("text") or item.get("name")))
  return [s for s in steps if s]


def first_name(value) -> str:
  if isinstance(value, list):
    value = value[0] if value else None
  if isinstance(value, dict):
    value = value.get("name")
  return clean_text(value)


def fetch_written_recipe(url: str) -> dict | None:
  """Read the schema.org Recipe of a page, if it has a complete one.

  Pages rendered by JavaScript (such as Nessma Cuisine) have no Recipe data in
  their HTML and are skipped.
  """
  try:
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=8)
    resp.raise_for_status()
  except requests.RequestException:
    return None
  page = resp.text
  site = re.search(
      r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)',
      page,
  )
  for block in re.findall(
      r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", page, re.S
  ):
    try:
      data = json.loads(block.strip())
    except ValueError:
      continue
    for node in find_recipe_nodes(data):
      ingredients = [
          clean_text(i) for i in node.get("recipeIngredient") or [] if i
      ]
      steps = recipe_steps(node.get("recipeInstructions"))
      if len(ingredients) >= 3 and len(steps) >= 2:
        author = node.get("author")
        if isinstance(author, list):
          author = author[0] if author else None
        return {
            "title": clean_text(node.get("name")),
            "author": first_name(author),
            "author_is_org": isinstance(author, dict)
            and author.get("@type") == "Organization",
            "site": clean_text(site.group(1)) if site else domain(url),
            "servings": first_name(node.get("recipeYield")),
            "ingredients": ingredients,
            "steps": steps,
            # Drop the tracking parameter Google adds to result links.
            "url": re.sub(r"[?&]srsltid=[^&]*$", "", url),
        }
  return None


def domain(url: str) -> str:
  return urlparse(url).netloc.lower().removeprefix("www.")


def matches(value: str, keys: tuple[str, ...]) -> bool:
  # Spaces and hyphens are ignored so "amour-de-cuisine.com" or an author
  # named "Amour de Cuisine" match "amourdecuisine.".
  value = re.sub(r"[\s-]", "", value.lower())
  return any(k in value for k in keys)


# Source ranking for written recipes. Sites are matched against the domain.
# Chef names are matched against the author, and only full or distinctive
# names: a first name such as "Samar" or "Olfa" alone is too common.
TUNISIAN_SITES = (
    "teyssir", "ksouri", "hendati", "mesinspirationsculinaires",
    "cuisineolfa", "madamejerbi",
)
TUNISIAN_CHEFS = (
    "teyssir", "ksouri", "hendati", "wafikbelhadj", "rafiktlatli",
    "cuisineolfa", "madamejerbi",
)
FOOD_PORTALS = (
    "marmiton.", "cuisineaz.", "750g.", "journaldesfemmes.", "cuisineactuelle.",
    "femmeactuelle.", "ricardocuisine.", "lesfoodies.", "nessma.tv", "elle.fr",
    "lefigaro.fr", "ptitchef.", "supertoinette.", "cuisinelibre.",
    "allrecipes.", "chefsimon.", "mangerbouger.",
)
# General Maghrebi food blogs that are not Tunisian: never ranked as a
# Tunisian author.
MAGHREB_BLOGS = (
    "amourdecuisine", "soulef", "lesdelicesdumaghreb", "cuisinealgerienne",
    "cuisinemarocaine", "choumicha.", "samiratv.", "oumwalid",
)
FOOD_BRANDS = (
    "lepidor.", "francoislambert.", "socopa.", "isladelice.", "panzani.",
    "barilla.", "tipiak.", "ferrero.", "maggi.", "knorr.", "ducros.", "herta.",
    "charal.", "carrefour.", "lidl.", "auchan.", "leclerc", "intermarche.",
    "monoprix.", "picard.", "hellofresh.", "quitoque.", "sicam.", "diari.",
    "warda.", "randa.", "cosumar.", "tabarka.",
)
TUNISIAN, AUTHOR, PORTAL, BRAND = 1, 2, 3, 4
# Portals and brands are ranked only to be filtered out.
SOURCE_LABELS = {
    TUNISIAN: "Tunisian chef or Tunisian site",
    AUTHOR: "independent food author",
}


def source_rank(recipe: dict) -> int:
  site, author = domain(recipe["url"]), recipe["author"]
  if matches(site, FOOD_BRANDS) or recipe["author_is_org"]:
    return BRAND
  if matches(site, MAGHREB_BLOGS) or matches(author, MAGHREB_BLOGS):
    return PORTAL
  if site.endswith((".dz", ".ma")):
    return PORTAL
  if matches(site, TUNISIAN_SITES) or matches(author, TUNISIAN_CHEFS):
    return TUNISIAN
  if site.endswith(".tn"):
    return TUNISIAN
  if matches(site, FOOD_PORTALS) or not author:
    return PORTAL
  # A named person on a site we do not know: most often a personal blog.
  return AUTHOR


def source_credit(recipe: dict) -> str:
  """Name to show in the CHEF line: the person, or the site without one."""
  author = recipe["author"]
  return author[0].upper() + author[1:] if author else recipe["site"]


MAX_STEPS = 10


def condense_steps(steps: list[str]) -> list[str]:
  """Merge neighbouring steps so there are at most MAX_STEPS.

  Steps are merged rather than cut, so the end of the method (baking,
  resting, serving) is never lost.
  """
  if len(steps) <= MAX_STEPS:
    return steps
  bounds = [i * len(steps) // MAX_STEPS for i in range(MAX_STEPS + 1)]
  return [" ".join(steps[a:b]) for a, b in zip(bounds, bounds[1:])]


def format_written_recipe(recipe: dict) -> str:
  rank = source_rank(recipe)
  return (
      f"- Title: {recipe['title']}\n"
      f"  Source type: {SOURCE_LABELS[rank]}\n"
      f"  Credit: {source_credit(recipe)}\n"
      f"  Site: {recipe['site']}\n"
      f"  URL: {recipe['url']}\n"
      f"  Servings: {recipe['servings'] or 'not given'}\n"
      "  Ingredients:\n"
      + "".join(f"    * {i}\n" for i in recipe["ingredients"])
      + "  Steps:\n"
      + "".join(f"    {n}. {s}\n" for n, s in enumerate(condense_steps(recipe["steps"]), 1))
  )


def search_written_recipes(names: list[str]) -> list[dict]:
  """The best complete written Tunisian recipe for the dish, if any.

  Only pages that publish schema.org Recipe data are kept, so the result has
  a real ingredient list and real steps, not a guess from page text. Only
  Tunisian chefs and sites or independent authors count as a chef's recipe:
  when the search finds nothing but food portals or brands, the list is
  empty and the model falls back to a Tunisian chef's video.
  """
  recipes, seen = [], set()
  for name in names:
    urls = []
    for r in serper_search(f"{name} recette tunisienne"):
      url, title = r.get("link", ""), r.get("title", "")
      if url in seen or SOCIAL_URL.search(url):
        continue
      if NEIGHBOR_CUISINE.search(url) or NEIGHBOR_CUISINE.search(title):
        continue
      seen.add(url)
      urls.append(url)
    with ThreadPoolExecutor(max_workers=8) as pool:
      found = pool.map(fetch_written_recipe, urls[:8])
    recipes += [
        r for r in found
        if r and not NEIGHBOR_CUISINE.search(r["title"])
        and not names_other_dish(r["title"], names)
        and source_rank(r) <= AUTHOR
    ]
    if any(source_rank(r) == TUNISIAN for r in recipes):
      break
  # Python's sort is stable, so search order is kept among equals.
  recipes.sort(key=source_rank)
  return recipes[:1]


def search_videos(names: list[str]) -> list[dict]:
  """YouTube videos of the dish with their real channel, preferred chefs first.

  Runs one simple query per name (Google returns nothing for long boolean
  queries). Serper snippets for YouTube pages mix in names from the
  recommended videos sidebar, so the channel is looked up with oEmbed.
  """
  videos, seen = [], set()
  for name in names:
    suffix = "" if "tunis" in name.lower() else " tunisien"
    for r in serper_search(f"site:youtube.com {name}{suffix}"):
      url, title = r.get("link", ""), r.get("title", "")
      if not YOUTUBE_VIDEO_URL.match(url) or url in seen:
        continue
      if NEIGHBOR_CUISINE.search(title) or names_other_dish(title, names):
        continue
      seen.add(url)
      videos.append({"url": url, "title": title})
    if len(videos) >= 3:
      break
  with ThreadPoolExecutor(max_workers=6) as pool:
    channels = list(pool.map(youtube_channel, [v["url"] for v in videos]))
  # Videos that oEmbed cannot resolve are private or removed: skip them.
  resolved = [{**v, "channel": c} for v, c in zip(videos, channels) if c]
  resolved.sort(
      key=lambda v: not any(p in v["channel"].lower() for p in PREFERRED_CHANNELS)
  )
  return resolved[:3]


class ChefSearchTool(BaseTool):
  """Written chef recipes and YouTube videos for a Tunisian dish, in one call.

  Both searches always run, in parallel, so the video fallback does not depend
  on the model making a second tool call.
  """

  name: str = "find_tunisian_chef_versions"
  description: str = (
      "Search the web for modern Tunisian chef versions of a dish. Returns at"
      " most 1 complete written recipe by a Tunisian chef or an independent"
      " author (author, site, URL, servings,"
      " ingredients, steps) and up to 3 YouTube videos (title, channel, URL)."
  )
  args_schema: type[BaseModel] = DishNamesInput

  def _run(self, dish_names: str) -> str:
    if not os.getenv("SERPER_API_KEY"):
      return "Error: SERPER_API_KEY is missing."
    names = split_dish_names(dish_names)
    with ThreadPoolExecutor(max_workers=2) as pool:
      recipes = pool.submit(search_written_recipes, names)
      videos = pool.submit(search_videos, names)
      recipes, videos = recipes.result(), videos.result()
    parts = ["WRITTEN RECIPES:"]
    parts += [format_written_recipe(r) for r in recipes] or ["none found."]
    parts.append("\nVIDEOS:")
    parts += [
        f"- Title: {v['title']}\n  Channel: {v['channel']}\n  URL: {v['url']}"
        for v in videos
    ] or ["none found."]
    return "\n".join(parts)


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