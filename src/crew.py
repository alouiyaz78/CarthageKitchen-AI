import os
from pathlib import Path
from typing import List, Optional
from crewai import LLM, Agent, Crew, Process, Task
from dotenv import load_dotenv
from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml

from src.tools import (
    extract_ingredients_from_image_and_text,
    filter_based_on_dietary_restrictions,
    filter_ingredients_list,
    search_tunisian_recipes_tool,
)

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

ENV_FILE = CURRENT_DIR / ".env"
if not ENV_FILE.exists():
  ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=ENV_FILE, override=True)

CONFIG_DIR = CURRENT_DIR / "config"
with open(CONFIG_DIR / "agents.yaml", "r", encoding="utf-8") as f:
  AGENTS_CONFIG = yaml.safe_load(f)

with open(CONFIG_DIR / "tasks.yaml", "r", encoding="utf-8") as f:
  TASKS_CONFIG = yaml.safe_load(f)


class Settings(BaseSettings):
  anthropic_api_key: SecretStr | None = None
  serper_api_key: SecretStr | None = None
  database_url: SecretStr | None = None

  model_config = SettingsConfigDict(
      env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"
  )


config = Settings()
api_key = (
    config.anthropic_api_key.get_secret_value()
    if config.anthropic_api_key
    else os.getenv("ANTHROPIC_API_KEY")
)

if not api_key:
  raise RuntimeError("ANTHROPIC_API_KEY introuvable.")

os.environ["ANTHROPIC_API_KEY"] = api_key

llm = LLM(
    model="anthropic/claude-haiku-4-5-20251001",
    api_key=api_key,
    temperature=0.2,
)


class NourishBotRecipeCrew:

  def __init__(
      self,
      image_data="None",
      manual_ingredients="None",
      dietary_restrictions="None",
      target_city="Ottawa / Gatineau",
      selected_dish="Auto-detect / Recipe from my ingredients",
      user_cravings="None",
  ):
    self.image_data = image_data
    self.manual_ingredients = manual_ingredients
    self.dietary_restrictions = dietary_restrictions
    self.target_city = target_city
    self.selected_dish = selected_dish
    self.user_cravings = user_cravings

  def ingredient_detection_agent(self) -> Agent:
    return Agent(
        config=AGENTS_CONFIG["ingredient_detection_agent"],
        tools=[
            extract_ingredients_from_image_and_text,
            filter_ingredients_list,
        ],
        llm=llm,
        verbose=True,
    )

  def dietary_filtering_agent(self) -> Agent:
    return Agent(
        config=AGENTS_CONFIG["dietary_filtering_agent"],
        tools=[filter_based_on_dietary_restrictions],
        llm=llm,
        verbose=True,
    )

  def recipe_suggestion_agent(self) -> Agent:
    return Agent(
        config=AGENTS_CONFIG["recipe_suggestion_agent"],
        tools=[search_tunisian_recipes_tool],
        llm=llm,
        verbose=True,
    )

  def ingredient_sourcing_agent(self) -> Agent:
    return Agent(
        config=AGENTS_CONFIG["ingredient_sourcing_agent"],
        llm=llm,
        verbose=True,
    )

  def nutrient_analysis_agent(self) -> Agent:
    return Agent(
        config=AGENTS_CONFIG["nutrient_analysis_agent"],
        llm=llm,
        verbose=True,
    )

  def crew(self) -> Crew:
    agent_detect = self.ingredient_detection_agent()
    agent_filter = self.dietary_filtering_agent()
    agent_chef = self.recipe_suggestion_agent()
    agent_source = self.ingredient_sourcing_agent()
    agent_nutri = self.nutrient_analysis_agent()

    task1 = Task(
        config=TASKS_CONFIG["detect_ingredients_task"], agent=agent_detect
    )
    task2 = Task(config=TASKS_CONFIG["filter_dietary_task"], agent=agent_filter)
    task3 = Task(
        config=TASKS_CONFIG["suggest_heritage_recipe_task"], agent=agent_chef
    )
    task4 = Task(
        config=TASKS_CONFIG["source_ingredients_task"], agent=agent_source
    )
    task5 = Task(
        config=TASKS_CONFIG["analyze_nutrition_task"], agent=agent_nutri
    )

    return Crew(
        agents=[agent_detect, agent_filter, agent_chef, agent_source, agent_nutri],
        tasks=[task1, task2, task3, task4, task5],
        process=Process.sequential,
        verbose=True,
    )


class NourishBotAnalysisCrew:

  def __init__(
      self,
      image_data=None,
      manual_ingredients=None,
      dietary_restrictions="None",
  ):
    self.image_data = image_data
    self.manual_ingredients = manual_ingredients
    self.dietary_restrictions = dietary_restrictions

  def nutrient_analysis_agent(self) -> Agent:
    return Agent(
        config=AGENTS_CONFIG["nutrient_analysis_agent"],
        llm=llm,
        verbose=True,
    )

  def crew(self) -> Crew:
    agent_nutri = self.nutrient_analysis_agent()
    task = Task(
        config=TASKS_CONFIG["analyze_nutrition_task"], agent=agent_nutri
    )
    return Crew(
        agents=[agent_nutri],
        tasks=[task],
        process=Process.sequential,
        verbose=True,
    )