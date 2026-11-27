"""Short captions timed to the narration.

The spoken words are split into brief lines. Each line stays on screen for
its share of the audio, so the text changes as the voice moves forward.
"""

import re
from pathlib import Path


def srt_clock(seconds):
    millis = max(0, int(round(float(seconds) * 1000)))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def ass_clock(seconds):
    millis = max(0, int(round(float(seconds) * 100)))
    hours, millis = divmod(millis, 360_000)
    minutes, millis = divmod(millis, 6_000)
    secs, millis = divmod(millis, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{millis:02}"


def phrases(text, limit=32):
    words = re.findall(r"\S+", " ".join(text.split()))
    if not words:
        return []
    lines = []
    current = ""
    for word in words:
        trial = (current + " " + word).strip()
        if current and len(trial) > limit:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def write_subtitles(folder, narration, duration):
    folder = Path(folder)
    cues = phrases(narration)
    if not cues:
        raise ValueError("Narration has no words for subtitles")
    duration = max(float(duration), 0.1)
    weights = [max(1, len(cue.split())) for cue in cues]
    total = sum(weights)
    clock = 0.0
    events = []
    for index, (cue, weight) in enumerate(zip(cues, weights), start=1):
        span = duration * weight / total
        end = duration if index == len(cues) else min(duration, clock + span)
        safe = cue.replace("\\", "").replace("{", "").replace("}", "")
        events.append(
            f"Dialogue: 0,{ass_clock(clock)},{ass_clock(end)},Caption,,0,0,0,,{safe}"
        )
        clock = end
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,DejaVu Sans,28,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,2,48,48,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    path = folder / "subtitles.ass"
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return path
