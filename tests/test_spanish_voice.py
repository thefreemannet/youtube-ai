"""Spanish narration uses the same speaker and a separate language flag."""

import unittest

from app.workflow_dashboard import scriptwriter_prompt, spoken_language


class SpanishVoiceTests(unittest.TestCase):
    def test_only_spanish_is_treated_as_spanish(self):
        self.assertEqual(spoken_language("es"), "es")
        self.assertEqual(spoken_language("ES"), "es")
        self.assertEqual(spoken_language("en"), "en")
        self.assertEqual(spoken_language(""), "en")
        self.assertEqual(spoken_language("fr"), "en")

    def test_spanish_script_stays_spanish_and_keeps_bacnet(self):
        prompt = scriptwriter_prompt("How a VAV damper opens", "Cooling research.", "es")
        self.assertIn("Latin American Spanish", prompt)
        self.assertIn("Do not translate BACnet.", prompt)
        self.assertNotIn("spoken narration in English", prompt)

    def test_english_script_stays_english(self):
        prompt = scriptwriter_prompt("How a VAV damper opens", "Cooling research.", "en")
        self.assertIn("spoken narration in English", prompt)
        self.assertNotIn("Latin American Spanish", prompt)


if __name__ == "__main__":
    unittest.main()
