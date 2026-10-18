import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

spec = importlib.util.spec_from_file_location('read_board', Path(__file__).resolve().parents[1] / 'skills/dashboard-kanban/scripts/read_board.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


class ReaderTests(unittest.TestCase):
    def test_private_environment_parsing_is_literal_and_does_not_execute(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / '.env'
            env.write_text('DASHBOARD_KANBAN_API_KEY=$(do-not-execute)\nDASHBOARD_KANBAN_API_USERNAME=Taylor\n')
            self.assertEqual(reader.read_environment(env), '$(do-not-execute)')
            env.write_text('DASHBOARD_KANBAN_API_KEY=\n')
            with patch.dict(os.environ, {'DASHBOARD_KANBAN_API_KEY': 'other-environment-key'}):
                with self.assertRaises(reader.ReadError):
                    reader.read_environment(env)

    def test_name_resolution_requires_unique_exact_match(self):
        boards = [{'id': 1, 'name': 'Dashboard'}, {'id': 2, 'name': 'Dashboard extra'}]
        self.assertEqual(reader.select_board(boards, 'dashboard', None)['id'], 1)
        with self.assertRaises(reader.ReadError):
            reader.select_board(boards + [{'id': 3, 'name': 'Dashboard'}], 'Dashboard', None)
        self.assertEqual(reader.select_board(boards, None, 2)['id'], 2)
        with self.assertRaises(reader.ReadError):
            reader.select_board(boards, 'Missing', None)

    def test_filtering_preserves_board_order_and_rejects_unknown_columns(self):
        board = {'columns': [{'id': 10, 'name': 'To do'}, {'id': 11, 'name': 'Done'}],
                 'items': [{'id': 4, 'column_id': 10}, {'id': 2, 'column_id': 10}, {'id': 3, 'column_id': 11}]}
        result, names = reader.filter_columns(board, ['to DO'])
        self.assertEqual([i['id'] for i in result['items']], [4, 2])
        self.assertEqual(names, ['To do'])
        with self.assertRaises(reader.ReadError):
            reader.filter_columns(board, ['Backlog'])

    def test_http_failures_never_print_server_echo_of_key_and_refuse_redirects(self):
        secret = 'private-test-key'
        client = reader.Client('http://127.0.0.1:8020', secret)
        for code in [301, 401, 404, 500]:
            with patch.object(client.opener, 'open', side_effect=HTTPError(client.base_url, code, secret, {}, None)):
                with self.assertRaises(reader.ReadError) as raised:
                    client.get('/api/tools/kanban/boards')
                self.assertNotIn(secret, str(raised.exception))
        self.assertIsNone(reader.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example'))
        with self.assertRaises(reader.ReadError):
            reader.origin('http://user:secret@server/')

    def test_cli_reads_snapshot_and_rejects_foreign_card_details(self):
        board = {'id': 7, 'name': 'Dashboard', 'columns': [{'id': 1, 'name': 'To do'}], 'items': [{'id': 8, 'column_id': 1, 'notes': 'Full notes'}]}
        responses = [{'boards': [{'id': 7, 'name': 'Dashboard'}]}, {'board': board}]
        output = io.StringIO()
        with patch.object(reader, 'read_environment', return_value='private'), patch.object(reader.Client, 'get', side_effect=responses), contextlib.redirect_stdout(output):
            self.assertEqual(reader.main(['--column', 'To do']), 0)
        self.assertEqual(json.loads(output.getvalue())['board']['items'][0]['notes'], 'Full notes')
        error = io.StringIO()
        with patch.object(reader, 'read_environment', return_value='private'), patch.object(reader.Client, 'get', side_effect=responses + [{'item': {'board_id': 99}}]), contextlib.redirect_stderr(error):
            self.assertEqual(reader.main(['--item-id', '8']), 1)
        self.assertNotIn('private', error.getvalue())
