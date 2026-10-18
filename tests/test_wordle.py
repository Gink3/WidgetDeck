import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
from test_security_boundaries import isolated_application, auth_post
from dashboard.wordle import score, hard_error
from dashboard.four_ad.models import db, timestamp

class WordleTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        _,self.app=isolated_application(directory.name);self.client=self.app.test_client()
        self.assertEqual(auth_post(self.client,'/register',{'username':'word-player','password':'test-only-password'}).status_code,302)
        self.headers={'X-CSRF-Token':self.client.get('/api/tools/wordle/game').json['csrf_token']}

    def start(self,hard=False,**kwargs):
        with patch('dashboard.wordle.secrets.choice',return_value='apple'):
            return self.client.post('/api/tools/wordle/games',json={'hard_mode':hard,**kwargs},headers=self.headers)

    def guess(self,game,word):
        return self.client.post('/api/tools/wordle/games/'+game['id']+'/guesses',json={'word':word,'revision':game['revision']},headers=self.headers)

    def test_repeat_letters_and_hard_mode_revealed_multiplicity(self):
        self.assertEqual(score('apple','allee'),['correct','present','absent','absent','correct'])
        history=[{'word':'puppy','marks':score('apple','puppy')}]
        self.assertIsNotNone(hard_error(history,'ample'))
        self.assertIsNone(hard_error(history,'apple'))
        game=self.start(True).json['game']
        self.assertEqual(self.guess(game,'zzzzz').status_code,400)
        game=self.guess(game,'allee').json['game']
        self.assertEqual(self.guess(game,'ocean').status_code,400)
        self.assertNotIn('answer',game)
        response=self.guess(game,'apple');self.assertEqual(response.json['game']['status'],'won')
        self.assertEqual(response.json['stats']['wins'],1);self.assertEqual(response.json['stats']['distribution']['2'],1)
        self.assertEqual(self.guess(game,'apple').status_code,409)

    def test_persistence_restart_stats_losses_and_account_isolation(self):
        game=self.start().json['game']
        self.assertEqual(self.start().status_code,409)
        for word in ['beach','bread','chair','cloud','dream','earth']:
            response=self.guess(game,word);self.assertEqual(response.status_code,200);game=response.json['game']
        self.assertEqual(game['status'],'lost');self.assertEqual(game['answer'],'apple')
        saved=self.client.get('/api/tools/wordle/game').json
        self.assertEqual(saved['game'],game);self.assertEqual(saved['stats']['played'],1);self.assertEqual(saved['stats']['wins'],0)
        other=self.app.test_client();auth_post(other,'/register',{'username':'other-player','password':'test-only-password'})
        state=other.get('/api/tools/wordle/game').json;self.assertIsNone(state['game']);self.assertEqual(state['stats']['played'],0)
        foreign=other.post('/api/tools/wordle/games/'+game['id']+'/guesses',json={'word':'apple','revision':game['revision']},headers={'X-CSRF-Token':state['csrf_token']})
        self.assertEqual(foreign.status_code,404)
        game=self.start().json['game'];game=self.guess(game,'crane').json['game']
        result=self.start(reset=True,revision=game['revision'])
        self.assertEqual(result.status_code,201);self.assertEqual(result.json['stats']['played'],2)
        self.assertEqual(self.start(reset=True,revision=0).status_code,201)
        self.assertEqual(self.client.get('/api/tools/wordle/game').json['stats']['played'],2)

    def test_csrf_and_bearer_permissions(self):
        self.assertEqual(self.client.post('/api/tools/wordle/games',json={}).status_code,403)
        token='dash_test_wordle_only'
        with self.app.app_context():
            db().execute('INSERT INTO dashboard_api_keys(user_id,name,prefix,token_hash,permissions,created_at) VALUES(?,?,?,?,?,?)',
                         (1,'test','dash_test',hashlib.sha256(token.encode()).hexdigest(),json.dumps({'wordle':'read'}),timestamp()));db().commit()
        headers={'Authorization':'Bearer '+token}
        self.assertEqual(self.client.get('/api/tools/wordle/game',headers=headers).status_code,200)
        self.assertEqual(self.client.post('/api/tools/wordle/games',json={},headers=headers).status_code,401)
        self.assertEqual(self.client.get('/api/tools/kanban/boards',headers=headers).status_code,401)
