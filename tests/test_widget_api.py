"""Widget metadata and trusted registration boundaries."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from dashboard.widgets import Manifest, WidgetError, read_manifest, register


def document(**overrides):
    return dict(schema_version=1, id='example', provider='dashboard', name='Example',
                version='1.0.0', core_api='>=1,<2', entry_point='example_widget:register', **overrides)


class WidgetApiTests(unittest.TestCase):
    def application(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Flask(__name__, instance_path=directory.name)

    def test_manifest_roundtrip_is_declarative(self):
        with patch('dashboard.widgets.import_module', side_effect=AssertionError('Imported code')):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'widget.json'
                path.write_text(json.dumps(document()))
                manifest = read_manifest(path)
                self.assertEqual(manifest.identity, 'dashboard/example')
                self.assertEqual(Manifest.from_dict(manifest.to_dict()), manifest)

    def test_invalid_metadata_is_rejected_without_execution(self):
        examples = [dict(schema_version=True), dict(id='../escape'), dict(provider='Upper'),
                    dict(version='1.0'), dict(core_api='broken'), dict(entry_point='code()'),
                    dict(dependencies={'example': '>=1'}), dict(dependencies={'other': ''}),
                    dict(capabilities=['mail', 'mail']), dict(unknown=True)]
        for override in examples:
            with self.subTest(override=override), self.assertRaises(WidgetError):
                Manifest.from_dict({**document(), **override})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'widget.json'
            path.write_text('{"id":"first","id":"second"}')
            with self.assertRaisesRegex(WidgetError, 'Duplicate'):
                read_manifest(path)

    def test_registration_provides_hooks_and_preserves_routes(self):
        module = types.ModuleType('example_widget')
        def factory(app, context):
            app.add_url_rule('/legacy-url', 'legacy_endpoint', lambda: 'existing')
            context.navigation('Tools', 'Example', 'legacy_endpoint')
            context.api_service('example_service', 'Example API', '/api/example/')
            context.settings('example/settings.html', lambda payload, settings: settings)
            context.search('examples', lambda: [])
            context.resolve(lambda ident, kind: None)
            context.activity('example', 'Examples')
            self.assertEqual(context.capabilities, frozenset({'mail'}))
        module.register = factory
        app = self.application()
        with patch.dict(sys.modules, example_widget=module):
            state = register(app, [Manifest.from_dict(document(capabilities=['mail']))],
                             capabilities={'example': ['mail']})
        self.assertTrue(state['ready'])
        self.assertEqual(app.test_client().get('/legacy-url').data, b'existing')
        contributions = state['contributions']
        self.assertEqual(contributions.services['example_service']['prefix'], '/api/example/')
        self.assertEqual(contributions.navigation[0]['id'], 'example')
        self.assertIn('examples', contributions.search)
        self.assertIn('example', contributions.resolvers)
        with self.assertRaises(WidgetError):
            register(app, [])

    def test_all_metadata_is_checked_before_any_widget_import(self):
        valid = Manifest.from_dict(document())
        bad = Manifest.from_dict({**document(), 'id': 'other', 'core_api': '>=2'})
        with patch('dashboard.widgets.import_module', side_effect=AssertionError('Imported code')):
            with self.assertRaisesRegex(WidgetError, 'incompatible'):
                register(self.application(), [valid, bad])
            with self.assertRaisesRegex(WidgetError, 'undeclared'):
                register(self.application(), [valid], capabilities={'example': ['mail']})

    def test_route_and_service_collisions_fail_closed(self):
        for mode in ['route', 'service']:
            module = types.ModuleType('example_widget')
            def factory(app, context):
                if mode == 'route':
                    app.add_url_rule('/same', 'another', lambda: 'second')
                else:
                    context.api_service('one', 'One', '/api/example/')
                    context.api_service('two', 'Two', '/api/example/nested/')
            module.register = factory
            app = self.application()
            app.add_url_rule('/same', 'existing', lambda: 'first')
            with patch.dict(sys.modules, example_widget=module), self.assertRaises(WidgetError):
                register(app, [Manifest.from_dict(document())])
            self.assertFalse(app.extensions['dashboard_widgets']['ready'])

    def test_widget_service_cannot_authorize_core_routes(self):
        module = types.ModuleType('example_widget')
        module.register = lambda app, context: context.api_service('broad', 'Broad', '/api/')
        app = self.application()
        app.add_url_rule('/api/core/settings', 'core_settings', lambda: 'private core')
        with patch.dict(sys.modules, example_widget=module), self.assertRaises(WidgetError):
            register(app, [Manifest.from_dict(document())])
        self.assertFalse(app.extensions['dashboard_widgets']['ready'])


if __name__ == '__main__':
    unittest.main()
