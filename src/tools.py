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


# Spellings of the same Tunisian dish name, as the dialect is written in
# French. Tunisian spellings only: never add a Moroccan or Algerian name, since
# a dish with the same name can be another dish there (tajine).
TUNISIAN_SPELLINGS = (
    ("nouasser", "nwasser", "nwacer", "nouacer"),
    ("kafteji", "keftaji", "kaftaji", "keffteji"),
    ("ojja", "ojjet"),
    ("lablabi", "leblebi"),
    ("mloukhia", "mloukhiya", "mlokhia"),
    ("makrouna", "maqrouna"),
    ("mhamsa", "mhamssa"),
    ("bsissa", "bsisa"),
    ("kammounia", "kamounia"),
    ("masfouf", "mesfouf"),
    ("brik", "brick"),
    ("mechouia", "méchouia", "mechwia"),
)
MAX_NAMES = 4


def with_tunisian_spellings(names: list[str]) -> list[str]:
  """The names followed by their other Tunisian spellings, MAX_NAMES at most."""
  out = list(names)
  for name in names:
    for spellings in TUNISIAN_SPELLINGS:
      for word in spellings:
        pattern = rf"\b{word}\b"
        if re.search(pattern, name, re.I):
          out += [re.sub(pattern, other, name, flags=re.I)
                  for other in spellings if other != word]
          break
  unique = {}
  for name in out:
    unique.setdefault(name.lower(), name)
  return list(unique.values())[:MAX_NAMES]


# A result titled "riz aux calamars farcis" is another dish than "calmars
# farcis": drop results whose title names a base the request does not.
BASE_STARCHES = {
    "riz": ("riz", "rouz"),
    "couscous": ("couscous", "kousksi", "kouski", "kesksi"),
    "boulgour": ("boulgour", "borghol", "burghul", "bulgur"),
    "pâtes": ("pâtes", "pates", "macaroni", "spaghetti"),
    "nwasser": TUNISIAN_SPELLINGS[0],
    "rechta": ("rechta",),
    "frik": ("frik", "chorba", "soupe"),
    "mhamsa": ("mhamsa", "mhamssa"),
}


def starch_groups(text: str) -> set[str]:
  text = text.lower()
  return {
      group for group, words in BASE_STARCHES.items()
      if any(re.search(rf"\b{w}\b", text) for w in words)
  }


def names_other_dish(title: str, names: list[str]) -> bool:
  # "Pâtes nwasser" is still nwasser: a title that also names a requested
  # base is kept.
  in_title, wanted = starch_groups(title), starch_groups(" ".join(names))
  return bool(in_title - wanted) and not in_title & wanted


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


def meta_content(page: str, key: str) -> str:
  match = re.search(
      rf'<meta[^>]+(?:property|name)=["\']{key}["\'][^>]+content=["\']([^"\']+)',
      page,
  )
  return clean_text(match.group(1)) if match else ""


# Words that mark a Tunisian recipe in its title, cuisine or description.
TUNISIAN_MARK = re.compile(r"tunis|tounsi|تونس", re.I)
# A quantity in an ingredient line: "500 g d'agneau", "Nwasser - 500 g".
QUANTITY = re.compile(r"[\d½¼¾]")


def page_text(page: str) -> str:
  """Readable text of a page, one line per list item, paragraph or heading,
  without menus and scripts. Divs do not break lines: sites often split an
  ingredient into quantity, unit and name divs inside one list item."""
  page = re.sub(
      r"<(script|style|noscript|header|footer|nav|aside|form)\b.*?</\1>",
      " ", page, flags=re.S | re.I,
  )
  page = re.sub(r"</?(br|p|li|h\d|tr)\b[^>]*>", "\n", page, flags=re.I)
  text = html.unescape(re.sub(r"<[^>]+>", " ", page))
  lines = (re.sub(r"\s+", " ", line).strip() for line in text.split("\n"))
  return "\n".join(line for line in lines if line)


def normalize_quote(text: str) -> str:
  text = text.lower().replace("\u2019", "'").replace("\u00a0", " ")
  return re.sub(r"\s+", " ", re.sub(r"[^\w'/,.½¼¾ ]", " ", text)).strip()


def ingredient_quoted(line: str, page_lines: list[str]) -> bool:
  """True if the ingredient is copied from a single line of the page, so a
  quantity cannot be moved from one ingredient to the next."""
  line = normalize_quote(line)
  return bool(line) and any(line in page_line for page_line in page_lines)


def step_quoted(line: str, source: str, source_words: set[str]) -> bool:
  """True if the step is copied from the page. It may differ by a word or two
  (the model fixes a typo, drops an emoji), so 90% of its words are enough."""
  line = normalize_quote(line)
  if not line:
    return False
  if line in source:
    return True
  words = [w for w in line.split() if len(w) > 3]
  return len(words) >= 6 and sum(w in source_words for w in words) >= 0.9 * len(words)


EXTRACT_PROMPT = """The text below is a recipe web page. Copy the recipe out of it as JSON:
{{"title": "...", "author": "person named as the author, or empty", "servings": "...",
"ingredients": ["one line per ingredient, with its quantity"], "steps": ["one line per step"]}}
Copy every ingredient line and every step word for word from the text: do not translate,
reword, complete or add anything. Keep the quantity written next to each ingredient.
If the page has no complete recipe, answer {{"ingredients": [], "steps": []}}.

PAGE TEXT:
{text}"""


def extract_recipe_from_text(page: str, llm) -> dict | None:
  """Ingredients and steps copied from the page text by the crew's LLM.

  Only lines found in the page text are kept, and the recipe is dropped if
  the model rewrote more than a quarter of it: nothing it adds can reach the
  card.
  """
  text = page_text(page)
  start = text.lower().find("ingr")
  if start < 0:
    return None
  text = text[max(0, start - 1500):start + 10000]
  try:
    answer = str(llm.call([{"role": "user", "content": EXTRACT_PROMPT.format(text=text)}]))
    data = json.loads(re.search(r"\{.*\}", answer, re.S).group(0))
  except Exception as e:
    logging.warning(f"Recipe extraction failed: {e}")
    return None
  page_lines = [normalize_quote(line) for line in text.split("\n")]
  source = " ".join(page_lines)
  source_words = set(source.split())
  checks = {
      "ingredients": lambda x: ingredient_quoted(x, page_lines),
      "steps": lambda x: step_quoted(x, source, source_words),
  }
  checked = {}
  for key, is_quoted in checks.items():
    lines = [clean_text(x) for x in data.get(key) or [] if clean_text(x)]
    kept = [x for x in lines if is_quoted(x)]
    if not lines or len(kept) < 0.75 * len(lines):
      return None
    checked[key] = kept
  return {
      "title": clean_text(data.get("title")),
      "author": clean_text(data.get("author")),
      "servings": clean_text(data.get("servings")),
      **checked,
  }


def fetch_written_recipe(url: str, llm=None) -> dict | None:
  """Read the recipe of a page, if it has a complete one.

  The schema.org Recipe data is used first. A Tunisian site without it, or
  whose data has no quantities, is read from the page text by the LLM, with
  every line checked against the page. Pages rendered by JavaScript (such as
  Nessma Cuisine) have no recipe in their HTML and are skipped.
  """
  try:
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=8)
    resp.raise_for_status()
  except requests.RequestException:
    return None
  page = resp.text
  site = meta_content(page, "og:site_name") or domain(url)
  page_title = meta_content(page, "og:title")
  # A page about the Moroccan or Algerian dish of the same name is another dish.
  if NEIGHBOR_CUISINE.search(page_title + " " + meta_content(page, "description")):
    return None
  recipe = None
  for block in re.findall(
      r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", page, re.S
  ):
    try:
      # strict=False: some sites leave raw line breaks inside strings.
      data = json.loads(block.strip(), strict=False)
    except ValueError:
      continue
    for node in find_recipe_nodes(data):
      ingredients = [
          clean_text(i) for i in node.get("recipeIngredient") or [] if i
      ]
      steps = recipe_steps(node.get("recipeInstructions"))
      if len(ingredients) < 3 or len(steps) < 2:
        continue
      about = " ".join(
          clean_text(node.get(k)) for k in ("name", "recipeCuisine", "description", "keywords")
      )
      if NEIGHBOR_CUISINE.search(about):
        return None
      author = node.get("author")
      if isinstance(author, list):
        author = author[0] if author else None
      recipe = {
          "title": clean_text(node.get("name")),
          "author": first_name(author),
          "author_is_org": isinstance(author, dict)
          and author.get("@type") == "Organization",
          "servings": first_name(node.get("recipeYield")),
          "ingredients": ingredients,
          "steps": steps,
          "tunisian_mark": bool(TUNISIAN_MARK.search(about + " " + page_title)),
      }
      break
    if recipe:
      break
  quantified = recipe and sum(
      bool(QUANTITY.search(i)) for i in recipe["ingredients"]
  ) >= len(recipe["ingredients"]) / 2
  if not quantified and llm is not None and is_tunisian_site(url):
    text_recipe = extract_recipe_from_text(page, llm)
    if text_recipe and len(text_recipe["ingredients"]) >= 3 and len(text_recipe["steps"]) >= 2:
      recipe = {
          "author": "",
          "author_is_org": False,
          "servings": "",
          "tunisian_mark": True,
          **(recipe or {}),
          **{k: v for k, v in text_recipe.items() if v},
      }
  # The card needs quantities (the nutrition is computed from them): a recipe
  # without them would make the model guess.
  if not recipe or sum(
      bool(QUANTITY.search(i)) for i in recipe["ingredients"]
  ) < len(recipe["ingredients"]) / 2:
    return None
  recipe["title"] = recipe.get("title") or page_title
  recipe["site"] = site
  # Drop the tracking parameter Google adds to result links.
  recipe["url"] = re.sub(r"[?&]srsltid=[^&]*$", "", url)
  return recipe


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
    "cuisineolfa", "madamejerbi", "bennasafi.",
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


def is_tunisian_site(url: str) -> bool:
  site = domain(url)
  return site.endswith(".tn") or matches(site, TUNISIAN_SITES)


def source_rank(recipe: dict) -> int:
  site, author = domain(recipe["url"]), recipe["author"]
  if matches(site, FOOD_BRANDS) or recipe["author_is_org"]:
    return BRAND
  if matches(site, MAGHREB_BLOGS) or matches(author, MAGHREB_BLOGS):
    return PORTAL
  if site.endswith((".dz", ".ma")):
    return PORTAL
  if is_tunisian_site(recipe["url"]) or matches(author, TUNISIAN_CHEFS):
    return TUNISIAN
  if matches(site, FOOD_PORTALS) or not author:
    return PORTAL
  # A named person on a site we do not know, most often a personal blog. It
  # only counts if the recipe says it is Tunisian.
  return AUTHOR if recipe.get("tunisian_mark") else PORTAL


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


MAX_TEXT_READS = 2


def search_written_recipes(names: list[str], llm=None) -> list[dict]:
  """The best complete written Tunisian recipe for the dish, if any.

  Only pages with schema.org Recipe data, or Tunisian sites whose text the
  LLM copies out line by line (see fetch_written_recipe), are kept, so the
  result has a real ingredient list and real steps. Only
  Tunisian chefs and sites or independent authors count as a chef's recipe:
  when the search finds nothing but food portals or brands, the list is
  empty and the model falls back to a Tunisian chef's video.
  """
  def keep(r):
    return (
        r and not NEIGHBOR_CUISINE.search(r["title"])
        and not names_other_dish(r["title"], names)
        and source_rank(r) <= AUTHOR
    )

  def has_tunisian():
    return any(source_rank(r) == TUNISIAN for r in recipes)

  recipes, seen, unread = [], set(), []
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
    urls = urls[:8]
    with ThreadPoolExecutor(max_workers=8) as pool:
      found = list(pool.map(fetch_written_recipe, urls))
    recipes += [r for r in found if keep(r)]
    unread += [u for u, r in zip(urls, found) if r is None and is_tunisian_site(u)]
    if has_tunisian():
      break
  # Tunisian pages without usable Recipe data are read by the LLM only when
  # no Tunisian recipe was found, one page at a time: the free Groq tier
  # allows 8000 tokens a minute.
  if llm is not None and not has_tunisian():
    for url in unread[:MAX_TEXT_READS]:
      r = fetch_written_recipe(url, llm)
      if keep(r):
        recipes.append(r)
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
    # Enough candidates to find a Tunisian chef among them after ranking.
    if len(videos) >= 8:
      break
  with ThreadPoolExecutor(max_workers=8) as pool:
    channels = list(pool.map(youtube_channel, [v["url"] for v in videos[:8]]))
  # Videos that oEmbed cannot resolve are private or removed: skip them.
  resolved = [{**v, "channel": c} for v, c in zip(videos, channels) if c]
  resolved.sort(key=video_rank)
  return resolved[:3]


def video_rank(video: dict) -> int:
  """Preferred chefs first, then other Tunisian chefs and Tunisian channels."""
  channel = video["channel"]
  if matches(channel, PREFERRED_CHANNELS):
    return 0
  if matches(channel, TUNISIAN_CHEFS) or TUNISIAN_MARK.search(channel):
    return 1
  return 2


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
  # The crew's LLM, to read Tunisian recipe pages that have no Recipe data.
  _llm = PrivateAttr(default=None)
  # What the search found, so the app writes the source line from real data.
  _found = PrivateAttr(default=None)

  def __init__(self, llm=None, **kwargs):
    super().__init__(**kwargs)
    self._llm = llm

  @property
  def found(self) -> dict | None:
    """{"recipe": dict or None, "videos": [...]}, or None before any search."""
    return self._found

  def _run(self, dish_names: str) -> str:
    if not os.getenv("SERPER_API_KEY"):
      return "Error: SERPER_API_KEY is missing."
    names = with_tunisian_spellings(split_dish_names(dish_names))
    with ThreadPoolExecutor(max_workers=2) as pool:
      recipes = pool.submit(search_written_recipes, names, self._llm)
      videos = pool.submit(search_videos, names)
      recipes, videos = recipes.result(), videos.result()
    self._found = {"recipe": recipes[0] if recipes else None, "videos": videos}
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