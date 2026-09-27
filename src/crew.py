import os
from pathlib import Path
from crewai import LLM, Agent, Crew, Process, Task
from dotenv import load_dotenv
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml

from src.tools import (
    ChefSearchTool,
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
  raise RuntimeError("ANTHROPIC_API_KEY is not set.")

os.environ["ANTHROPIC_API_KEY"] = api_key

# Web search for modern chef variants. ChefSearchTool reads the key from the
# environment, so copy it there when it only comes from the .env file.
serper_key = (
    config.serper_api_key.get_secret_value()
    if config.serper_api_key
    else os.getenv("SERPER_API_KEY")
)
if serper_key:
  os.environ["SERPER_API_KEY"] = serper_key
WEB_SEARCH_AVAILABLE = bool(serper_key)

# recipe_style values sent by app.py. Only "classic" runs without web search.
CLASSIC_STYLE = "classic"
COMPARISON_STYLE = "comparison"
RECIPE_STYLES = [CLASSIC_STYLE, "chefs_variants", COMPARISON_STYLE]

llm = LLM(
    model="anthropic/claude-haiku-4-5-20251001",
    api_key=api_key,
    temperature=0.2,
)

# Agent and crew logs are off by default. Set CREW_VERBOSE=1 to debug.
VERBOSE = os.getenv("CREW_VERBOSE") == "1"

# Task names, used by app.py to find each output regardless of how many
# tasks actually ran.
RECIPE_TASK = "suggest_heritage_recipe_task"
SOURCING_TASK = "source_ingredients_task"
NUTRITION_TASK = "analyze_nutrition_task"
MEAL_ANALYSIS_TASK = "analyze_meal_task"

AGENT_TOOLS = {
    "ingredient_detection_agent": [
        extract_ingredients_from_image_and_text,
        filter_ingredients_list,
    ],
    "dietary_filtering_agent": [filter_based_on_dietary_restrictions],
    "recipe_suggestion_agent": [search_tunisian_recipes_tool],
}


def make_agent(name: str, extra_tools=()) -> Agent:
  return Agent(
      config=AGENTS_CONFIG[name],
      tools=AGENT_TOOLS.get(name, []) + list(extra_tools),
      llm=llm,
      verbose=VERBOSE,
  )


def make_task(name: str, agent: Agent, context=None) -> Task:
  kwargs = {"context": context} if context is not None else {}
  return Task(config=TASKS_CONFIG[name], name=name, agent=agent, **kwargs)


def web_search_tool() -> ChefSearchTool:
  # A fresh tool per crew, since the usage count lives on the instance. The
  # tool runs all its queries itself, so one call is enough.
  return ChefSearchTool(max_usage_count=1)


class NourishBotRecipeCrew:

  def __init__(
      self, image_data="None", manual_ingredients="None", recipe_style=CLASSIC_STYLE
  ):
    self.image_data = image_data
    self.manual_ingredients = manual_ingredients
    self.recipe_style = recipe_style

  def crew(self) -> Crew:
    agents = []
    tasks = []

    # Vision only runs when there are photos. Typed ingredients go straight to
    # the dietary filter through {manual_input}, and with neither (dish picked
    # from the menu) there is nothing to filter.
    filter_task = None
    if _is_set(self.image_data):
      detect_agent = make_agent("ingredient_detection_agent")
      agents.append(detect_agent)
      tasks.append(make_task("detect_ingredients_task", detect_agent))
    if _is_set(self.image_data) or _is_set(self.manual_ingredients):
      filter_agent = make_agent("dietary_filtering_agent")
      agents.append(filter_agent)
      filter_task = make_task("filter_dietary_task", filter_agent)
      tasks.append(filter_task)

    # Classic mode keeps the chef on the Neon RAG tool only, for speed.
    use_web = self.recipe_style != CLASSIC_STYLE and WEB_SEARCH_AVAILABLE
    chef = make_agent(
        "recipe_suggestion_agent",
        extra_tools=[web_search_tool()] if use_web else [],
    )
    sourcer = make_agent("ingredient_sourcing_agent")
    nutritionist = make_agent("nutrient_analysis_agent")

    recipe_task = make_task(
        RECIPE_TASK, chef, context=[filter_task] if filter_task else []
    )
    # Sourcing and nutrition only need the recipe, not the whole history.
    sourcing_task = make_task(SOURCING_TASK, sourcer, context=[recipe_task])
    nutrition_task = make_task(
        NUTRITION_TASK, nutritionist, context=[recipe_task]
    )

    return Crew(
        agents=agents + [chef, sourcer, nutritionist],
        tasks=tasks + [recipe_task, sourcing_task, nutrition_task],
        process=Process.sequential,
        verbose=VERBOSE,
    )


class NourishBotAnalysisCrew:

  def __init__(self, image_data="None", manual_ingredients="None"):
    self.image_data = image_data
    self.manual_ingredients = manual_ingredients

  def crew(self) -> Crew:
    agents = []
    tasks = []

    # Typed ingredients reach the analysis through {manual_input}; vision only
    # runs when there are photos.
    if _is_set(self.image_data):
      detect_agent = make_agent("ingredient_detection_agent")
      agents.append(detect_agent)
      tasks.append(make_task("detect_ingredients_task", detect_agent))

    nutritionist = make_agent("nutrient_analysis_agent")
    agents.append(nutritionist)
    tasks.append(make_task(MEAL_ANALYSIS_TASK, nutritionist))

    return Crew(
        agents=agents,
        tasks=tasks,
        process=Process.sequential,
        verbose=VERBOSE,
    )


def _is_set(value) -> bool:
  return bool(value) and value != "None"
