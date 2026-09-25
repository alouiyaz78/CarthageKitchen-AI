import base64
import json
import os
from pathlib import Path
import re
import anthropic
from dotenv import load_dotenv
from fastembed import TextEmbedding
import fitz
import psycopg2

env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

DATABASE_URL = os.getenv("DATABASE_URL")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
CACHE_DIR = Path("Doc/recipes_json_cache")

# Pages ayant déclenché l'erreur Extra data
FAILED_PAGES = [117, 126, 129, 130, 131, 132, 134]


def robust_json_parse(text: str) -> dict:
  """Extrait le premier objet JSON valide même s'il y a du texte en trop autour."""
  text = text.strip()
  if "```" in text:
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

  # Recherche du premier bloc { ... }
  match = re.search(r"(\{.*\})", text, re.DOTALL)
  if match:
    candidate = match.group(1)
    try:
      return json.loads(candidate)
    except Exception:
      pass

  # Décodage progressif
  decoder = json.JSONDecoder()
  idx = text.find("{")
  if idx != -1:
    obj, _ = decoder.raw_decode(text[idx:])
    return obj

  return {"is_recipe": False}


def fix_pages():
  pdf_path = "Doc/52687157-Traditions-Culinaires-de-Tunisie.pdf"
  doc = fitz.open(pdf_path)
  conn = psycopg2.connect(DATABASE_URL)
  added_count = 0

  prompt = """Tu es un expert en numérisation du patrimoine culinaire tunisien.
Analyse cette page scannée. Si la page contient une recette de cuisine :
Renvoie EXCLUSIVEMENT un objet JSON valide avec cette structure exacte, sans aucun commentaire avant ni après :
{
  "is_recipe": true,
  "dish_name": "Nom du plat en français (et phonétique tunisienne si mentionnée)",
  "portions": "ex: Pour 6 personnes",
  "ingredients": [
    "quantité et ingrédient 1",
    "quantité et ingrédient 2"
  ],
  "instructions": "Texte intégral des étapes de préparation sans rien couper."
}
Si la page ne contient PAS de recette :
{
  "is_recipe": false
}"""

  with conn.cursor() as cur:
    for page_num in FAILED_PAGES:
      page_idx = page_num - 1
      page = doc[page_idx]

      pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
      img_bytes = pix.tobytes("jpeg")
      base64_image = base64.b64encode(img_bytes).decode("utf-8")

      try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": base64_image,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )

        raw_text = response.content[0].text
        data = robust_json_parse(raw_text)

        # Sauvegarde propre dans le cache
        cache_file = CACHE_DIR / f"page_{page_num}.json"
        with open(cache_file, "w", encoding="utf-8") as f:
          json.dump(data, f, ensure_ascii=False, indent=2)

        if not data.get("is_recipe", False):
          print(f"[{page_num}/137] Confirmé : hors recette.")
          continue

        dish_name = data.get("dish_name", f"Recette Page {page_num}")
        ingredients_str = "\n".join(data.get("ingredients", []))
        instructions = data.get("instructions", "")
        portions = data.get("portions", "")

        full_chunk = f"Plat: {dish_name}\nPortions: {portions}\n\nIngrédients:\n{ingredients_str}\n\nPréparation:\n{instructions}"
        vec = list(embedding_model.embed([full_chunk]))[0].tolist()

        cur.execute(
            """
                    INSERT INTO tunisian_recipes (dish_name, source_book, page_number, ingredients, instructions, full_content, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
            (
                dish_name,
                "Traditions Culinaires de Tunisie",
                page_num,
                ingredients_str,
                instructions,
                full_chunk,
                vec,
            ),
        )
        conn.commit()
        added_count += 1
        print(f"[{page_num}/137] Rattrapée avec succès : '{dish_name}'")

      except Exception as e:
        print(f"[{page_num}/137] Échec : {e}")

  conn.close()
  print(f"\nRattrapage terminé : {added_count} recettes ajoutées.")


if __name__ == "__main__":
  fix_pages()