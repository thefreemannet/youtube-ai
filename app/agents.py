import json
import os
import httpx

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://192.168.120.107:11434"
)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")

AGENT_ROLES = {
    "orchestrator": (
        "Coordinate the YouTube business workflow. "
        "Assign tasks, check dependencies, and report failures."
    ),
    "research": (
        "Research educational video topics. Identify the target "
        "audience and distinguish verified facts from assumptions. "
        "Never invent sources or current trends."
    ),
    "scriptwriter": (
        "Write original educational YouTube scripts with a hook, "
        "introduction, main content, and conclusion."
    ),
    "quality": (
        "Evaluate factual accuracy, clarity, originality, and "
        "copyright risks. Identify unsupported statements."
    ),
    "production": (
        "Plan video scenes, narration, visuals, subtitles, "
        "and production requirements."
    ),
    "publishing": (
        "Prepare YouTube titles, descriptions, tags, and "
        "publishing metadata. Never claim an upload occurred."
    ),
    "analytics": (
        "Evaluate channel performance using supplied metrics. "
        "Never invent views, subscribers, or watch time."
    ),
    "revenue": (
        "Analyze business expenses, revenue, and profitability. "
        "Clearly identify estimated or simulated financial data."
    )
}


async def run_agent(agent_name, task, context=None):
    if agent_name not in AGENT_ROLES:
        raise ValueError(f"Unknown agent: {agent_name}")

    system_prompt = f"""
You are the {agent_name} agent in J3G YouTube AI Business.

ROLE:
{AGENT_ROLES[agent_name]}

CONSTITUTION:
1. Perform only your assigned responsibility.
2. Never fabricate facts, sources, or API results.
3. Clearly identify assumptions.
4. Return valid JSON.
5. Report failures instead of inventing success.
6. Follow the supplied context and requirements.

REQUIRED JSON OUTPUT:
{{
  "agent": "{agent_name}",
  "status": "completed",
  "result": "Your detailed response",
  "warnings": []
}}
"""

    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "think": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps({
                    "task": task,
                    "context": context or {}
                })
            }
        ],
        "options": {
            "temperature": 0,
            "num_ctx": 4096
        }
    }

    async with httpx.AsyncClient(timeout=240) as client:
        response = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload
        )
        response.raise_for_status()

    content = response.json()["message"]["content"]
    result = json.loads(content)

    if not isinstance(result, dict):
        raise ValueError("Agent returned invalid JSON structure")

    return result
