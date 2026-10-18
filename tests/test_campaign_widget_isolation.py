"""Kanban can run without importing or creating other campaign utilities."""
import importlib
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask

from dashboard.auth import init_auth
from dashboard.campaign_tools import init_campaign_tools
from dashboard.database import db


class CampaignWidgetIsolationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.app = Flask(__name__, instance_path=self.folder.name)
        self.app.config['SECRET_KEY'] = 'isolated-test-secret'
        init_auth(self.app)

    def test_kanban_owns_only_its_schema_and_preserves_legacy_endpoints(self):
        def import_selected(name, package=None):
            self.assertNotIn('frostgrave', name)
            self.assertNotIn('rdt', name)
            return importlib.import_module(name, package)
        with patch('dashboard.campaign_tools.import_module', side_effect=import_selected), \
             patch('dashboard.campaign_tools.routes.import_module', side_effect=import_selected):
            init_campaign_tools(self.app, utilities=['kanban'])
        with self.app.app_context():
            tables = {r[0] for r in db().execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn('kanban_items', tables)
        self.assertNotIn('frostgrave_parties', tables)
        self.assertNotIn('rdt_tables', tables)
        self.assertIn('campaign_tools.kanban_create_item', self.app.view_functions)
        self.assertNotIn('campaign_tools.frostgrave', self.app.view_functions)
        self.assertNotIn('campaign_tools.rdt', self.app.view_functions)

    def test_legacy_combined_initialization_and_model_exports_remain_supported(self):
        from dashboard.campaign_tools import models
        from dashboard.campaign_tools.kanban_models import kanban_item, ItemConflict
        self.assertIs(models.kanban_item, kanban_item)
        self.assertIs(models.ItemConflict, ItemConflict)
        namespace = {}
        exec("from dashboard.campaign_tools.models import *", namespace)
        self.assertIs(namespace["kanban_item"], kanban_item)
        init_campaign_tools(self.app, utilities=["kanban"])
        for endpoint in ['campaign_tools.kanban']:
            self.assertIn(endpoint, self.app.view_functions)
        with self.app.app_context():
            self.assertIsNone(db().execute("SELECT name FROM sqlite_master WHERE name='frostgrave_parties'").fetchone())

    def test_invalid_selection_fails_before_schema_changes(self):
        with self.assertRaises(ValueError):
            init_campaign_tools(self.app, utilities=['kanban', 'unknown'])
        with self.app.app_context():
            self.assertIsNone(db().execute("SELECT name FROM sqlite_master WHERE name='kanban_boards'").fetchone())


if __name__ == '__main__':
    unittest.main()
