# Dish type of each recipe in tunisian_recipes, keyed by exact dish_name.
# Dishes missing from this map (new ingestions) fall into OTHER, so they
# still show up in the dropdown.

MAIN = "main"
STARTER = "starter"
SOUP = "soup"
BREAD = "bread"
SWEET = "sweet"
DRINK = "drink"
SAUCE = "sauce"
OTHER = "other"

# Display order in the UI.
CATEGORIES = [MAIN, STARTER, SOUP, BREAD, SWEET, DRINK, SAUCE, OTHER]

_DISHES_BY_CATEGORY = {
    MAIN: [
        "Andouillettes aux Tripes",
        "Artichauts Farcis",
        "Aubergines Farcies - Bitinjen Mihchi",
        "Aubergines Farcies - Bitinjen Mihchi à l'Égyptienne",
        "Borghol",
        "Calmars Farcis / Kalmars Mihchi",
        "Calmars en Sauce - Marquat Kalmar",
        "Chakchouka",
        "Couscous Quif-Tunisien (Kousksi Yehoudi)",
        "Couscous Zerda (Kousksi Zerda)",
        "Couscous au Poisson (Kousksi Bil Hout)",
        "Couscous au Poisson à La Sfaxienne (Kousksi Sfaxi Bil Hout)",
        "Couscous au Poulet / Kousksi bid'Djaj",
        "Couscous aux Andouillettes (Kousksi bil Âosbane)",
        "Couscous aux Calmars Farcis (Kousksi bil Kalmar Mihchi)",
        "Couscous aux Légumes (Kousksi bil Khodhra)",
        "Couscous aux Poulpes (Kousksi bil Quarnit)",
        "Couscous d'Orge au Fenouil (Mafthouh bil Besbes)",
        "Couscous de Fin d'Année - Kousksi Ras El Aâm",
        "Couscous à l'Agneau (Kousksi bil Âallouch)",
        "Gigot Farci - Aallouch Mihchi",
        "Gigot d'Agneau au Four (Aâlouch fil Koucha)",
        "Macaroni Maqrouna",
        "Medfouna - Plat aux Épinards avec la Queue et le Pied de Bœuf",
        "Mhammes - Repas aux Légumes à base de Boules de Blé",
        "Nouasser",
        "Poisson Complet - Hout Kemel",
        "Poisson au Four (Kousha Hout)",
        "Poivrons Farcis (Filfel Mihchi)",
        "Poulet Farci - Diej Mihchi",
        "Poulet au Four (Diej fil Koucha)",
        "Pâtes Rapides - Maqrouna Sarîaa",
        "Quartiers de Poulet Farcis (Diej Mihchi)",
        "Ragoût aux Fenouils",
        "Ragoût aux Gombos (Gnaoüiya)",
        "Ragoût aux Haricots Blancs",
        "Ragoût aux Légumes - Marquit Khodhra",
        "Ragoût aux Petits Pois (Marquit Jilbana)",
        "Ragoût à la Corète - Mloukhia",
        "Recette de Base / Le Couscous Réchauffé (Kousksi Mjammer)",
        "Riz au Poulet à la Vapeur (Rouz Mlaouer Bid'Djej)",
        "Riz à la Djerbienne (Rouz Jerbi)",
        "Roulade de Boeuf - L'Ham Mihchi",
        "Spaghetti aux Fruits de Mer - Maqrouna Ghilel el Bhar",
        "Viande au Four",
    ],
    STARTER: [
        "Aïja - Recette de Base",
        "Beignets de Chou-fleurs - Mbatten Brouklou",
        "Brik Dannouni",
        "Brik à L'Oeuf (Brik bil Âdham)",
        "Keftegi - Plat Garni aux Légumes et aux Œufs Frits",
        "Légumes Panés - Khodra Mkalfna",
        "Plat Tunisien - S'han Tounsi",
        "Salade Grillée (Slata Michwiya)",
        "Salade de Riz - Slatit Rouz",
        "Samsa à la Viande (Samsa Bil'lham)",
        "Tajine au Fromage (Tajine bij'Jben)",
        "Tajine au Persil (Tajine Maâdnous)",
        "Tajine aux Courgettes (Tajine bil Qrâa)",
        "Tajine aux Feuilles de Brik - Tajine Malsouka",
        "Testira - Plat de légumes aux Piments",
        "Tourte aux Épinards (Tarta Sebnakh)",
        "Tourte aux Épinards - Tarta Sebnakh",
        "Œufs Farcis (Âdham Mihchi)",
    ],
    SOUP: [
        "Bouillon à la Viande de Mouton",
        "Soupe au Poisson à la Sfaxienne",
        "Soupe aux Légumes - Mhammes Jari",
        "Soupe aux Pois Chiches - lablabi",
        "Soupe à la Semoule",
        "Soupe à la Semoule d'Orge Verte - Chorba Frik",
    ],
    BREAD: [
        "Pain Arabe - Khobz Aarbi",
        "Pain Feuilleté à la Semoule (Khobz Mlaoui)",
        "Pain aux Olives - Khobz biz'Zitoun",
        "Pain de Campagne - Khobz Tabouna",
    ],
    SWEET: [
        "Couscous Sucré",
        "Crème Pâtissière - Krima",
        "Crème de Graines de Pin d'Alep - Assida Zgougou",
    ],
    DRINK: [
        "Café Glacé",
        "Cocktail Fraise-Orange",
        "La Citronnade",
        "Sirop de Citron",
        "Thé à la Menthe (Tei Bi'Nâanâa)",
    ],
    SAUCE: [
        "Charmoula - Sauce aux Raisins Secs (Une spécialité de Sfax)",
        "Hrous",
    ],
}

DISH_CATEGORY = {
    dish: category
    for category, dishes in _DISHES_BY_CATEGORY.items()
    for dish in dishes
}


def dish_category(dish_name: str) -> str:
  return DISH_CATEGORY.get(dish_name, OTHER)
