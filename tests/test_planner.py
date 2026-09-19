"""Unit tests for the planner node's own logic, with a fake model.

What these CAN check: the messages we send, and how we handle what comes back.
What they CANNOT check: whether the sub-questions are any good. That depends on
the real model and is measured by evals, not tests.
"""

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage

from dossier import nodes
from dossier.prompts import PLANNER_SYSTEM


def test_instructions_go_in_system_message_and_topic_in_user_message(fake_model):
    model = fake_model({"sub_questions": ["What is X?", "Why X?", "When X?"]})
    nodes.planner({"topic": "solid-state batteries"})

    system, user = model.messages
    assert isinstance(system, SystemMessage) and system.content == PLANNER_SYSTEM
    assert isinstance(user, HumanMessage) and "solid-state batteries" in user.content
    assert model.schema is nodes.Plan


def test_schema_sent_to_model_contains_only_model_facing_text():
    # Pydantic copies the class docstring and Field descriptions into the JSON
    # schema, and that schema is sent to the LLM. Guard against developer notes
    # leaking into the prompt.
    schema = nodes.Plan.model_json_schema()
    assert schema["description"] == "A research plan for the given topic."
    assert schema["properties"]["sub_questions"]["description"] == "3 to 5 self-contained research sub-questions"


def test_returns_only_sub_questions(fake_model):
    fake_model({"sub_questions": ["What is X?", "Why X?", "When X?"]})
    assert nodes.planner({"topic": "X"}) == {"sub_questions": ["What is X?", "Why X?", "When X?"]}


def test_cleans_whitespace_blanks_and_duplicates(fake_model):
    fake_model({"sub_questions": ["  What is X?  ", "", "what is x?", "Why X?"]})
    assert nodes.planner({"topic": "X"})["sub_questions"] == ["What is X?", "Why X?"]


def test_trims_to_max_sub_questions(fake_model):
    fake_model({"sub_questions": [f"Question {i}?" for i in range(8)]})
    assert len(nodes.planner({"topic": "X"})["sub_questions"]) == nodes.MAX_SUB_QUESTIONS


def test_empty_plan_raises_retryable_error(fake_model):
    fake_model({"sub_questions": ["   ", ""]})
    with pytest.raises(OutputParserException):
        nodes.planner({"topic": "X"})
