import os
from pathlib import Path
from dotenv import load_dotenv
from fastembed import TextEmbedding
import fitz  # PyMuPDF
import psycopg2

env_path = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path=env_path, override=True)

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
  raise ValueError(f'DATABASE_URL is not set in {env_path}.')

# Runs locally, no API key needed. Must match the model in src/tools.py.
EMBEDDING_DIM = 384
embedding_model = TextEmbedding(model_name='BAAI/bge-small-en-v1.5')


def init_db():
  print('Connecting to Neon Postgres...')
  conn = psycopg2.connect(DATABASE_URL)
  conn.autocommit = True
  with conn.cursor() as cur:
    cur.execute('CREATE EXTENSION IF NOT EXISTS vector;')

    # DROP TABLE is disabled on purpose: this is the production table.
    # To rebuild it from scratch, drop the table by hand in the Neon console.
    # cur.execute("DROP TABLE IF EXISTS tunisian_recipes CASCADE;")
    cur.execute(f"""
            CREATE TABLE IF NOT EXISTS tunisian_recipes (
                id SERIAL PRIMARY KEY,
                dish_name VARCHAR(255) NOT NULL,
                source_book VARCHAR(255) NOT NULL,
                page_number INT,
                ingredients TEXT NOT NULL,
                instructions TEXT NOT NULL,
                full_content TEXT NOT NULL,
                embedding vector({EMBEDDING_DIM}),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

    cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_recipes_embedding 
            ON tunisian_recipes USING hnsw (embedding vector_cosine_ops);
        """)
  print(f'Schema ready (vector dimension {EMBEDDING_DIM}).')
  return conn


def get_embedding(text: str):
  """Embed text locally with FastEmbed. Returns None on failure."""
  try:
    embeddings = list(embedding_model.embed([text]))
    return embeddings[0].tolist()
  except Exception as e:
    print(f'Embedding failed: {e}')
    return None


def ingest_atelier_cuisine(conn):
  pdf_path = os.path.join(
      'Doc', '172081151-Atelier-Cuisine-Tunisienne-11-03-09.pdf'
  )
  if not os.path.exists(pdf_path):
    print(f'File not found: {pdf_path}')
    return

  doc = fitz.open(pdf_path)
  print(f'Ingesting {os.path.basename(pdf_path)} ({len(doc)} pages)...')

  recipes_added = 0
  with conn.cursor() as cur:
    for page_num in range(1, len(doc)):
      page_text = doc[page_num].get_text().strip()
      if not page_text or len(page_text) < 50:
        continue

      lines = [line.strip() for line in page_text.splitlines() if line.strip()]
      dish_name = lines[0] if lines else f'Recipe Page {page_num + 1}'

      full_chunk = f'dish: {dish_name}\n\nRecipe:\n{page_text}'
      print(f"Embedding '{dish_name}'...")

      vec = get_embedding(full_chunk)
      if vec:
        cur.execute(
            """
                    INSERT INTO tunisian_recipes (dish_name, source_book, page_number, ingredients, instructions, full_content, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
            (
                dish_name,
                'Atelier Cuisine Tunisienne 2009',
                page_num + 1,
                'Included in the instructions',
                page_text,
                full_chunk,
                vec,
            ),
        )
        recipes_added += 1

  print(f'\nDone: {recipes_added} recipes inserted.')


if __name__ == '__main__':
  conn = init_db()
  ingest_atelier_cuisine(conn)
  conn.close()