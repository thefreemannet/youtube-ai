"""Agent pipeline for dashboard-triggered jobs, preserving app/workflow.py."""
import asyncio
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.agents import run_agent
from app.categories import category_info, normalize_category

ROOT = Path(os.environ.get("J3G_ROOT", "/opt/j3g-youtube-ai"))
JOBS = ROOT / "data" / "jobs"


# The script model sometimes renames a protocol the operator typed.
# BACnet is the usual case: the narration comes back as BASnet.
TERM_GUARDS = (
    (re.compile(r"bacnet", re.IGNORECASE), re.compile(r"bas[\s-]?net", re.IGNORECASE), "BACnet"),
)


def spoken_language(value):
    return "es" if str(value or "").strip().lower() == "es" else "en"


def spoken_words(text):
    return [word for word in str(text or "").split() if word]


def script_needs_expansion(text):
    """A natural reading of fewer than 160 words lasts under a minute."""
    return len(spoken_words(text)) < 160


def _picture_line(picture):
    text = " ".join(str(picture or "").split())
    if not text:
        return ""
    return (
        "The operator uploaded a picture. The video explains what that picture shows. "
        "Do not switch to a different subject. "
        "What the picture shows: " + text + " "
    )


def expand_script_prompt(topic, script, language, category="hvac", picture=""):
    language = spoken_language(language)
    info = category_info(category)
    if language == "es":
        opening = (
            "The operator wrote a short script. Expand it into 160 to 190 words of spoken narration "
            "in clear Latin American Spanish so it lasts more than one minute. "
            "Keep the same idea, the same facts, and the same order. Do not change the subject. "
            "Do not stop before 160 words. Return only the spoken Spanish narration in the result field. "
            "Keep equipment abbreviations and protocol names exactly as they appear. "
            "Do not translate BACnet. "
        )
    else:
        opening = (
            "The operator wrote a short script. Expand it into 160 to 190 words of spoken narration "
            "in English so it lasts more than one minute. "
            "Keep the same idea, the same facts, and the same order. Do not change the subject. "
            "Do not stop before 160 words. Return only the spoken narration in the result field. "
        )
    if info["id"] == "hvac":
        subject = (
            "If the topic says BACnet or bacnet, write BACnet every time. "
            "Never write BASnet, BASNet, or another spelling, and do not describe BACnet "
            "as a different protocol or as a Honeywell product. "
        )
    else:
        subject = (
            "The audience is " + info["audience"] + ". "
            "Stay on this subject. Do not turn the video into an HVAC, controls, BAS, or EMS lesson "
            "unless the topic itself is about that. "
            + info["script_note"] + " "
        )
    subject += _picture_line(picture)
    return (
        opening +
        "Do not include headings, stage directions or citations. "
        + subject +
        "Topic: " + topic +
        "\nOperator script:\n" + script
    )


def scriptwriter_prompt(topic, research_text, language, category="hvac", picture=""):
    language = spoken_language(language)
    info = category_info(category)
    if language == "es":
        opening = (
            "Write 160 to 190 words of original spoken narration in clear Latin American Spanish. "
            "Read aloud at a natural pace, this must last at least 60 seconds, and it may run longer. "
            "Do not stop before 160 words. Return only the spoken Spanish narration in the result field. "
            "Keep equipment abbreviations and protocol names exactly as they appear in the topic. "
            "Do not translate BACnet. "
        )
    else:
        opening = (
            "Write 160 to 190 words of original spoken narration in English. "
            "Read aloud at a natural pace, this must last at least 60 seconds, and it may run longer. "
            "Do not stop before 160 words. Return only the spoken narration in the result field. "
        )
    if info["id"] == "hvac":
        subject = (
            "If the topic says BACnet or bacnet, write BACnet every time. "
            "Never write BASnet, BASNet, or another spelling, and do not describe BACnet "
            "as a different protocol or as a Honeywell product. "
        )
    else:
        subject = (
            "The audience is " + info["audience"] + ". "
            "Stay on this subject. Do not turn the video into an HVAC, controls, BAS, or EMS lesson "
            "unless the topic itself is about that. "
            + info["script_note"] + " "
        )
    subject += _picture_line(picture)
    return (
        opening +
        "Do not include headings, stage directions or citations. "
        "Spell technical names exactly as they appear in the topic. "
        + subject +
        "Topic: " + topic +
        "\nResearch background:\n" + research_text
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
    try:
        with (folder / "worker.log").open("a", encoding="utf-8") as log:
            log.write(f"{existing['updated_utc']} {status}\n")
    except OSError:
        pass


async def create_video_draft(topic, job_id=None, language=None, category=None):
    if job_id is None:
        job_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    if not re.fullmatch(r"\d{8}-\d{6}-[a-f0-9]{6}", job_id):
        raise ValueError("Invalid job ID")
    folder = JOBS / job_id
    folder.mkdir(parents=True, exist_ok=True)
    stored = {}
    if (folder / "job.json").is_file():
        try:
            stored = json.loads((folder / "job.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
    if language is None:
        language = stored.get("language")
    if category is None:
        category = stored.get("category")
    language = spoken_language(language)
    category = normalize_category(category)
    info = category_info(category)
    audience = info["audience"]
    supplied = " ".join(str(stored.get("supplied_script") or "").split())
    picture = " ".join(str(stored.get("picture_subject") or "").split())
    if not picture and (folder / "source_picture.jpg").is_file():
        from app.picture_subject import describe_picture
        picture = describe_picture(folder / "source_picture.jpg")
        stored["picture_subject"] = picture
    if supplied and not script_needs_expansion(supplied):
        narration = preserve_topic_terms(topic, supplied)
        (folder / "narration.txt").write_text(narration + "\n", encoding="utf-8")
        save_stage(
            folder,
            "AWAITING_HUMAN_REVIEW",
            job_id=job_id,
            topic=topic,
            language=language,
            category=category,
            **({"picture_subject": picture} if picture else {}),
            quality={
                "agent": "quality",
                "status": "completed",
                "result": "APPROVE_FOR_HUMAN_REVIEW. The operator supplied this script.",
            },
        )
        print("SUPPLIED SCRIPT IS LONG ENOUGH. NOT REWRITTEN.", flush=True)
        return job_id
    if supplied:
        save_stage(
            folder,
            "SCRIPTWRITING",
            job_id=job_id,
            topic=topic,
            language=language,
            category=category,
            **({"picture_subject": picture} if picture else {}),
        )
        print("SHORT SCRIPT. EXPANDING PAST ONE MINUTE.", flush=True)
        script = await run_agent(
            "scriptwriter",
            expand_script_prompt(topic, supplied, language, category, picture),
            {"audience": audience, "language": language, "category": info["label"]},
        )
        narration = preserve_topic_terms(topic, validate_agent("scriptwriter", script))
        research_text = supplied
    else:
        if picture:
            research_text = picture
            save_stage(folder, "SCRIPTWRITING", job_id=job_id, topic=topic, language=language, category=category, picture_subject=picture)
            print("PICTURE SUBJECT. WRITING THE VIDEO ABOUT THAT PICTURE.", flush=True)
            script = await run_agent(
                "scriptwriter",
                scriptwriter_prompt(topic, research_text, language, category, picture),
                {"audience": audience, "language": language, "category": info["label"]},
            )
            narration = preserve_topic_terms(topic, validate_agent("scriptwriter", script))
        else:
            research_task = (
                "Prepare background knowledge for an educational video of at least 60 seconds about: " + topic +
                ". The audience is " + audience + ". Provide essential concepts and cautions. "
            )
            if category != "hvac":
                research_task += "Stay on this subject. Do not recast it as an HVAC, controls, BAS, or EMS lesson. "
            if info["script_note"]:
                research_task += info["script_note"] + " "
            research_task += "You have no live web search. Do not invent sources."
            save_stage(folder, "RESEARCHING", job_id=job_id, topic=topic, language=language, category=category)
            print(f"JOB: {job_id}; [1/3] Research Agent", flush=True)
            research = await run_agent(
                "research",
                research_task,
                {"audience": audience, "category": info["label"]},
            )
            research_text = validate_agent("research", research)
            save_stage(folder, "SCRIPTWRITING", research=research)
            print("[2/3] Scriptwriting Agent", flush=True)
            script = await run_agent(
                "scriptwriter",
                scriptwriter_prompt(topic, research_text, language, category),
                {"audience": audience, "language": language, "category": info["label"]},
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
        "independent verification. If the narration is in Spanish, review that Spanish text. "
        "Give exactly one recommendation: "
        "APPROVE_FOR_HUMAN_REVIEW or REVISE, and explain why. "
        "Keep that recommendation token in English. "
        "The category is " + info["label"] + ". "
        "Review this narration for that category.\n\n" + narration,
        {"research_background": research_text, "category": info["label"]},
    )
    validate_agent("quality", quality)
    save_stage(folder, "AWAITING_HUMAN_REVIEW", quality=quality)
    print("AGENT DRAFT COMPLETED. HUMAN REVIEW STILL REQUIRED.", flush=True)
    return job_id


if __name__ == "__main__":
    asyncio.run(create_video_draft("What is BACnet and how does it help HVAC technicians?"))
