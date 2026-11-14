"""Agent pipeline for dashboard-triggered jobs, preserving app/workflow.py."""
import asyncio
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.agents import run_agent

ROOT = Path(os.environ.get("J3G_ROOT", "/opt/j3g-youtube-ai"))
JOBS = ROOT / "data" / "jobs"


# The script model sometimes renames a protocol the operator typed.
# BACnet is the usual case: the narration comes back as BASnet.
TERM_GUARDS = (
    (re.compile(r"bacnet", re.IGNORECASE), re.compile(r"bas[\s-]?net", re.IGNORECASE), "BACnet"),
)


def preserve_topic_terms(topic, narration):
    """Keep protocol names spelled the way the topic requested."""
    text = narration
    for topic_pattern, wrong_pattern, canonical in TERM_GUARDS:
        if topic_pattern.search(topic or ""):
            text = wrong_pattern.sub(canonical, text)
    return text


def validate_agent(name, response):
    if not isinstance(response, dict) or response.get("agent") != name:
        raise ValueError(f"{name}: invalid agent response")
    if response.get("status") != "completed":
        raise ValueError(f"{name}: agent did not complete")
    result = response.get("result")
    if not isinstance(result, str) or not result.strip():
        raise ValueError(f"{name}: empty or malformed result")
    return result.strip()


def save_stage(folder, status, **fields):
    path = folder / "job.json"
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    existing.update(fields)
    existing["status"] = status
    existing["updated_utc"] = datetime.now(timezone.utc).isoformat()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


async def create_video_draft(topic, job_id=None):
    if job_id is None:
        job_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    if not re.fullmatch(r"\d{8}-\d{6}-[a-f0-9]{6}", job_id):
        raise ValueError("Invalid job ID")
    folder = JOBS / job_id
    folder.mkdir(parents=True, exist_ok=True)
    save_stage(folder, "RESEARCHING", job_id=job_id, topic=topic)
    print(f"JOB: {job_id}; [1/3] Research Agent", flush=True)
    research = await run_agent(
        "research",
        "Prepare background knowledge for a 60-second educational video about: " + topic +
        ". Provide essential concepts and technical cautions. "
        "You have no live web search. Do not invent sources.",
        {"audience": "HVAC technicians and beginners"},
    )
    research_text = validate_agent("research", research)
    save_stage(folder, "SCRIPTWRITING", research=research)
    print("[2/3] Scriptwriting Agent", flush=True)
    script = await run_agent(
        "scriptwriter",
        "Write approximately 120-145 words of original spoken narration for a 60-second "
        "educational YouTube video. Return only the spoken narration in the result field. "
        "Do not include headings, stage directions or citations. "
        "Spell technical names exactly as they appear in the topic. "
        "If the topic says BACnet or bacnet, write BACnet every time. "
        "Never write BASnet, BASNet, or another spelling, and do not describe BACnet "
        "as a different protocol or as a Honeywell product. Topic: " + topic +
        "\nResearch background:\n" + research_text,
        {"audience": "HVAC technicians and beginners"},
    )
    narration = preserve_topic_terms(topic, validate_agent("scriptwriter", script))
    save_stage(folder, "QUALITY_REVIEW", script={"agent": "scriptwriter", "status": "completed", "result": narration})
    (folder / "narration.txt").write_text(narration + "\n", encoding="utf-8")
    print("[3/3] Quality Agent", flush=True)
    quality = await run_agent(
        "quality",
        "Review the following educational video narration. "
        "Identify unsupported technical claims, confusing explanations, factual concerns "
        "and originality risks. You have no external fact-checking tools; do not claim "
        "independent verification. Give exactly one recommendation: "
        "APPROVE_FOR_HUMAN_REVIEW or REVISE, and explain why.\n\n" + narration,
        {"research_background": research_text},
    )
    validate_agent("quality", quality)
    save_stage(folder, "AWAITING_HUMAN_REVIEW", quality=quality)
    print("AGENT DRAFT COMPLETED. HUMAN REVIEW STILL REQUIRED.", flush=True)
    return job_id


if __name__ == "__main__":
    asyncio.run(create_video_draft("What is BACnet and how does it help HVAC technicians?"))
