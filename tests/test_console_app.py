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


    def test_maintenance_validation_and_token(self):
        identity=self.state.save_service(self.service())['id']
        route=f'/api/services/{identity}/maintenance'
        valid={'duration_minutes':30,'reason':'Planned migration'}
        self.assertEqual(self.request(route,'POST',valid,{'X-Console-Token':''})[0],403)
        for changes in ({'duration_minutes':0},{'duration_minutes':1441},{'duration_minutes':True},{'duration_minutes':1.5},{'reason':''},{'reason':'x'*301},{'reason':'bad\nreason'},{'extra':1}):
            payload={**valid,**changes}
            self.assertEqual(self.request(route,'POST',payload)[0],400,payload)
        self.assertEqual(self.request('/api/services/missing/maintenance','POST',valid)[0],404)
        self.assertEqual(self.state.maintenance_windows(),[])

    def test_maintenance_excludes_manual_checks_and_health_totals(self):
        self.finished(self.state.demo('seed')['id'])
        service=next(s for s in self.state.services() if s['name']=='lab-worker')
        self.state.start_maintenance(service['id'],{'duration_minutes':30,'reason':'Worker upgrade'})
        job=self.state.start_check()
        run=self.finished(job['id'])
        self.assertEqual(run['report']['summary']['total'],2)
        self.assertNotIn('lab-worker',[s['name'] for s in run['report']['services']])
        summary=self.state.overview()['summary']
        self.assertEqual(summary['maintenance'],1)
        self.assertEqual(summary['monitoring'],2)
        self.assertEqual(summary['warning'],0)
        self.assertEqual(self.state.incidents()[0]['state'],'open')
        self.assertIsNone(next(s for s in self.state.services() if s['id']==service['id'])['last'])

    def test_maintenance_overlap_and_early_end(self):
        identity=self.state.save_service(self.service())['id']
        payload={'duration_minutes':30,'reason':'Planned upgrade'}
        code,window,_=self.request(f'/api/services/{identity}/maintenance','POST',payload)
        self.assertEqual(code,201)
        self.assertEqual(self.request(f'/api/services/{identity}/maintenance','POST',payload)[0],409)
        self.assertEqual(self.request('/api/checks','POST',{})[0],400)
        self.assertEqual(self.request(f'/api/maintenance/{window["id"]}/end','POST',{})[0],200)
        self.assertEqual(self.request(f'/api/maintenance/{window["id"]}/end','POST',{})[0],404)
        self.assertEqual(self.state.maintenance_windows()[0]['state'],'ended')
        self.finished(self.state.start_check()['id'])
        self.assertEqual(self.state.services()[0]['last']['status'],'healthy')

    def test_expired_maintenance_resumes_without_changing_enabled_setting(self):
        identity=self.state.save_service(self.service())['id']
        window=self.state.start_maintenance(identity,{'duration_minutes':1,'reason':'Short upgrade'})
        with self.state.db() as db:
            db.execute('UPDATE maintenance SET expires_at=? WHERE id=?',(time.time()-1,window['id']))
        self.assertIsNone(self.state.services()[0]['maintenance'])
        self.assertEqual(self.state.maintenance_windows()[0]['state'],'expired')
        self.finished(self.state.start_check()['id'])
        payload=self.service();payload['enabled']=False
        self.state.save_service(payload,identity)
        window=self.state.start_maintenance(identity,{'duration_minutes':1,'reason':'Paused upgrade'})
        self.state.end_maintenance(window['id'])
        self.assertFalse(self.state.services()[0]['enabled'])

    def test_maintenance_survives_console_restart(self):
        identity=self.state.save_service(self.service())['id']
        self.state.start_maintenance(identity,{'duration_minutes':30,'reason':'Persistent window'})
        restarted=ConsoleState(self.root)
        try:
            self.assertEqual(restarted.services()[0]['maintenance']['reason'],'Persistent window')
            with self.assertRaises(RequestError):
                restarted.start_check()
        finally:
            restarted.close()

    def test_inflight_failure_cannot_open_incident_after_maintenance_cycle(self):
        identity=self.state.save_service(self.service())['id']
        snapshot=self.state.services()[0]
        entered,release=threading.Event(),threading.Event()
        def delayed_monitor(*args,**kwargs):
            entered.set();release.wait(5)
            return {'services':[{'name':snapshot['name'],'group':snapshot['group'],'type':'http','status':'warning','detail':{'status':'timeout'}}],'summary':{'total':1,'healthy':0,'warning':1},'status':'warning'}
        with patch('console_app.monitor',delayed_monitor):
            job=self.state.start_check()
            self.assertTrue(entered.wait(3))
            try:
                window=self.state.start_maintenance(identity,{'duration_minutes':1,'reason':'Emergency upgrade'})
                self.state.end_maintenance(window['id'])
            finally:
                release.set()
            self.finished(job['id'])
        self.assertEqual(self.state.incidents(),[])
        self.assertIsNone(self.state.services()[0]['last'])

    def test_maintenance_does_not_resolve_existing_incident_and_recovers_after_end(self):
        incident=self.lab_incident()
        snapshot=next(s for s in self.state.services() if s['id']==incident['service_id'])
        window=self.state.start_maintenance(snapshot['id'],{'duration_minutes':30,'reason':'Repairing worker'})
        with self.state.db() as db:
            self.state._observe_incident(db,snapshot,{'status':'healthy'})
        self.assertEqual(self.state.incidents()[0]['state'],'open')
        self.state.demo_degraded=False
        self.state.end_maintenance(window['id'])
        self.finished(self.state.start_check()['id'])
        self.assertEqual(self.state.incidents()[0]['resolution'],'recovered')

    def test_scheduler_skips_all_services_in_maintenance_then_resumes(self):
        self.stop_scheduler_thread()
        identity=self.state.save_service(self.service())['id']
        self.state.configure_schedule({'enabled':True,'interval_seconds':10})
        window=self.state.start_maintenance(identity,{'duration_minutes':30,'reason':'Updating API'})
        self.due_schedule()
        self.assertEqual(self.state.runs(),[])
        self.assertIn('maintenance',self.state.schedule_status()['last_result'])
        self.state.end_maintenance(window['id'])
        self.due_schedule()
        run=self.finished(self.state.runs()[0]['id'])
        self.assertEqual(run['source'],'scheduled')


    def compare(self, baseline, current):
        return self.request('/api/runs/compare','POST',{'baseline_id':baseline,'current_id':current})

    def test_compare_runs_failure_recovery_and_ongoing(self):
        failure=self.finished(self.state.demo('seed')['id'])
        ongoing=self.finished(self.state.start_check()['id'])
        self.assertEqual(self.compare(failure['id'],ongoing['id'])[1]['counts']['ongoing_failure'],1)
        recovery=self.finished(self.state.demo('recover')['id'])
        code,report,_=self.compare(failure['id'],recovery['id'])
        self.assertEqual(code,200)
        self.assertEqual(report['counts']['recovered'],1)
        self.assertEqual(report['counts']['unchanged_healthy'],2)
        new_failure=self.finished(self.state.demo('degrade')['id'])
        self.assertEqual(self.compare(recovery['id'],new_failure['id'])[1]['counts']['new_failure'],1)

    def test_partial_run_absence_is_not_recovery(self):
        before=self.finished(self.state.demo('seed')['id'])
        api=next(s for s in self.state.services() if s['name']=='lab-api')
        after=self.finished(self.state.start_check([api['id']])['id'])
        report=self.compare(before['id'],after['id'])[1]
        self.assertEqual(report['counts']['absent_from_run'],2)
        self.assertEqual(report['counts']['recovered'],0)
        reverse=self.compare(after['id'],before['id'])
        self.assertEqual(reverse[0],400)

    def test_configuration_change_cannot_claim_recovery(self):
        before=self.finished(self.state.demo('seed')['id'])
        service=next(s for s in self.state.services() if s['name']=='lab-worker')
        payload={key:service[key] for key in ('name','group','type','target','timeout','expected_status','enabled')}
        payload['expected_status']=503
        self.state.save_service(payload,service['id'])
        after=self.finished(self.state.start_check()['id'])
        report=self.compare(before['id'],after['id'])[1]
        self.assertEqual(report['counts']['configuration_changed'],1)
        self.assertEqual(report['counts']['recovered'],0)
        row=next(s for s in report['services'] if s['name']=='lab-worker')
        self.assertIsNone(row['duration_delta_ms'])

    def test_maintenance_boundary_is_explicit(self):
        before=self.finished(self.state.demo('seed')['id'])
        service=next(s for s in self.state.services() if s['name']=='lab-worker')
        window=self.state.start_maintenance(service['id'],{'duration_minutes':1,'reason':'Upgrade'})
        self.state.end_maintenance(window['id'])
        after=self.finished(self.state.demo('recover')['id'])
        report=self.compare(before['id'],after['id'])[1]
        self.assertEqual(report['counts']['maintenance_boundary'],1)
        self.assertEqual(report['counts']['recovered'],0)

    def test_reused_service_name_is_added_and_absent(self):
        original=self.state.save_service(self.service())['id']
        before=self.finished(self.state.start_check()['id'])
        self.state.delete_service(original)
        replacement=self.state.save_service(self.service())['id']
        after=self.finished(self.state.start_check()['id'])
        report=self.compare(before['id'],after['id'])[1]
        self.assertNotEqual(original,replacement)
        self.assertEqual(report['counts']['added_to_run'],1)
        self.assertEqual(report['counts']['absent_from_run'],1)
        self.assertEqual(report['counts']['unchanged_healthy'],0)

    def test_comparison_input_missing_and_unfinished_runs(self):
        self.assertEqual(self.compare('missing','other')[0],404)
        self.assertEqual(self.compare('same','same')[0],400)
        for payload in ({}, {'baseline_id':False,'current_id':'x'}, {'baseline_id':'a','current_id':'b','extra':1}):
            self.assertEqual(self.request('/api/runs/compare','POST',payload)[0],400)
        with self.state.db() as db:
            db.execute('INSERT INTO runs(id,state,started_at) VALUES(?,?,?)',('unfinished','interrupted',now()))
        self.assertEqual(self.compare('unfinished','other')[0],409)
        self.assertEqual(self.request('/api/runs/compare','POST',{'baseline_id':'a','current_id':'b'},{'X-Console-Token':''})[0],403)

    def test_comparison_duration_delta_and_missing_measurements(self):
        self.state.save_service(self.service())
        before=self.finished(self.state.start_check()['id'])
        after=self.finished(self.state.start_check()['id'])
        with self.state.db() as db:
            for identity,value in ((before['id'],100),(after['id'],125.25)):
                row=db.execute('SELECT payload FROM observations WHERE run_id=?',(identity,)).fetchone()
                payload=json.loads(row['payload']);payload['detail']['duration_ms']=value
                db.execute('UPDATE observations SET payload=? WHERE run_id=?',(json.dumps(payload),identity))
        report=self.compare(before['id'],after['id'])[1]
        self.assertEqual(report['services'][0]['duration_delta_ms'],25.25)
        with self.state.db() as db:
            payload['detail']['duration_ms']=True
            db.execute('UPDATE observations SET payload=? WHERE run_id=?',(json.dumps(payload),after['id']))
        self.assertIsNone(self.compare(before['id'],after['id'])[1]['services'][0]['duration_delta_ms'])

    def test_incomplete_comparison_metadata_rejected(self):
        self.state.save_service(self.service())
        before=self.finished(self.state.start_check()['id'])
        after=self.finished(self.state.start_check()['id'])
        with self.state.db() as db:
            db.execute('DELETE FROM observations WHERE run_id=?',(before['id'],))
        self.assertEqual(self.compare(before['id'],after['id'])[0],409)


    def test_export_includes_recovery_and_full_activity(self):
        incident=self.lab_incident()
        self.state.update_incident(incident['id'],{'version':incident['version'],'action':'acknowledge','owner':'Local operator','note':'Checked worker dependencies.'})
        self.finished(self.state.demo('recover')['id'])
        code,result,_=self.request(f'/api/incidents/{incident["id"]}/export','POST',{'format':'json','include_notes':True})
        self.assertEqual(code,200)
        report=json.loads(result['content'])
        self.assertEqual(report['incident']['resolution'],'recovered')
        self.assertEqual(report['incident']['owner'],'Local operator')
        self.assertEqual(len(report['evidence']),2)
        self.assertEqual(report['evidence'][-1]['status'],'healthy')
        self.assertEqual(report['evidence'][-1]['http_status'],200)
        self.assertIn('note',[event['kind'] for event in report['activity']])
        self.assertTrue(result['filename'].endswith('.json'))

    def test_export_omits_notes_and_arbitrary_probe_fields(self):
        incident=self.lab_incident()
        marker='PRIVATE_INVESTIGATION_CONTENT'
        self.state.update_incident(incident['id'],{'version':incident['version'],'action':'note','note':marker})
        with self.state.db() as db:
            row=db.execute('SELECT run_id,payload FROM observations WHERE service_id=?',(incident['service_id'],)).fetchone()
            payload=json.loads(row['payload']);payload['detail']['raw_log']=marker
            db.execute('UPDATE observations SET payload=? WHERE run_id=? AND service_id=?',(json.dumps(payload),row['run_id'],incident['service_id']))
        for format in ('json','markdown'):
            result=self.state.export_incident(incident['id'],{'format':format,'include_notes':False})
            self.assertNotIn(marker,result['content'])
            self.assertFalse(result['summary']['notes_included'])
        included=self.state.export_incident(incident['id'],{'format':'json','include_notes':True})
        self.assertIn(marker,included['content'])
        self.assertNotIn('raw_log',included['content'])

    def test_markdown_export_keeps_notes_literal(self):
        incident=self.lab_incident()
        note='<script>alert(1)</script>\n# Invented report heading\n[link](https://example.test)'
        self.state.update_incident(incident['id'],{'version':incident['version'],'action':'note','note':note})
        result=self.state.export_incident(incident['id'],{'format':'markdown','include_notes':True})
        self.assertIn('    <script>alert(1)</script>',result['content'])
        self.assertIn('    # Invented report heading',result['content'])
        self.assertNotIn('\n# Invented report heading',result['content'])
        self.assertEqual(result['media_type'],'text/markdown')

    def test_export_validation_missing_incident_and_token(self):
        incident=self.lab_incident()
        route=f'/api/incidents/{incident["id"]}/export'
        for payload in ({},{'format':'html','include_notes':False},{'format':'json','include_notes':1},{'format':'json','include_notes':False,'extra':True}):
            self.assertEqual(self.request(route,'POST',payload)[0],400)
        valid={'format':'json','include_notes':False}
        self.assertEqual(self.request(route,'POST',valid,{'X-Console-Token':''})[0],403)
        self.assertEqual(self.request('/api/incidents/missing/export','POST',valid)[0],404)

    def test_export_bounds_retained_evidence_and_flags_truncation(self):
        incident=self.lab_incident()
        sample={'status':'warning','detail':{'status':'timeout','duration_ms':3}}
        with self.state.db() as db:
            for index in range(101):
                run_id='export-sample-'+str(index)
                db.execute("INSERT INTO runs(id,state,started_at,finished_at,source) VALUES(?,'completed',?,?,'manual')",(run_id,now(),now()))
                db.execute('INSERT INTO observations(run_id,service_id,revision,payload,maintenance_version) VALUES(?,?,?,?,0)',(run_id,incident['service_id'],incident['revision'],json.dumps(sample)))
        result=self.state.export_incident(incident['id'],{'format':'json','include_notes':False})
        report=json.loads(result['content'])
        self.assertEqual(len(report['evidence']),100)
        self.assertTrue(report['scope']['evidence_truncated'])
        self.assertTrue(report['scope']['retained_history_only'])


if __name__ == '__main__':
    unittest.main()
