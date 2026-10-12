import gc
import pathlib
import tempfile
import threading
import types
import unittest
import weakref
from unittest.mock import Mock, patch

from trade_alert import notifier
from trade_alert.news import normalize_news_link
from trade_alert.state import MAX_ALERT_HISTORY, StateStore


class NotifierTests(unittest.TestCase):
    def setUp(self):
        notifier._active_toasts.clear()
        self.addCleanup(notifier._active_toasts.clear)

    def send(self, **kwargs):
        from winrt.windows.ui import notifications
        native = Mock()
        toaster = Mock()
        with (patch.object(notifier.os, 'name', 'nt'),
              patch.object(notifier, '_windows_toaster', return_value=toaster),
              patch.object(notifications, 'ToastNotification', return_value=native) as constructor):
            accepted = notifier.notify('Trade Alert', 'Test', **kwargs)
        constructor.assert_called_once_with(toaster._setup_toast.return_value.xmlDocument)
        self.assertEqual(False, toaster._setup_toast.call_args.args[1])
        self.assertEqual(['Trade Alert', 'Test'], toaster._setup_toast.call_args.args[0].text_fields)
        return accepted, native, toaster

    def test_native_notification_is_retained_with_stable_identity_and_bounded_history(self):
        accepted, native, toaster = self.send(item_key='story-a', on_click=Mock())
        self.assertTrue(accepted)
        toaster.toastNotifier.show.assert_called_once_with(native)
        self.assertEqual('alerts', native.group)
        self.assertEqual(16, len(native.tag))
        self.assertEqual(native.tag, self.send(item_key='story-a', on_click=Mock())[1].tag)
        self.assertNotEqual(native.tag, self.send(item_key='story-b', on_click=Mock())[1].tag)
        accepted, retained, _ = self.send(item_key='retain', on_click=Mock())
        reference = weakref.ref(retained)
        del retained
        gc.collect()
        self.assertIsNotNone(reference())
        for i in range(MAX_ALERT_HISTORY):
            self.send(item_key=str(i), on_click=Mock())
        self.assertEqual(MAX_ALERT_HISTORY, len(notifier._active_toasts))

    def invoke(self, native):
        # Join only the callback worker; the real backend uses an ordinary daemon thread.
        threads = []
        real_thread = threading.Thread
        def thread(**kwargs):
            worker = real_thread(**kwargs)
            threads.append(worker)
            return worker
        with patch.object(notifier.threading, 'Thread', side_effect=thread):
            native.add_activated.call_args.args[0](native, object())
        for worker in threads:
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())

    def test_successful_click_is_handled_once(self):
        action = Mock(return_value=True)
        _, native, _ = self.send(item_key='target', on_click=action)
        self.invoke(native)
        self.invoke(native)
        action.assert_called_once_with()

    def test_failed_click_and_exception_are_retryable(self):
        action = Mock(side_effect=[False, RuntimeError('browser failed'), True])
        _, native, _ = self.send(item_key='target', on_click=action)
        for _ in range(4):
            self.invoke(native)
        self.assertEqual(3, action.call_count)

    def test_plain_test_notification_has_no_click_handler(self):
        accepted, native, _ = self.send()
        self.assertTrue(accepted)
        native.add_activated.assert_not_called()
        self.assertFalse(notifier._active_toasts)

    def test_backend_failure_is_reported(self):
        with patch.object(notifier, '_windows_toaster', side_effect=RuntimeError('boom')):
            self.assertFalse(notifier.notify('Trade Alert', 'Test'))
        self.assertFalse(notifier._active_toasts)

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
