"""Daily HVAC, controls, BAS, and EMS videos waiting for approval.

Each studio day keeps three topics in the side list. Every topic is made
twice: once in English and once in Spanish, with the same voice. A video
that is still unreviewed on the next day moves onto that day.
"""

import json
import os
import uuid
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


def studio_zone():
    try:
        return ZoneInfo("America/New_York")
    except Exception:
        return timezone.utc
DAILY_COUNT = 3
LANGUAGES = ("en", "es")
ACTIVE_STATES = {
    "QUEUED",
    "RESEARCHING",
    "SCRIPTWRITING",
    "QUALITY_REVIEW",
    "RENDERING_PREVIEW",
}
CHECKED_STATES = {"APPROVED", "CHANGES_REQUESTED"}

TOPICS = (
    "How a building automation system reads zone temperature and adjusts a VAV damper",
    "What an energy management system does with occupancy schedules after hours",
    "How a chilled-water valve responds when supply-air temperature leaves its setpoint",
    "Why an HVAC economizer checks outdoor enthalpy before opening the outside-air damper",
    "How a BAS keeps unoccupied floors from being cooled overnight",
    "What a supply-air temperature reset does for chiller energy in an EMS",
    "How a pressure-independent VAV box holds airflow when duct pressure changes",
    "Why a hot-water reset curve lowers boiler temperature in mild weather",
    "How a BAS proves a fan is running before it enables a heating coil",
    "What demand limiting means when an energy management system sheds HVAC load",
    "How a conference-room CO2 sensor increases outdoor air through the BAS",
    "Why a freeze stat stops a coil and closes the outside-air damper",
    "How an EMS trend log shows a heating valve that stayed open overnight",
    "What static-pressure reset does for supply fans in a VAV system",
    "How a BAS morning warmup ends when the zone reaches the occupied setpoint",
    "Why condenser-water temperature reset saves chiller energy in cool weather",
    "How an occupancy sensor releases a VAV box to its unoccupied airflow",
    "What a building automation alarm does when a pump fails to prove flow",
)


def studio_today(now=None):
    zone = studio_zone()
    moment = now or datetime.now(zone)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    return moment.astimezone(zone).date()


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)


def _jobs(jobs_dir):
    found = []
    if not jobs_dir.is_dir():
        return found
    for folder in jobs_dir.iterdir():
        if not folder.is_dir():
            continue
        data = _read_json(folder / "job.json")
        if data:
            found.append((folder, data))
    return found


def _language(data):
    return "es" if str(data.get("language") or "").strip().lower() == "es" else "en"


def _waiting(data):
    return (
        data.get("source") == "automation"
        and not data.get("parked")
        and data.get("status") not in CHECKED_STATES
    )


def _checked(data):
    return (
        data.get("source") == "automation"
        and not data.get("parked")
        and data.get("status") in CHECKED_STATES
    )


def _pick_topics(state, waiting_topics, count):
    if count <= 0:
        return []
    index = int(state.get("next_index") or 0) % len(TOPICS)
    chosen = []
    seen = set(waiting_topics)
    scanned = 0
    while len(chosen) < count and scanned < len(TOPICS):
        topic = TOPICS[index % len(TOPICS)]
        index += 1
        scanned += 1
        if topic in seen:
            continue
        seen.add(topic)
        chosen.append(topic)
    state["next_index"] = index % len(TOPICS)
    return chosen


def ensure_daily_slate(jobs_dir, state_path, today, launch, lock=None):
    """Keep three topics on `today`, each in English and Spanish, and start one render."""
    if lock is not None:
        with lock:
            return _ensure(jobs_dir, state_path, today, launch)
    return _ensure(jobs_dir, state_path, today, launch)


def create_three_in_language(jobs_dir, state_path, today, launch, languages, created_by="studio", lock=None):
    """Add three HVAC topics in the requested language and start one when the queue is free."""
    if lock is not None:
        with lock:
            return _create_three(jobs_dir, state_path, today, launch, languages, created_by)
    return _create_three(jobs_dir, state_path, today, launch, languages, created_by)


def force_daily_slate(jobs_dir, state_path, today, launch, lock=None):
    """Create three new topics, each in English and Spanish.

    Videos still waiting for review stay in the side list under their day.
    """
    if lock is not None:
        with lock:
            return _force(jobs_dir, state_path, today, launch)
    return _force(jobs_dir, state_path, today, launch)


def _create_three(jobs_dir, state_path, today, launch, languages, created_by):
    if not isinstance(today, date):
        raise TypeError("today must be a date")
    chosen = []
    for language in languages:
        code = "es" if str(language).strip().lower() == "es" else "en"
        if code not in chosen:
            chosen.append(code)
    if not chosen:
        raise ValueError("Choose English, Spanish, or both")
    today_text = today.isoformat()
    jobs_dir.mkdir(parents=True, exist_ok=True)
    state = _read_json(state_path)
    occupied = []
    for _folder, data in _jobs(jobs_dir):
        if data.get("parked") or data.get("status") in CHECKED_STATES or data.get("status") == "FAILED":
            continue
        topic = data.get("topic")
        if topic and topic not in occupied:
            occupied.append(topic)
    topics = _pick_topics(state, occupied, DAILY_COUNT)
    _write_json(state_path, state)
    created = []
    order = 0
    for topic in topics:
        pair_id = uuid.uuid4().hex if len(chosen) > 1 else ""
        for language in chosen:
            job_id = datetime.now(studio_zone()).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
            folder = jobs_dir / job_id
            folder.mkdir()
            record = {
                "job_id": job_id,
                "topic": topic,
                "language": language,
                "category": "hvac",
                "status": "SCHEDULED",
                "created_utc": datetime.now(studio_zone()).isoformat(),
                "created_by": created_by,
                "source": "manual",
                "slate_day": today_text,
                "review_day": today_text,
                "slate_order": order,
            }
            if pair_id:
                record["pair_id"] = pair_id
            order += 1
            _write_json(folder / "job.json", record)
            created.append(job_id)
    started = start_next_scheduled(jobs_dir, launch)
    return {"created": created, "started": started, "languages": chosen}


def _force(jobs_dir, state_path, today, launch):
    parked = []
    for folder, data in _jobs(jobs_dir):
        if not _waiting(data):
            continue
        data["parked"] = True
        _write_json(folder / "job.json", data)
        parked.append(data["job_id"])
    state = _read_json(state_path)
    dismissed = state.get("dismissed")
    if isinstance(dismissed, dict):
        dismissed.pop(today.isoformat(), None)
        state["dismissed"] = dismissed
        _write_json(state_path, state)
    result = _ensure(jobs_dir, state_path, today, launch, fill=True)
    result["parked"] = parked
    return result


def _ensure(jobs_dir, state_path, today, launch, fill=False):
    if not isinstance(today, date):
        raise TypeError("today must be a date")
    today_text = today.isoformat()
    jobs_dir.mkdir(parents=True, exist_ok=True)
    moved = []
    for folder, data in _jobs(jobs_dir):
        if not _waiting(data):
            continue
        if str(data.get("review_day") or "") < today_text:
            data["review_day"] = today_text
            _write_json(folder / "job.json", data)
            moved.append(data["job_id"])

    current = _jobs(jobs_dir)
    waiting = [data for _folder, data in current if _waiting(data)]
    checked = [data for _folder, data in current if _checked(data)]
    state = _read_json(state_path)
    dismissed = set() if fill else _dismissed_pairs(state)
    held_today = set() if fill else _dismissed_pairs(state, today_text)
    created = []
    order = 0

    def add_job(topic, language):
        nonlocal order
        job_id = datetime.now(studio_zone()).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        folder = jobs_dir / job_id
        folder.mkdir()
        record = {
            "job_id": job_id,
            "topic": topic,
            "language": language,
            "category": "hvac",
            "status": "SCHEDULED",
            "created_utc": datetime.now(studio_zone()).isoformat(),
            "created_by": "automation",
            "source": "automation",
            "slate_day": today_text,
            "review_day": today_text,
            "slate_order": order,
        }
        order += 1
        _write_json(folder / "job.json", record)
        created.append(job_id)

    waiting_topics = []
    for item in waiting:
        topic = item.get("topic")
        if topic and topic not in waiting_topics:
            waiting_topics.append(topic)

    def already_made(topic, language):
        if (topic, language) in dismissed:
            return True
        return any(
            item.get("topic") == topic and _language(item) == language
            for item in waiting + checked
        )

    for topic in waiting_topics:
        for language in LANGUAGES:
            if not already_made(topic, language):
                add_job(topic, language)
    needed = 0 if held_today else DAILY_COUNT - len(waiting_topics)
    for topic in _pick_topics(state, waiting_topics, needed):
        for language in LANGUAGES:
            add_job(topic, language)
    if created or moved:
        _write_json(state_path, state)

    started = start_next_scheduled(jobs_dir, launch)
    waiting_now = [data["job_id"] for _folder, data in _jobs(jobs_dir) if _waiting(data) and data.get("review_day") == today_text]
    return {"created": created, "moved": moved, "started": started, "waiting": waiting_now}


def start_next_scheduled(jobs_dir, launch, after_job_id=None):
    """Start one scheduled video. A language pair continues with its other language first."""
    current = _jobs(jobs_dir)
    if any(data.get("status") in ACTIVE_STATES for _folder, data in current):
        return None
    scheduled = [
        (folder, data)
        for folder, data in current
        if data.get("status") == "SCHEDULED"
        and not data.get("parked")
        and data.get("source") != "automation"
    ]
    if after_job_id:
        finished = next((data for _folder, data in current if data.get("job_id") == after_job_id), {})
        pair = finished.get("pair_id")
        if pair:
            partner = [item for item in scheduled if item[1].get("pair_id") == pair]
            if partner:
                scheduled = partner
    if not scheduled:
        return None
    scheduled.sort(key=lambda item: (
        item[1].get("created_utc", ""),
        item[1].get("slate_order", 0),
        item[1].get("job_id", ""),
    ))
    folder, data = scheduled[0]
    data["status"] = "QUEUED"
    _write_json(folder / "job.json", data)
    try:
        launch(folder, data["job_id"])
    except Exception as exc:
        data["status"] = "FAILED"
        data["error"] = "Could not launch worker: " + str(exc)[:200]
        _write_json(folder / "job.json", data)
        raise
    return data["job_id"]


def dismiss_topic(state_path, today, topic, language):
    """Remember a deleted video so today's reload does not create it again."""
    if not isinstance(today, date):
        raise TypeError("today must be a date")
    text = " ".join(str(topic or "").split())
    if not text:
        return
    state = _read_json(state_path)
    dismissed = state.get("dismissed")
    if not isinstance(dismissed, dict):
        dismissed = {}
    day = today.isoformat()
    items = [item for item in dismissed.get(day, []) if isinstance(item, dict)]
    entry = {"topic": text, "language": _language({"language": language})}
    if entry not in items:
        items.append(entry)
    dismissed[day] = items[-200:]
    state["dismissed"] = dismissed
    _write_json(state_path, state)


def _dismissed_pairs(state, day=None):
    raw = state.get("dismissed") if isinstance(state.get("dismissed"), dict) else {}
    days = [day] if day else list(raw)
    found = set()
    for name in days:
        for item in raw.get(name) or []:
            if isinstance(item, dict) and item.get("topic"):
                found.add((" ".join(str(item.get("topic")).split()), _language(item)))
    return found
