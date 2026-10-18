from flask import request


def named_values(key, fallback=()):
    return [value.strip()[:80] for value in request.form.getlist(key) if value.strip()][:20] or list(fallback)
