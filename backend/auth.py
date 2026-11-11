"""Shared HTTP and live subscription authentication."""

import jwt


def token_user(db, token, secret):
    payload = jwt.decode(token, secret, algorithms=["HS256"],
                         options={"require": ["exp", "user_id", "username", "token_version"]})
    user = db.get_user_by_id(payload["user_id"])
    if (not user or user["username"] != payload["username"] or user["status"] != "active"
            or user["token_version"] != payload["token_version"]):
        raise jwt.InvalidTokenError("Account or token has been revoked")
    return user
