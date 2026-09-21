"""Shared test helpers. pytest imports conftest.py automatically."""

import pytest
from langchain_core.messages import AIMessage

from dossier import learn, nodes


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
    """Install a FakeModel everywhere chat_model() is looked up.

    Each module imports the name into its own namespace, so patching one does
    not patch the other — which is exactly how a new module quietly starts
    making real API calls during tests.
    """

    def install(reply):
        model = FakeModel(reply)
        for module in (nodes, learn):
            monkeypatch.setattr(module, "chat_model", lambda *args, **kwargs: model)
        return model

    return install
