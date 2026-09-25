import os
import base64
from typing import List, Union
from crewai.tools import tool
from litellm import completion


def encode_image_to_base64(path: str) -> str:
    """Lit un fichier image et le convertit en chaîne Base64."""
    with open(path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


@tool("extract_ingredients_from_image_and_text")
def extract_ingredients_from_image_and_text(
    image_input: str = "None", 
    manual_input: str = "None"
) -> str:
    """
    Extrait et fusionne les ingrédients visibles sur une ou plusieurs images 
    avec les ingrédients saisis manuellement au format texte.
    """
    content = []

    # 1. Traitement des images (une seule ou liste délimitée par des virgules)
    if image_input and image_input not in ["None", "null", ""]:
        # Gestion multi-chemins
        raw_paths = [p.strip() for p in image_input.split(",") if p.strip()]
        valid_paths = [p for p in raw_paths if os.path.exists(p)]

        for path in valid_paths:
            try:
                b64_img = encode_image_to_base64(path)
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}
                })
            except Exception as e:
                continue

        if valid_paths:
            content.append({
                "type": "text",
                "text": (
                    "Identifie avec précision tous les ingrédients comestibles, légumes, fruits, "
                    "protéines, condiments, boîtes de conserve et épices visibles sur ces photographies. "
                    "Renvoie uniquement la liste de ces ingrédients séparés par des virgules."
                )
            })

    # 2. Traitement du texte manuel additionnel
    if manual_input and manual_input not in ["None", "null", ""]:
        content.append({
            "type": "text",
            "text": f"Prends également en compte ces ingrédients saisis manuellement : {manual_input}"
        })

    if not content:
        return "Aucun ingrédient détecté ni renseigné."

    # Appel au modèle de vision via LiteLLM
    vision_model = os.getenv("VISION_MODEL", "claude-3-5-sonnet-latest")
    clean_model = vision_model.replace("anthropic/", "")
    litellm_model = f"anthropic/{clean_model}"

    try:
        response = completion(
            model=litellm_model,
            messages=[{"role": "user", "content": content}],
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )
        return response.choices[0].message.content
    except Exception as err:
        return f"Erreur lors de la détection visuelle : {str(err)}"


@tool("filter_ingredients_list")
def filter_ingredients_list(raw_ingredients: str) -> List[str]:
    """
    Nettoie, standardise et dé-duplique une chaîne d'ingrédients bruts 
    pour renvoyer une liste Python propre.
    """
    if not raw_ingredients or raw_ingredients in ["None", "null"]:
        return []
    
    # Nettoyage des puces Markdown et retours à la ligne
    cleaned = raw_ingredients.replace("\n", ",").replace("-", ",").replace("*", "")
    items = [item.strip().lower() for item in cleaned.split(",") if item.strip()]
    
    # Déduplication en préservant l'ordre
    unique_items = list(dict.fromkeys(items))
    return unique_items


@tool("filter_based_on_dietary_restrictions")
def filter_based_on_dietary_restrictions(
    ingredients: Union[List[str], str], 
    dietary_restrictions: str = "None"
) -> List[str]:
    """
    Filtre les ingrédients selon les intolérances et régimes spécifiés.
    """
    if isinstance(ingredients, str):
        ing_list = [i.strip().lower() for i in ingredients.split(",") if i.strip()]
    else:
        ing_list = [str(i).strip().lower() for i in ingredients]

    if not dietary_restrictions or dietary_restrictions.lower() in ["none", "standard", ""]:
        return ing_list

    restrictions_lower = dietary_restrictions.lower()
    filtered = []

    # Mots-clés d'exclusion courante
    gluten_items = ["couscous", "farine", "pain", "pâtes", "semoule", "orzo", "frik", "malsouka", "brik"]
    meat_items = ["viande", "foie", "poulet", "boeuf", "agneau", "merguez", "veau", "thon", "poisson", "crevette"]
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