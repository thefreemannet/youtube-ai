"""Build a staged production_engine_v3.py from the live v2 source on VM 111.

Never modifies or activates the live worker. Can be safely re-run.
"""
from pathlib import Path

app = Path('/opt/j3g-youtube-ai/app')
src = app / 'production_engine_v2.py'
out = app / 'production_engine_v3.py'
source = src.read_text(encoding='utf-8')
start = source.index('def ensure_photos(plan, folder):')
end = source.index('\ndef render_slides(', start)
replacement = '''def ensure_photos(plan, folder):
    """Every scene must pass licensing AND real image-content checks.

    Cached photos are never trusted without revalidation for the current scene.
    The selection is isolated by job ID and scene number, so different jobs
    cannot accidentally reuse a photograph with an unrelated caption.
    """
    app_dir = ROOT / 'app'
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    from visual_photo_selector import select_photo
    from visual_engine import create_background

    final = []
    for scene in plan['scenes']:
        query = (scene.get('photo_query') or '').strip()
        if not query:
            raise ValueError(f'Scene {scene["number"]}: no photographic subject')
        print(f'[PHOTO] Scene {scene["number"]}: visual verification required', flush=True)
        jpg = select_photo(plan['topic'], scene, folder)
        background = create_background(jpg)
        final.append((jpg, background))
        scene['photo_path'] = str(jpg)
        scene['license_review_required'] = True
        scene['visual_relevance_checked'] = True
    return final

'''
result = source[:start] + replacement + source[end:]
# A non-destructive test mode fetches/checks photos without touching video or narration.
needle = "    modes.add_argument('--render', action='store_true')"
assert result.count(needle) == 1, 'Could not find render option'
result = result.replace(needle, needle + "\n    modes.add_argument('--verify-photos', action='store_true', help='Run image and license checks, without video assembly')")
needle2 = "    backgrounds = ensure_photos(plan, folder)\n    slides = render_slides(plan, folder, backgrounds)"
assert result.count(needle2) == 1, 'Could not find render pipeline'
replacement2 = "    backgrounds = ensure_photos(plan, folder)\n    if args.verify_photos:\n        (folder / 'production_plan.json').write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding='utf-8')\n        print('VISUAL REVIEW COMPLETE: all scenes passed image + license screening')\n        print('NO VIDEO REBUILT. ORIGINAL PREVIEW UNCHANGED.')\n        return\n    slides = render_slides(plan, folder, backgrounds)"
result = result.replace(needle2, replacement2)
compile(result, str(out), 'exec')
out.write_text(result, encoding='utf-8')
print('STAGED PRODUCTION ENGINE CREATED:', out)
print('LIVE WORKER NOT MODIFIED; ORIGINAL V2 UNCHANGED')
