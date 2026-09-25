import os
from pathlib import Path
import re
from dotenv import load_dotenv
from fastembed import TextEmbedding
import fitz  # PyMuPDF
import psycopg2

# 1. Environment and database configuration
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("Missing DATABASE_URL in .env file.")

# 2. Initialize local embedding model (384 dimensions)
embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")


def parse_recipe_text(text: str) -> dict:
    """Parse recipe sections: title, ingredients, and instructions."""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return {}

    # The first line usually contains the dish name
    dish_name = lines[0]

    ingredients = []
    instructions = []
    current_section = "none"

    # Keywords to detect transitions
    ing_pattern = re.compile(r"ingr[eé]dients", re.IGNORECASE)
    prep_pattern = re.compile(
        r"(pr[eé]paration|instructions|r[eé]alisation)", re.IGNORECASE
    )

    for line in lines[1:]:
        if ing_pattern.search(line):
            current_section = "ingredients"
            continue
        elif prep_pattern.search(line):
            current_section = "instructions"
            continue

        if current_section == "ingredients":
            ingredients.append(line)
        elif current_section == "instructions":
            instructions.append(line)
        else:
            # Lines before explicit section markers default to ingredients
            ingredients.append(line)

    return {
        "dish_name": dish_name,
        "ingredients": "\n".join(ingredients),
        "instructions": "\n".join(instructions),
    }


def ingest_native_pdf(pdf_path: str):
    """Extract, embed, and store native PDF recipes in Neon PostgreSQL."""
    if not os.path.exists(pdf_path):
        print(f"Error: File not found at {pdf_path}")
        return

    doc = fitz.open(pdf_path)
    book_title = Path(pdf_path).stem
    total_pages = len(doc)

    print(f"Starting ingestion for: {book_title} ({total_pages} pages)")

    conn = psycopg2.connect(DATABASE_URL)
    indexed_count = 0

    with conn.cursor() as cur:
        for page_idx in range(total_pages):
            page_num = page_idx + 1
            page = doc[page_idx]
            raw_text = page.get_text().strip()

            # Skip empty pages or cover pages with minimal text
            if len(raw_text) < 50:
                print(
                    f"[{page_num}/{total_pages}] Skipping page (insufficient"
                    " text)."
                )
                continue

            parsed = parse_recipe_text(raw_text)
            dish_name = parsed.get("dish_name", f"Recipe Page {page_num}")
            ingredients = parsed.get("ingredients", "")
            instructions = parsed.get("instructions", "")

            # Build semantic content block for vectorization
            full_content = (
                f"Plat: {dish_name}\n\n"
                f"Ingrédients:\n{ingredients}\n\n"
                f"Préparation:\n{instructions}"
            )

            # Generate vector embedding
            embedding = list(embedding_model.embed([full_content]))[0].tolist()

            # Insert record into PostgreSQL
            cur.execute(
                """
                INSERT INTO tunisian_recipes (dish_name, source_book, page_number, ingredients, instructions, full_content, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
            """,
                (
                    dish_name,
                    book_title,
                    page_num,
                    ingredients,
                    instructions,
                    full_content,
                    embedding,
                ),
            )
            conn.commit()
            indexed_count += 1
            print(f"[{page_num}/{total_pages}] Successfully indexed: '{dish_name}'")

    conn.close()
    print(
        f"Ingestion completed! Total recipes indexed from this document:"
        f" {indexed_count}."
    )


if __name__ == "__main__":
    target_pdf = "Doc/172081151-Atelier-Cuisine-Tunisienne-11-03-09.pdf"
    ingest_native_pdf(target_pdf)