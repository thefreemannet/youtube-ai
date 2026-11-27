"""Create a video uses the categories from the J3G catalog."""

import unittest

from app.categories import CATEGORIES, category_info, normalize_category, require_category
from app.dashboard_page import render_dashboard
from app.workflow_dashboard import scriptwriter_prompt


CATALOG_LABELS = (
    "HVAC, BAS and building controls",
    "Artificial intelligence and machine learning",
    "IT, networking and protocols",
    "Cybersecurity and digital privacy",
    "HomeLab, servers and hardware",
    "Smart home and home automation",
    "Software tutorials and productivity",
    "Science and technology",
    "Math, statistics and data storytelling",
    "How things work / engineering mechanisms",
    "History and geography",
    "News, commentary and explainers",
    "Fiction, drama and micro-stories",
    "Cartoon characters and animated series",
    "Kids, family and classroom learning",
    "Family",
    "Languages, culture and communication",
    "Career, money and personal planning",
    "Business, branding and marketing",
    "Products, reviews and e-commerce",
    "Lifestyle, travel and everyday learning",
    "Short-form, interactive and entertainment",
)


class CategoryTests(unittest.TestCase):
    def test_catalog_lists_every_category_in_order(self):
        self.assertEqual([item["label"] for item in CATEGORIES], list(CATALOG_LABELS))

    def test_missing_category_stays_hvac(self):
        self.assertEqual(normalize_category(""), "hvac")
        self.assertEqual(normalize_category(None), "hvac")
        self.assertEqual(category_info("nope")["character_id"], "hvac-tech")

    def test_catalog_subjects_use_the_presenter_except_hvac(self):
        self.assertEqual(require_category("hvac"), "hvac")
        self.assertEqual(category_info("hvac")["character_id"], "hvac-tech")
        for item in CATEGORIES:
            if item["id"] == "hvac":
                continue
            self.assertEqual(require_category(item["id"]), item["id"])
            self.assertEqual(item["character_id"], "presenter")
        with self.assertRaises(ValueError):
            require_category("sports-cars")

    def test_older_network_choice_maps_to_the_catalog(self):
        self.assertEqual(require_category("network"), "it")
        self.assertEqual(category_info("network")["label"], "IT, networking and protocols")

    def test_other_subjects_are_not_rewritten_as_hvac(self):
        prompt = scriptwriter_prompt("How yeast makes bread rise", "Food research.", "en", "lifestyle")
        self.assertIn("Do not turn the video into an HVAC", prompt)
        self.assertIn("food safety", prompt)
        self.assertNotIn("HVAC technicians and beginners", prompt)

    def test_security_stays_defensive(self):
        prompt = scriptwriter_prompt("Why MFA matters", "Security research.", "en", "security")
        self.assertIn("Do not describe how to attack", prompt)

    def test_smart_home_stays_a_home_and_uses_the_presenter(self):
        self.assertEqual(require_category("smart home"), "smarthome")
        self.assertEqual(category_info("smarthome")["character_id"], "presenter")
        prompt = scriptwriter_prompt("How a smart lock talks to a hub", "Home research.", "en", "smarthome")
        self.assertIn("not a commercial building", prompt)
        self.assertIn("Do not turn the video into an HVAC", prompt)
        self.assertNotIn("HVAC technicians and beginners", prompt)

    def test_family_explains_why_family_matters(self):
        self.assertEqual(require_category("family"), "family")
        self.assertEqual(require_category("families"), "family")
        self.assertEqual(category_info("family")["label"], "Family")
        self.assertEqual(category_info("family")["character_id"], "presenter")
        prompt = scriptwriter_prompt("Why family is important", "Family research.", "en", "family")
        self.assertIn("why family is important", prompt)
        self.assertIn("Do not turn the video into an HVAC", prompt)
        self.assertNotIn("HVAC technicians and beginners", prompt)

    def test_hvac_prompt_still_guards_bacnet(self):
        prompt = scriptwriter_prompt("What is BACnet?", "Controls research.", "en", "hvac")
        self.assertIn("write BACnet every time", prompt)
        self.assertNotIn("Do not turn the video into an HVAC", prompt)

    def test_create_form_lists_the_catalog(self):
        page = render_dashboard([], "", {"youtube": False, "instagram": False})
        for label in CATALOG_LABELS:
            self.assertIn(label, page)
        self.assertIn("A video starts when you ask for it here.", page)
        self.assertIn("Both, English and Spanish", page)
        self.assertIn(">Create 3 videos<", page)
        self.assertIn("Generate 3 videos in English and Spanish", page)
        self.assertIn("Drag to resize the side list", page)
        self.assertIn("A script that would last under a minute is expanded past one minute", page)

    def test_a_short_script_is_expanded_without_changing_the_idea(self):
        from app.workflow_dashboard import expand_script_prompt, script_needs_expansion
        short = "A freeze stat watches the coil and closes the damper."
        self.assertTrue(script_needs_expansion(short))
        self.assertFalse(script_needs_expansion("word " * 160))
        prompt = expand_script_prompt("Why a freeze stat stops a coil", short, "en", "hvac")
        self.assertIn("more than one minute", prompt)
        self.assertIn("Keep the same idea", prompt)
        self.assertIn(short, prompt)
        self.assertIn("160", prompt)


if __name__ == "__main__":
    unittest.main()
