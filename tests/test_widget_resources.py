"""Extracted resources preserve old URLs without allowing core asset replacement."""
from pathlib import Path
import tempfile
import unittest
from flask import Flask, render_template
from dashboard.widgets.resources import mount_resources
from dashboard.widgets.manifest import WidgetError

class WidgetResourceTests(unittest.TestCase):
    def test_template_and_legacy_static_url_remain_available(self):
        with tempfile.TemporaryDirectory() as scratch:
            root=Path(scratch); core=root/'core'; widget=root/'widget'
            for package in (core,widget):
                (package/'static').mkdir(parents=True)
                (package/'templates').mkdir()
            (core/'static/core.js').write_text('core')
            (core/'templates/base.html').write_text('base {% block body %}{% endblock %}')
            (widget/'static/legacy.js').write_text('private')
            (widget/'templates/widget.html').write_text('{% extends "base.html" %}{% block body %}widget{% endblock %}')
            app=Flask(__name__,root_path=str(core))
            mount_resources(app,widget);mount_resources(app,widget)
            with app.test_request_context():
                self.assertEqual(render_template('widget.html'),'base widget')
            client=app.test_client()
            with client.get('/static/core.js') as response:
                self.assertEqual(response.text,'core')
            with client.get('/static/legacy.js') as response:
                self.assertEqual(response.text,'private')
            self.assertEqual(client.get('/static/../widget/templates/widget.html').status_code,404)
            self.assertEqual(len(app.extensions['dashboard_widget_resource_roots']),1)
    def test_conflicting_assets_fail_before_replacing_existing_mapping(self):
        with tempfile.TemporaryDirectory() as scratch:
            root=Path(scratch);(root/'static').mkdir();(root/'static/same.js').write_text('core')
            widget=root/'widget';(widget/'static').mkdir(parents=True);(widget/'static/same.js').write_text('widget')
            app=Flask(__name__,root_path=str(root))
            with self.assertRaisesRegex(WidgetError,'conflicts with core'):
                mount_resources(app,widget)
            with app.test_client().get('/static/same.js') as response:
                self.assertEqual(response.text,'core')

if __name__=='__main__':unittest.main()
