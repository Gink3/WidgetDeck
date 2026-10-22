"""Widget-defined actions share the account feed and the widget transaction."""
import tempfile
import unittest
from flask import g
from dashboard.activity import recent_activity
from dashboard.database import db
from dashboard.widgets import Context, Contributions, Manifest, WidgetError
from test_dashboard_tools import test_app
from test_widget_api import document


class WidgetActivityTests(unittest.TestCase):
    def test_custom_quantities_isolation_and_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            app=test_app(directory)
            state=Contributions()
            context=Context(Manifest.from_dict(document()),state)
            record=context.activity('painting','Painting',actions={
                'painted':{'label':'Painted','unit':'miniature','plural':'miniatures'}})
            with app.test_request_context():
                g.dashboard_user={'id':1}
                with db():record('painted','scheme-1','Space marine',quantity=2)
                event=recent_activity()[0]
                self.assertEqual((event['action'],event['added_lines'],event['count_unit']),('Painted',2,'miniatures'))
                with self.assertRaises(RuntimeError),db():
                    record('painted','scheme-2','Rolled back')
                    raise RuntimeError('Widget save failed')
                self.assertEqual(len(recent_activity()),1)
                for bad in (0,-1,True,1.5):
                    with self.assertRaises(ValueError):record('painted','x','Invalid',quantity=bad)
                with self.assertRaises(WidgetError):record('unknown','x','Unknown')
                g.dashboard_user={'id':2}
                self.assertEqual(recent_activity(),[])
                with db():record('painted','other','Other account')
                self.assertEqual(recent_activity()[0]['count_unit'],'miniature')

    def test_invalid_action_definitions_fail_before_registration(self):
        for definition in ({'label':'Played'}, {'label':'Played','unit':'lines'}, {'label':'','unit':'games'}):
            state=Contributions();context=Context(Manifest.from_dict(document()),state)
            with self.assertRaises(WidgetError):context.activity('games','Games',actions={'played':definition})
            self.assertEqual(state.activity,{})
