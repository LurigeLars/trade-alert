import pathlib
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from trade_alert import notifier
from trade_alert.news import normalize_news_link
from trade_alert.state import MAX_ALERT_HISTORY, StateStore


class NotifierTests(unittest.TestCase):
    def send(self, **kwargs):
        toaster = Mock()
        with (patch.object(notifier.os, 'name', 'nt'),
              patch.object(notifier, '_windows_toaster', return_value=toaster),
              patch.object(notifier, '_click_url', return_value='http://127.0.0.1:12345/alerts/token') as register):
            accepted = notifier.notify('Trade Alert', 'Test', **kwargs)
        return accepted, toaster.show_toast.call_args.args[0], register

    def test_standard_web_activation_and_stable_identity(self):
        action = Mock()
        accepted, toast, register = self.send(item_key='story-a', on_click=action)
        self.assertTrue(accepted)
        self.assertEqual(['Trade Alert', 'Test'], toast.text_fields)
        self.assertEqual('http://127.0.0.1:12345/alerts/token', toast.launch_action)
        register.assert_called_once_with(action)
        self.assertEqual('alerts', toast.group)
        self.assertEqual(16, len(toast.tag))
        self.assertEqual(toast.tag, self.send(item_key='story-a')[1].tag)
        self.assertNotEqual(toast.tag, self.send(item_key='story-b')[1].tag)

    def test_plain_test_notification_has_no_click_listener(self):
        accepted, toast, register = self.send()
        self.assertTrue(accepted)
        self.assertIsNone(toast.launch_action)
        register.assert_not_called()

    def test_backend_failure_is_reported_and_pending_action_removed(self):
        notifier._click_actions['/alerts/token'] = (Mock(), threading.Lock())
        toaster = Mock()
        toaster.show_toast.side_effect = RuntimeError('boom')
        with (patch.object(notifier, '_windows_toaster', return_value=toaster),
              patch.object(notifier, '_click_url', return_value='http://127.0.0.1:12345/alerts/token')):
            self.assertFalse(notifier.notify('Trade Alert', 'Test', on_click=Mock()))
        self.assertNotIn('/alerts/token', notifier._click_actions)

    def test_registers_only_notification_display_identity(self):
        import winreg
        with (patch.object(winreg, 'CreateKeyEx') as create,
              patch.object(winreg, 'SetValueEx') as write,
              patch('windows_toasts.WindowsToaster') as factory):
            notifier._windows_toaster()
        self.assertEqual(r'Software\Classes\AppUserModelId\Trade Alert', create.call_args.args[1])
        self.assertEqual('DisplayName', write.call_args.args[1])
        factory.assert_called_once_with('Trade Alert')

    def test_safe_urls_and_relative_tradingview_article(self):
        self.assertEqual('https://www.tradingview.com/news/reuters.com,2026:test/',
                         normalize_news_link('/news/reuters.com,2026:test/'))
        self.assertEqual('https://www.reuters.com/world/story/',
                         normalize_news_link('https://www.reuters.com/world/story/'))
        for value in (None, '', '//evil.test/news/x', '/other/x', '/news/',
                      '\nhttps://a.test/story', 'https://a.test/story\x7f',
                      '/news/../accounts/', '/news/%2e%2e/accounts/',
                      'http://tradingview.com/news/x', 'javascript:alert(1)',
                      'file:///secret', 'https://user@tradingview.com/news/x',
                      'https://www.tradingview.com\\@evil.test/news/x',
                      'https://www.tradingview.com/news/x\nhttps://evil.test',
                      'https://[broken/news/x', 'https://a.test:bad/x',
                      'https://a.test:8443/x'):
            with self.subTest(value=value):
                self.assertIsNone(normalize_news_link(value))


class ClickListenerTests(unittest.TestCase):
    def setUp(self):
        notifier._click_actions.clear()
        self.addCleanup(notifier._click_actions.clear)

    @classmethod
    def tearDownClass(cls):
        if notifier._click_server is not None:
            notifier._click_server.shutdown()
            notifier._click_server.server_close()
            notifier._click_server = None

    def request(self, url, host=None):
        from http.client import HTTPConnection
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        client = HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        try:
            client.request('GET', parsed.path, headers={'Host': host} if host else {})
            response = client.getresponse()
            return response.status, response.getheader('Location'), response.getheader('Cache-Control')
        finally:
            client.close()

    def test_one_listener_loopback_only_bounded_unpredictable_tokens(self):
        first = notifier._click_url(Mock())
        server = notifier._click_server
        self.assertEqual('127.0.0.1', server.server_address[0])
        self.assertNotIn('headline', first)
        self.assertGreaterEqual(len(first.rsplit('/', 1)[-1]), 32)
        for _ in range(MAX_ALERT_HISTORY):
            self.assertNotEqual(first, notifier._click_url(Mock()))
            self.assertIs(server, notifier._click_server)
        self.assertEqual(MAX_ALERT_HISTORY, len(notifier._click_actions))
        self.assertEqual(410, self.request(first)[0])

    def test_exact_redirect_read_acknowledgement_and_repeated_click(self):
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / 'state.db'
            store = StateStore(path)
            store.record_alert(item_key='target',source='TEST',headline='Target',body='body',score=3,
                               link='/news/reuters.com,2026:test/')
            store.record_alert(item_key='control',source='TEST',headline='Control',body='body',score=3)
            acknowledged = threading.Event()
            url = notifier._click_url(notifier.alert_click(path,'target',lambda _n:acknowledged.set()))
            self.assertEqual((303,'https://www.tradingview.com/news/reuters.com,2026:test/','no-store'),self.request(url))
            self.assertTrue(acknowledged.wait(5))
            records = {a.item_key:a for a in store.recent_alerts()}
            self.assertFalse(records['target'].unread)
            self.assertTrue(records['control'].unread)
            self.assertEqual(410,self.request(url)[0])
            store.close()

    def test_concurrent_requests_dispatch_once(self):
        done = threading.Event()
        def action(open_article):
            open_article('https://example.test/article')
            done.set()
            return True
        callback = Mock(side_effect=action)
        url = notifier._click_url(callback)
        results = []
        workers = [threading.Thread(target=lambda:results.append(self.request(url)[0])) for _ in range(4)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(timeout=5)
        self.assertTrue(done.wait(5))
        self.assertEqual([303,410,410,410],sorted(results))
        callback.assert_called_once()

    def test_host_unknown_token_and_injected_query_never_invoke_callback(self):
        callback = Mock()
        url = notifier._click_url(callback)
        self.assertEqual(403,self.request(url,host='evil.test')[0])
        self.assertEqual(410,self.request(url+'unknown')[0])
        # The exact request path must match; no caller-supplied redirect is accepted.
        from http.client import HTTPConnection
        client = HTTPConnection('127.0.0.1',notifier._click_server.server_port,timeout=5)
        client.request('GET',url.split(str(notifier._click_server.server_port),1)[1]+'?url=https://evil.test')
        self.assertEqual(410,client.getresponse().status)
        client.close()
        callback.assert_not_called()

    def test_handler_failure_keeps_token_for_retry_without_redirect(self):
        callback = Mock(side_effect=RuntimeError('failed'))
        url = notifier._click_url(callback)
        self.assertEqual(500,self.request(url)[0])
        self.assertEqual(500,self.request(url)[0])
        self.assertEqual(2,callback.call_count)


class AlertClickTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = pathlib.Path(self.temp.name) / 'state.db'
        self.store = StateStore(self.path)
        self.addCleanup(self.store.close)
        self.store.record_alert(item_key='target', source='DTV_NEWS_FLOW', headline='Target',
                                body='diagnostics', score=3, published=10, at=20,
                                link='/news/reuters.com,2026:test/')
        self.store.record_alert(item_key='newer', source='OTHER', headline='Newer',
                                body='body', score=3, at=30)

    def test_click_opens_exact_persisted_url_and_reads_only_target_on_its_own_thread(self):
        counts = []
        with patch.object(notifier.webbrowser, 'open_new_tab', return_value=True) as browser:
            worker = threading.Thread(target=notifier.alert_click(self.path, 'target', counts.append))
            worker.start()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
        browser.assert_called_once_with('https://www.tradingview.com/news/reuters.com,2026:test/')
        records = {a.item_key: a for a in self.store.recent_alerts()}
        self.assertFalse(records['target'].unread)
        self.assertTrue(records['newer'].unread)
        self.assertEqual([1], counts)
        self.assertEqual(10, records['target'].published)
        self.assertEqual(20, records['target'].created_at)

    def test_browser_failure_and_exception_leave_history_unread(self):
        with patch.object(notifier.webbrowser, 'open_new_tab', return_value=False):
            self.assertFalse(notifier.alert_click(self.path, 'target')())
        with patch.object(notifier.webbrowser, 'open_new_tab', side_effect=RuntimeError('browser failed')):
            with self.assertRaises(RuntimeError):
                notifier.alert_click(self.path, 'target')()
        self.assertEqual(2, self.store.unread_alert_count())

    def test_failed_redirect_write_does_not_acknowledge_or_consume_click(self):
        handler = object.__new__(notifier._ClickHandler)
        handler.path = '/alerts/test-write-failure'
        handler.server = Mock(server_port=12345)
        handler.headers = {'Host':'127.0.0.1:12345'}
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = Mock()
        handler.wfile.flush.side_effect = [ConnectionError('browser disconnected'), None]
        notifier._click_actions[handler.path] = (notifier.alert_click(self.path,'target'),threading.Lock())
        self.addCleanup(notifier._click_actions.pop, handler.path, None)
        handler.do_GET()
        self.assertEqual(2,self.store.unread_alert_count())
        self.assertIn(handler.path,notifier._click_actions)
        self.assertEqual(500,handler.send_response.call_args.args[0])

    def test_unknown_or_expired_key_never_opens_another_article(self):
        with patch.object(notifier.webbrowser, 'open_new_tab') as browser:
            self.assertFalse(notifier.alert_click(self.path, 'absent')())
            self.store.con.execute("DELETE FROM alerts WHERE item_key='target'")
            self.store.con.commit()
            self.assertFalse(notifier.alert_click(self.path, 'target')())
        browser.assert_not_called()
        self.assertEqual(1, self.store.unread_alert_count())

    def test_unsafe_link_reads_only_after_matching_history_is_shown(self):
        self.store.con.execute("UPDATE alerts SET link='javascript:bad' WHERE item_key='target'")
        self.store.con.commit()
        with (patch('trade_alert.tray._show_text_window') as show,
              patch.object(notifier.webbrowser, 'open_new_tab') as browser):
            self.assertTrue(notifier.alert_click(self.path, 'target')())
            self.assertEqual(2, self.store.unread_alert_count())
            self.assertIn('Target', show.call_args.args[1])
            self.assertNotIn('Newer', show.call_args.args[1])
            show.call_args.kwargs['on_shown']()
        browser.assert_not_called()
        self.assertEqual(1, self.store.unread_alert_count())

    def test_window_creation_failure_leaves_alert_unread(self):
        with patch('trade_alert.tray._show_text_window', side_effect=RuntimeError('window failed')):
            with self.assertRaises(RuntimeError):
                notifier.alert_click(self.path, 'newer')()
        self.assertEqual(2, self.store.unread_alert_count())

    def test_badge_refresh_failure_does_not_reopen_successful_article(self):
        callback = Mock(side_effect=RuntimeError('tray unavailable'))
        with patch.object(notifier.webbrowser, 'open_new_tab', return_value=True):
            self.assertTrue(notifier.alert_click(self.path, 'target', callback)())
        self.assertEqual(1, self.store.unread_alert_count())


if __name__ == '__main__':
    unittest.main()
