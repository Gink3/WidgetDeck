"""Private unlimited English word puzzles, persisted independently per account."""
from collections import Counter
import hmac
import json
import re
import secrets
import sqlite3
import uuid
from pathlib import Path
from flask import Blueprint, jsonify, render_template, request, session
from dashboard.auth import current_user_id, login_required
from dashboard.database import db, timestamp

routes=Blueprint('wordle',__name__)
WORDS=frozenset((Path(__file__).parent/'words.txt').read_text().split())
ANSWERS=tuple('''apple beach bread brain brave brick bring brown brush chair charm chase chest chief child claim clean clear climb clock cloud coast color crane cream dance dream drink drive earth early elbow enjoy equal event every faith field flame floor flute focus force frame fresh fruit ghost giant glass globe grape grass green group guard guide happy heart heavy honey horse hotel house human image index ivory jelly joint judge juice knife knock label large laugh lemon light limit local lucky magic major maple match metal model money month mouse movie music night north ocean olive onion order other outer paint paper party peach pearl phase phone piano pilot place plain plane plant plate point power pride prize queen quick quiet radio raise reach ready reply right river roast robot rough round royal scale scene scope score shade shake share sharp sheep shelf shell shine shirt shock short shout sight skill sleep slice smile smoke snake solar sound south space spare speak speed spice spoon sport stage stand start state steam steel stone store storm story sugar sweet table teach thank theme thick thing think third tiger toast today tooth total touch tower trace track trade train treat trial trust truth under union unity upper value video visit voice waste watch water wheel white whole woman world worth would write youth zebra'''.split())
assert set(ANSWERS)<=WORDS


def init_wordle(app):
    with sqlite3.connect(app.config['FOUR_AD_DATABASE']) as connection:
        connection.execute('''CREATE TABLE IF NOT EXISTS wordle_games (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,user_id INTEGER NOT NULL,
            answer TEXT NOT NULL,guesses TEXT NOT NULL DEFAULT '[]',hard_mode INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',revision INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''')
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS wordle_active_owner ON wordle_games(user_id) WHERE status='active'")
        connection.execute('CREATE INDEX IF NOT EXISTS wordle_owner ON wordle_games(user_id,sequence)')
    app.register_blueprint(routes)


@routes.before_request
def protect_writes():
    if request.method in ('GET','HEAD','OPTIONS'):return
    if request.headers.get('Authorization','').partition(' ')[0].lower()=='bearer':return
    expected=session.get('wordle_csrf','');supplied=request.headers.get('X-CSRF-Token','')
    if not expected or not hmac.compare_digest(expected.encode(),supplied.encode()):
        return jsonify(error='Reload the game and try again.'),403


def score(answer,guess):
    result=['absent']*5
    remaining=Counter(a for a,g in zip(answer,guess) if a!=g)
    for i,(a,g) in enumerate(zip(answer,guess)):
        if a==g:result[i]='correct'
    for i,g in enumerate(guess):
        if result[i]!='correct' and remaining[g]>0:
            result[i]='present';remaining[g]-=1
    return result


def hard_error(history,guess):
    for entry in history:
        known=Counter(letter for letter,mark in zip(entry['word'],entry['marks']) if mark!='absent')
        if any(guess.count(letter)<count for letter,count in known.items()):return 'Hard mode: use every revealed letter, including repeated letters.'
        for i,(letter,mark) in enumerate(zip(entry['word'],entry['marks'])):
            if mark=='correct' and guess[i]!=letter:return f'Hard mode: position {i+1} must be {letter.upper()}.'
            if mark=='present' and guess[i]==letter:return f'Hard mode: move {letter.upper()} out of position {i+1}.'
    return None


def payload(game):
    if not game:return None
    result={key:game[key] for key in ('id','hard_mode','status','revision','created_at','updated_at')}
    result['hard_mode']=bool(result['hard_mode']);result['guesses']=json.loads(game['guesses'])
    if game['status']!='active':result['answer']=game['answer']
    return result


def statistics():
    games=db().execute("SELECT status,guesses FROM wordle_games WHERE user_id=? AND status IN ('won','lost') ORDER BY sequence",(current_user_id(),)).fetchall()
    wins=0;streak=0;maximum=0;distribution={str(i):0 for i in range(1,7)}
    for game in games:
        if game['status']=='won':
            wins+=1;streak+=1;distribution[str(len(json.loads(game['guesses'])))]+=1;maximum=max(maximum,streak)
        else:streak=0
    return {'played':len(games),'wins':wins,'win_percent':round(wins*100/len(games)) if games else 0,
            'current_streak':streak,'max_streak':maximum,'distribution':distribution}


@routes.get('/tools/wordle')
@login_required
def index():return render_template('wordle.html')


@routes.get('/api/tools/wordle/game')
@login_required
def get_game():
    session.setdefault('wordle_csrf',secrets.token_urlsafe(32))
    game=db().execute('SELECT * FROM wordle_games WHERE user_id=? ORDER BY sequence DESC LIMIT 1',(current_user_id(),)).fetchone()
    response=jsonify(game=payload(game),stats=statistics(),csrf_token=session['wordle_csrf'])
    response.headers['Cache-Control']='private, no-store';return response


@routes.post('/api/tools/wordle/games')
@login_required
def new_game():
    data=request.get_json(silent=True)
    if not isinstance(data,dict) or type(data.get('hard_mode',False)) is not bool:return jsonify(error='Choose a hard-mode setting.'),400
    connection=db()
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        previous=connection.execute("SELECT * FROM wordle_games WHERE user_id=? AND status='active'",(current_user_id(),)).fetchone()
        if previous:
            if data.get('reset') is not True or type(data.get('revision')) is not int or previous['revision']!=data['revision']:
                return jsonify(error='An active game exists. Reload before starting another.'),409
            status='lost' if json.loads(previous['guesses']) else 'abandoned'
            connection.execute('UPDATE wordle_games SET status=?,updated_at=?,revision=revision+1 WHERE id=?',(status,timestamp(),previous['id']))
        ident=uuid.uuid4().hex;now=timestamp()
        connection.execute('INSERT INTO wordle_games(id,user_id,answer,hard_mode,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                           (ident,current_user_id(),secrets.choice(ANSWERS),data.get('hard_mode',False),now,now))
    game=connection.execute('SELECT * FROM wordle_games WHERE id=?',(ident,)).fetchone()
    return jsonify(game=payload(game),stats=statistics()),201


@routes.post('/api/tools/wordle/games/<game_id>/guesses')
@login_required
def submit_guess(game_id):
    data=request.get_json(silent=True)
    if not isinstance(data,dict) or not isinstance(data.get('word'),str) or type(data.get('revision')) is not int:
        return jsonify(error='Supply a five-letter word and current revision.'),400
    word=data['word'].strip().lower()
    if not re.fullmatch('[a-z]{5}',word) or word not in WORDS:return jsonify(error='Choose a word from the English five-letter dictionary.'),400
    connection=db()
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        game=connection.execute('SELECT * FROM wordle_games WHERE id=? AND user_id=?',(game_id,current_user_id())).fetchone()
        if not game:return jsonify(error='Game not found.'),404
        if game['status']!='active' or game['revision']!=data['revision']:return jsonify(error='Game changed. Reload to see the latest guesses.'),409
        guesses=json.loads(game['guesses'])
        if game['hard_mode']:
            error=hard_error(guesses,word)
            if error:return jsonify(error=error),400
        guesses.append({'word':word,'marks':score(game['answer'],word)})
        status='won' if word==game['answer'] else 'lost' if len(guesses)==6 else 'active'
        connection.execute('UPDATE wordle_games SET guesses=?,status=?,revision=revision+1,updated_at=? WHERE id=?',
                           (json.dumps(guesses),status,timestamp(),game_id))
    return jsonify(game=payload(connection.execute('SELECT * FROM wordle_games WHERE id=?',(game_id,)).fetchone()),stats=statistics())
