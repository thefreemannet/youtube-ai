"""Stage safer photo selection on VM 111 without touching active production engine."""
from pathlib import Path
import shutil

p = Path('app/visual_photo_selector.py')
s = p.read_text(encoding='utf-8')
if 'def _previous_media(' in s:
    raise SystemExit('STOP: duplicate protection already installed')
if 'MAX_VISION_CHECKS = 8' not in s:
    raise SystemExit('STOP: unexpected source version')
shutil.copy2(p, p.with_suffix('.py.before-v4'))

def replace_section(src, first, last, replacement):
    if src.count(first) != 1 or src.count(last) != 1:
        raise SystemExit(f'STOP: unexpected source section: {first}')
    start = src.index(first)
    end = src.index(last, start)
    return src[:start] + replacement + src[end:]

s = replace_section(s, 'def _queries(', 'def _subject(', '''def _queries(query: str, topic: str, body: str = "") -> list[str]:
    """Prioritize exact equipment, not common words or general industry photos."""
    query = ' '.join(query.split())
    q = query.casefold()
    choices = [query]
    if any(x in topic.casefold() for x in ('vav', 'variable air volume')):
        if 'filter' in q:
            choices += ['HVAC air filter', 'air handling unit filter']
        elif any(x in q for x in ('reheat', 'coil', 'heater')):
            choices += ['electric duct heater', 'HVAC reheat coil', 'duct heating coil']
        elif any(x in q for x in ('thermostat', 'sensor', 'temperature')):
            choices += ['HVAC thermostat', 'building temperature sensor']
        elif any(x in q for x in ('damper', 'actuator', 'motor')):
            choices += ['HVAC damper actuator', 'ventilation damper actuator', 'motorized air damper']
        elif any(x in q for x in ('vav', 'terminal', 'box')):
            choices += ['variable air volume terminal unit', 'VAV terminal box HVAC', 'variable air volume box']
        # No automatic fallback to generic ductwork: it can give false positives.
    else:
        # Keep the AI-selected physical subject specific for other topics.
        words = query.split()
        if len(words) >= 4:
            choices.append(' '.join(words[:3]))
    results = []
    for item in choices:
        item = ' '.join(item.split())
        if (2 <= len(item.split()) <= 9
                and re.fullmatch(r"[A-Za-z0-9 ,/()\\-]+", item)
                and item.casefold() not in {x.casefold() for x in results}):
            results.append(item)
    return results[:12]


''')

s = replace_section(s, 'def _subject(', 'def _file_fingerprint(', '''def _subject(topic: str, body: str, query: str) -> str:
    return (
        'Inspect the ACTUAL photograph, not its name or metadata. '
        f'Video topic: {topic}\\n'
        f'Scene narration: {body[:950]}\\n'
        f'Requested visible equipment: {query}\\n'
        'APPROVE only if the photo visibly shows specific physical equipment '
        'that directly illustrates the main subject of BOTH the requested '
        'equipment and the scene narration. A broad industry connection is NOT '
        'enough. Generic ductwork does not prove a VAV terminal, damper actuator '
        'or reheat coil is visible. A server room does not prove encrypted networking. '
        'If the search query mismatches the narration, REJECT. If an item is '
        'hidden, only inferred, or ambiguous, REJECT. If uncertain, REJECT.'
    )


''')

helper = '''def _previous_media(folder: Path, number: int) -> tuple[set[str], set[str]]:
    """Identify Commons originals already accepted for earlier scenes of this job."""
    sources, hashes = set(), set()
    for earlier in range(1, number):
        sidecar = ASSETS / f'{folder.name}_scene_{earlier:02d}.json'
        if not sidecar.is_file():
            continue
        try:
            entry = json.loads(sidecar.read_text(encoding='utf-8'))
            if entry.get('scene_job_id') != folder.name or entry.get('scene_number') != earlier:
                continue
            if entry.get('source'):
                sources.add(entry['source'])
            digest = (entry.get('vision_gate') or {}).get('image_sha256')
            if digest:
                hashes.add(digest)
        except (ValueError, OSError):
            continue
    return sources, hashes


'''
needle = 'def select_photo(topic: str, scene: dict, folder: Path) -> Path:'
assert s.count(needle) == 1
s = s.replace(needle, helper + needle)

def replace_once(old, new):
    global s
    if s.count(old) != 1:
        raise SystemExit('STOP: unable to locate expected code: '+old[:80])
    s = s.replace(old, new, 1)

replace_once("    subject = _subject(topic, body, query)\n    log: list[dict] = []", "    subject = _subject(topic, body, query)\n    used_sources, used_hashes = _previous_media(folder, num)\n    log: list[dict] = []")
replace_once("            outcome = _screen(target, subject)  # Never trust old cached decision alone.", "            if (metadata.get('source') in used_sources or\n                    _file_fingerprint(target) in used_hashes):\n                raise ValueError('Photograph already used by an earlier scene')\n            outcome = _screen(target, subject)  # Never trust old cached decision alone.")
replace_once("                if img_url in seen_urls:", "                if source in used_sources:\n                    continue\n                if img_url in seen_urls:")
replace_once("                    blob = b''.join(parts)\n                    with Image.open", "                    blob = b''.join(parts)\n                    digest = hashlib.sha256(blob).hexdigest()\n                    if digest in used_hashes:\n                        continue\n                    with Image.open")
replace_once("'image_sha256': hashlib.sha256(blob).hexdigest(),", "'image_sha256': digest,")
compile(s, str(p), 'exec')
p.write_text(s, encoding='utf-8')
print('VISUAL SELECTOR v4: INSTALLED')
print('STRICT SUBJECT MATCHING: ENABLED')
print('DUPLICATE PHOTOS IN A JOB: BLOCKED')
print('ACTIVE PRODUCTION ENGINE v2: UNCHANGED')
