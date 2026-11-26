"""Real HTTP workflow tests for the local operations workspace."""
import http.client
import json
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from console_app import ConsoleState, RequestError, make_server, now, service_fields


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copytree(Path(__file__).resolve().parents[1] / 'web_console', self.root / 'web_console')
        self.state = ConsoleState(self.root)
        self.server = make_server(self.state, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.state.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, method='GET', body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.state.port, timeout=10)
        options = {'X-Console-Token': self.state.token, 'Content-Type': 'application/json'}
        options.update(headers or {})
        connection.request(method, path, None if body is None else json.dumps(body), options)
        response = connection.getresponse()
        data = response.read().decode()
        result = (response.status, json.loads(data) if response.getheader('Content-Type').startswith('application/json') else data, dict(response.getheaders()))
        connection.close()
        return result

    def service(self, **changes):
        return dict(name='test-api', group='application', type='http', target=f'http://127.0.0.1:{self.state.port}/demo/ready', timeout=3, expected_status=200, enabled=True, **changes)

    def finished(self, identity):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            run = next(r for r in self.state.runs() if r['id'] == identity)
            if run['state'] not in ('queued', 'running'):
                self.assertEqual(run['state'], 'completed', run)
                return run
            time.sleep(.02)
        self.fail('Check did not complete within 15 seconds')

    def test_home_and_assets(self):
        code, html, headers = self.request('/')
        self.assertEqual(code, 200)
        self.assertIn(self.state.token, html)
        self.assertNotIn('__CONSOLE_TOKEN__', html)
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        for asset in ('/app.js', '/styles.css'):
            self.assertEqual(self.request(asset)[0], 200)
        self.assertEqual(self.request('/../console_app.py')[0], 404)

    def test_mutations_require_session_token(self):
        self.assertEqual(self.request('/api/services', 'POST', self.service(), {'X-Console-Token': ''})[0], 403)
        self.assertEqual(self.state.services(), [])

    def test_foreign_origin_and_host_rejected(self):
        self.assertEqual(self.request('/api/overview', headers={'Origin': 'https://untrusted.example'})[0], 403)
        self.assertEqual(self.request('/api/overview', headers={'Host': 'untrusted.example'})[0], 403)

    def test_json_content_required(self):
        self.assertEqual(self.request('/api/services', 'POST', self.service(), {'Content-Type': 'text/plain'})[0], 415)

    def test_crud_pause_and_duplicates(self):
        code, created, _ = self.request('/api/services', 'POST', self.service())
        self.assertEqual(code, 201)
        identity = created['id']
        self.assertEqual(self.request('/api/services', 'POST', self.service())[0], 409)
        payload = self.service(); payload['enabled'] = False
        self.assertEqual(self.request('/api/services/' + identity, 'PATCH', payload)[0], 200)
        self.assertEqual(self.request('/api/checks', 'POST', {})[0], 400)
        self.assertEqual(self.request('/api/services/' + identity, 'DELETE')[0], 200)
        self.assertEqual(self.request('/api/services/' + identity, 'DELETE')[0], 404)

    def test_loopback_validation(self):
        for target in ('http://example.com/health', 'http://192.168.1.2/', 'http://127.0.0.1/?token=secret', 'http://user:secret@localhost/'):
            payload = self.service(); payload['target'] = target
            self.assertEqual(self.request('/api/services', 'POST', payload)[0], 400)
        for timeout in (True, 0, 11, float('nan')):
            payload = self.service(); payload['timeout'] = timeout
            with self.assertRaises(RequestError):
                service_fields(payload)

    def test_actual_failure_and_recovery(self):
        code, job, _ = self.request('/api/demo', 'POST', {'action': 'seed'})
        self.assertEqual(code, 202)
        failure = self.finished(job['id'])
        self.assertEqual(failure['report']['summary'], {'total': 3, 'healthy': 2, 'warning': 1})
        worker = next(s for s in failure['report']['services'] if s['name'] == 'lab-worker')
        self.assertEqual(worker['detail']['http_status'], 503)
        _, job, _ = self.request('/api/demo', 'POST', {'action': 'recover'})
        recovery = self.finished(job['id'])
        self.assertEqual(recovery['report']['summary']['healthy'], 3)
        self.assertEqual(len(self.state.runs()), 2)

    def test_changed_endpoint_does_not_inherit_health(self):
        identity = self.state.save_service(self.service())['id']
        self.finished(self.state.start_check()['id'])
        self.assertEqual(self.state.services()[0]['last']['status'], 'healthy')
        payload = self.service(); payload['target'] = f'http://127.0.0.1:{self.state.port}/missing'
        self.state.save_service(payload, identity)
        self.assertIsNone(self.state.services()[0]['last'])
        self.assertEqual(self.state.services()[0]['revision'], 2)
        self.assertEqual(len(self.state.runs()), 1)

    def test_concurrent_checks_rejected_without_mutating_lab(self):
        self.state.save_service(self.service())
        entered, release = threading.Event(), threading.Event()
        def slow_monitor(*args, **kwargs):
            entered.set(); release.wait(5)
            return {'services': [], 'summary': {'total': 0, 'healthy': 0, 'warning': 0}, 'status': 'healthy'}
        with patch('console_app.monitor', slow_monitor):
            job = self.state.start_check()
            self.assertTrue(entered.wait(3))
            try:
                self.assertEqual(self.request('/api/checks', 'POST', {})[0], 409)
                self.assertEqual(self.request('/api/demo', 'POST', {'action':'seed'})[0], 409)
                self.assertEqual(len(self.state.services()), 1)
            finally:
                release.set()
            self.finished(job['id'])

    def test_raw_logs_never_persist(self):
        marker = 'PRIVATE_CUSTOMER_8472'
        log = json.dumps({'timestamp': now(), 'level':'ERROR', 'message': 'request timed out ' + marker, 'secret': marker})
        code, result, _ = self.request('/api/triage', 'POST', {'text':log})
        self.assertEqual(code, 200)
        self.assertEqual(result['levels']['ERROR'], 1)
        self.assertNotIn(marker, json.dumps(result))
        with self.state.db() as db:
            self.assertNotIn(marker, '\n'.join(db.iterdump()))
        self.assertEqual(self.request('/api/triage/latest')[1]['summary'], result)

    def test_persistence_and_interrupted_recovery(self):
        self.state.save_service(self.service())
        with self.state.db() as db:
            db.execute('INSERT INTO runs(id,state,started_at) VALUES(?,?,?)', ('interrupted-job','queued',now()))
        restarted = ConsoleState(self.root)
        try:
            self.assertEqual(len(restarted.services()), 1)
            self.assertEqual(restarted.runs()[0]['state'], 'interrupted')
            self.assertNotEqual(restarted.token, self.state.token)
        finally:
            restarted.close()

    def test_evidence_timeline_sandbox_and_path_guard(self):
        evidence = self.root / 'reports' / 'investigations' / 'run-test'
        evidence.mkdir(parents=True)
        (evidence / 'timeline.html').write_text('<h1>Evidence</h1>', encoding='utf-8')
        code, _, headers = self.request('/api/evidence/run-test/timeline')
        self.assertEqual(code, 200)
        self.assertIn('sandbox', headers['Content-Security-Policy'])
        with self.assertRaises(RequestError):
            self.state.evidence_path('../outside')
        self.assertEqual(self.request('/api/evidence/run-missing/timeline')[0], 404)


    def lab_incident(self):
        job = self.state.demo('seed')
        self.finished(job['id'])
        return self.state.incidents()[0]

    def test_incident_lifecycle_deduplicates_recovers_and_reopens(self):
        incident = self.lab_incident()
        self.assertEqual(incident['state'], 'open')
        self.assertEqual(incident['service_name'], 'lab-worker')
        self.finished(self.state.start_check()['id'])
        current = self.state.incidents()[0]
        self.assertEqual(current['id'], incident['id'])
        self.assertEqual(current['failures'], 2)
        self.assertEqual(len(current['events']), 1)
        code, _, _ = self.request('/api/incidents/' + current['id'], 'PATCH', {'version': current['version'], 'action':'acknowledge', 'owner':'Operations', 'note':'Checking the worker response.'})
        self.assertEqual(code, 200)
        self.assertEqual(self.state.incidents()[0]['state'], 'acknowledged')
        self.finished(self.state.demo('recover')['id'])
        recovered = self.state.incidents()[0]
        self.assertEqual(recovered['state'], 'resolved')
        self.assertEqual(recovered['resolution'], 'recovered')
        self.assertEqual(recovered['owner'], 'Operations')
        self.finished(self.state.demo('degrade')['id'])
        incidents = self.state.incidents()
        self.assertEqual(len(incidents), 2)
        self.assertEqual(incidents[0]['state'], 'open')
        self.assertNotEqual(incidents[0]['id'], incident['id'])

    def test_incident_edits_are_versioned_and_token_protected(self):
        incident = self.lab_incident()
        route = '/api/incidents/' + incident['id']
        payload = {'version':incident['version'], 'action':'acknowledge', 'owner':'On-call'}
        self.assertEqual(self.request(route, 'PATCH', payload, {'X-Console-Token':''})[0], 403)
        self.assertEqual(self.request(route, 'PATCH', payload)[0], 200)
        self.assertEqual(self.request(route, 'PATCH', payload)[0], 409)
        current = self.state.incidents()[0]
        self.assertEqual(self.request(route, 'PATCH', {'version':current['version'], 'action':'assign', 'owner':'Platform'})[0], 200)
        self.assertEqual(self.state.incidents()[0]['owner'], 'Platform')

    def test_incident_notes_preserved_after_restart_and_recovery(self):
        incident = self.lab_incident()
        self.state.update_incident(incident['id'], {'version':incident['version'], 'action':'note', 'note':'Observed 503.\nChecking dependencies.'})
        self.finished(self.state.demo('recover')['id'])
        current = self.state.incidents()[0]
        self.state.update_incident(current['id'], {'version':current['version'], 'action':'note', 'note':'Recovery confirmed.'})
        restarted = ConsoleState(self.root)
        try:
            saved = restarted.incidents()[0]
            self.assertEqual(saved['state'], 'resolved')
            self.assertIn('Recovery confirmed.', [e['detail'] for e in saved['events']])
            self.assertEqual(saved['resolution'], 'recovered')
        finally:
            restarted.close()

    def test_invalid_incident_input_and_resolved_acknowledgement(self):
        incident = self.lab_incident()
        route = '/api/incidents/' + incident['id']
        for changes in ({'owner':''}, {'owner':'x'*81}, {'owner':'bad\nlabel'}, {'version':True}, {'action':'resolve'}, {'note':'x'*2001}, {'extra':'unsupported'}):
            payload = {'version':incident['version'], 'action':'acknowledge', 'owner':'Ops'}
            payload.update(changes)
            self.assertEqual(self.request(route, 'PATCH', payload)[0], 400, changes)
        self.finished(self.state.demo('recover')['id'])
        incident = self.state.incidents()[0]
        self.assertEqual(self.request(route, 'PATCH', {'version':incident['version'], 'action':'acknowledge', 'owner':'Ops'})[0], 409)
        self.assertEqual(self.request('/api/incidents/missing', 'PATCH', {'version':1,'action':'note','note':'test'})[0], 404)

    def test_configuration_changes_close_incident_without_claiming_recovery(self):
        incident = self.lab_incident()
        service = next(s for s in self.state.services() if s['id'] == incident['service_id'])
        payload = {k:service[k] for k in ('name','group','type','target','timeout','expected_status','enabled')}
        payload['expected_status'] = 503
        self.state.save_service(payload, service['id'])
        closed = self.state.incidents()[0]
        self.assertEqual(closed['resolution'], 'configuration_changed')
        self.assertIsNone(next(s for s in self.state.services() if s['id']==service['id'])['last'])

    def test_pausing_does_not_claim_recovery_and_removal_is_recorded(self):
        incident = self.lab_incident()
        service = next(s for s in self.state.services() if s['id'] == incident['service_id'])
        payload = {k:service[k] for k in ('name','group','type','target','timeout','expected_status','enabled')}
        payload['enabled'] = False
        self.state.save_service(payload, service['id'])
        self.finished(self.state.start_check()['id'])
        self.assertEqual(self.state.incidents()[0]['state'], 'open')
        self.state.delete_service(service['id'])
        self.assertEqual(self.state.incidents()[0]['resolution'], 'service_removed')

    def test_stale_inflight_warning_cannot_open_incident(self):
        identity = self.state.save_service(self.service())['id']
        snapshot = self.state.services()[0]
        payload = self.service(); payload['expected_status'] = 204
        self.state.save_service(payload, identity)
        with self.state.db() as db:
            self.state._observe_incident(db, snapshot, {'status':'warning'})
        self.assertEqual(self.state.incidents(), [])


    def test_incident_activity_limit_reserves_recovery(self):
        incident = self.lab_incident()
        with self.state.db() as db:
            for _ in range(197):
                self.state._incident_event(db, incident['id'], 'note', 'Existing investigation activity')
        with self.assertRaises(RequestError):
            self.state.update_incident(incident['id'], {'version':incident['version'], 'action':'acknowledge', 'owner':'Ops', 'note':'Two new events would exceed the limit.'})
        self.state.update_incident(incident['id'], {'version':incident['version'], 'action':'note', 'note':'Final investigation note.'})
        self.finished(self.state.demo('recover')['id'])
        self.assertEqual(self.state.incidents()[0]['resolution'], 'recovered')
        with self.state.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM incident_events WHERE incident_id=?', (incident['id'],)).fetchone()[0], 200)

    def test_resolved_incident_retention_preserves_active_work(self):
        incident = self.lab_incident()
        with self.state.db() as db:
            for i in range(200):
                db.execute("INSERT INTO incidents(id,service_id,revision,service_name,target,state,opened_at,last_seen,resolved_at,resolution) VALUES(?,?,1,'old','local','resolved',?,?,?,'recovered')", (str(i),'old-service','2020-01-01','2020-01-01',f'2020-{i:03}'))
        self.finished(self.state.demo('recover')['id'])
        with self.state.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM incidents WHERE state='resolved'").fetchone()[0], 200)
        self.assertIn(incident['id'], [i['id'] for i in self.state.incidents()])


    def stop_scheduler_thread(self):
        self.state.schedule_stop.set()
        self.state.scheduler.join()

    def due_schedule(self):
        self.state.schedule_due = time.monotonic() - 1
        self.state._schedule_tick()

    def test_schedule_validation_and_token(self):
        valid = {'enabled':True,'interval_seconds':10}
        self.assertEqual(self.request('/api/schedule','PATCH',valid)[0],400)
        self.state.save_service(self.service())
        self.assertEqual(self.request('/api/schedule','PATCH',valid,{'X-Console-Token':''})[0],403)
        for payload in ({'enabled':True,'interval_seconds':9}, {'enabled':True,'interval_seconds':3601}, {'enabled':True,'interval_seconds':True}, {'enabled':1,'interval_seconds':10}, {'enabled':True,'interval_seconds':10.5}, {'enabled':True}, {**valid,'extra':1}):
            self.assertEqual(self.request('/api/schedule','PATCH',payload)[0],400,payload)
        self.assertFalse(self.state.schedule_status()['enabled'])

    def test_scheduled_checks_use_real_probes_and_mark_source(self):
        self.stop_scheduler_thread()
        self.state.save_service(self.service())
        self.state.configure_schedule({'enabled':True,'interval_seconds':10})
        self.assertEqual(self.state.runs(),[])
        self.due_schedule()
        run = self.finished(self.state.runs()[0]['id'])
        self.assertEqual(run['source'],'scheduled')
        self.assertEqual(run['report']['summary']['healthy'],1)
        self.assertIsNotNone(self.state.schedule_status()['next_check_at'])

    def test_schedule_waits_until_due_and_skips_missed_intervals(self):
        self.stop_scheduler_thread()
        self.state.save_service(self.service())
        self.state.configure_schedule({'enabled':True,'interval_seconds':10})
        self.state._schedule_tick()
        self.assertEqual(self.state.runs(),[])
        self.state.schedule_due = time.monotonic() - 1000
        self.state._schedule_tick()
        self.finished(self.state.runs()[0]['id'])
        self.state._schedule_tick()
        self.assertEqual(len(self.state.runs()),1)
        self.assertGreater(self.state.schedule_due,time.monotonic())

    def test_schedule_skips_overlapping_run_without_backlog(self):
        self.stop_scheduler_thread()
        self.state.save_service(self.service())
        self.state.configure_schedule({'enabled':True,'interval_seconds':10})
        entered,release=threading.Event(),threading.Event()
        def slow_monitor(*args,**kwargs):
            entered.set(); release.wait(5)
            return {'services':[],'summary':{'total':0,'healthy':0,'warning':0},'status':'healthy'}
        with patch('console_app.monitor',slow_monitor):
            job=self.state.start_check()
            self.assertTrue(entered.wait(3))
            try:
                self.due_schedule()
                self.assertEqual(len(self.state.runs()),1)
                self.assertIn('already running',self.state.schedule_status()['last_result'])
                self.assertGreater(self.state.schedule_due,time.monotonic())
            finally:
                release.set()
            self.finished(job['id'])
        self.assertEqual(self.state.runs()[0]['source'],'manual')

    def test_stopping_schedule_keeps_existing_run_and_blocks_future_ticks(self):
        self.stop_scheduler_thread()
        self.state.save_service(self.service())
        self.state.configure_schedule({'enabled':True,'interval_seconds':10})
        self.due_schedule()
        job=self.state.runs()[0]
        self.state.configure_schedule({'enabled':False,'interval_seconds':10})
        self.finished(job['id'])
        self.state._schedule_tick()
        self.assertEqual(len(self.state.runs()),1)
        self.assertIsNone(self.state.schedule_status()['next_check_at'])

    def test_schedule_interval_persists_but_restart_is_stopped(self):
        self.stop_scheduler_thread()
        self.state.save_service(self.service())
        self.state.configure_schedule({'enabled':True,'interval_seconds':45})
        restarted=ConsoleState(self.root)
        try:
            status=restarted.schedule_status()
            self.assertEqual(status['interval_seconds'],45)
            self.assertFalse(status['enabled'])
            self.assertIsNone(status['next_check_at'])
        finally:
            restarted.close()

    def test_schedule_respects_paused_services_and_can_resume(self):
        self.stop_scheduler_thread()
        identity=self.state.save_service(self.service())['id']
        self.state.configure_schedule({'enabled':True,'interval_seconds':10})
        payload=self.service();payload['enabled']=False
        self.state.save_service(payload,identity)
        self.due_schedule()
        self.assertEqual(self.state.runs(),[])
        self.assertIn('enable a service',self.state.schedule_status()['last_result'])
        payload['enabled']=True
        self.state.save_service(payload,identity)
        self.due_schedule()
        self.finished(self.state.runs()[0]['id'])

    def test_scheduled_failure_and_recovery_integrate_with_incidents(self):
        self.stop_scheduler_thread()
        self.finished(self.state.demo('seed')['id'])
        self.state.configure_schedule({'enabled':True,'interval_seconds':10})
        self.due_schedule()
        self.finished(self.state.runs()[0]['id'])
        self.assertEqual(self.state.incidents()[0]['failures'],2)
        self.state.demo_degraded=False
        self.due_schedule()
        self.finished(self.state.runs()[0]['id'])
        self.assertEqual(self.state.incidents()[0]['resolution'],'recovered')

    def test_legacy_run_history_migrates_without_loss(self):
        import sqlite3
        legacy=self.root/'legacy'
        legacy.mkdir()
        with sqlite3.connect(legacy/'console.sqlite3') as db:
            db.execute('CREATE TABLE runs(id TEXT PRIMARY KEY,state TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT,report TEXT,error TEXT)')
            db.execute('INSERT INTO runs(id,state,started_at) VALUES(?,?,?)',('old-job','queued',now()))
        db.close()
        migrated=ConsoleState(self.root,data_dir=legacy)
        try:
            row=migrated.runs()[0]
            self.assertEqual(row['id'],'old-job')
            self.assertEqual(row['source'],'manual')
            self.assertEqual(row['state'],'interrupted')
        finally:
            migrated.close()


if __name__ == '__main__':
    unittest.main()
