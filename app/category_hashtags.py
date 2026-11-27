"""Hashtags posted with a TikTok video. They follow the video category."""

from app.categories import category_info

# HVAC is the only category with the brand tags the studio was given.
_TAGS = {
    "hvac": ("#Trane", "#TraneTechnologies", "#HVAC", "#Automation"),
    "ai": ("#AI", "#MachineLearning", "#ArtificialIntelligence"),
    "it": ("#IT", "#Networking", "#Protocols"),
    "security": ("#Cybersecurity", "#Privacy", "#OnlineSafety"),
    "homelab": ("#HomeLab", "#Servers", "#Hardware"),
    "smarthome": ("#SmartHome", "#HomeAutomation"),
    "software": ("#Software", "#Tutorial", "#Productivity"),
    "science": ("#Science", "#Technology"),
    "math": ("#Math", "#Statistics", "#Data"),
    "mechanisms": ("#Engineering", "#HowItWorks"),
    "history": ("#History", "#Geography"),
    "news": ("#Explainer", "#News"),
    "fiction": ("#Fiction", "#ShortStory"),
    "cartoons": ("#Cartoon", "#Animation"),
    "kids": ("#KidsLearning", "#Family", "#Classroom"),
    "family": ("#Family", "#FamilyMatters", "#Together"),
    "languages": ("#Languages", "#Culture", "#Communication"),
    "career": ("#Career", "#Money", "#PersonalFinance"),
    "business": ("#Business", "#Branding", "#Marketing"),
    "products": ("#ProductReview", "#Ecommerce"),
    "lifestyle": ("#Lifestyle", "#EverydayLearning"),
    "shorts": ("#Shorts", "#Learning"),
}


def category_hashtags(category):
    info = category_info(category)
    return _TAGS.get(info["id"], _TAGS["hvac"])


def tiktok_caption(title, category):
    """Title plus the category hashtags, inside TikTok's caption limit."""
    tags = " ".join(category_hashtags(category))
    heading = " ".join(str(title or "").split())
    room = 2200 - len(tags) - 1
    if room < 1:
        return tags[:2200]
    heading = heading[:room].rstrip()
    if not heading:
        return tags
    return heading + "\n" + tags
