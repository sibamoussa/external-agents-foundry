# External Weather Agent Brought into Foundry for Observability 

End-to-end test runner for an **External Agent brought into Microsoft  AI Foundry** . It sends questions to the agent, traces every HTTP call and tool invocation to **Azure Monitor / Foundry Tracing**, and scores responses with built-in (F1, BLEU, ROUGE) and custom (WeatherCompleteness) evaluators.

---


## Project Structure

```
weather_agent/
├── main.py                      # Entry point — run this
├── requirements.txt
├── .env.example                 # Copy to .env and fill in your values
│
├── config/
│   └── settings.py              # All constants, env vars, prompts, questions
│
├── agent/
│   └── client.py                # HTTP client — calls the Foundry agent endpoint
│
├── tracing/
│   ├── setup.py                 # OTel TracerProvider initialisation
│   └── spans.py                 # Tool-call / tool-result span extraction
│
└── evaluators/
    ├── sdk_eval.py              # F1 / BLEU / ROUGE via azure.ai.evaluation
    └── custom_eval.py           # WeatherCompletenessEvaluator (no model needed)
```

---

## Prerequisites



| Requirement | Notes |
|---|---|
| Python 3.10+ | Earlier versions not tested |
| Azure subscription | Required for Foundry and Application Insights |
| Azure CLI logged in | Run `az login` before using gateway mode |
| Application Insights resource | For receiving OTel traces |
| Foundry External agent deployed | The weather agent must be live at your gateway URL. The agent must be registered in foundry as an asset. See link for more information: https://learn.microsoft.com/en-us/azure/foundry/control-plane/register-custom-agent?view=foundry|

---

## Quick Start

### 1. Clone / copy the project

```bash
git clone <your-repo>
cd weather_agent
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate      # macOS / Linux
.venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and set at variables


Find the connection string in:
**Azure Portal → Application Insights → Overview → Connection String**

All other variables have sensible defaults (see `.env.example` for details).

### 5. Log in to Azure (gateway mode only)

```bash
az login
```

---

## Running the Tests

### Basic run (gateway, prompt v1)

```bash
python main.py
```

### Use a different prompt version

```bash
python main.py --prompt-version v2
python main.py --prompt-version compare-analyst
```

Available prompt versions are defined in `config/settings.py`:

| Version | Behaviour |
|---|---|
| `v1` | Concise answers in Celsius (default) |
| `v2` | Detailed forecast — temperature, humidity, wind |
| `compare-analyst` | Side-by-side city comparison in table/bullet format |

### Run against the local LangGraph dev server

```bash
# In one terminal:
langgraph dev

# In another:
python main.py --local
```

### Override the gateway URL

```bash
python main.py --url https://your-apim.azure-api.net/your-agent
```

### Debug mode (print raw agent message payloads)

```bash
python main.py --debug
```

### Skip evaluation (agent calls only)

```bash
python main.py --skip-eval
```

---

## Output Files

| File | Contents |
|---|---|
| `weather_eval_dataset.jsonl` | Input dataset written before SDK evaluation |
| `weather_eval_results.json` | F1, BLEU, ROUGE scores per row + aggregate |
| `weather_custom_eval_results.json` | WeatherCompleteness scores per row + aggregate |

All files are written to the project root directory.

---

## Trace Hierarchy in Foundry

Navigate to **Foundry → Observability → Tracing** (allow ~2 minutes for spans to appear).

```
weather-agent.test-run                  ← root span for the full run
  ├── agent.call                        ← one per question
  │     └── apim.gateway                ← HTTP call to the APIM gateway
  │           ├── tool_call.<name>      ← one per tool the agent invoked
  │           └── tool_result.<name>    ← one per tool result returned
  ├── eval.run                          ← SDK evaluation (F1 / BLEU / ROUGE)
  │     ├── eval.row.1
  │     ├── eval.row.2
  │     └── eval.row.3
  └── custom_eval.run                   ← WeatherCompleteness evaluation
        ├── custom_eval.row.1
        ├── custom_eval.row.2
        └── custom_eval.row.3
```

---

## Customisation

### Add a new prompt version

Edit `config/settings.py` and add an entry to the `PROMPTS` dict:

```python
PROMPTS = {
    ...
    "my-prompt": {
        "system": "You are a ..."
    },
}
```

Then use it with `--prompt-version my-prompt`.

### Add new test questions

Edit the `QUESTIONS` list in `config/settings.py`:

```python
QUESTIONS = [
    {
        "query": "What is the weather in Berlin?",
        "ground_truth": "Berlin is overcast with 8°C.",
    },
    ...
]
```

### Add a new city to the completeness evaluator

Edit `_cities` in `evaluators/custom_eval.py`:

```python
_cities = ["dubai", "london", "tokyo", "sydney", "berlin", "new york"]
```

---

## Troubleshooting

**`EnvironmentError: Missing APPLICATIONINSIGHTS_CONNECTION_STRING`**
→ Make sure your `.env` file exists and contains the connection string.

**`HTTP 401 Unauthorized`**
→ Run `az login` and ensure your account has access to the Foundry resource.

**`HTTP 404 Not Found`**
→ Check that `FOUNDRY_AGENT_URL` and `ASSISTANT_ID` in `.env` are correct.

**Traces not appearing in Foundry**
→ Wait up to 2 minutes. If still missing, confirm the connection string points to the Application Insights resource linked to your Foundry project.

**`ModuleNotFoundError`**
→ Ensure you activated your virtual environment and ran `pip install -r requirements.txt`.
