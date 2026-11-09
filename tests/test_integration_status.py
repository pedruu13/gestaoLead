from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import app as application
from integration_status import gemini_status, record_check


class IntegrationStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temp.name) / 'test.db')

    def tearDown(self):
        self.temp.cleanup()

    def test_saved_key_is_not_a_verified_connection(self):
        self.assertEqual('missing', gemini_status(self.database, '')['status'])
        self.assertEqual('untested', gemini_status(self.database, 'key-one')['status'])

    def test_result_survives_reload_and_key_change_invalidates_it(self):
        record_check(self.database, 'key-one', 'ok', 'Responded', 'model-test')
        state = gemini_status(self.database, 'key-one')
        self.assertEqual('ok', state['status'])
        self.assertEqual('model-test', state['model'])
        self.assertTrue(state['checked_at'])
        self.assertNotIn('key-one', str(state))
        self.assertEqual('untested', gemini_status(self.database, 'key-two')['status'])

    def test_failure_replaces_success_and_old_results_expire(self):
        record_check(self.database, 'key', 'ok', 'Responded', 'model-test')
        record_check(self.database, 'key', 'error', 'Quota exceeded')
        self.assertEqual('error', gemini_status(self.database, 'key')['status'])
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute('UPDATE integration_checks SET checked_at=?', ((datetime.now(timezone.utc)-timedelta(days=2)).isoformat(),))
        self.assertEqual('stale', gemini_status(self.database, 'key')['status'])

    def test_api_failure_for_another_key_preserves_saved_key_status(self):
        record_check(self.database, 'saved-key', 'ok', 'Responded', 'tested-model')
        client = application.app.test_client()
        with client.session_transaction() as session:
            session['authenticated'] = True
            session['csrf_token'] = 'test-token'
        with patch.object(application, 'DB_NAME', self.database), patch.dict(application.os.environ, {'GEMINI_API_KEY': 'saved-key'}), patch.object(application, 'first_available_response', side_effect=RuntimeError('private-key-data')):
            response = client.post('/api/test_gemini', json={'key': 'different-key'}, headers={'X-CSRF-Token': 'test-token'})
        self.assertEqual(502, response.status_code)
        self.assertEqual('ok', response.get_json()['status']['status'])
        self.assertNotIn('private-key-data', response.get_data(as_text=True))
