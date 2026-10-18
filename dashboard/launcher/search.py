"""Bounded, account-scoped search providers for the browser workspace."""
import json
import unicodedata
from datetime import datetime
from flask import Blueprint, current_app, jsonify, request
from dashboard.auth import current_user_id
from dashboard.database import db
from dashboard.navigation import utility_groups
from . import browser_only, private, resolve

routes=Blueprint('workspace_search',__name__)
routes.before_request(browser_only)
routes.after_request(private)


def normal(value):
    text=str(value or '')
    if text.isascii():return text.casefold()
    return ''.join(c for c in unicodedata.normalize('NFKD',text).casefold() if not unicodedata.combining(c))


def candidate(utility,ident,title,text='',codes=(),kind='',context=''):
    return {'utility':utility,'id':str(ident),'kind':kind,'label':title,'text':text,'codes':codes,'context':context}


def tools():
    return [{**candidate(link['id'],link['id'],link['label'],link['description']+' '+group['name'],context=group['name']),
             'result_kind':'utility','url':link['url'],'external':link['external']} for group in utility_groups() for link in group['links']]


def actions():
    return [{**candidate(link['id'],link['id'],link['action_label'],link['label']+' '+group['name'],context=group['name']),
             'result_kind':'action','url':link['action_url'],'external':link['external']} for group in utility_groups() for link in group['links']]


def zettels():
    from importlib import import_module
    return import_module("dashboard_private_widgets.zettelkasten.hooks").zettels()


def wiki():
    return [candidate('wiki',r['id'],r['title'],r['content'],context='Wiki page') for r in db().execute('SELECT id,title,content FROM wiki_pages WHERE user_id=? AND deleted_at IS NULL',(current_user_id(),))]


def kanban():
    results=[candidate('kanban',r['id'],r['name'],context='Board') for r in db().execute('SELECT id,name FROM kanban_boards WHERE user_id=?',(current_user_id(),))]
    for row in db().execute('SELECT i.id,i.title,i.notes,b.name FROM kanban_items i JOIN kanban_boards b ON b.id=i.board_id WHERE b.user_id=?',(current_user_id(),)):
        results.append(candidate('kanban',row['id'],row['title'],row['notes'],[str(row['id']),'#'+str(row['id'])],kind='item',context=row['name']+' · #'+str(row['id'])))
    return results


def paints():
    from importlib import import_module
    return import_module("dashboard_private_widgets.paint_rack.hooks").paints()


def maps():
    results=[]
    for row in db().execute('SELECT id,name,description FROM mind_maps WHERE user_id=?',(current_user_id(),)):
        nodes=db().execute('SELECT title,description FROM mind_map_nodes WHERE map_id=?',(row['id'],))
        text=row['description']+' '+' '.join(n['title']+' '+n['description'] for n in nodes)
        results.append(candidate('mind-maps',row['id'],row['name'],text,context='Mind map'))
    return results


def decks():
    from importlib import import_module
    return import_module("dashboard_private_widgets.flashcards.hooks").decks()


def schemes():
    from importlib import import_module
    return import_module("dashboard_private_widgets.chapter_painter.hooks").schemes()


def warbands():
    from importlib import import_module
    return import_module("dashboard_private_widgets.frostgrave.hooks").warbands()


def trackers():
    from importlib import import_module
    return import_module("dashboard_private_widgets.rdt.hooks").trackers()


PROVIDERS={'utilities':tools,'actions':actions,'zettels':zettels,'wiki':wiki,'kanban':kanban,'paints':paints,'maps':maps,'decks':decks,'schemes':schemes,'warbands':warbands,'trackers':trackers}


def score(item,query,words):
    title=item.get('_title') or normal(item['label']);codes=item.get('_codes') if '_codes' in item else [normal(c) for c in item['codes'] if c]
    text=item.get('_search') or title+' '+' '.join(codes)+' '+normal(item['text'])
    if not all(word in text for word in words):return None
    if query in codes:return 0
    if title==query:return 1
    if title.startswith(query):return 2
    if query in title:return 3
    return 4


@routes.get('/api/search')
def search():
    raw=request.args.get('q','').strip()
    if len(raw)>160:return jsonify(error='Search allows up to 160 characters.'),400
    query=normal(raw);words=query.split()
    if not words:return jsonify(results=[],total=0,has_more=False,unavailable=[])
    labels={link['id']:link['label'] for group in utility_groups() for link in group['links']}
    visits={}
    for row in db().execute('SELECT utility,resource_id,kind,opened_at FROM launcher_visits WHERE user_id=?',(current_user_id(),)):
        try:visits[(row['utility'],row['resource_id'],row['kind'])]=datetime.fromisoformat(row['opened_at']).timestamp()
        except ValueError:pass
    collected=[];total=0;unavailable=[]
    state = current_app.extensions.get('dashboard_widgets')
    providers = PROVIDERS if state is None else {'utilities': tools, 'actions': actions, **state['contributions'].search}
    for provider,read in providers.items():
        try:
            ranked=[]
            for item in read():
                rank=score(item,query,words)
                if rank is None:continue
                key=(item['utility'],item['id'],item['kind'])
                ranked.append((rank,-visits.get(key,0),normal(item['label']),item))
            ranked.sort(key=lambda row:row[:3]);total+=len(ranked)
            for rank,recency,title,item in ranked[:10]:
                result_kind=item.get('result_kind','content')
                target=item if result_kind!='content' else resolve(item['utility'],item['id'],item['kind'])
                if not target:continue
                result={'provider':provider,'utility':item['utility'],'utility_label':labels[item['utility']],
                        'id':item['id'],'kind':item['kind'],'result_kind':result_kind,'label':item['label'],
                        'context':item['context'] or (labels[item['utility']] if result_kind!='content' else target.get('context','')),
                        'preview':' '.join(item['text'][:500].split())[:160] if result_kind=='content' else '',
                        'url':target['url'],'external':target.get('external',False)}
                collected.append((rank,recency,title,result))
        except Exception:
            current_app.logger.warning('Workspace search provider unavailable: %s',provider,exc_info=True)
            unavailable.append(provider)
    collected.sort(key=lambda row:row[:3]);results=[row[3] for row in collected[:30]]
    return jsonify(results=results,total=total,has_more=total>len(results),unavailable=unavailable)
