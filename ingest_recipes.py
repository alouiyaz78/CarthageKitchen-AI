import os
from pathlib import Path
from dotenv import load_dotenv
from fastembed import TextEmbedding
import fitz  # PyMuPDF
import psycopg2

# Chargement du .env
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError(f"❌ DATABASE_URL introuvable dans {env_path}.")

# Modèle open-source local (zéro appel API, zéro clé requise)
EMBEDDING_DIM = 384
embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")

def init_db():
    print("🔌 Connexion à PostgreSQL Neon...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute("DROP TABLE IF EXISTS tunisian_recipes CASCADE;")
        cur.execute(f"""
            CREATE TABLE tunisian_recipes (
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
    print(f"✅ Schéma Neon prêt (dimension {EMBEDDING_DIM} avec FastEmbed local).")
    return conn

def get_embedding(text: str):
    """Génère le vecteur 100% localement sur votre machine."""
    try:
        embeddings = list(embedding_model.embed([text]))
        return embeddings[0].tolist()
    except Exception as e:
        print(f"⚠️ Erreur d'embedding local : {e}")
        return None

def ingest_atelier_cuisine(conn):
    pdf_path = os.path.join("Doc", "172081151-Atelier-Cuisine-Tunisienne-11-03-09.pdf")
    if not os.path.exists(pdf_path):
        print(f"❌ Fichier non trouvé : {pdf_path}")
        return

    doc = fitz.open(pdf_path)
    print(f"📖 Ingestion de {os.path.basename(pdf_path)} ({len(doc)} pages)...")

    recipes_added = 0
    with conn.cursor() as cur:
        for page_num in range(1, len(doc)):
            page_text = doc[page_num].get_text().strip()
            if not page_text or len(page_text) < 50:
                continue

            lines = [l.strip() for l in page_text.splitlines() if l.strip()]
            dish_name = lines[0] if lines else f"Recette Page {page_num + 1}"

            full_chunk = f"Plat: {dish_name}\n\nRecette:\n{page_text}"
            print(f"⚙️ Vectorisation locale de : '{dish_name}'...")

            vec = get_embedding(full_chunk)
            if vec:
                cur.execute("""
                    INSERT INTO tunisian_recipes (dish_name, source_book, page_number, ingredients, instructions, full_content, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                """, (
                    dish_name,
                    "Atelier Cuisine Tunisienne 2009",
                    page_num + 1,
                    "Inclus dans les instructions",
                    page_text,
                    full_chunk,
                    vec
                ))
                recipes_added += 1

    print(f"\n🎉 Succès : {recipes_added} recettes insérées et indexées dans pgvector !")

if __name__ == "__main__":
    conn = init_db()
    ingest_atelier_cuisine(conn)
    conn.close()
