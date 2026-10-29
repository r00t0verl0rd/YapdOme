"""OAuth registration-switch and goal prompt tests without external account access."""
import json
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend.server.auth as triad
from backend.controls.host import shared_goal

class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'accounts.json'
        self.auth=triad.State(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def params(self, url):
        return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))

    def test_fresh_registration_and_invalid_grant_recovery(self):
        first=self.params(self.auth.start_auth())
        self.assertEqual(first['client_id'],'dynamic_agent_client')
        self.assertIn('ext_agent_host_id',first)
        self.assertNotIn('id_token_hint',first)
        self.assertNotIn('login_hint',first)
        issued='oaiapp_test_registration'
        callback={'state':[first['state']],'code':['expired-code'],'client_id':[issued]}
        with patch.object(triad,'json_request',side_effect=triad.BridgeError('OpenAI HTTP 400: invalid_grant')):
            with self.assertRaisesRegex(triad.BridgeError,'invalid_grant'):
                self.auth.finish_auth(callback)
        self.assertEqual(self.auth.credentials['registration_pending']['client_id'],issued)
        # The issued ID survives a process restart: official SIWC retry path.
        revived=triad.State(self.path)
        second=self.params(revived.start_auth())
        self.assertEqual(second['client_id'], issued)
        self.assertNotEqual(second['state'], first['state'])
        self.assertNotEqual(second['code_challenge'], first['code_challenge'])
        self.assertNotIn('id_token_hint',second)
        token={'id_token':'FAKE','access_token':'TOKEN1','refresh_token':'REFRESH1',
               'scope':'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct',
               'expires_in':3600}
        with patch.object(triad,'json_request',return_value=token) as token_call,\
             patch.object(triad,'verify_jwt',return_value={'sub':'user1','email':'one@example.net'}):
            revived.finish_auth({'state':[second['state']],'code':['new-code']})
            self.assertEqual(token_call.call_args.args[1]['client_id'],issued)
            self.assertEqual(token_call.call_args.args[1]['code_verifier'],revived.pending['verifier'] if revived.pending else token_call.call_args.args[1]['code_verifier'])
        self.assertEqual(revived.credentials['active'],issued)
        self.assertFalse(revived.status()['recoverable'])

    def test_other_account_does_not_reuse_old_client_or_hints(self):
        self.auth.credentials['accounts']['oaiapp_first']={
            'client_id':'oaiapp_first','subject':'user1','email':'one@example.net',
            'id_token':'ID1', 'access_token':'T1',
            'scopes':['chatgpt.tokens.use.direct'],'expires_at':9999999999}
        self.auth.credentials['active']='oaiapp_first'
        self.auth.save()
        returning=self.params(self.auth.start_auth('auto'))
        self.assertEqual(returning['client_id'],'oaiapp_first')
        self.assertEqual(returning['id_token_hint'],'ID1')
        self.assertEqual(returning['login_hint'],'one@example.net')
        switching=self.params(self.auth.start_auth('switch'))
        self.assertEqual(switching['client_id'],'dynamic_agent_client')
        self.assertEqual(switching['prompt'],'select_account')
        self.assertNotIn('id_token_hint',switching)
        self.assertNotIn('login_hint',switching)
        token={'id_token':'FAKE','access_token':'T2','refresh_token':'R2',
               'scope':'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'}
        with patch.object(triad,'json_request',return_value=token),\
             patch.object(triad,'verify_jwt',return_value={'sub':'user2','email':'two@example.net'}):
            self.auth.finish_auth({'state':[switching['state']],'code':['code'],'client_id':['oaiapp_second']})
        self.assertEqual(self.auth.credentials['active'],'oaiapp_second')
        self.assertEqual(self.auth.credentials['accounts']['oaiapp_first']['subject'],'user1')
        self.assertEqual(self.auth.credentials['accounts']['oaiapp_second']['subject'],'user2')
        self.assertEqual(self.auth.status()['account'],'two@example.net')
        self.assertNotIn('accounts',self.auth.status())  # UI has no picker, no raw client IDs.

    def test_state_mismatch_never_redeems_code(self):
        self.auth.start_auth()
        with patch.object(triad,'json_request') as caller:
            with self.assertRaisesRegex(triad.BridgeError, 'state'):
                self.auth.finish_auth({'state':['wrong'],'code':['x'],'client_id':['oaiapp_id']})
            caller.assert_not_called()

    def test_access_denied_explains_plan_eligibility(self):
        params = self.params(self.auth.start_auth())
        with self.assertRaisesRegex(triad.BridgeError, "Plus/Pro"):
            self.auth.finish_auth({
                "state": [params["state"]],
                "error": ["access_denied"],
            })

    def test_bad_unicode_callback_does_not_consume_oauth_state(self):
        self.auth.start_auth()
        pending = self.auth.pending
        with patch.object(triad, 'json_request') as exchange:
            with self.assertRaises(triad.BridgeError):
                self.auth.finish_auth({'state': ['é-state'], 'code': ['x']})
            exchange.assert_not_called()
        self.assertIs(self.auth.pending, pending)

    def test_refresh_does_not_hold_master_lock_during_network(self):
        with self.auth.lock:
            self.auth.credentials['accounts']['oaiapp_test'] = {
                'client_id': 'oaiapp_test', 'subject': 'u',
                'scopes': ['chatgpt.tokens.use.direct'],
                'refresh_token': 'refresh', 'access_token': 'stale', 'expires_at': 1}
            self.auth.credentials['active'] = 'oaiapp_test'
        begun, release = threading.Event(), threading.Event()
        errors = []

        def slow_exchange(*args, **kwargs):
            begun.set()
            if not release.wait(2):
                raise AssertionError('refresh was not released')
            return {'access_token': 'new', 'expires_in': 3600}

        def worker():
            try:
                self.auth.access_token()
            except Exception as error:
                errors.append(error)

        with patch.object(triad, 'json_request', side_effect=slow_exchange):
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            try:
                self.assertTrue(begun.wait(1))
                # Token exchange must not block unrelated state operations.
                self.assertTrue(self.auth.lock.acquire(timeout=.2))
                self.auth.lock.release()
                self.assertIsNotNone(self.auth.status()['connected'])
            finally:
                release.set()
                thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertFalse(errors, errors)
        self.assertEqual(self.auth.access_token(), 'new')

    def test_bad_mode_rejected(self):
        with self.assertRaises(triad.BridgeError):
            self.auth.start_auth('oaiapp_old')

    def test_shared_goal_validation(self):
        self.assertEqual(shared_goal({'shared_goal':'  Дойти до прототипа  '}),'Дойти до прототипа')
        with self.assertRaises(triad.BridgeError):
            shared_goal({'shared_goal':'а'*901})
        with self.assertRaises(triad.BridgeError):
            shared_goal({'shared_goal':{'role':'system'}})

if __name__ == '__main__': unittest.main()
