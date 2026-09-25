import os
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from crewai import LLM, Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from dotenv import load_dotenv

from src.tools import (
    extract_ingredients_from_image_and_text,
    filter_based_on_dietary_restrictions,
    filter_ingredients_list,
)

# ==========================================
# 1. Gestion & Chargement de src/.env
# ==========================================
CURRENT_DIR = Path(__file__).resolve().parent       # /home/alouiyaz/NourishBot/src
ENV_FILE = CURRENT_DIR / ".env"

if not ENV_FILE.exists():
    ENV_FILE = CURRENT_DIR.parent / ".env"          # Fallback racine si déplacé

load_dotenv(dotenv_path=ENV_FILE, override=True)


class Settings(BaseSettings):
    anthropic_api_key: SecretStr | None = None
    serper_api_key: SecretStr | None = None

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore"
    )


config = Settings()

api_key = config.anthropic_api_key.get_secret_value() if config.anthropic_api_key else os.getenv("ANTHROPIC_API_KEY")

if not api_key:
    raise RuntimeError(
        f"ANTHROPIC_API_KEY introuvable dans {ENV_FILE} ou l'environnement système."
    )

os.environ["ANTHROPIC_API_KEY"] = api_key

if config.serper_api_key:
    os.environ["SERPER_API_KEY"] = config.serper_api_key.get_secret_value()
elif os.getenv("SERPER_API_KEY"):
    os.environ["SERPER_API_KEY"] = os.getenv("SERPER_API_KEY")

# Instance LLM globale
llm = LLM(
    model="anthropic/claude-haiku-4-5-20251001",
    api_key=api_key,
    temperature=0.2,
)


# ==========================================
# Modèles Pydantic pour les Recettes
# ==========================================
class SourcingItem(BaseModel):
    ingredient: str
    canadian_substitute: str
    specialty_stores: List[str]


class Recipe(BaseModel):
    title: str
    description: str
    prep_time: str
    cook_time: str
    base_ingredients: List[str]
    pantry_staples: List[str]
    missing_items_to_grab: List[str]
    instructions: List[str]
    chef_tips: str
    sourcing_guide: Optional[List[SourcingItem]] = []


class RecipeOutput(BaseModel):
    recipes: List[Recipe]


# ==========================================
# Modèles Pydantic pour l'Analyse Nutritionnelle
# ==========================================
class FoodItemPortion(BaseModel):
    food_item: str
    portion_size: str
    calories: int


class MacronutrientSplit(BaseModel):
    protein_g: float
    carbs_g: float
    fats_g: float
    fiber_g: float
    sodium_mg: float


class NutritionalAnalysisOutput(BaseModel):
    total_calories: int
    items: List[FoodItemPortion]
    macronutrients: MacronutrientSplit
    health_evaluation: str
    disclaimer: str


# ==========================================
# 1. Crew Recettes & Sourcing
# ==========================================
@CrewBase
class NourishBotRecipeCrew:
    """NourishBot Recipe Generation Crew"""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    def __init__(
        self,
        image_data=None,
        manual_ingredients=None,
        dietary_restrictions="None",
        target_city="Ottawa / Gatineau",
    ):
        self.image_data = image_data
        self.manual_ingredients = manual_ingredients
        self.dietary_restrictions = dietary_restrictions
        self.target_city = target_city

    @agent
    def ingredient_detection_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["ingredient_detection_agent"],
            tools=[
                extract_ingredients_from_image_and_text,
                filter_ingredients_list,
            ],
            llm=llm,
            verbose=True,
        )

    @agent
    def dietary_filtering_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["dietary_filtering_agent"],
            tools=[filter_based_on_dietary_restrictions],
            llm=llm,
            verbose=True,
        )

    @agent
    def recipe_suggestion_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["recipe_suggestion_agent"],
            llm=llm,
            verbose=True,
        )

    @agent
    def ingredient_sourcing_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["ingredient_sourcing_agent"],
            llm=llm,
            verbose=True,
        )

    @agent
    def nutrient_analysis_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["nutrient_analysis_agent"],
            llm=llm,
            verbose=True,
        )

    @task
    def ingredient_detection_task(self) -> Task:
        return Task(config=self.tasks_config["ingredient_detection_task"])

    @task
    def dietary_filtering_task(self) -> Task:
        return Task(config=self.tasks_config["dietary_filtering_task"])

    @task
    def recipe_suggestion_task(self) -> Task:
        return Task(
            config=self.tasks_config["recipe_suggestion_task"],
            output_pydantic=RecipeOutput,
        )

    @task
    def ingredient_sourcing_task(self) -> Task:
        return Task(config=self.tasks_config["ingredient_sourcing_task"])

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=[
                self.ingredient_detection_agent(),
                self.dietary_filtering_agent(),
                self.recipe_suggestion_agent(),
                self.ingredient_sourcing_agent(),
            ],
            tasks=[
                self.ingredient_detection_task(),
                self.dietary_filtering_task(),
                self.recipe_suggestion_task(),
                self.ingredient_sourcing_task(),
            ],
            process=Process.sequential,
            verbose=True,
        )


# ==========================================
# 2. Crew Analyse Nutritionnelle
# ==========================================
@CrewBase
class NourishBotAnalysisCrew:
    """NourishBot Nutritional & Clinical Assessment Crew"""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    def __init__(
        self,
        image_data=None,
        manual_ingredients=None,
        dietary_restrictions="None",
    ):
        self.image_data = image_data
        self.manual_ingredients = manual_ingredients
        self.dietary_restrictions = dietary_restrictions

    @agent
    def ingredient_detection_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["ingredient_detection_agent"],
            tools=[
                extract_ingredients_from_image_and_text,
                filter_ingredients_list,
            ],
            llm=llm,
            verbose=True,
        )

    @agent
    def dietary_filtering_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["dietary_filtering_agent"],
            tools=[filter_based_on_dietary_restrictions],
            llm=llm,
            verbose=True,
        )

    @agent
    def nutrient_analysis_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["nutrient_analysis_agent"],
            llm=llm,
            verbose=True,
        )

    @agent
    def recipe_suggestion_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["recipe_suggestion_agent"],
            llm=llm,
            verbose=True,
        )

    @agent
    def ingredient_sourcing_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["ingredient_sourcing_agent"],
            llm=llm,
            verbose=True,
        )

    @task
    def ingredient_detection_task(self) -> Task:
        return Task(config=self.tasks_config["ingredient_detection_task"])

    @task
    def dietary_filtering_task(self) -> Task:
        return Task(config=self.tasks_config["dietary_filtering_task"])

    @task
    def nutrient_analysis_task(self) -> Task:
        return Task(
            config=self.tasks_config["nutrient_analysis_task"],
            output_pydantic=NutritionalAnalysisOutput,
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=[
                self.ingredient_detection_agent(),
                self.dietary_filtering_agent(),
                self.nutrient_analysis_agent(),
            ],
            tasks=[
                self.ingredient_detection_task(),
                self.dietary_filtering_task(),
                self.nutrient_analysis_task(),
            ],
            process=Process.sequential,
            verbose=True,
        )