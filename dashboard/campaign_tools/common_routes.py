import re
from flask import redirect, request, url_for


def named_values(key, fallback=()):
    return [value.strip()[:80] for value in request.form.getlist(key) if value.strip()][:20] or list(fallback)


def native_draft_redirect(endpoint, **values):
    """Echo a browser receipt only after the caller has persisted a native POST."""
    token = request.form.get('_draft_token', '')
    if re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', token):
        values['_draft_ack'] = token
    return redirect(url_for(endpoint, **values))
