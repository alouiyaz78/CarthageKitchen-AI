from typing import List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sourcing Models (Canadian Market / Ottawa & Montreal)
# ---------------------------------------------------------------------------
class SourcingItem(BaseModel):
    ingredient: str = Field(
        ..., 
        description="Authentic Tunisian staple or missing ingredient name"
    )
    canadian_substitute: str = Field(
        ..., 
        description="Direct culinary substitute found at Maxi, Metro, Loblaws,Walmart,Costco, Super C, or IGA"
    )
    specialty_stores: List[str] = Field(
        default_factory=list, 
        description="Specific markets in Ottawa/Gatineau (e.g., Mid-East Food Centre, Adonis) or Montreal (e.g., Jean-Talon Est / Petit Maghreb, Adonis, Sami Fruits)"
    )


# ---------------------------------------------------------------------------
# Recipe Models (Teyssir Ksouri & Pantry + Add-on)
# ---------------------------------------------------------------------------
class Recipe(BaseModel):
    title: str = Field(..., description="Authentic or modernized Tunisian recipe title")
    description: Optional[str] = Field(None, description="Culinary backstory and concept overview")
    prep_time: str = Field(..., description="Estimated prep time (e.g., '15 mins')")
    cook_time: str = Field(..., description="Estimated cooking time (e.g., '25 mins')")
    
    # Pantry + Add-on structure
    base_ingredients: List[str] = Field(
        ..., 
        description="Ingredients utilized directly from user's detected photo or manual text"
    )
    pantry_staples: List[str] = Field(
        default_factory=lambda: ["Olive oil", "Salt", "Black pepper", "Garlic", "Water"],
        description="Assumed essential condiments and basics"
    )
    missing_items_to_grab: List[str] = Field(
        default_factory=list, 
        description="1 to 3 key missing elements suggested to achieve true Tunisian depth"
    )
    
    instructions: List[str] = Field(
        ..., 
        description="Step-by-step culinary preparation instructions"
    )
    chef_tips: Optional[str] = Field(
        None, 
        description="Teyssir Ksouri pedagogical advice (e.g., techwih blooming, oven roasting, spice balance)"
    )
    sourcing_guide: List[SourcingItem] = Field(
        default_factory=list, 
        description="Canadian grocery substitutes and local store recommendations"
    )


class RecipeOutput(BaseModel):
    recipes: List[Recipe] = Field(
        ..., 
        description="List of crafted Tunisian recipes conforming to dietary restrictions"
    )


# ---------------------------------------------------------------------------
# Nutritional & Metabolic Models
# ---------------------------------------------------------------------------
class NutrientItem(BaseModel):
    food_item: str = Field(..., description="Name of the food item or dish component")
    portion_size: str = Field(..., description="Estimated portion size (e.g., 150g, 1 cup, 2 tbsp)")
    calories: int = Field(..., description="Estimated calories for this portion")


class MacroBreakdown(BaseModel):
    protein_g: float = Field(..., description="Protein content in grams")
    carbs_g: float = Field(..., description="Carbohydrate content in grams (note refined bread/pasta impact)")
    fats_g: float = Field(..., description="Total fats in grams (factoring in olive oil dosage)")
    fiber_g: Optional[float] = Field(None, description="Dietary fiber in grams")
    sodium_mg: Optional[float] = Field(None, description="Estimated sodium in milligrams")


class NutrientAnalysisOutput(BaseModel):
    dish: Optional[str] = Field(None, description="Identified dish or main preparation")
    total_calories: int = Field(..., description="Estimated total energy in kcal")
    items: List[NutrientItem] = Field(default_factory=list, description="Itemized portion and calorie breakdown")
    macronutrients: MacroBreakdown = Field(..., description="Detailed macronutrient split")
    health_evaluation: str = Field(
        ..., 
        description="Clinical evaluation of glycemic balance, satiety, heart health, and optimization tips"
    )
    disclaimer: str = Field(
        default="Nutritional estimations are approximate and intended for educational guidance.",
        description="Health and advisory disclaimer"
    )