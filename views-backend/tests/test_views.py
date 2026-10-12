import concurrent.futures
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from app import create_app


class ViewsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.registry = self.root / 'profiles.json'
        self.registry.write_text(json.dumps(['test', 'other'] + ['page' + str(i) for i in range(32)]))
        self.now = 172800.0
        self.config = {'TESTING': True, 'DATABASE_PATH': str(self.root/'views.sqlite3'), 'REGISTRY_PATH': str(self.registry), 'IP_SECRET': 'private-test-secret-'*4, 'CLOCK': lambda: self.now}
        self.app = create_app(self.config)
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary.cleanup()

    def headers(self, ip='8.8.8.8', **extra):
        return {'Host': 'api.onimai.site', 'Origin': 'https://onimai.site', 'CF-Connecting-IP': ip, 'CF-Ray': '0123456789abcdef-LHR', **extra}

    def challenge(self, endpoint='test', ip='8.8.8.8'):
        response = self.client.post('/v1/views/'+endpoint+'/challenge', headers=self.headers(ip), json={})
        self.assertEqual(response.status_code, 200)
        return response.json['token']

    def claim(self, token, endpoint='test', ip='8.8.8.8'):
        return self.client.post('/v1/views/'+endpoint, headers=self.headers(ip), json={'token': token})

    def test_counts_one_daily_view_and_survives_restart(self):
        token = self.challenge()
        self.now += 2.2
        self.assertEqual(self.claim(token).json, {'views': 1, 'counted': True})
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        token = self.challenge()
        self.now += 2.2
        self.assertEqual(self.claim(token).json, {'views': 1, 'counted': False})
        self.now += 86401
        token = self.challenge()
        self.now += 2.2
        self.assertEqual(self.claim(token).json, {'views': 2, 'counted': True})

    def test_ticket_cannot_be_replayed_reused_on_another_profile_or_ip(self):
        token = self.challenge()
        self.now += 2.2
        self.assertEqual(self.claim(token, 'other').status_code, 403)
        self.assertEqual(self.claim(token, ip='1.1.1.1').status_code, 403)
        self.assertEqual(self.claim(token).status_code, 200)
        self.assertEqual(self.claim(token).status_code, 403)

    def test_expired_and_too_early_tickets_do_not_count(self):
        token = self.challenge()
        self.assertEqual(self.claim(token).status_code, 425)
        self.now += 121
        self.assertEqual(self.claim(token).status_code, 403)

    def test_ipv6_addresses_in_same_subnet_share_deduplication(self):
        token = self.challenge(ip='2001:4860:1234:5678::1')
        self.now += 2.2
        self.assertTrue(self.claim(token, ip='2001:4860:1234:5678::2').json['counted'])
        token = self.challenge(ip='2001:4860:1234:5678::ffff')
        self.now += 2.2
        self.assertFalse(self.claim(token, ip='2001:4860:1234:5678::ffff').json['counted'])

    def test_forwarded_headers_and_body_cannot_override_trusted_ip_or_count(self):
        headers = self.headers(**{'X-Forwarded-For': '1.1.1.1', 'X-Real-IP': '1.1.1.1'})
        token = self.challenge()
        self.now += 2.2
        response = self.client.post('/v1/views/test', headers=headers, json={'token': token})
        self.assertTrue(response.json['counted'])
        token = self.challenge()
        self.now += 2.2
        response = self.client.post('/v1/views/test', headers=self.headers(**{'X-Forwarded-For': '9.9.9.9'}), json={'token': token})
        self.assertFalse(response.json['counted'])
        self.assertEqual(self.client.post('/v1/views/test', headers=headers, json={'token': token, 'views': 999, 'ip': '1.1.1.1'}).status_code, 400)

    def test_missing_trusted_headers_private_ips_and_workers_are_rejected(self):
        for headers in [{'Host':'api.onimai.site', 'X-Forwarded-For':'8.8.8.8'}, self.headers('127.0.0.1'), self.headers('not-an-ip'), self.headers(**{'CF-Worker':'attacker.workers.dev'}), self.headers('2a06:98c0:3600::103')]:
            self.assertEqual(self.client.get('/v1/views/test', headers=headers).status_code, 403)

    def test_origin_host_body_limits_and_unknown_profiles(self):
        self.assertEqual(self.client.post('/v1/views/test/challenge', headers=self.headers(Origin='https://attacker.example'), json={}).status_code, 403)
        self.assertEqual(self.client.get('/v1/views/test', headers=self.headers(Host='attacker.example')).status_code, 400)
        self.assertEqual(self.client.post('/v1/views/test', headers=self.headers(), data='x'*2100, content_type='application/json').status_code, 413)
        self.assertEqual(self.client.get('/v1/views/missing', headers=self.headers()).status_code, 404)
        response = self.client.options('/v1/views/test/challenge', headers=self.headers())
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers['Access-Control-Allow-Origin'], 'https://onimai.site')

    def test_failed_claims_are_rate_limited_and_limit_survives_restart(self):
        for _ in range(12):
            self.assertEqual(self.claim('invalid').status_code, 403)
        self.assertEqual(self.claim('invalid').status_code, 429)
        self.client = create_app(self.config).test_client()
        self.assertEqual(self.claim('invalid').status_code, 429)
        self.now += 61
        self.assertEqual(self.claim('invalid').status_code, 403)

    def test_daily_global_cap_is_not_removed_by_minute_cleanup(self):
        for index in range(31):
            token = self.challenge('page'+str(index))
            self.now += 2.2
            response = self.claim(token, 'page'+str(index))
            self.assertEqual(response.status_code, 200 if index < 30 else 429)
            self.now += 61

    def test_concurrent_tickets_cannot_double_count_same_visitor(self):
        tokens = [self.challenge() for _ in range(5)]
        self.now += 2.2
        def claim(token):
            with self.app.test_client() as client:
                return client.post('/v1/views/test', headers=self.headers(), json={'token':token}).json
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(claim, tokens))
        self.assertEqual(sum(result['counted'] for result in results), 1)
        self.assertEqual(self.client.get('/v1/views/test', headers=self.headers()).json['views'], 1)

    def test_database_contains_no_plain_client_ip_or_secret(self):
        token = self.challenge()
        self.now += 2.2
        self.claim(token)
        db = sqlite3.connect(self.config['DATABASE_PATH'])
        dump = '\n'.join(db.iterdump())
        db.close()
        self.assertNotIn('8.8.8.8', dump)
        self.assertNotIn(self.config['IP_SECRET'], dump)
        self.assertNotIn(token, dump)

if __name__ == '__main__':
    unittest.main()
