"""VAV must be spoken as letters so the voice does not say baby."""

import unittest

from app.spoken_terms import spoken_narration


class SpokenTermTests(unittest.TestCase):
    def test_english_vav_is_spelled(self):
        self.assertEqual(
            spoken_narration("The VAV box holds airflow.", "en"),
            "The vee ay vee box holds airflow.",
        )

    def test_lowercase_and_plural(self):
        self.assertEqual(spoken_narration("two vavs", "en"), "two vee ay vees")
        self.assertEqual(spoken_narration("the VAV's damper", "en"), "the vee ay vees damper")

    def test_spanish_letters(self):
        self.assertEqual(spoken_narration("el VAV abre", "es"), "el uve a uve abre")

    def test_other_words_stay(self):
        text = "Variable air volume and BACnet stay written."
        self.assertEqual(spoken_narration(text, "en"), text)

    def test_english_technical_words_stay(self):
        text = "Use Wi-Fi, WPA3, MFA, USB, and Bluetooth."
        self.assertEqual(spoken_narration(text, "en"), text)

    def test_spanish_technical_words_stay_in_spanish(self):
        spoken = spoken_narration(
            "Proteja su Wi-Fi. Use WPA3 o WPA2. Active el MFA. Evite el phishing.",
            "es",
        )
        self.assertNotIn("Wi-Fi", spoken)
        self.assertNotIn("WPA", spoken)
        self.assertNotIn("MFA", spoken)
        self.assertNotIn("phishing", spoken)
        self.assertIn("güifi", spoken)
        self.assertIn("eme efe a", spoken)
        self.assertIn("fishin", spoken)


if __name__ == "__main__":
    unittest.main()
