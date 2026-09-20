"""Two ways to prove who you are.

**People** sign in through Clerk in the browser and arrive with a session JWT.
**Machines** — the CLI, the MCP server, a cron job — carry an API key, because
no script is going to complete a sign-in flow.

Both land on the same user row, so budgets, history and limits do not care
which door you came through. A Clerk user is also issued an API key on first
sight, which is what makes "here is your key for the CLI" possible without a
second system.
"""

import base64
import logging
import os
from functools import cache

import jwt
from jwt import PyJWKClient

logger = logging.getLogger(__name__)

# Clerk's publishable key encodes the instance's frontend API domain, so the
# JWKS URL can be derived rather than configured twice. An explicit
# CLERK_JWKS_URL still wins, for proxied or custom domains.
CLERK_PUBLISHABLE_KEY = os.getenv("CLERK_PUBLISHABLE_KEY", "")
CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL", "")


class InvalidToken(ValueError):
    """The bearer token is not a session we will accept."""


def clerk_domain(publishable_key: str) -> str | None:
    """`pk_test_<base64 of "domain$">` → `domain`."""
    for prefix in ("pk_test_", "pk_live_"):
        if publishable_key.startswith(prefix):
            encoded = publishable_key.removeprefix(prefix)
            padded = encoded + "=" * (-len(encoded) % 4)
            try:
                return base64.b64decode(padded).decode().rstrip("$") or None
            except (ValueError, UnicodeDecodeError):
                return None
    return None


def jwks_url() -> str | None:
    if CLERK_JWKS_URL:
        return CLERK_JWKS_URL
    domain = clerk_domain(CLERK_PUBLISHABLE_KEY)
    return f"https://{domain}/.well-known/jwks.json" if domain else None


def clerk_is_configured() -> bool:
    """Without Clerk the app still works, on API keys alone — which is what
    self-hosting and local development use."""
    return jwks_url() is not None


@cache
def _jwk_client(url: str) -> PyJWKClient:
    # PyJWKClient caches the keys and refetches when it meets an unknown kid,
    # so a key rotation does not need a redeploy.
    return PyJWKClient(url, cache_keys=True, lifespan=3600)


def verify_clerk_token(token: str) -> dict:
    """Return the token's claims, or raise InvalidToken.

    Signature, expiry and not-before are all checked. Audience is not: Clerk
    session tokens do not carry one by default, and pretending to verify a
    claim that is absent is worse than not checking it.
    """
    url = jwks_url()
    if not url:
        raise InvalidToken("Clerk is not configured on this server")

    try:
        signing_key = _jwk_client(url).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False, "require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidToken(str(exc)) from exc
    except Exception as exc:  # network failure fetching JWKS, malformed URL
        logger.warning("could not verify token: %s: %s", type(exc).__name__, exc)
        raise InvalidToken("Could not verify the session") from exc


def email_from_claims(claims: dict) -> str:
    """Clerk can be configured to include the email in the session token; when
    it is not, fall back to something stable and unique so the user row can
    still be created. The subject is always present."""
    for key in ("email", "email_address", "primary_email_address"):
        value = claims.get(key)
        if isinstance(value, str) and "@" in value:
            return value
    return f"{claims['sub']}@clerk.local"
