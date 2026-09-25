---
title: CarthageKitchen AI
emoji: 🇹🇳
colorFrom: amber
colorTo: red
sdk: gradio
sdk_version: 5.12.0
app_file: app.py
pinned: false
license: mit
---

# 🇹🇳 CarthageKitchen-AI — Autonomous Culinary Studio & Health Coach

CarthageKitchen-AI is a multi-agent culinary and clinical nutrition platform designed to bridge authentic Tunisian gastronomy with modern dietary management and localized grocery sourcing in Canada (**Ottawa/Gatineau** and **Montreal**).

The platform accepts photos of pantry/fridge items or dish images, detects ingredients, respects clinical restrictions, suggests authentic recipes with cultural precision (e.g., proper *techwih* spice blooming technique), maps out local specialty grocers, and delivers detailed metabolic diagnostics.

---

##  Key Capabilities

- **Multimodal Ingredient & Meal Parsing:** Processes uploaded images (fridge, countertop, or prepared dishes) alongside free-form text ingredients.
- **Cultural Culinary Grounding:** Preserves authentic Tunisian flavor profiles, caraway-to-coriander ratios, and healthier contemporary techniques (e.g., roasted variations of traditional classics).
- **Localized Specialty Sourcing:** Suggests verified Mediterranean and Middle Eastern markets across Ottawa/Gatineau and Montreal for hard-to-find ingredients, paired with common supermarket alternatives.
- **Clinical & Metabolic Profiling:** Estimates calorie load, portion sizing, macronutrient splits, glycemic considerations, and sodium levels.
- **Provider-Agnostic LLM Routing:** Built for flexible deployment supporting free-tier inference (e.g., Google Gemini Flash, Groq) or Bring-Your-Own-Key (BYOK) for proprietary models.
- **Printable Recipe Cards:** Clean, dedicated print stylesheets optimized for direct browser printing and PDF generation without UI clutter.

---

##  Multi-Agent Architecture (CrewAI)

The system leverages sequential agent pipelines orchestrated via **CrewAI**:

```
[User Input: Images / Ingredients / Dish Selection]
                        │
                        ▼
         ┌──────────────────────────────┐
         │  Ingredient Detection Agent  │  (Multimodal Vision + OCR)
         └──────────────┬───────────────┘
                        │
                        ▼
         ┌──────────────────────────────┐
         │   Dietary Filtering Agent    │  (Gluten-free, Low-GI, Sodium guardrails)
         └──────────────┬───────────────┘
                        │
         ┌──────────────┴───────────────┐
         │                             │
         ▼                             ▼
[Recipe Studio Workflow]      [Clinical Assessment Workflow]
         │                             │
         ▼                             ▼
┌─────────────────────────┐   ┌───────────────────────────┐
│   Tunisian Chef Agent   │   │ Clinical Nutrition Agent  │
│  (Structured Recipes)   │   │  (Pydantic Macro Splits)  │
└────────────┬────────────┘   └───────────────────────────┘
             │
             ▼
┌─────────────────────────┐
│ Local Sourcing Agent    │
│ (Ottawa/Montreal Map)   │
└─────────────────────────┘
```

---

##  Tech Stack

- **Orchestration:** [CrewAI](https://github.com/crewAIInc/crewAI)
- **User Interface:** [Gradio](https://gradio.app/) with customized print/PDF stylesheets
- **Model Layer:** Model-agnostic multimodal routing via [LiteLLM](https://github.com/BerriAI/litellm) (supporting Gemini, Anthropic, Groq, and OpenAI)
- **Data Validation & Settings:** [Pydantic v2](https://docs.pydantic.dev/) and `pydantic-settings`
- **Package Management:** `uv` / `pip`

---

##  Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/alouiyaz78/CarthageKitchen-AI.git
cd CarthageKitchen-AI
```

### 2. Set Up Environment Variables

Create a `.env` file in the project root or inside `src/`:

```env
# Primary Model Provider
MODEL_NAME=anthropic/claude-haiku-4-5-20251001

# API Keys (Provide according to your active provider)
ANTHROPIC_API_KEY=your_anthropic_key_here
# GEMINI_API_KEY=your_gemini_api_key_here
# GROQ_API_KEY=your_groq_key_here

# Search API for local market resolution (Optional)
SERPER_API_KEY=your_serper_key_here
```

### 3. Installation & Local Run

Using `uv`:
```bash
uv sync
uv run app.py
```

Using standard `pip`:
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open your browser and navigate to `http://localhost:7860`.

---

##  Repository Structure

```text
CarthageKitchen-AI/
├── app.py                     # Gradio interface & execution handlers
├── requirements.txt           # Project dependencies
├── README.md                  # Project documentation
├── src/
│   ├── .env                   # Environment secrets (ignored by Git)
│   ├── crew.py                # Crew definitions, settings, and agent workflows
│   ├── models.py              # Pydantic data schemas
│   ├── tools.py               # Custom vision and filtering tools
│   └── config/
│       ├── agents.yaml        # Agent personas and roles
│       └── tasks.yaml         # Task prompts and expected outputs
```

---



---

## 📄 License

Distributed under the MIT License. See `LICENSE` for details.
