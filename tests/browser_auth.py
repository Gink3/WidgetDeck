"""Fetch browser-form CSRF state for development-only HTTP fixtures."""
import html
import re

def auth_form(request, base):
    response=request.get(base+'/register')
    assert response.status==200
    match=re.search(r'name="csrf_token" value="([^"]+)"',response.text())
    assert match
    return {'csrf_token':html.unescape(match.group(1))}
