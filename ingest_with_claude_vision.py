import base64
import io
import json
import os
from pathlib import Path
import re
import time
import anthropic
from dotenv import load_dotenv
from fastembed import TextEmbedding
import fitz
import psycopg2

# 1. Environment and database configuration
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

DATABASE_URL = os.getenv("DATABASE_URL")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

if not DATABASE_URL or not ANTHROPIC_API_KEY:
    raise ValueError("Missing DATABASE_URL or ANTHROPIC_API_KEY in .env file.")

# 2. Client and embedding initialization
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")

# 3. Local cache directory to store raw JSON results
CACHE_DIR = Path("Doc/recipes_json_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def extract_recipe_with_vision(img_bytes: bytes) -> dict:
    """Send scanned page image to Claude Vision API for structured recipe extraction."""
    base64_image = base64.b64encode(img_bytes).decode("utf-8")
    prompt = """Tu es un expert en numérisation du patrimoine culinaire tunisien.
Analyse cette page scannée. Si la page contient une recette de cuisine :
Renvoie EXCLUSIVEMENT un objet JSON valide avec cette structure exacte (sans texte d'explication) :
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

Si la page ne contient PAS de recette (couverture, table des matières, préface, illustration seule) :
{
  "is_recipe": false
}"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[
                {
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
                }
            ],
        )

        content = response.content[0].text.strip()
        # Clean markdown wrappers if present
        if "```" in content:
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

        return json.loads(content)
    except Exception as e:
        print(f"Error during API extraction: {e}")
        return {"is_recipe": False}


def run_pipeline():
    """Process all pages, cache JSON files locally, embed, and store in PostgreSQL."""
    pdf_path = "Doc/52687157-Traditions-Culinaires-de-Tunisie.pdf"
    if not os.path.exists(pdf_path):
        print(f"Error: File not found at {pdf_path}")
        return

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    print(f"Starting Vision ingestion for {total_pages} pages...")

    conn = psycopg2.connect(DATABASE_URL)
    recipes_indexed = 0

    with conn.cursor() as cur:
        for page_idx in range(total_pages):
            page_num = page_idx + 1
            cache_file = CACHE_DIR / f"page_{page_num}.json"

            # Check local cache first to avoid redundant API billing
            if cache_file.exists():
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                page = doc[page_idx]
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                img_bytes = pix.tobytes("jpeg")

                data = extract_recipe_with_vision(img_bytes)
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                time.sleep(0.3)  # Gentle delay to respect rate limits

            # Skip non-recipe pages
            if not data.get("is_recipe", False):
                print(f"[{page_num}/{total_pages}] Skipped (non-recipe page).")
                continue

            dish_name = data.get("dish_name", f"Recipe Page {page_num}")
            ingredients_list = data.get("ingredients", [])
            ingredients_str = "\n".join(ingredients_list)
            instructions = data.get("instructions", "")
            portions = data.get("portions", "")

            # Build semantic content block for vectorization
            full_chunk = (
                f"Plat: {dish_name}\n"
                f"Portions: {portions}\n\n"
                f"Ingrédients:\n{ingredients_str}\n\n"
                f"Préparation:\n{instructions}"
            )

            # Generate local vector embedding (384 dimensions)
            vec = list(embedding_model.embed([full_chunk]))[0].tolist()

            # Insert record into PostgreSQL
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
            recipes_indexed += 1
            print(f"[{page_num}/{total_pages}] Successfully indexed: '{dish_name}'")

    conn.close()
    print(f"\nIngestion complete! Total indexed recipes: {recipes_indexed}.")


if __name__ == "__main__":
    run_pipeline()