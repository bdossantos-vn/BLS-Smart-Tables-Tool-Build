"""Regression checks for comma-bearing answer-choice labels."""

from __future__ import annotations

import unittest

import pandas as pd

from src.custom_vars import (
    _value_matches_all_selected_choices as custom_value_matches_all_selected_choices,
)
from src.custom_vars import (
    _value_matches_selected_choices as custom_value_matches_selected_choices,
)
from src.metadata import build_question_metadata, extract_answer_choices
from src.tables import (
    _value_matches_all_selected_choices as table_value_matches_all_selected_choices,
)
from src.tables import _value_matches_selected_choices as table_value_matches_selected_choices


CONTENT_TOOL_LABEL = "Thinking about the content you saw, what was the main way ChatGPT was being used?"
ANALYSIS = "Analysis and calculations (e.g. data analysis, spreadsheets, calculations)"
ADVICE = "Advice (e.g. beauty, financial, spiritual, career, legal)"
COMMERCE = "Commerce (e.g. product reviews, product specs, shopping decisions)"
CREATIVE = "Creative Media (e.g. generating or editing images, video, audio)"
SUPPORT = "Support (e.g. relationships, emotional support, coaching, goal setting)"
EDUCATION = "Education and learning (e.g. homework assignments, essay development/revisions)"
NONE = "None of these"


class MultiselectDetectionTest(unittest.TestCase):
    def test_comma_bearing_single_select_labels_stay_whole(self) -> None:
        df = pd.DataFrame(
            {
                "Content_Tool": [
                    ADVICE,
                    COMMERCE,
                    ANALYSIS,
                    CREATIVE,
                    SUPPORT,
                    EDUCATION,
                    ADVICE,
                    COMMERCE,
                ] * 4
            }
        )

        metadata = build_question_metadata(df, {"Content_Tool": CONTENT_TOOL_LABEL})[0]

        self.assertEqual(metadata["detected_type"], "Single-Select")
        self.assertIn(SUPPORT, metadata["answer_choices_list"])
        self.assertIn(EDUCATION, metadata["answer_choices_list"])
        self.assertNotIn("emotional support", metadata["answer_choices_list"])
        self.assertNotIn("goal setting)", metadata["answer_choices_list"])
        self.assertNotIn("essay development/revisions)", metadata["answer_choices_list"])

    def test_comma_delimited_multi_select_preserves_parenthetical_commas(self) -> None:
        values = pd.Series(
            [
                f"{ANALYSIS}, {CREATIVE}",
                f"{ANALYSIS}, {SUPPORT}",
                f"{CREATIVE}, {NONE}",
                SUPPORT,
            ]
        )

        choices = extract_answer_choices(values, "Multi-Select", "Please select all that apply.")

        self.assertEqual(choices, [ANALYSIS, CREATIVE, SUPPORT, NONE])
        self.assertNotIn("spreadsheets", choices)
        self.assertNotIn("video", choices)
        self.assertNotIn("coaching", choices)

    def test_matching_uses_full_comma_bearing_choices_not_fragments(self) -> None:
        value = f"{ANALYSIS}, {SUPPORT}"

        self.assertTrue(table_value_matches_selected_choices(value, [SUPPORT]))
        self.assertTrue(custom_value_matches_selected_choices(value, [SUPPORT]))
        self.assertTrue(table_value_matches_all_selected_choices(value, [ANALYSIS, SUPPORT]))
        self.assertTrue(custom_value_matches_all_selected_choices(value, [ANALYSIS, SUPPORT]))

        self.assertFalse(table_value_matches_selected_choices(SUPPORT, ["coaching"]))
        self.assertFalse(custom_value_matches_selected_choices(SUPPORT, ["coaching"]))


if __name__ == "__main__":
    unittest.main()
