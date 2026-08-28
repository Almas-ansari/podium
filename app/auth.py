"""Google sign-in, and the session helpers that decide who is looking.

The account belongs to the parent. Children are profiles underneath it and never
hold credentials of their own - a 7 year old should not have a password, and a
13 year old should not be the party consenting to their own data collection.
"""
import logging
from typing import Any, Optional

from authlib.integrations.starlette_client import OAuth
from fastapi import Request

from . import db
from .config import (
    ALLOW_DEV_LOGIN, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, google_configured,
)

log = logging.getLogger(__name__)

GOOGLE_METADATA = "https://accounts.google.com/.well-known/openid-configuration"

PARENT_KEY = "parent_id"
CHILD_KEY = "child_id"

oauth = OAuth()

if google_configured():
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url=GOOGLE_METADATA,
        client_kwargs={"scope": "openid email profile"},
    )
else:
    log.warning(
        "Google sign-in is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET "
        "in .env, or set ALLOW_DEV_LOGIN=true for a local-only sign-in."
    )


# --- who is signed in -----------------------------------------------------

def parent_id(request: Request) -> Optional[str]:
    return request.session.get(PARENT_KEY)


def current_parent(request: Request) -> Optional[Any]:
    pid = parent_id(request)
    return db.get_parent(pid) if pid else None


def sign_in(request: Request, parent_row: Any) -> None:
    request.session[PARENT_KEY] = parent_row["id"]
    request.session.pop(CHILD_KEY, None)


def sign_out(request: Request) -> None:
    request.session.clear()


# --- which child is practising --------------------------------------------

def active_child(request: Request) -> Optional[Any]:
    """The selected profile, re-checked against the signed-in parent every time.

    Scoping the lookup by parent means a stale or tampered cookie can never
    surface another family's child.
    """
    pid = parent_id(request)
    if not pid:
        return None

    cid = request.session.get(CHILD_KEY)
    if cid:
        child = db.get_child(cid, pid)
        if child:
            return child
        request.session.pop(CHILD_KEY, None)

    # Fall back to the only child, if there is exactly one. With several,
    # the parent has to pick, so nobody's baseline gets polluted by accident.
    children = db.list_children(pid)
    if len(children) == 1:
        request.session[CHILD_KEY] = children[0]["id"]
        return children[0]
    return None


def select_child(request: Request, child_id: str) -> bool:
    pid = parent_id(request)
    if not pid or not db.get_child(child_id, pid):
        return False
    request.session[CHILD_KEY] = child_id
    return True


def dev_login_available() -> bool:
    return ALLOW_DEV_LOGIN and not google_configured()
