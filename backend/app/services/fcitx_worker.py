"""One private offline pinyin context, JSON lines in/out. Invoked as desktop user.

Keeping the Fcitx input context alive between keystrokes avoids rebuilding the
DBus context (and replaying the whole pinyin string) on every key press.
"""
import json
import sys
import time


class PinyinSession:
    def __init__(self):
        import dbus
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib

        DBusGMainLoop(set_as_default=True)
        self.dbus = dbus
        self.GLib = GLib
        self.bus = dbus.SessionBus(private=True)
        self.im = dbus.Interface(
            self.bus.get_object('org.fcitx.Fcitx5', '/org/freedesktop/portal/inputmethod'),
            'org.fcitx.Fcitx.InputMethod1')
        self.ic = None
        self.applied = []
        self.result = {}
        self._create_context()

    def _new_result(self):
        return {'candidates': [], 'committed': '', 'has_next': False}

    def _create_context(self):
        # Destroy the previous context when available.
        if self.ic is not None:
            try:
                self.ic.DestroyIC()
            except Exception:
                pass
        self.result = self._new_result()
        self.applied = []
        path, _ = self.im.CreateInputContext([
            ('program', 'elevator-offline-input'),
            ('display', 'elevator:offline'),
        ])
        obj = self.bus.get_object('org.fcitx.Fcitx5', path)
        self.ic = self.dbus.Interface(obj, 'org.fcitx.Fcitx.InputContext1')
        obj.connect_to_signal('UpdateClientSideUI', self._update,
                              dbus_interface='org.fcitx.Fcitx.InputContext1')
        obj.connect_to_signal('CommitString', self._commit,
                              dbus_interface='org.fcitx.Fcitx.InputContext1')
        self.ic.SetCapability(self.dbus.UInt64((1 << 39) | 4 | 2 | 1))
        self.ic.FocusIn()
        self.ic.ProcessKeyEvent(32, 0, 4, False, 0)

    def _update(self, preedit, cursor, up, down, candidates, index, layout, prev, next_):
        self.result['candidates'] = [str(c[1]) for c in candidates]
        self.result['has_next'] = bool(next_)

    def _commit(self, text):
        self.result['committed'] = self.result.get('committed', '') + str(text)

    def _drain(self):
        context = self.GLib.MainContext.default()
        end = time.monotonic() + .005
        while time.monotonic() < end:
            while context.pending():
                context.iteration(False)
            time.sleep(.0005)

    def process(self, actions):
        # Frontend sends the complete action history. If it was reset or
        # rewound (candidate commit/backspace), rebuild the Fcitx context.
        common = 0
        while (common < len(actions) and common < len(self.applied)
               and actions[common] == self.applied[common]):
            common += 1
        if common < len(self.applied):
            self._create_context()
            common = 0
        for action in actions[common:]:
            if 'key' in action:
                key = action['key']
                value = 0xff08 if key == 'BackSpace' else ord(key)
                self.ic.ProcessKeyEvent(value, 0, 0, False, 0)
            elif 'candidate' in action:
                self._drain()
                if action['candidate'] not in self.result['candidates']:
                    raise ValueError('候选词已变化，请重新选择')
                self.ic.SelectCandidate(self.result['candidates'].index(action['candidate']))
            else:
                self.ic.NextPage()
            self.applied.append(action)
            self._drain()
        return self.result


_session = None


def get_session():
    global _session
    if _session is None:
        _session = PinyinSession()
    return _session


if __name__ == '__main__':
    for line in sys.stdin:
        try:
            result = get_session().process(json.loads(line))
            sys.stdout.write(json.dumps(result, ensure_ascii=False) + '\n')
        except Exception:
            # A broken context should never poison the next composition.
            try:
                if _session is not None:
                    _session._create_context()
            except Exception:
                _session = None
            sys.stdout.write(json.dumps({'error': '本机拼音输入暂不可用，请重试'},
                                         ensure_ascii=False) + '\n')
        sys.stdout.flush()
