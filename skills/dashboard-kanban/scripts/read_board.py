#!/usr/bin/env python3
"""Read an owned Kanban board without modifying cards or printing credentials."""
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

DEFAULT_URL = 'http://192.168.0.245:8020'
DEFAULT_ENV = '/proj/Dashboard/.env.kanban'


class ReadError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the bearer token to a redirect destination.
        return None


def read_environment(path):
    values = {}
    file = Path(path).expanduser()
    if file.exists():
        if file.stat().st_size > 65536:
            raise ReadError('The environment file is too large.')
        for line in file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, sep, value = line.partition('=')
            if key.strip() in ('DASHBOARD_KANBAN_API_KEY', 'DASHBOARD_KANBAN_API_USERNAME'):
                if not sep:
                    raise ReadError('Use NAME=value entries in the environment file.')
                values[key.strip()] = value.strip()
    # File values win, including an intentionally blank/unconfigured key.
    token = values.get('DASHBOARD_KANBAN_API_KEY', os.environ.get('DASHBOARD_KANBAN_API_KEY', ''))
    if not token:
        raise ReadError('Set DASHBOARD_KANBAN_API_KEY in the private environment file before reading a board.')
    if any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ReadError('Use an ASCII API key without whitespace.')
    return token


def origin(value):
    try:
        parts = urlsplit(value)
        port = parts.port  # Validate malformed ports without showing input secrets.
    except ValueError:
        raise ReadError('Invalid base URL.') from None
    if (parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or parts.path not in ('', '/', '/tools/kanban', '/tools/kanban/')):
        raise ReadError('Use the Dashboard origin, without credentials or query parameters, as --base-url.')
    return urlunsplit((parts.scheme, parts.netloc, '', '', ''))


class Client:
    def __init__(self, base_url, token):
        self.base_url = origin(base_url)
        self.token = token
        self.opener = build_opener(NoRedirect())

    def get(self, path):
        request = Request(self.base_url + path, headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json'})
        try:
            with self.opener.open(request, timeout=20) as response:
                if response.headers.get_content_type() != 'application/json':
                    raise ReadError('Expected JSON. Verify the host, API deployment, and authentication.')
                return json.load(response)
        except HTTPError as error:
            if error.code in (301, 302, 303, 307, 308):
                raise ReadError('Redirect refused. Set --base-url to the canonical Dashboard origin; the key was not forwarded.') from None
            if error.code in (401, 403):
                raise ReadError('Authentication failed. Check the key and its configured account on this server.') from None
            if error.code == 404:
                raise ReadError('Board/item or API route not found. Verify the board ID and deploy the read API to this host.') from None
            raise ReadError(f'Dashboard API returned HTTP {error.code}.') from None
        except (URLError, TimeoutError, OSError):
            raise ReadError('Could not reach the Dashboard API within the request timeout.') from None
        except (ValueError, UnicodeError):
            raise ReadError('The Dashboard API returned invalid JSON.') from None


def select_board(boards, name, board_id):
    matches = [b for b in boards if b['id'] == board_id] if board_id is not None else [b for b in boards if b['name'].casefold() == name.casefold()]
    if not matches:
        raise ReadError('No matching board exists for this account.')
    if len(matches) != 1:
        raise ReadError('Multiple boards have this name. Use --list-boards and select --board-id explicitly.')
    return matches[0]


def filter_columns(board, requested):
    if not requested:
        return board, []
    ids, names = set(), []
    for name in requested:
        matches = [c for c in board['columns'] if c['name'].casefold() == name.casefold()]
        if len(matches) != 1:
            raise ReadError('A requested column is missing or ambiguous. Inspect the board before selecting columns.')
        ids.add(matches[0]['id'])
        names.append(matches[0]['name'])
    return {**board, 'items': [i for i in board['items'] if i['column_id'] in ids]}, names


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default=DEFAULT_URL)
    parser.add_argument('--env-file', default=DEFAULT_ENV)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--board', default='Dashboard')
    selection.add_argument('--board-id', type=int)
    parser.add_argument('--list-boards', action='store_true')
    parser.add_argument('--column', action='append', default=[], help='Exact column name; repeat to include more columns.')
    parser.add_argument('--item-id', type=int, help='Read fresh card details/history, after verifying board membership.')
    args = parser.parse_args(argv)
    try:
        base = origin(args.base_url)
        client = Client(base, read_environment(args.env_file))
        discovery = client.get('/api/tools/kanban/boards' + ('?' + urlencode({'name': args.board}) if args.board_id is None and not args.list_boards else ''))
        if args.list_boards:
            output = {'source': base, **discovery}
        else:
            selected = select_board(discovery['boards'], args.board, args.board_id)
            board = client.get(f"/api/tools/kanban/boards/{selected['id']}")['board']
            if board['id'] != selected['id']:
                raise ReadError('Board identity changed unexpectedly.')
            board, columns = filter_columns(board, args.column)
            output = {'source': base, 'selected_columns': columns, 'board': board}
            if args.item_id is not None:
                if not any(i['id'] == args.item_id for i in board['items']):
                    raise ReadError('The requested item is not in the selected board/columns.')
                item = client.get(f'/api/tools/kanban/items/{args.item_id}')['item']
                if item['board_id'] != board['id']:
                    raise ReadError('Item no longer belongs to this board.')
                output = {'source': base, 'board': {'id': board['id'], 'name': board['name']}, 'item': item}
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 0
    except (ReadError, OSError) as error:
        print(str(error) if isinstance(error, ReadError) else 'Could not read the private environment file.', file=sys.stderr)
        return 1
    except (KeyError, TypeError):
        print('Unexpected API response schema; verify the server version.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
