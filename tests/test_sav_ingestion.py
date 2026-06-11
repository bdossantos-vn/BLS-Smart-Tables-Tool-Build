"""Regression checks for SPSS SAV intake metadata."""

from __future__ import annotations

from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

import pandas as pd

from src.cleaning import ingest_qualtrics_sav
from src.metadata import build_question_metadata


class _UploadedFile:
    name = "survey.sav"

    def getvalue(self) -> bytes:
        return b"fake sav bytes"


class SavIngestionTest(unittest.TestCase):
    def test_sav_value_labels_seed_unobserved_answer_choices(self) -> None:
        dataframe = pd.DataFrame(
            {
                "ResponseId": ["R_1", "R_2"],
                "Feature Awareness": ["Search", "Images"],
                "cell": ["Control", "Test"],
            }
        )
        metadata = SimpleNamespace(
            column_names=["ResponseId", "Feature Awareness", "cell"],
            column_labels=[
                "Response ID",
                "Before today, which features were you aware of?",
                "Cell",
            ],
            variable_value_labels={
                "Feature Awareness": {
                    1: "Search",
                    2: "Images",
                    3: "Voice",
                },
                "cell": {
                    1: "Control",
                    2: "Test",
                },
            },
        )

        def fake_read_sav(path: str, **kwargs: object) -> tuple[pd.DataFrame, SimpleNamespace]:
            self.assertTrue(path.endswith(".sav"))
            self.assertTrue(kwargs["apply_value_formats"])
            return dataframe, metadata

        fake_pyreadstat = SimpleNamespace(read_sav=fake_read_sav)
        with patch.dict(sys.modules, {"pyreadstat": fake_pyreadstat}):
            result = ingest_qualtrics_sav(_UploadedFile())

        self.assertEqual(list(result.cleaned_df.columns), ["Feature Awareness", "cell"])
        self.assertEqual(
            result.question_labels["Feature Awareness"],
            "Before today, which features were you aware of?",
        )
        self.assertEqual(result.source_answer_choices["Feature Awareness"], ["Search", "Images", "Voice"])

        question_metadata = build_question_metadata(
            result.cleaned_df,
            result.question_labels,
            result.cell_column,
            result.source_answer_choices,
        )
        feature_row = next(row for row in question_metadata if row["variable"] == "Feature Awareness")
        self.assertEqual(feature_row["answer_choices_list"], ["Search", "Images", "Voice"])

    def test_sav_mr_sets_collapse_checkbox_columns_to_one_multiselect_question(self) -> None:
        dataframe = pd.DataFrame(
            {
                "ResponseId": ["R_1", "R_2", "R_3"],
                "Content_Recall_1": ["Selected", "Not selected", "Selected"],
                "Content_Recall_2": ["Not selected", "Selected", "Selected"],
                "cell": ["Control", "Test", "Test"],
            }
        )
        question = "In the past 2 weeks, which types of content have you seen on social media?"
        metadata = SimpleNamespace(
            column_names=["ResponseId", "Content_Recall_1", "Content_Recall_2", "cell"],
            column_labels=[
                "Response ID",
                "Cooking",
                "Fitness",
                "Cell",
            ],
            variable_value_labels={
                "Content_Recall_1": {0: "Not selected", 1: "Selected"},
                "Content_Recall_2": {0: "Not selected", 1: "Selected"},
                "cell": {1: "Control", 2: "Test"},
            },
            mr_sets={
                "$Content_Recall": {
                    "type": "D",
                    "is_dichotomy": True,
                    "counted_value": 1,
                    "label": question,
                    "variable_list": ["Content_Recall_1", "Content_Recall_2"],
                }
            },
        )

        def fake_read_sav(path: str, **kwargs: object) -> tuple[pd.DataFrame, SimpleNamespace]:
            self.assertTrue(path.endswith(".sav"))
            self.assertTrue(kwargs["apply_value_formats"])
            return dataframe, metadata

        fake_pyreadstat = SimpleNamespace(read_sav=fake_read_sav)
        with patch.dict(sys.modules, {"pyreadstat": fake_pyreadstat}):
            result = ingest_qualtrics_sav(_UploadedFile())

        self.assertEqual(list(result.cleaned_df.columns), ["Content_Recall", "cell"])
        self.assertEqual(
            result.cleaned_df["Content_Recall"].tolist(),
            ["Cooking", "Fitness", "Cooking; Fitness"],
        )
        self.assertEqual(result.question_labels["Content_Recall"], question)
        self.assertEqual(result.source_answer_choices["Content_Recall"], ["Cooking", "Fitness"])

        question_metadata = build_question_metadata(
            result.cleaned_df,
            result.question_labels,
            result.cell_column,
            result.source_answer_choices,
        )
        content_row = next(row for row in question_metadata if row["variable"] == "Content_Recall")
        self.assertEqual(content_row["detected_type"], "Multi-Select")
        self.assertEqual(content_row["answer_choices_list"], ["Cooking", "Fitness"])

    def test_sav_numbered_select_all_labels_collapse_without_mr_sets(self) -> None:
        dataframe = pd.DataFrame(
            {
                "ResponseId": ["R_1", "R_2", "R_3"],
                "Media_Consumption_1": ["Social Media", "", "Social Media"],
                "Media_Consumption_8": ["", "Podcasts", "Podcasts"],
                "cell": ["Control", "Test", "Test"],
            }
        )
        question = "What types of content do you consume online? Please select all that apply."
        metadata = SimpleNamespace(
            column_names=["ResponseId", "Media_Consumption_1", "Media_Consumption_8", "cell"],
            column_labels=[
                "Response ID",
                f"{question} Social Media",
                f"{question} Podcasts",
                "Cell",
            ],
            variable_value_labels={
                "Media_Consumption_1": {1: "Social Media"},
                "Media_Consumption_8": {1: "Podcasts"},
                "cell": {1: "Control", 2: "Test"},
            },
            mr_sets={},
        )

        def fake_read_sav(path: str, **kwargs: object) -> tuple[pd.DataFrame, SimpleNamespace]:
            self.assertTrue(path.endswith(".sav"))
            self.assertTrue(kwargs["apply_value_formats"])
            return dataframe, metadata

        fake_pyreadstat = SimpleNamespace(read_sav=fake_read_sav)
        with patch.dict(sys.modules, {"pyreadstat": fake_pyreadstat}):
            result = ingest_qualtrics_sav(_UploadedFile())

        self.assertEqual(list(result.cleaned_df.columns), ["Media_Consumption", "cell"])
        self.assertEqual(
            result.cleaned_df["Media_Consumption"].tolist(),
            ["Social Media", "Podcasts", "Social Media; Podcasts"],
        )
        self.assertEqual(result.question_labels["Media_Consumption"], question)
        self.assertEqual(result.source_answer_choices["Media_Consumption"], ["Social Media", "Podcasts"])

        question_metadata = build_question_metadata(
            result.cleaned_df,
            result.question_labels,
            result.cell_column,
            result.source_answer_choices,
        )
        media_row = next(row for row in question_metadata if row["variable"] == "Media_Consumption")
        self.assertEqual(media_row["detected_type"], "Multi-Select")
        self.assertEqual(media_row["answer_choices_list"], ["Social Media", "Podcasts"])


if __name__ == "__main__":
    unittest.main()
