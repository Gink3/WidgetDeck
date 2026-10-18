"""Browser-only administrator mail controls; submission only queues mail."""
from functools import wraps

from flask import Blueprint, current_app, jsonify, make_response, redirect, render_template, request, session, url_for

from dashboard.auth import current_user
from dashboard.auth_security import valid_csrf
from . import MailError
from . import outbox

routes = Blueprint('mail_admin', __name__)


def administrator(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if (request.headers.get('Authorization', '').partition(' ')[0].lower() == 'bearer'
                or not session.get('user_id')):
            return jsonify(error='Sign in as an administrator.'), 401
        user = current_user()
        if user is None or not user['is_admin']:
            return jsonify(error='Administrator access required.'), 403
        if request.content_length is not None and request.content_length > 2*1024*1024:
            return jsonify(error='Submission is too large.'), 413
        if request.method != 'GET' and not valid_csrf():
            return jsonify(error='Reload the page and try again.'), 403
        response = make_response(view(*args, **kwargs))
        response.headers['Cache-Control'] = 'no-store'
        return response
    return wrapped


@routes.get('/admin/mail')
@administrator
def index():
    return render_template('mail_admin.html', messages=outbox.admin_messages(),
                           mail_enabled=current_app.extensions['dashboard_mail'].enabled,
                           queued=request.args.get('queued') == '1')


@routes.post('/admin/mail/test')
@administrator
def test_message():
    config = current_app.extensions['dashboard_mail']
    if not config.enabled:
        return jsonify(error='Email is not configured on this Dashboard.'), 400
    # Bound request parsing as well as the encoded mail size enforced by enqueue.
    if request.content_length is None or request.content_length > 2*1024*1024:
        return jsonify(error='Test submission is too large.'), 413
    try:
        outbox.enqueue('core/mail-admin', session['user_id'], config,
                       [request.form.get('recipient', '')], request.form.get('subject', ''),
                       request.form.get('text', ''), None, None)
    except MailError as error:
        return jsonify(error=str(error)), 400
    return redirect(url_for('mail_admin.index', queued=1), code=303)


@routes.post('/admin/mail/<ident>/retry')
@administrator
def retry(ident):
    if not current_app.extensions['dashboard_mail'].enabled:
        return jsonify(error='Email is not configured on this Dashboard.'), 400
    try:
        revision = int(request.form.get('revision', ''))
        outbox.reviewed_retry(ident, revision, session['user_id'],
                              request.form.get('acknowledge_uncertain') == 'yes')
    except (ValueError, MailError) as error:
        message = str(error) if isinstance(error, MailError) else 'Supply the current message revision.'
        return jsonify(error=message), 400
    return redirect(url_for('mail_admin.index', queued=1), code=303)


@routes.post('/admin/mail/retention')
@administrator
def retention():
    outbox.retain()
    return redirect(url_for('mail_admin.index'), code=303)
