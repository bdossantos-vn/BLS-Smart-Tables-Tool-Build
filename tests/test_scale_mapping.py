"""Regression checks for scale mapping persistence."""

from __future__ import annotations

import unittest

import pandas as pd

from src.mapping import ensure_scale_mappings


class ScaleMappingTest(unittest.TestCase):
    def test_ensure_scale_mappings_preserves_saved_custom_order(self) -> None:
        question = {
            "variable": "AI_Comfort",
            "answer_choices_list": [
                "Very Comfortable",
                "Somewhat Comfortable",
                "Neutral",
                "Somewhat Uncomfortable",
            ],
        }
        saved_mapping = {
            "AI_Comfort": {
                "polarity": "standard",
                "rows": [
                    {"response_value": "Neutral", "bucket": 1},
                    {"response_value": "Somewhat Comfortable", "bucket": 2},
                    {"response_value": "Somewhat Uncomfortable", "bucket": 3},
                    {"response_value": "Very Comfortable", "bucket": 4},
                ],
            }
        }
        df = pd.DataFrame(
            {
                "AI_Comfort": [
                    "Very Comfortable",
                    "Somewhat Comfortable",
                    "Neutral",
                    "Somewhat Uncomfortable",
                ]
            }
        )

        mappings = ensure_scale_mappings([question], df, saved_mapping)
        ordered_values = [
            row["response_value"]
            for row in sorted(mappings["AI_Comfort"]["rows"], key=lambda item: item["bucket"])
        ]

        self.assertEqual(
            ordered_values,
            ["Neutral", "Somewhat Comfortable", "Somewhat Uncomfortable", "Very Comfortable"],
        )

    def test_ensure_scale_mappings_appends_new_choices_after_saved_order(self) -> None:
        question = {
            "variable": "AI_Comfort",
            "answer_choices_list": [
                "Very Comfortable",
                "Somewhat Comfortable",
                "Neutral",
                "Somewhat Uncomfortable",
                "Very Uncomfortable",
            ],
        }
        saved_mapping = {
            "AI_Comfort": {
                "polarity": "standard",
                "rows": [
                    {"response_value": "Neutral", "bucket": 1},
                    {"response_value": "Very Comfortable", "bucket": 2},
                ],
            }
        }
        df = pd.DataFrame(
            {
                "AI_Comfort": [
                    "Very Comfortable",
                    "Somewhat Comfortable",
                    "Neutral",
                    "Somewhat Uncomfortable",
                    "Very Uncomfortable",
                ]
            }
        )

        mappings = ensure_scale_mappings([question], df, saved_mapping)
        ordered_values = [
            row["response_value"]
            for row in sorted(mappings["AI_Comfort"]["rows"], key=lambda item: item["bucket"])
        ]

        self.assertEqual(
            ordered_values,
            [
                "Neutral",
                "Very Comfortable",
                "Somewhat Comfortable",
                "Somewhat Uncomfortable",
                "Very Uncomfortable",
            ],
        )


if __name__ == "__main__":
    unittest.main()
