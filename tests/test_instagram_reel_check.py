"""Instagram Reel confirmation checks. No network and no upload."""

import unittest

from app.instagram_reel_check import reel_confirmation, safe_permalink


class ReelConfirmationTests(unittest.TestCase):
    def test_matching_reel_is_confirmed(self):
        result = reel_confirmation("1789001", {
            "id": "1789001",
            "media_type": "VIDEO",
            "media_product_type": "REELS",
            "permalink": "https://www.instagram.com/reel/ABC123/",
        })
        self.assertEqual(result["media_product_type"], "REELS")
        self.assertEqual(result["permalink"], "https://www.instagram.com/reel/ABC123/")

    def test_a_feed_video_is_not_accepted_as_a_reel(self):
        with self.assertRaises(RuntimeError):
            reel_confirmation("1789001", {
                "id": "1789001",
                "media_type": "VIDEO",
                "media_product_type": "FEED",
                "permalink": "https://www.instagram.com/p/ABC123/",
            })

    def test_a_different_id_is_rejected(self):
        with self.assertRaises(RuntimeError):
            reel_confirmation("1789001", {
                "id": "999",
                "media_type": "VIDEO",
                "media_product_type": "REELS",
                "permalink": "https://www.instagram.com/reel/ABC123/",
            })

    def test_permalink_must_be_an_instagram_https_link(self):
        self.assertEqual(safe_permalink("https://instagram.com/reel/ABC123/"), "https://instagram.com/reel/ABC123/")
        self.assertEqual(safe_permalink("http://www.instagram.com/reel/ABC123/"), "")
        self.assertEqual(safe_permalink("https://example.com/reel/ABC123/"), "")


if __name__ == "__main__":
    unittest.main()
