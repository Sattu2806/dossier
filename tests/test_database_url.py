"""The connection string a platform gives you must just work.

A real deploy failed with `ModuleNotFoundError: No module named 'psycopg2'`
because the URL said `postgresql://`, which SQLAlchemy maps to psycopg2. We
ship psycopg 3. Documenting "edit the scheme by hand" was not a fix.
"""

import pytest

from dossier.db import normalise_url

NEON = "postgresql://user:pw@ep-cool-name.eu-central-1.aws.neon.tech/dossier?sslmode=require"


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        # What Neon, Render and Railway actually put on the clipboard
        (NEON, "postgresql+psycopg://user:pw@ep-cool-name.eu-central-1.aws.neon.tech/dossier?sslmode=require"),
        # Legacy Heroku scheme, which SQLAlchemy refuses outright
        ("postgres://user:pw@host:5432/db", "postgresql+psycopg://user:pw@host:5432/db"),
        # Already correct: left alone
        ("postgresql+psycopg://user:pw@host:5432/db", "postgresql+psycopg://user:pw@host:5432/db"),
        # Someone else's driver choice is respected, not overridden
        ("postgresql+asyncpg://user:pw@host/db", "postgresql+asyncpg://user:pw@host/db"),
        # SQLite untouched
        ("sqlite:///data/dossier.db", "sqlite:///data/dossier.db"),
    ],
)
def test_urls_are_normalised_to_a_driver_we_ship(given, expected):
    assert normalise_url(given) == expected


def test_query_parameters_survive():
    # sslmode=require is not optional on Neon; losing it breaks the connection.
    assert normalise_url(NEON).endswith("?sslmode=require")
