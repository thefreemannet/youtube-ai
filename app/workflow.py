import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.agents import run_agent

ROOT = Path(__file__).resolve().parent.parent
JOBS = ROOT / "data" / "jobs"


def validate_agent(name, response):
    if not isinstance(response, dict):
        raise ValueError(f"{name}: invalid response")

    if response.get("agent") != name:
        raise ValueError(f"{name}: agent mismatch")

    if response.get("status") != "completed":
        raise ValueError(f"{name}: task not completed")

    result = response.get("result")

    if not isinstance(result, str) or not result.strip():
        raise ValueError(f"{name}: empty result")

    return result.strip()


async def create_video_draft(topic):
    job_id = (
        datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        + "-" + uuid.uuid4().hex[:6]
    )

    folder = JOBS / job_id
    folder.mkdir(parents=True, exist_ok=True)

    print(f"\nJOB: {job_id}", flush=True)

    # Agent 1: Research
    print("\n[1/3] Research Agent running...", flush=True)

    research = await run_agent(
        "research",
        "Prepare background knowledge for a 60-second "
        "educational video about: " + topic +
        ". Provide essential concepts and technical cautions. "
        "You have no live web search. Do not invent sources.",
        {"audience": "HVAC technicians and beginners"}
    )

    research_text = validate_agent("research", research)

    # Agent 2: Scriptwriter
    print("[2/3] Scriptwriting Agent running...", flush=True)

    script = await run_agent(
        "scriptwriter",
        "Write approximately 120-145 words of original spoken "
        "narration for a 60-second educational YouTube video. "
        "Return only the spoken narration in the result field. "
        "Do not include headings, stage directions or citations. "
        "Topic: " + topic +
        "\nResearch background:\n" + research_text,
        {"audience": "HVAC technicians and beginners"}
    )

    narration = validate_agent("scriptwriter", script)

    # Agent 3: Quality
    print("[3/3] Quality Agent running...", flush=True)

    quality = await run_agent(
        "quality",
        "Review the following educational video narration. "
        "Identify unsupported technical claims, confusing "
        "explanations, factual concerns and originality risks. "
        "You have no external fact-checking tools. "
        "Do not claim independent verification. "
        "Recommend APPROVE_FOR_HUMAN_REVIEW or REVISE "
        "and explain why.\n\n" + narration,
        {"research_background": research_text}
    )

    quality_text = validate_agent("quality", quality)

    # Save all intermediate results
    record = {
        "job_id": job_id,
        "topic": topic,
        "status": "AWAITING_HUMAN_REVIEW",
        "research": research,
        "script": script,
        "quality": quality,
        "created_utc": datetime.now(timezone.utc).isoformat()
    }

    (folder / "job.json").write_text(
        json.dumps(record, indent=2),
        encoding="utf-8"
    )

    (folder / "narration.txt").write_text(
        narration + "\n",
        encoding="utf-8"
    )

    print("\n=== WORKFLOW RESULTS ===")
    print("Research: COMPLETED")
    print("Scriptwriting: COMPLETED")
    print("Quality review: COMPLETED")
    print("Word count:", len(narration.split()))
    print("Status: AWAITING_HUMAN_REVIEW")

    print("\n=== NARRATION ===")
    print(narration)

    print("\n=== QUALITY REVIEW ===")
    print(quality_text)

    print("\nSaved to:", folder)
    print("\nWORKFLOW TEST PASSED")


if __name__ == "__main__":
    asyncio.run(
        create_video_draft(
            "What is BACnet and how does it help HVAC technicians?"
        )
    )
