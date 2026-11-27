"""The topic categories from the J3G Video Creation Catalog.

The daily three stay on HVAC, BAS and building controls. A category only
changes the video started from Create a video.
"""


def _item(category_id, label, audience, script_note, publishing_note, scene_note=""):
    return {
        "id": category_id,
        "label": label,
        "audience": audience,
        "character_id": "hvac-tech" if category_id == "hvac" else "presenter",
        "scene_note": scene_note,
        "script_note": script_note,
        "publishing_note": publishing_note,
    }


_PRESENTER = "Show simple props that match the scene. No tool belt and no HVAC equipment unless the scene is about that."

CATEGORIES = (
    _item(
        "hvac",
        "HVAC, BAS and building controls",
        "HVAC technicians and beginners",
        "",
        "Educational HVAC explanation for technicians and beginners. This is not a substitute for equipment manuals or applicable codes.",
        "",
    ),
    _item(
        "ai",
        "Artificial intelligence and machine learning",
        "people learning artificial intelligence",
        "Explain the idea and its limits. Do not overclaim what the system can do.",
        "An educational explanation of artificial intelligence. Capabilities and limits should be stated plainly.",
        _PRESENTER,
    ),
    _item(
        "it",
        "IT, networking and protocols",
        "people learning computer networks and IT",
        "Explain the network or IT idea in plain language.",
        "An educational explanation for people learning IT, networking, and protocols.",
        _PRESENTER,
    ),
    _item(
        "security",
        "Cybersecurity and digital privacy",
        "a general audience learning how to stay safe online",
        "Teach defensive habits only. Do not describe how to attack, break in, or write malware.",
        "Defensive security education for a general audience. This is not an attack guide.",
        _PRESENTER,
    ),
    _item(
        "homelab",
        "HomeLab, servers and hardware",
        "people learning home labs, servers, and hardware",
        "Explain the hardware or lab concept so someone can understand it.",
        "An educational explanation of home-lab, server, or hardware concepts.",
        _PRESENTER,
    ),
    _item(
        "smarthome",
        "Smart home and home automation",
        "people learning smart-home devices and home automation",
        "Explain the home device, hub, routine, or automation. Keep names such as Matter, Zigbee, Z-Wave, and Thread unchanged. This is a home, not a commercial building.",
        "An educational explanation of smart-home devices and home automation. Follow the device manual and applicable electrical rules.",
        _PRESENTER,
    ),
    _item(
        "software",
        "Software tutorials and productivity",
        "people learning software and everyday productivity tools",
        "Give a clear step-by-step explanation of the software task.",
        "A software tutorial for beginners and working users.",
        _PRESENTER,
    ),
    _item(
        "science",
        "Science and technology",
        "a general audience curious about science and technology",
        "Answer the question directly. If health comes up, give general information only and say it is not medical advice.",
        "A science or technology explainer for a general audience.",
        _PRESENTER,
    ),
    _item(
        "math",
        "Math, statistics and data storytelling",
        "people learning math, statistics, and data",
        "Explain the number or chart in plain language and do not overclaim what it proves.",
        "An educational explanation of math, statistics, or a data story.",
        _PRESENTER,
    ),
    _item(
        "mechanisms",
        "How things work / engineering mechanisms",
        "people who want to see how a mechanism works",
        "Explain the mechanism in a concrete way.",
        "An educational explanation of how a mechanism works.",
        _PRESENTER,
    ),
    _item(
        "history",
        "History and geography",
        "a general audience learning history and geography",
        "Keep names, places, and dates careful. Do not invent sources.",
        "An educational history or geography explanation. Dates and places should be checked before publishing.",
        _PRESENTER,
    ),
    _item(
        "news",
        "News, commentary and explainers",
        "a general audience looking for a clear explanation",
        "Do not invent headlines, dates, or sources. The studio has no live news feed.",
        "An explainer. It is not a live news report and it does not invent sources.",
        _PRESENTER,
    ),
    _item(
        "fiction",
        "Fiction, drama and micro-stories",
        "viewers of an original short story",
        "Write an original story. Do not use copyrighted characters or existing franchises.",
        "An original short story. It is not a documentary.",
        _PRESENTER,
    ),
    _item(
        "cartoons",
        "Cartoon characters and animated series",
        "viewers of an original cartoon",
        "Keep the same original character. Do not copy an existing cartoon or mascot.",
        "An original cartoon explanation.",
        _PRESENTER,
    ),
    _item(
        "kids",
        "Kids, family and classroom learning",
        "children, families, and classrooms",
        "Keep it age-appropriate for a classroom. No graphic, romantic, or adult content.",
        "A classroom-friendly explanation for kids and families.",
        _PRESENTER,
    ),
    _item(
        "family",
        "Family",
        "people thinking about why family matters",
        "Show why family is important. Use warm, concrete examples such as showing up, listening, shared meals, and helping one another. Do not lecture, shame, or invent a real family's private story. Keep it age-appropriate. No graphic, romantic, or adult content.",
        "A respectful explanation of why family is important. It is general, not advice for one particular family.",
        _PRESENTER,
    ),
    _item(
        "languages",
        "Languages, culture and communication",
        "people learning a language or about a culture",
        "Teach the language or cultural point clearly, and keep protocol names unchanged when they appear.",
        "A language, culture, or communication explainer.",
        _PRESENTER,
    ),
    _item(
        "career",
        "Career, money and personal planning",
        "people learning about careers and everyday money decisions",
        "Give general education only. Do not give personalized financial, tax, or legal advice.",
        "General career and money education. This is not personalized financial, tax, or legal advice.",
        _PRESENTER,
    ),
    _item(
        "business",
        "Business, branding and marketing",
        "people learning business, branding, and marketing",
        "Explain the business idea plainly. Do not promise results.",
        "A business, branding, or marketing explainer. It does not promise results.",
        _PRESENTER,
    ),
    _item(
        "products",
        "Products, reviews and e-commerce",
        "people comparing a product or learning what it does",
        "Describe the product honestly. Do not invent test results or prices.",
        "A product explanation. Prices, tests, and claims should be checked before publishing.",
        _PRESENTER,
    ),
    _item(
        "lifestyle",
        "Lifestyle, travel and everyday learning",
        "a general audience learning an everyday skill",
        "Stay on the everyday topic. Mention safety when it matters, including food safety.",
        "A practical everyday explainer. Check safety details before publishing.",
        _PRESENTER,
    ),
    _item(
        "shorts",
        "Short-form, interactive and entertainment",
        "viewers of a short educational video",
        "Make the point quickly and do not mislead the viewer.",
        "A short educational video.",
        _PRESENTER,
    ),
)

_BY_ID = {item["id"]: item for item in CATEGORIES}
_ALIASES = {
    "smart-home": "smarthome",
    "smart home": "smarthome",
    "home-automation": "smarthome",
    "home automation": "smarthome",
    "network": "it",
    "health": "science",
    "food": "lifestyle",
    "recipes": "lifestyle",
    "receipts": "career",
    "general": "lifestyle",
    "families": "family",
}


def normalize_category(value):
    """Missing or unknown stored values stay on HVAC, BAS and building controls."""
    key = _ALIASES.get(str(value or "").strip().lower(), str(value or "").strip().lower())
    if key in _BY_ID:
        return key
    return "hvac"


def require_category(value):
    key = str(value or "").strip().lower()
    canonical = _ALIASES.get(key, key)
    if canonical not in _BY_ID:
        raise ValueError("Choose a category from the list")
    return canonical


def category_info(value):
    return _BY_ID[normalize_category(value)]
