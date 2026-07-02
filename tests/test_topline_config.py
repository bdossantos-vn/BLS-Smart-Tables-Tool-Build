"""Regression checks for topline configuration helpers."""

from __future__ import annotations

import unittest

from app.pages.page_11_topline_config import (
    _serialize_display_choices,
    _topline_available_choices,
    _topline_choice_display_labels,
)


class ToplineChoiceDisplayTest(unittest.TestCase):
    def test_net_choices_display_underlying_response_labels(self) -> None:
        question = {
            "answer_choices_list": [
                "Definitely would buy",
                "Probably would buy",
                "Might or might not buy",
            ],
            "choice_expansion_map": {
                "T2B": ["Definitely would buy", "Probably would buy"],
            },
        }

        choices = _topline_available_choices(question)
        display_labels = _topline_choice_display_labels(question)

        self.assertEqual(choices, ["T2B"])
        self.assertEqual(display_labels["T2B"], "T2B: Definitely would buy, Probably would buy")
        self.assertEqual(
            _serialize_display_choices(choices, display_labels),
            "T2B: Definitely would buy, Probably would buy",
        )

    def test_raw_choices_display_as_themselves(self) -> None:
        question = {
            "answer_choices_list": ["Control", "Test"],
            "choice_expansion_map": {},
        }

        display_labels = _topline_choice_display_labels(question)

        self.assertEqual(display_labels, {"Control": "Control", "Test": "Test"})


if __name__ == "__main__":
    unittest.main()
