import asyncio
import tempfile
import unittest
import uuid
import json
import threading
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .client import MicroLightClient
from pathlib import Path
from quart import Quart
from .inbox import Inbox
from .main import MicroLightPlugin, TOOL_NAMES
from .templates import render_message, DEFAULT_TEMPLATES


class NotificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'inbox.sqlite3'
        self.inbox = Inbox(self.path)
        self.event = dict(version=1, id=str(uuid.uuid4()), kind='feedback', recordId='fixture', title='测试', summary='fixture', status='待处理', occurredAt='2026-11-16T00:00:00Z')

    def test_persistence_deduplication_and_retry(self):
        self.assertTrue(self.inbox.accept(self.event))
        self.assertTrue(Inbox(self.path).accept(self.event))
        self.assertEqual(self.inbox.status(), {'pending': 1})
        event_id, _, _ = Inbox(self.path).next()
        self.inbox.finish(event_id, 9, True)
        self.assertEqual(self.inbox.status(), {'failed': 1})
        self.assertEqual(self.inbox.retry(), 1)
        self.assertEqual(self.inbox.next()[0], event_id)
        self.inbox.finish(event_id, 0)
        self.assertIsNone(self.inbox.next())
        self.assertTrue(self.inbox.accept(self.event))
        self.assertEqual(self.inbox.status(), {'sent': 1})

    def test_notification_templates(self):
        for kind in ('alerts', 'feedback', 'friends'):
            event = {**self.event, 'kind': kind, 'level': 'error'}
            self.assertEqual(render_message(event, {}), render_message(event, {'template_'+kind: ''}))
            self.assertIn('测试', render_message(event, {}))
            self.assertIn('时间：', render_message(event, {}))
            custom = {'template_'+kind: '{category}\n{title}: {summary} [{status}] {level} {unknown}'}
            result = render_message({**event, 'summary': '{title}'}, custom)
            self.assertIn('测试: {title}', result)
            self.assertIn('错误 {unknown}', result)
            self.assertNotIn('编号：', result)
        self.assertEqual(len(DEFAULT_TEMPLATES), 3)

    def test_api_client_bearer_and_no_redirect(self):
        token = 'ml_' + 'a'*43
        requests = []
        redirect = [False]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                requests.append((self.path, self.headers.get('Authorization')))
                if redirect[0]:
                    self.send_response(302)
                    self.send_header('Location', '/redirected')
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(json.dumps({'service': 'MicroLight', 'version': 1, 'scopes': ['alerts:read']}).encode())
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = MicroLightClient(f'http://127.0.0.1:{server.server_port}', token)
            self.assertEqual(client.status()['scopes'], ['alerts:read'])
            self.assertEqual(requests[0], ('/api/microlight/v1/status', 'Bearer '+token))
            redirect[0] = True
            with self.assertRaisesRegex(ValueError, 'HTTP 302'):
                client.status()
            self.assertEqual(len(requests), 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        with self.assertRaises(ValueError):
            MicroLightClient('https://site.test', 'bad\nsecret')

    async def test_management_guidance_is_admin_only(self):
        plugin = object.__new__(MicroLightPlugin)
        plugin.config = {'enabled': True, 'admin_uids': ['42']}
        req = SimpleNamespace(system_prompt='existing')
        event = SimpleNamespace(get_sender_id=lambda: '7', get_message_str=lambda: '弃用友链')
        await plugin.guide_microlight_tools(event, req)
        self.assertEqual(req.system_prompt, 'existing')
        event.get_sender_id = lambda: '42'
        await plugin.guide_microlight_tools(event, req)
        self.assertTrue(req.system_prompt.startswith('existing'))
        self.assertIn('microlight_abandon_friend', req.system_prompt)
        self.assertIn('不能代替弃用', req.system_prompt)

    async def test_persona_allowlist_preserves_existing_tools(self):
        plugin = object.__new__(MicroLightPlugin)
        plugin.config = {'tool_persona': 'fixture-persona'}
        manager = SimpleNamespace(get_persona=AsyncMock(return_value=SimpleNamespace(tools=['existing-tool', 'microlight_review_friend'])), update_persona=AsyncMock())
        plugin.context = SimpleNamespace(persona_manager=manager)
        self.assertEqual(await plugin.ensure_persona_tools(), len(TOOL_NAMES))
        manager.update_persona.assert_awaited_once_with('fixture-persona', tools=['existing-tool']+list(TOOL_NAMES))
        manager.get_persona.return_value.tools = ['existing-tool']+list(TOOL_NAMES)
        manager.update_persona.reset_mock()
        self.assertEqual(await plugin.ensure_persona_tools(), 0)
        manager.update_persona.assert_not_awaited()

    async def test_llm_tools_authorization_and_routes(self):
        plugin = object.__new__(MicroLightPlugin)
        plugin.config = {'enabled': True, 'admin_uids': ['42'], 'api_token': 'ml_'+'a'*43}
        denied = SimpleNamespace(get_sender_id=lambda: '7')
        allowed = SimpleNamespace(get_sender_id=lambda: '42')
        with patch.object(MicroLightClient, 'call', return_value={'ok': True}) as call:
            self.assertIn('未授权', await plugin.delete_alert_tool(denied, '1'))
            call.assert_not_called()
            await plugin.delete_alert_tool(allowed, '1')
            call.assert_called_with('DELETE', 'alerts/1')
            await plugin.approve_friend_tool(allowed, 'fixture-id')
            call.assert_called_with('POST', 'friends/fixture-id/approve')
            await plugin.resolve_feedback_tool(allowed, 'fixture-id')
            call.assert_called_with('POST', 'feedback/fixture-id/resolve')
            call.reset_mock()
            self.assertIn('确认', await plugin.failure_mail_tool(allowed, 'fixture-id', False))
            call.assert_not_called()
            self.assertIn('未授权', await plugin.failure_mail_tool(denied, 'fixture-id', True))
            call.assert_not_called()
            await plugin.failure_mail_tool(allowed, 'fixture-id', True)
            call.assert_called_with('POST', 'friends/fixture-id/failure-mail')
            call.reset_mock()
            self.assertIn('未授权', await plugin.retry_task_tool(denied, 'article-index'))
            call.assert_not_called()
            await plugin.retry_task_tool(allowed, 'article-index')
            call.assert_called_with('POST', 'tasks/article-index/retry')
            call.reset_mock()
            self.assertIn('确认', await plugin.abandon_friend_tool(allowed, 'fixture-id', False))
            call.assert_not_called()
            self.assertIn('未授权', await plugin.abandon_friend_tool(denied, 'fixture-id', True))
            call.assert_not_called()
            await plugin.abandon_friend_tool(allowed, 'fixture-id', True)
            call.assert_called_with('POST', 'friends/fixture-id/abandon')
            call.reset_mock()
            self.assertIn('未授权', await plugin.auto_review_friends_tool(denied))
            call.assert_not_called()
            await plugin.auto_review_friends_tool(allowed)
            call.assert_called_with('POST', 'friends/auto-review')
            await plugin.auto_review_friends_tool(allowed, 'fixture-id')
            call.assert_called_with('POST', 'friends/fixture-id/auto-review')
            await plugin.records_tool(allowed, 'tasks', 'article-index')
            call.assert_called_with('GET', 'tasks/article-index')
            call.reset_mock()
            self.assertIn('无效', await plugin.approve_friend_tool(allowed, '../bad'))
            call.assert_not_called()

    async def test_webhook_auth_validation_and_durable_ack(self):
        plugin = object.__new__(MicroLightPlugin)
        plugin.config = {'enabled': True, 'api_token': 'fixture-token'}
        plugin.inbox = self.inbox
        app = Quart(__name__)
        app.add_url_rule('/webhook', view_func=plugin.webhook, methods=['POST'])
        client = app.test_client()
        response = await client.post('/webhook', json=self.event)
        self.assertEqual(response.status_code, 401)
        response = await client.post('/webhook', json={**self.event, 'kind': 'unknown'}, headers={'X-MicroLight-Token': 'fixture-token'})
        self.assertEqual(response.status_code, 400)
        for _ in range(2):
            response = await client.post('/webhook', json=self.event, headers={'X-MicroLight-Token': 'fixture-token'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(await response.get_json(), {'accepted': True, 'id': self.event['id']})
        self.assertEqual(Inbox(self.path).status(), {'pending': 1})
        plugin.config['api_token'] = 'rotated'
        response = await client.post('/webhook', json=self.event, headers={'X-MicroLight-Token': 'fixture-token'})
        self.assertEqual(response.status_code, 401)


if __name__ == '__main__':
    unittest.main()
