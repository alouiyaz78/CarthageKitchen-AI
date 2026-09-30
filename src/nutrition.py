"""Deterministic nutrition estimate for a recipe card, with no LLM call.

Quantities are read from the ingredient bullets of the card, matched against
a small reference table and summed in Python. Values are per 100 g of raw
(or dry) ingredient, rounded from Ciqual (ANSES) and USDA FoodData Central.
Visible text comes from the `t` labels dict built in app.py (UI_TEXT).
"""

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Food:
  name: str
  pattern: str  # regex on the normalized (lowercase, unaccented) line
  kcal: float
  protein: float
  fat: float
  carbs: float
  fiber: float
  sodium: float  # mg
  piece: float = 0  # grams for one unit, as in "3 oignons"; 0 if unknown
  density: float = 1.0  # grams per ml, for volume units


# Order matters: the first matching entry wins, so specific names come
# before generic ones (tomato paste before tomato, olive oil before olive).
FOODS = [
    # Fats
    Food("olive_oil", r"huile d'olive|olive oil", 884, 0, 100, 0, 0, 2, density=0.92),
    Food("oil", r"huile|\boil\b", 884, 0, 100, 0, 0, 0, density=0.92),
    Food("smen", r"smen|samna|ghee", 880, 0, 99, 0, 0, 2, density=0.9),
    Food("butter", r"beurre|butter", 717, 0.9, 81, 0.1, 0, 11, density=0.95),
    # Salty condiments and stock
    Food("stock_cube", r"cubes? de bouillon|bouillon cubes?|stock cubes?|\bmaggi\b|\bknorr\b",
         250, 10, 15, 20, 0, 20000, piece=10),
    Food("water", r"\beau\b|\bwater\b|bouillon|\bstock\b|\bbroth\b", 0, 0, 0, 0, 0, 0),
    Food("tomato_paste", r"concentre|tomato paste|tomato concentrate|double concentr",
         82, 4.3, 0.5, 19, 4.1, 60, density=1.1),
    Food("harissa", r"harissa|hrissa", 70, 3, 3, 10, 6, 1900, density=1.1),
    Food("preserved_lemon", r"citrons? confits?|preserved lemons?", 30, 0.8, 0.5, 5, 3, 3000, piece=60),
    Food("capers", r"capres|capers", 23, 2.4, 0.9, 4.9, 3.2, 2350, density=0.6),
    Food("olives", r"\bolives?\b", 145, 1, 15, 3.8, 3.3, 1560, piece=4, density=0.6),
    Food("salt", r"\bsel\b|\bsalt\b", 0, 0, 0, 0, 0, 38760, density=1.2),
    # Meat, fish and eggs
    Food("minced_meat", r"viande hachee|hachis|ground (?:beef|lamb|meat)|minced (?:beef|lamb|meat)",
         250, 17, 20, 0, 0, 70),
    Food("merguez", r"merguez", 300, 15, 26, 1, 0, 900, piece=50),
    Food("lamb", r"agneau|mouton|\blamb\b|mutton", 250, 17, 20, 0, 0, 65),
    Food("veal", r"\bveau\b|\bveal\b", 150, 20, 7, 0, 0, 85),
    Food("beef", r"boeuf|\bbeef\b", 200, 19, 14, 0, 0, 60),
    Food("liver", r"\bfoie\b|\bliver\b", 135, 20, 3.6, 4, 0, 70),
    Food("chicken", r"poulet|volaille|chicken", 190, 19, 12, 0, 0, 70, piece=1200),
    Food("meat", r"viande|\bmeat\b", 230, 18, 17, 0, 0, 65),
    Food("anchovies", r"anchois|anchov", 210, 29, 10, 0, 0, 3670),
    Food("tuna", r"\bthon\b|\btuna\b", 190, 27, 9, 0, 0, 350),
    Food("sardines", r"sardines?", 140, 20, 7, 0, 0, 100, piece=50),
    Food("squid", r"calmars?|calamars?|encornets?|kalamar|squid", 92, 15.6, 1.4, 3.1, 0, 45, piece=150),
    Food("octopus", r"poulpe|\bourita\b|octopus", 82, 15, 1, 2.2, 0, 230),
    Food("cuttlefish", r"seiches?|cuttlefish", 79, 16, 0.7, 0.8, 0, 370),
    Food("shrimp", r"crevettes?|shrimps?|prawns?", 85, 20, 0.5, 0, 0, 120),
    Food("fish", r"poissons?|merou|\bloup\b|daurade|dorade|pageot|rouget|mulet|\bbar\b|\bfish\b|sea ?bream|\bcod\b|grouper",
         100, 19, 2.5, 0, 0, 70),
    Food("egg", r"oeufs?|\beggs?\b", 143, 12.6, 9.5, 0.7, 0, 140, piece=55),
    # Dairy
    Food("cheese", r"fromage|gruyere|emmental|parmesan|mozzarella|ricotta|cheese", 380, 27, 29, 1, 0, 600),
    Food("yogurt", r"\blben\b|\bleben\b|\brayeb\b|\braib\b|yaourt|yogourt|yogh?urt", 61, 3.5, 3.3, 4.7, 0, 46),
    Food("milk", r"\blait\b|\bmilk\b", 46, 3.3, 1.6, 4.8, 0, 43),
    Food("cream", r"\bcreme\b|\bcream\b", 300, 2, 30, 3, 0, 30),
    # Starches (dry weight)
    Food("brick", r"malsouka|brick|brik|feuilles? de dioul|warka", 300, 8, 5, 57, 2, 500, piece=12),
    Food("bread", r"\bpain\b|\bbread\b|baguette|tabouna|mlaoui", 265, 9, 3.2, 49, 2.7, 490),
    Food("semolina", r"semoule|couscous|semolina|mhamsa|boulgour|borghol|bulgur", 360, 12.5, 1.5, 73, 4, 10, density=0.7),
    Food("rice", r"\briz\b|\brice\b", 360, 6.6, 0.6, 80, 1.3, 5, density=0.85),
    Food("pasta", r"pates|vermicelles?|langues? d'oiseau|nouasser|nwasser|nwacer|nouacer|hlalem|pasta|noodles|spaghetti|orzo",
         360, 12.5, 1.5, 72, 3, 6, density=0.6),
    Food("flour", r"farine|\bflour\b", 364, 10, 1, 76, 2.7, 2, density=0.55),
    Food("potato", r"pommes? de terre|potato(?:es)?", 77, 2, 0.1, 17.5, 2.2, 6, piece=150),
    # Legumes: canned or cooked first, then dry
    Food("chickpeas_cooked", r"pois chiches? (?:cuits?|en conserve|en boite)|(?:cooked|canned) chickpeas",
         139, 7, 2.6, 22.5, 7.6, 240),
    Food("chickpeas", r"pois chiches?|chickpeas?|garbanzo", 364, 19, 6, 61, 17, 24, density=0.8),
    Food("lentils", r"lentilles?|lentils?", 352, 24.6, 1.1, 63, 10.7, 6, density=0.8),
    Food("fava_dry", r"feves? (?:seches|concassees)|dried (?:fava|broad) beans", 341, 26, 1.5, 58, 25, 13, density=0.8),
    Food("fava", r"\bfeves?\b|fava beans?|broad beans?", 72, 5.6, 0.6, 11.7, 4.2, 50),
    Food("white_beans", r"haricots? blancs?|white beans?|cannellini", 333, 23, 0.9, 60, 15, 16, density=0.8),
    Food("peas", r"petits? pois|\bpeas\b", 81, 5.4, 0.4, 14.5, 5.1, 5),
    # Vegetables
    Food("canned_tomato", r"tomates? (?:pelees|concassees|en conserve)|(?:canned|crushed|peeled) tomato",
         20, 1, 0.2, 4, 1, 130),
    Food("tomato", r"tomates?|tomato(?:es)?", 18, 0.9, 0.2, 3.9, 1.2, 5, piece=120),
    Food("bell_pepper", r"poivrons?|bell peppers?|sweet peppers?|(?:green|red) peppers?", 26, 1, 0.3, 6, 2, 4, piece=150),
    Food("spices", r"cumin|carvi|caraway|paprika|piment doux|tabel|tabil|curcuma|turmeric|cannelle|cinnamon"
         r"|ras el hanout|coriandre moulue|graines de coriandre|ground coriander|coriander seeds|\bpoivre\b"
         r"|\bpepper\b|piment (?:rouge )?(?:seche|moulu|en poudre)|cayenne|chili powder|safran|saffron"
         r"|gingembre|ginger|girofle|laurier|bay leaf|thym|thyme|romarin|rosemary|origan|oregano"
         r"|menthe sechee|dried mint|epices?|spices?", 330, 13, 12, 50, 30, 80, density=0.5),
    Food("chili", r"piments?|chil(?:i|li)e?s?|hot peppers?", 40, 2, 0.4, 9, 1.5, 9, piece=15),
    Food("onion", r"oignons?|onions?|echalotes?|shallots?", 40, 1.1, 0.1, 9.3, 1.7, 4, piece=110),
    Food("garlic", r"\bail\b|garlic", 149, 6.4, 0.5, 33, 2.1, 17, piece=40),
    Food("carrot", r"carottes?|carrots?", 41, 0.9, 0.2, 9.6, 2.8, 69, piece=80),
    Food("zucchini", r"courgettes?|zucchini", 17, 1.2, 0.3, 3.1, 1, 8, piece=200),
    Food("eggplant", r"aubergines?|eggplants?", 25, 1, 0.2, 5.9, 3, 2, piece=250),
    Food("turnip", r"navets?|turnips?", 28, 0.9, 0.1, 6.4, 1.8, 67, piece=120),
    Food("pumpkin", r"citrouille|potiron|courge|pumpkin|squash", 26, 1, 0.1, 6.5, 0.5, 1),
    Food("cauliflower", r"chou-?fleur|cauliflower", 25, 1.9, 0.3, 5, 2, 30, piece=600),
    Food("cabbage", r"\bchoux?\b|cabbage", 25, 1.3, 0.1, 5.8, 2.5, 18, piece=900),
    Food("okra", r"gombos?|okra|gnaouia", 33, 1.9, 0.2, 7.5, 3.2, 7),
    Food("celery", r"celeri|celery", 16, 0.7, 0.2, 3, 1.6, 80),
    Food("fennel", r"fenouil|fennel", 31, 1.2, 0.2, 7.3, 3.1, 52, piece=250),
    Food("spinach", r"epinards?|spinach", 23, 2.9, 0.4, 3.6, 2.2, 79),
    Food("chard", r"blettes?|bettes?|\bchard\b", 19, 1.8, 0.2, 3.7, 1.6, 213),
    Food("lemon_juice", r"jus de citron|lemon juice", 22, 0.4, 0.2, 6.9, 0.3, 1),
    Food("lemon", r"citrons?|lemons?", 29, 1.1, 0.3, 9.3, 2.8, 2, piece=100),
    Food("herbs", r"persil|parsley|coriandre|cilantro|coriander|menthe|\bmint\b|aneth|dill|basilic|basil",
         35, 3, 0.7, 6, 3.5, 50),
    # Sweet
    Food("sugar", r"sucre|sugar", 400, 0, 0, 100, 0, 1, density=0.85),
    Food("honey", r"\bmiel\b|honey", 304, 0.3, 0, 82, 0.2, 4, density=1.4),
    Food("dates", r"dattes?|\bdates\b|deglet", 282, 2.5, 0.4, 75, 8, 2, piece=8),
    Food("raisins", r"raisins? secs?|raisins", 299, 3, 0.5, 79, 3.7, 11),
    Food("almonds", r"amandes?|almonds?", 579, 21, 50, 22, 12.5, 1, density=0.6),
    Food("pine_nuts", r"pignons?|pine nuts?|zgougou", 673, 13.7, 68, 13, 3.7, 2, density=0.6),
    Food("walnuts", r"\bnoix\b|walnuts?", 654, 15, 65, 14, 6.7, 2, density=0.5),
    Food("sesame", r"sesame", 573, 17.7, 50, 23, 11.8, 11, density=0.6),
]
_FOOD_RES = [(food, re.compile(food.pattern)) for food in FOODS]

OIL_FOODS = {"olive_oil", "oil", "smen", "butter"}
# Seasonings a card often lists without a quantity: skipped silently.
TO_TASTE_FOODS = {"salt", "spices", "water", "herbs", "chili"}
# Salty foods named in the sodium tip, with the grams per serving from which
# each one is worth pointing out.
SALTY_FOODS = {
    "tomato_paste": 15, "olives": 25, "harissa": 10, "capers": 5,
    "preserved_lemon": 10, "stock_cube": 3, "anchovies": 10, "salt": 1,
    "cheese": 30, "merguez": 50,
}

# EU reference intakes for an adult (Regulation 1169/2011); fiber: 25 g.
REFERENCE = {"kcal": 2000, "protein": 50, "carbs": 260, "fat": 70, "fiber": 25, "sodium": 2400}
NUTRIENTS = ("kcal", "protein", "carbs", "fat", "fiber", "sodium")

NUM = r"\d+\s+\d/\d|\d/\d|\d+(?:[.,]\d+)?"
QTY_RE = re.compile(rf"(?<![\w/])({NUM})(?:\s*(?:-|a|to)\s*({NUM}))?")
# (pattern at the start of the text after a number, unit kind, factor)
UNITS = [
    (r"(?:kg|kilos?|kilogrammes?)\b", "g", 1000),
    (r"mg\b", "g", 0.001),
    (r"(?:g|gr|grammes?|grams?)\b", "g", 1),
    (r"dl\b", "ml", 100),
    (r"cl\b", "ml", 10),
    (r"ml\b", "ml", 1),
    (r"(?:l|litres?|liters?)\b", "ml", 1000),
    (r"cuil\w*\.?\s*(?:a|de)?\s*soupe|c\.?\s*(?:a\.?\s*)?s(?:oupe)?\b|tbsp\b|tbs\b|tablespoons?\b", "ml", 15),
    (r"cuil\w*\.?\s*(?:a|de)?\s*cafe|c\.?\s*(?:a\.?\s*)?c(?:afe)?\b|tsp\b|teaspoons?\b", "ml", 5),
    (r"(?:verres?|glass(?:es)?)\b", "ml", 200),
    (r"(?:tasses?|cups?)\b", "ml", 240),
    (r"(?:pincees?|pinch(?:es)?)\b", "g", 0.5),
    (r"(?:poignees?|handfuls?)\b", "g", 30),
    (r"(?:gousses?|cloves?)\b", "g", 5),
    (r"(?:bottes?|bouquets?|bunch(?:es)?)\b", "g", 50),
    (r"(?:tranches?|slices?)\b", "g", 30),
]
_UNIT_RES = [(re.compile(p), kind, factor) for p, kind, factor in UNITS]
# Meat cuts counted as pieces: "4 cuisses de poulet" is not 4 whole chickens.
MEAT_CUTS = [
    (re.compile(r"\b(?:cuisses?|pilons?|drumsticks?|legs?)\b"), 200),
    (re.compile(r"\b(?:blancs?|filets?|escalopes?|breasts?)\b"), 150),
    (re.compile(r"\b(?:ailes?|wings?)\b"), 90),
    (re.compile(r"\b(?:morceaux?|pieces?)\b"), 150),
]
MEATS = {"lamb", "veal", "beef", "chicken", "meat"}
FRYING = re.compile(r"friture|pour frire|frying|deep.?fry|to fry")
TO_TASTE = re.compile(r"au gout|to taste|selon|facultatif|optional|a volonte")
FRACTIONS = {"½": " 1/2", "¼": " 1/4", "¾": " 3/4", "⅓": " 1/3", "⅔": " 2/3"}


def normalize(text: str) -> str:
  for char, repl in FRACTIONS.items():
    text = text.replace(char, repl)
  text = text.lower().replace("œ", "oe").replace("’", "'").replace("⁄", "/")
  text = unicodedata.normalize("NFKD", text)
  return "".join(c for c in text if not unicodedata.combining(c))


def to_number(text: str) -> float:
  total = 0.0
  for part in text.replace(",", ".").split():
    if "/" in part:
      num, den = part.split("/")
      total += float(num) / float(den) if float(den) else 0
    else:
      total += float(part)
  return total


def match_food(text: str) -> Food | None:
  for food, pattern in _FOOD_RES:
    if pattern.search(text):
      return food
  return None


def quantity_grams(text: str, food: Food) -> float | None:
  """Grams of the ingredient in the line, or None if no usable quantity.

  A weight or volume anywhere in the line wins ("1 poulet de 1,2 kg");
  otherwise the first number counts pieces ("3 oignons").
  """
  count = None
  for match in QTY_RE.finditer(text):
    value = to_number(match.group(1))
    if match.group(2):
      value = (value + to_number(match.group(2))) / 2
    rest = text[match.end():].lstrip()
    for pattern, kind, factor in _UNIT_RES:
      if pattern.match(rest):
        grams = value * factor
        return grams * food.density if kind == "ml" else grams
    if count is None:
      count = value
  if count is not None and food.name in MEATS:
    for pattern, grams in MEAT_CUTS:
      if pattern.search(text):
        return count * grams
  if count is not None and food.piece:
    return count * food.piece
  return None


def ingredient_lines(recipe_md: str) -> list[str]:
  """Bullets of the ingredient section(s) of a recipe card.

  The section starts at a heading that names the ingredients (or the
  pantry and add-on groups) and ends at the steps. Without such a heading,
  every bullet before the first numbered step is taken.
  """
  start = re.compile(r"ingredient|deja dans votre cuisine|a ajouter|you already have|to add")
  stop = re.compile(r"preparation|etapes?|steps?|method|instructions|conseils?|tips?|astuces?|ce que change")
  bullet = re.compile(r"^\s*[-*•]\s+(.+)")
  numbered = re.compile(r"^\s*\d+[.)]\s")
  heading = re.compile(r"^\s*(?:#+\s*|\*\*[^*]+\*\*\s*:?\s*$|[^-*•\d].{0,60}:\s*$)")
  lines = recipe_md.splitlines()

  found, inside = [], False
  for line in lines:
    norm = normalize(line)
    if heading.match(line) and not bullet.match(line):
      if start.search(norm):
        inside = True
      elif stop.search(norm):
        inside = False
      continue
    if numbered.match(line):
      inside = False
    elif inside and (m := bullet.match(line)):
      found.append(m.group(1))
  if found:
    return found
  for line in lines:
    if numbered.match(line):
      break
    if m := bullet.match(line):
      found.append(m.group(1))
  return found


def recipe_servings(recipe_md: str, default: int = 4) -> int:
  norm = normalize(recipe_md)
  match = re.search(
      r"(\d+)\s*(?:personnes?|pers\b|portions?|parts?|servings?|people|persons)"
      r"|(?:portions?|servings?|pour|serves)\s*:?\s*(\d+)",
      norm,
  )
  if not match:
    return default
  servings = int(match.group(1) or match.group(2))
  return servings if 1 <= servings <= 20 else default


def clean_item(line: str) -> str:
  return re.sub(r"[*_`]", "", line).strip()


def calculate_recipe_nutrition(
    ingredients_text: str, servings: int = 4, t: dict | None = None,
    dietary_restrictions: str = "None",
) -> str:
  """Markdown nutrition panel per serving for a list of ingredient lines.

  `ingredients_text` holds one ingredient per line (bullets or plain).
  `t` is the UI labels dict from app.py; the advice comes from fixed rules
  on the per-serving values.
  """
  totals = dict.fromkeys(NUTRIENTS, 0.0)
  grams_by_food: dict[str, float] = {}
  counted, missing, salt_to_taste = 0, [], False
  lines = [clean_item(re.sub(r"^\s*[-*•]\s+", "", line))
           for line in ingredients_text.splitlines() if line.strip()]

  for line in lines:
    text = normalize(line)
    food = match_food(text)
    grams = quantity_grams(text, food) if food else None
    if grams is None:
      if food and food.name == "salt":
        salt_to_taste = True
      if not food or (food.name not in TO_TASTE_FOODS and not TO_TASTE.search(text)):
        missing.append(line)
      continue
    if food.name in OIL_FOODS and FRYING.search(text):
      grams *= 0.1  # most frying oil stays in the pan
    counted += 1
    grams_by_food[food.name] = grams_by_food.get(food.name, 0) + grams
    for key in NUTRIENTS:
      totals[key] += getattr(food, key) * grams / 100

  if not counted:
    return t["nut_none"]

  per = {key: value / servings for key, value in totals.items()}
  rows = [
      f"| {t['nut_col_nutrient']} | {t['nut_col_serving']} | {t['nut_col_ri']} |",
      "|---|---|---|",
  ]
  for key in NUTRIENTS:
    value = per[key]
    shown = f"{value:.1f} g" if key == "fiber" else (
        f"{value:.0f} mg" if key == "sodium" else
        f"{value:.0f} kcal" if key == "kcal" else f"{value:.0f} g"
    )
    rows.append(f"| {t['nut_rows'][key]} | {shown} | {value / REFERENCE[key]:.0%} |")

  tips = nutrition_tips(per, grams_by_food, servings, t, dietary_restrictions)
  notes = [t["nut_coverage"].format(done=counted, total=len(lines))]
  if missing:
    notes.append(t["nut_missing"].format(items="; ".join(missing)))
  if salt_to_taste:
    notes.append(t["nut_salt_taste"])
  notes.append(t["nut_disclaimer"])

  return "\n".join(
      [t["nut_servings"].format(n=servings), "", *rows, "",
       f"### {t['nut_tips_head']}", "", *[f"- {tip}" for tip in tips], "",
       *[f"*{note}*  " for note in notes]]
  )


def nutrition_tips(
    per: dict, grams_by_food: dict, servings: int, t: dict, dietary_restrictions: str
) -> list[str]:
  """Up to 3 fixed-rule tips from the per-serving values, most important first."""
  diet = dietary_restrictions.lower()
  low_sodium = "sodium" in diet
  diabetic = "diabet" in diet or "glycemic" in diet
  per_food = {name: grams / servings for name, grams in grams_by_food.items()}
  tips = []

  salty = [name for name, limit in SALTY_FOODS.items() if per_food.get(name, 0) >= limit]
  # Commercial concentrate and brined olives are often saltier than the table
  # says, so a large amount alone triggers the tip.
  if per["sodium"] > (600 if low_sodium else 800) or {"tomato_paste", "olives"} & set(salty):
    sources = ", ".join(t["nut_foods"][name] for name in salty or ["salt"])
    tips.append(t["nut_tip_salt"].format(mg=round(per["sodium"]), items=sources))

  oil_ml = sum(per_food.get(name, 0) / 0.92 for name in OIL_FOODS)
  if oil_ml > 50:
    tips.append(t["nut_tip_fat"].format(ml=round(oil_ml)))

  if per["carbs"] > (60 if diabetic else 90):
    key = "nut_tip_carbs_diabetic" if diabetic else "nut_tip_carbs"
    tips.append(t[key].format(g=round(per["carbs"])))
  if per["kcal"] > 900:
    tips.append(t["nut_tip_kcal"].format(kcal=round(per["kcal"])))
  if per["fiber"] < 5:
    tips.append(t["nut_tip_fiber"].format(g=round(per["fiber"], 1)))
  if per["protein"] < 15:
    tips.append(t["nut_tip_protein"].format(g=round(per["protein"])))
  return tips[:3] or [t["nut_tip_balanced"]]


def nutrition_report(recipe_md: str, t: dict, dietary_restrictions: str = "None") -> str:
  """Nutrition panel for a whole recipe card: ingredients and servings are read from it."""
  lines = ingredient_lines(recipe_md)
  if not lines:
    return t["nut_none"]
  return calculate_recipe_nutrition(
      "\n".join(lines), recipe_servings(recipe_md), t, dietary_restrictions
  )
