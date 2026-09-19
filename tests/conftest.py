"""Shared test helpers. pytest imports conftest.py automatically."""

import pytest
from langchain_core.messages import AIMessage

from dossier import nodes


class FakeModel:
    """Stands in for chat_model(): records what was sent, returns a canned reply.

    Handles both node styles:
    - structured (`with_structured_output(Schema)`) → reply is a dict of fields
    - prose (`invoke`) → reply is a string, returned as an AIMessage
    """

    def __init__(self, reply):
        self.reply = reply
        self.messages = None
        self.schema = None

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    def invoke(self, messages):
        self.messages = messages
        if self.schema is not None:
            return self.schema(**self.reply)
        return AIMessage(content=self.reply)

    @property
    def prompt(self) -> str:
        """Everything the node sent, as one string, for `in` assertions."""
        return "\n".join(message.text for message in self.messages)


@pytest.fixture
def fake_model(monkeypatch):
    """Install a FakeModel where the nodes look chat_model() up."""

    def install(reply):
        model = FakeModel(reply)
        monkeypatch.setattr(nodes, "chat_model", lambda *args, **kwargs: model)
        return model

    return install
