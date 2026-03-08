"""
config/settings.py
------------------
Centralised configuration — all constants and environment variables
are loaded here and imported by every other module.
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv(override=True)

# ── Azure / Foundry ────────────────────────────────────────────────────────────
APPLICATIONINSIGHTS_CONNECTION_STRING: str = os.getenv(
    "APPLICATIONINSIGHTS_CONNECTION_STRING", ""
)
FOUNDRY_GATEWAY_URL: str = os.getenv(
    "FOUNDRY_AGENT_URL",
    "",
)
ASSISTANT_ID: str = os.getenv(
    "ASSISTANT_ID",
    "",
)

# ── Local dev ──────────────────────────────────────────────────────────────────
LOCAL_URL: str = os.getenv("LOCAL_URL", "http://127.0.0.1:8000")

# ── Prompt governance ─────────────────────────────────────────────────────────
PROMPT_ASSET_NAME: str = os.getenv("PROMPT_ASSET_NAME", "weather-system-prompt")
DEFAULT_PROMPT_VERSION: str = os.getenv("PROMPT_VERSION", "v1")

# ── Debug ─────────────────────────────────────────────────────────────────────
DEBUG_RAW_MESSAGES: bool = os.getenv("DEBUG_RAW_MESSAGES", "false").lower() == "true"

# ── File paths ────────────────────────────────────────────────────────────────
# Always land next to the project root (one level up from this file)
PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET_PATH: str = os.path.join(PROJECT_ROOT, "weather_eval_dataset.jsonl")
RESULTS_PATH: str = os.path.join(PROJECT_ROOT, "weather_eval_results.json")
CUSTOM_RESULTS_PATH: str = os.path.join(PROJECT_ROOT, "weather_custom_eval_results.json")

# ── Prompt registry ───────────────────────────────────────────────────────────
PROMPTS: dict[str, dict] = {
    "v1": {
        "system": (
            "You are a weather assistant. "
            "Answer concisely and provide temperatures in Celsius."
        )
    },
    "v2": {
        "system": (
            "You are an expert meteorologist. "
            "Provide a detailed forecast including temperature, "
            "humidity, wind speed, and a short explanation of conditions."
        )
    },
    "compare-analyst": {
        "system": (
            "You are a comparative weather analyst. "
            "When multiple cities are mentioned, compare them clearly "
            "using bullet points or a table."
        )
    },
}

# ── Test questions + ground truth ─────────────────────────────────────────────
QUESTIONS: list[dict] = [
    {
        "query": "What is the weather in Dubai?",
        "ground_truth": "Dubai is sunny with a temperature of 38°C and low humidity.",
    },
    {
        "query": "Give me a 3-day forecast for London.",
        "ground_truth": (
            "London will be cloudy with rain expected over the next 3 days, "
            "temperatures around 14°C."
        ),
    },
    {
        "query": "Compare the weather in Tokyo and Sydney.",
        "ground_truth": "Tokyo is partly cloudy at 22°C while Sydney is sunny at 26°C.",
    },
]


def get_prompt(prompt_version: str) -> dict:
    """Return the prompt dict for the given version, raising on unknown versions."""
    if prompt_version not in PROMPTS:
        raise ValueError(
            f"Unknown prompt version '{prompt_version}'. "
            f"Available: {list(PROMPTS.keys())}"
        )
    return PROMPTS[prompt_version]
