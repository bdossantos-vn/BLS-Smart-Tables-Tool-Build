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
        self.assertEqual(result.source_question_types["Content_Recall"], "Multi-Select")

        question_metadata = build_question_metadata(
            result.cleaned_df,
            result.question_labels,
            result.cell_column,
            result.source_answer_choices,
            result.source_question_types,
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
        self.assertEqual(result.source_question_types["Media_Consumption"], "Multi-Select")

        question_metadata = build_question_metadata(
            result.cleaned_df,
            result.question_labels,
            result.cell_column,
            result.source_answer_choices,
            result.source_question_types,
        )
        media_row = next(row for row in question_metadata if row["variable"] == "Media_Consumption")
        self.assertEqual(media_row["detected_type"], "Multi-Select")
        self.assertEqual(media_row["answer_choices_list"], ["Social Media", "Podcasts"])

    def test_sav_duplicate_numbered_options_collapse_to_unique_choices(self) -> None:
        dataframe = pd.DataFrame(
            {
                "ResponseId": ["R_1", "R_2", "R_3"],
                "Brand_Usage_2": ["", "1.0", ""],
                "Brand_Usage_10": ["1.0", "", "1.0"],
                "Brand_Usage_20": ["", "", "1.0"],
                "cell": ["Control", "Test", "Test"],
            }
        )
        question = "Which of the following AI tools have you used, if any? Please select all that apply."
        metadata = SimpleNamespace(
            column_names=["ResponseId", "Brand_Usage_2", "Brand_Usage_10", "Brand_Usage_20", "cell"],
            column_labels=[
                "Response ID",
                f"{question} - Selected Choice None of these",
                f"{question} - Selected Choice ChatGPT",
                f"{question} - Selected Choice None of these",
                "Cell",
            ],
            variable_value_labels={
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

        self.assertEqual(list(result.cleaned_df.columns), ["Brand_Usage", "cell"])
        self.assertEqual(
            result.cleaned_df["Brand_Usage"].tolist(),
            ["ChatGPT", "None of these", "ChatGPT; None of these"],
        )
        self.assertEqual(result.source_answer_choices["Brand_Usage"], ["None of these", "ChatGPT"])
        self.assertEqual(result.source_question_types["Brand_Usage"], "Multi-Select")

    def test_sav_shared_checkbox_prompt_collapse_without_select_all_hint(self) -> None:
        option_1 = (
            'I\'m navigating a lot of big "firsts" right now: first job, '
            "first apartment, first time managing money on my own"
        )
        option_2 = (
            "I'm usually one of the first in my group to know what's trending "
            "in pop culture, music, or shows"
        )
        option_3 = (
            "I'm always optimizing my routine with tech: the right apps, gadgets, "
            "or tools to make life easier"
        )
        none_option = "None of these really describe me"
        question = "Which of these describes you right now?"
        dataframe = pd.DataFrame(
            {
                "ResponseId": ["R_1", "R_2", "R_3"],
                "SELF_DESCRIPTION_1": [option_1, "", ""],
                "SELF_DESCRIPTION_2": ["", option_2, ""],
                "SELF_DESCRIPTION_3": ["", "", ""],
                "SELF_DESCRIPTION_4": ["", "", none_option],
                "cell": ["Control", "Test", "Test"],
            }
        )
        metadata = SimpleNamespace(
            column_names=[
                "ResponseId",
                "SELF_DESCRIPTION_1",
                "SELF_DESCRIPTION_2",
                "SELF_DESCRIPTION_3",
                "SELF_DESCRIPTION_4",
                "cell",
            ],
            column_labels=[
                "Response ID",
                f"{question} {option_1}",
                f"{question} {option_2}",
                f"{question} {option_3}",
                f"{question} {none_option}",
                "Cell",
            ],
            variable_value_labels={
                "SELF_DESCRIPTION_1": {1: option_1},
                "SELF_DESCRIPTION_2": {1: option_2},
                "SELF_DESCRIPTION_3": {1: option_3},
                "SELF_DESCRIPTION_4": {1: none_option},
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

        self.assertEqual(list(result.cleaned_df.columns), ["SELF_DESCRIPTION", "cell"])
        self.assertEqual(
            result.cleaned_df["SELF_DESCRIPTION"].tolist(),
            [option_1, option_2, none_option],
        )
        self.assertEqual(result.question_labels["SELF_DESCRIPTION"], question)
        self.assertEqual(
            result.source_answer_choices["SELF_DESCRIPTION"],
            [option_1, option_2, option_3, none_option],
        )
        self.assertEqual(result.source_question_types["SELF_DESCRIPTION"], "Multi-Select")

        question_metadata = build_question_metadata(
            result.cleaned_df,
            result.question_labels,
            result.cell_column,
            result.source_answer_choices,
            result.source_question_types,
        )
        self_description_row = next(row for row in question_metadata if row["variable"] == "SELF_DESCRIPTION")
        self.assertEqual(self_description_row["detected_type"], "Multi-Select")

    def test_sav_likert_statement_grid_does_not_collapse_as_checkbox_group(self) -> None:
        dataframe = pd.DataFrame(
            {
                "ResponseId": ["R_1", "R_2"],
                "Brand_Perceptions_1": ["Strongly agree", "Somewhat agree"],
                "Brand_Perceptions_2": ["Strongly disagree", "Neither agree nor disagree"],
                "cell": ["Control", "Test"],
            }
        )
        question = "To what extent do you agree or disagree with the following statements?"
        value_labels = {
            1: "Strongly agree",
            2: "Somewhat agree",
            3: "Neither agree nor disagree",
            4: "Somewhat disagree",
            5: "Strongly disagree",
        }
        metadata = SimpleNamespace(
            column_names=["ResponseId", "Brand_Perceptions_1", "Brand_Perceptions_2", "cell"],
            column_labels=[
                "Response ID",
                f"{question} - Yahoo Scout is a brand I feel good about using",
                f"{question} - Yahoo Scout is a brand I trust",
                "Cell",
            ],
            variable_value_labels={
                "Brand_Perceptions_1": value_labels,
                "Brand_Perceptions_2": value_labels,
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

        self.assertEqual(
            list(result.cleaned_df.columns),
            ["Brand_Perceptions_1", "Brand_Perceptions_2", "cell"],
        )


if __name__ == "__main__":
    unittest.main()
