#!/usr/bin/env python3
"""Create planned cards and add an effort without overwriting existing work.

Dry-run by default. Rerun with --apply after deploying effort support to attach
native effort tags. Stable note markers prevent duplicate cards on explicit reruns;
ambiguous writes stop immediately so the next run can inspect server state first.
"""
import argparse
import json
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request


class ApiError(RuntimeError):
    def __init__(self,status):
        self.status=status
        super().__init__(f'Kanban API returned HTTP {status}; no automatic retry.')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class Client:
    def __init__(self,base_url,token):
        parts=urllib.parse.urlsplit(base_url)
        if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password or parts.path not in ('','/') or parts.query or parts.fragment:
            raise ValueError('Use a server origin without credentials, path or query.')
        self.base=base_url.rstrip('/');self.token=token
        self.opener=urllib.request.build_opener(NoRedirect())

    def request(self,method,path,payload=None):
        req=urllib.request.Request(self.base+path,method=method,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={'Authorization':'Bearer '+self.token,'Accept':'application/json','Content-Type':'application/json'})
        try:
            with self.opener.open(req,timeout=25) as response:
                if response.status==204:return None
                if response.headers.get_content_type()!='application/json':raise ValueError('Expected a JSON API response.')
                return json.load(response)
        except urllib.error.HTTPError as error:raise ApiError(error.code) from None
        except (urllib.error.URLError,TimeoutError,OSError):
            raise RuntimeError('Request failed or timed out. Inspect server state or rerun explicitly; writes were not retried.') from None


def load_token(path):
    values={}
    for raw in Path(path).read_text().splitlines():
        key,sep,value=raw.strip().partition('=');key=key.strip()
        if sep and key in ('DASHBOARD_KANBAN_API_KEY','DASHBOARD_API_KEY'):
            value=value.strip()
            if len(value)>=2 and value[0]==value[-1] and value[0] in ('"',"'"):value=value[1:-1]
            values[key]=value
    token=values.get('DASHBOARD_KANBAN_API_KEY',values.get('DASHBOARD_API_KEY',''))
    if not token or any(ord(c)<33 or ord(c)>126 for c in token):raise ValueError('Configure an ASCII Kanban API key in the private environment file.')
    return token


def validate_plan(plan):
    if plan.get('schema_version')!=1:raise ValueError('Unsupported plan schema.')
    rows=plan['items'];keys=[r['key'] for r in rows]
    if not rows or len(set(keys))!=len(keys) or keys[0]!='overview':raise ValueError('Supply unique item keys with overview first.')
    for row in rows:
        if not 1<=len(row['title'])<=160 or not 1<=len(row['notes'])<=4000 or row['column'] not in ('To do','Backlog'):
            raise ValueError('Invalid planned card title, notes or column.')
        if any(k not in keys or k==row['key'] for k in row['depends_on']):raise ValueError('Invalid planned dependency.')
    graph={r['key']:r['depends_on'] for r in rows}
    visiting,visited=set(),set()
    def visit(key):
        if key in visiting:raise ValueError('Planned dependencies cannot form a cycle.')
        if key in visited:return
        visiting.add(key)
        for dependency in graph[key]:visit(dependency)
        visiting.remove(key);visited.add(key)
    for key in graph:visit(key)
    if len(rows)>40:raise ValueError('Split larger plans to retain room for existing links.')
    return plan


def sync(client,plan,apply=False):
    validate_plan(plan)
    boards=client.request('GET','/api/tools/kanban/boards')['boards']
    target=[b for b in boards if b['name'].casefold()==plan['board'].casefold()]
    if len(target)!=1:raise ValueError('Plan board is missing or ambiguous; no writes performed.')
    board_id=target[0]['id'];snapshot=client.request('GET',f'/api/tools/kanban/boards/{board_id}')['board']
    columns={}
    for name in {r['column'] for r in plan['items']}:
        matches=[c['id'] for c in snapshot['columns'] if c['name'].casefold()==name.casefold()]
        if len(matches)!=1:raise ValueError('Required plan column is missing or ambiguous; no writes performed.')
        columns[name]=matches[0]
    all_items=list(snapshot['items'])
    for board in boards:
        if board['id']!=board_id:all_items.extend(client.request('GET',f"/api/tools/kanban/boards/{board['id']}")['board']['items'])
    found={}
    for row in plan['items']:
        marker=f"[plan:{plan['plan_id']}:{row['key']}]"
        matches=[i for i in all_items if marker in i['notes']]
        if len(matches)>1:raise ValueError('Duplicate plan markers found; reconcile before applying.')
        found[row['key']]=matches[0]['id'] if matches else None
    # Older servers authenticate only known routes, so probing an unknown route
    # may return 401. Discover support from the additive board snapshot instead;
    # never reinterpret a real authentication failure as feature unavailability.
    native='efforts' in snapshot
    efforts=client.request('GET','/api/tools/kanban/efforts')['efforts'] if native else []
    matches=[e for e in efforts if e['name'].casefold()==plan['effort'].casefold()]
    if len(matches)>1:raise ValueError('Effort name is ambiguous.')
    effort=matches[0] if matches else None
    if not apply:return dict(mode='dry-run',board_id=board_id,native_efforts=native,existing=sum(i is not None for i in found.values()),to_create=sum(i is None for i in found.values()))
    if native and effort is None:effort=client.request('POST','/api/tools/kanban/efforts',{'name':plan['effort']})['effort']
    for row in plan['items']:
        if found[row['key']] is None:
            notes=f"Effort: {plan['effort']}\n[plan:{plan['plan_id']}:{row['key']}]\n\n{row['notes']}"
            payload=dict(title=row['title'],notes=notes,column_id=columns[row['column']])
            if effort:payload['effort_ids']=[effort['id']]
            found[row['key']]=client.request('POST',f'/api/tools/kanban/boards/{board_id}/items',payload)['item']['id']
    for row in plan['items']:
        ident=found[row['key']];path=f'/api/tools/kanban/items/{ident}'
        item=client.request('GET',path)['item']
        marker=f"[plan:{plan['plan_id']}:{row['key']}]"
        if marker not in item['notes']:raise ValueError('Plan marker changed during synchronization; stopped.')
        if effort and effort['id'] not in {e['id'] for e in item.get('efforts',[])}:
            ids=[e['id'] for e in item.get('efforts',[])]+[effort['id']]
            item=client.request('PUT',path+'/efforts',dict(effort_ids=ids,revision=item['revision']))['item']
        desired=[dict(target_id=found[k],kind='depends_on') for k in row['depends_on']]
        if row['key']=='overview':desired += [dict(target_id=i,kind='related') for k,i in found.items() if k!='overview']
        links=[dict(target_id=l['target_id'],kind=l['kind']) for l in item.get('links',[])]
        missing=[l for l in desired if l not in links]
        if missing:client.request('PUT',path+'/links',dict(links=links+missing,revision=item['revision']))
        verify=client.request('GET',path)['item']
        if effort and effort['id'] not in {e['id'] for e in verify.get('efforts',[])}:raise RuntimeError('Effort verification failed.')
        if not all(any(l['target_id']==d['target_id'] and l['kind']==d['kind'] for l in verify.get('links',[])) for d in desired):raise RuntimeError('Link verification failed.')
    return dict(mode='applied',board_id=board_id,effort_id=effort['id'] if effort else None,native_effort_pending=not native,items=found)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',required=True);parser.add_argument('--env-file',required=True)
    parser.add_argument('--plan',default=str(Path(__file__).resolve().parents[1]/'plans/mcp-wiki-rag.json'))
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args(argv)
    try:
        result=sync(Client(args.base_url,load_token(args.env_file)),json.loads(Path(args.plan).read_text()),args.apply)
        print(json.dumps(result,indent=2));return 0
    except (ValueError,RuntimeError,OSError,KeyError) as error:
        # Configuration and API errors contain no response payloads or credentials.
        print(str(error) if not isinstance(error,(OSError,KeyError)) else 'Check the plan and private environment file.',file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
