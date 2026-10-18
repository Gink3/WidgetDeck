"""Dependency ordering, version backtracking and import-free failure boundaries."""
import sys
import types
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask

from dashboard.widgets import Manifest, WidgetError, register
from dashboard.widgets.dependencies import dependency_order, resolve
from dashboard.widgets.sources import Candidate, Selection, Source
from test_widget_api import document


def candidate(ident, version='1.0.0', dependencies=None, provider='dashboard'):
    return Candidate(Manifest.from_dict({**document(), 'id': ident, 'version': version,
        'dependencies': dependencies or {}, 'provider': provider}), Source('local', '/tmp/widgets'))


class WidgetDependencyTests(unittest.TestCase):
    def application(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Flask(__name__, instance_path=directory.name)

    def test_dependencies_register_before_dependents(self):
        first = candidate('foundation')
        second = candidate('dependent', dependencies={'foundation': '>=1,<2'})
        self.assertEqual([m.id for m in dependency_order([second.manifest, first.manifest])],
                         ['foundation', 'dependent'])
        module = types.ModuleType('example_widget'); order = []
        module.register = lambda app, context: order.append(context.manifest.id)
        with patch.dict(sys.modules, example_widget=module):
            register(self.application(), [second.manifest, first.manifest])
        self.assertEqual(order, ['foundation', 'dependent'])

    def test_joint_resolution_backtracks_to_compatible_dependency_version(self):
        app = candidate('app', dependencies={'library': '>=1,<2'})
        old, new = candidate('library'), candidate('library', '2.0.0')
        selection = {'app': Selection('dashboard'), 'library': Selection('dashboard')}
        resolved = resolve([app, new, old], selection)
        self.assertEqual(resolved, [old, app])

    def test_joint_resolution_can_choose_older_dependent_release(self):
        old = candidate('app', '1.0.0', {'library': '>=1,<2'})
        new = candidate('app', '2.0.0', {'library': '>=2'})
        library = candidate('library')
        resolved = resolve([new, library, old], {'app': Selection('dashboard'), 'library': Selection('dashboard')})
        self.assertEqual(resolved, [library, old])

    def test_missing_dependencies_and_version_conflicts_fail_before_import(self):
        app = candidate('app', dependencies={'library': '>=2'})
        with patch('dashboard.widgets.import_module', side_effect=AssertionError('Imported code')):
            for manifests in [[app.manifest], [app.manifest, candidate('library').manifest]]:
                with self.assertRaises(WidgetError):
                    register(self.application(), manifests)
        with self.assertRaises(WidgetError):
            resolve([app, candidate('library')], {'app': Selection('dashboard'), 'library': Selection('dashboard')})

    def test_cycles_fail_without_importing_any_factory(self):
        a = candidate('a', dependencies={'b': '>=1'})
        b = candidate('b', dependencies={'a': '>=1'})
        with patch('dashboard.widgets.import_module', side_effect=AssertionError('Imported code')):
            with self.assertRaisesRegex(WidgetError, 'cycle'):
                register(self.application(), [a.manifest, b.manifest])
        with self.assertRaisesRegex(WidgetError, 'cycle'):
            resolve([a, b], {'a': Selection('dashboard'), 'b': Selection('dashboard')})

    def test_cycles_can_be_resolved_with_an_older_compatible_release(self):
        old = candidate('a')
        new = candidate('a', '2.0.0', {'b': '>=1'})
        b = candidate('b', dependencies={'a': '>=1'})
        self.assertEqual(resolve([new, old, b], {'a': Selection('dashboard'), 'b': Selection('dashboard')}), [old, b])

    def test_dependency_resolution_never_substitutes_provider(self):
        app = candidate('app', dependencies={'library': '>=2'})
        private = candidate('library', provider='personal')
        public = candidate('library', '2.0.0')
        with self.assertRaises(WidgetError):
            resolve([app, private, public], {'app': Selection('dashboard'), 'library': Selection('personal')})

    def test_parameter_names_cannot_hide_route_collisions(self):
        module = types.ModuleType('example_widget')
        module.register = lambda app, context: app.add_url_rule('/item/<other>', 'other', lambda other: other)
        app = self.application()
        app.add_url_rule('/item/<ident>', 'existing', lambda ident: ident)
        with patch.dict(sys.modules, example_widget=module), self.assertRaises(WidgetError):
            register(app, [candidate('app').manifest])


if __name__ == '__main__':
    unittest.main()
