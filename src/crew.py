import os
from pathlib import Path
from crewai import LLM, Agent, Crew, Process, Task
from dotenv import load_dotenv
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml

from src.tools import (
    ChefSearchTool,
    IngredientVisionTool,
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
  groq_api_key: SecretStr | None = None
  gemini_api_key: SecretStr | None = None
  google_api_key: SecretStr | None = None
  serper_api_key: SecretStr | None = None
  database_url: SecretStr | None = None

  model_config = SettingsConfigDict(
      env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"
  )


config = Settings()

# Service keys go to the environment, where LiteLLM and the provider SDKs
# look for them. A user's own key is never put there: it is passed to that
# user's LLM and vision tool only.
for env_name in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
  secret = getattr(config, env_name.lower())
  if secret:
    os.environ[env_name] = secret.get_secret_value()
if os.getenv("GOOGLE_API_KEY") and not os.getenv("GEMINI_API_KEY"):
  os.environ["GEMINI_API_KEY"] = os.environ["GOOGLE_API_KEY"]

# One model per provider, each overridable from the environment.
PROVIDER_MODELS = {
    "groq": os.getenv("GROQ_MODEL", "groq/openai/gpt-oss-120b"),
    "gemini": os.getenv("GEMINI_MODEL", "gemini/gemini-3.5-flash-lite"),
    "anthropic": os.getenv("ANTHROPIC_MODEL", "anthropic/claude-haiku-4-5-20251001"),
    "openai": os.getenv("OPENAI_MODEL", "openai/gpt-4o-mini"),
}
# First match wins, so "sk-ant-" must come before "sk-".
KEY_PREFIXES = [
    ("gsk_", "groq"),
    ("AIza", "gemini"),
    ("AQ.", "gemini"),
    ("sk-ant-", "anthropic"),
    ("sk-", "openai"),
]
# Free service pool, used when the user gives no key: Groq first, Gemini if
# Groq fails (quota, outage).
FREE_POOL = [("groq", "GROQ_API_KEY"), ("gemini", "GEMINI_API_KEY")]
VISION_PROVIDERS = {"gemini", "anthropic"}


def key_provider(user_key: str | None) -> str | None:
  """Provider of a user's key from its prefix, or None for an empty key.

  Raises ValueError for a key whose prefix is not recognized.
  """
  user_key = (user_key or "").strip()
  if not user_key:
    return None
  for prefix, provider in KEY_PREFIXES:
    if user_key.startswith(prefix):
      return provider
  raise ValueError("Unrecognized API key prefix.")


GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def make_llm(provider: str, api_key: str | None) -> LLM:
  model = PROVIDER_MODELS[provider]
  if provider == "groq":
    # Groq goes through CrewAI's native OpenAI client on Groq's OpenAI
    # compatible endpoint. On the LiteLLM route, CrewAI leaves its
    # cache_breakpoint flag in the messages and Groq rejects the request.
    return LLM(
        model=f"openai/{model.removeprefix('groq/')}", custom_openai=True,
        base_url=GROQ_BASE_URL, api_key=api_key, temperature=0.2,
    )
  return LLM(model=model, api_key=api_key, temperature=0.2)


def get_llm_from_user_key(user_key: str | None) -> list[LLM]:
  """LLMs to try, in order, for this request.

  With a key, only that provider's model. Without one, the free pool
  (Groq, then Gemini), limited to the providers that have a service key.
  """
  provider = key_provider(user_key)
  if provider:
    return [make_llm(provider, user_key.strip())]
  return [make_llm(name, os.getenv(env)) for name, env in FREE_POOL if os.getenv(env)]


def vision_tool_for(user_key: str | None) -> IngredientVisionTool:
  """Vision on the user's key when it is a Gemini or Anthropic key (the
  providers used here for images), otherwise VISION_MODEL on service keys."""
  provider = key_provider(user_key)
  if provider in VISION_PROVIDERS:
    return IngredientVisionTool(model=PROVIDER_MODELS[provider], api_key=user_key.strip())
  return IngredientVisionTool(model=os.getenv("VISION_MODEL", PROVIDER_MODELS["gemini"]))


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

# Agent and crew logs are off by default. Set CREW_VERBOSE=1 to debug.
VERBOSE = os.getenv("CREW_VERBOSE") == "1"

# Task names, used by app.py to find each output regardless of how many
# tasks actually ran.
RECIPE_TASK = "suggest_heritage_recipe_task"
SOURCING_TASK = "source_ingredients_task"
MEAL_ANALYSIS_TASK = "analyze_meal_task"

# The vision tool is added per crew (vision_tool_for), since it may carry
# the user's key.
AGENT_TOOLS = {
    "ingredient_detection_agent": [filter_ingredients_list],
    "dietary_filtering_agent": [filter_based_on_dietary_restrictions],
    "recipe_suggestion_agent": [search_tunisian_recipes_tool],
}


def make_agent(name: str, llm: LLM, extra_tools=()) -> Agent:
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
      self, llm: LLM, image_data="None", manual_ingredients="None",
      recipe_style=CLASSIC_STYLE, user_key=None,
  ):
    self.llm = llm
    self.image_data = image_data
    self.manual_ingredients = manual_ingredients
    self.recipe_style = recipe_style
    self.user_key = user_key

  def crew(self) -> Crew:
    agents = []
    tasks = []

    # Vision only runs when there are photos. Typed ingredients go straight to
    # the dietary filter through {manual_input}, and with neither (dish picked
    # from the menu) there is nothing to filter.
    filter_task = None
    if _is_set(self.image_data):
      detect_agent = make_agent(
          "ingredient_detection_agent", self.llm, [vision_tool_for(self.user_key)]
      )
      agents.append(detect_agent)
      tasks.append(make_task("detect_ingredients_task", detect_agent))
    if _is_set(self.image_data) or _is_set(self.manual_ingredients):
      filter_agent = make_agent("dietary_filtering_agent", self.llm)
      agents.append(filter_agent)
      filter_task = make_task("filter_dietary_task", filter_agent)
      tasks.append(filter_task)

    # Classic mode keeps the chef on the Neon RAG tool only, for speed.
    use_web = self.recipe_style != CLASSIC_STYLE and WEB_SEARCH_AVAILABLE
    chef = make_agent(
        "recipe_suggestion_agent", self.llm,
        extra_tools=[web_search_tool()] if use_web else [],
    )
    sourcer = make_agent("ingredient_sourcing_agent", self.llm)

    recipe_task = make_task(
        RECIPE_TASK, chef, context=[filter_task] if filter_task else []
    )
    # Sourcing only needs the recipe, not the whole history. Nutrition is
    # computed in Python by app.py (src/nutrition.py), without an LLM call.
    sourcing_task = make_task(SOURCING_TASK, sourcer, context=[recipe_task])

    return Crew(
        agents=agents + [chef, sourcer],
        tasks=tasks + [recipe_task, sourcing_task],
        process=Process.sequential,
        verbose=VERBOSE,
    )


class NourishBotAnalysisCrew:

  def __init__(self, llm: LLM, image_data="None", manual_ingredients="None", user_key=None):
    self.llm = llm
    self.image_data = image_data
    self.manual_ingredients = manual_ingredients
    self.user_key = user_key

  def crew(self) -> Crew:
    agents = []
    tasks = []

    # Typed ingredients reach the analysis through {manual_input}; vision only
    # runs when there are photos.
    if _is_set(self.image_data):
      detect_agent = make_agent(
          "ingredient_detection_agent", self.llm, [vision_tool_for(self.user_key)]
      )
      agents.append(detect_agent)
      tasks.append(make_task("detect_ingredients_task", detect_agent))

    nutritionist = make_agent("nutrient_analysis_agent", self.llm)
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
