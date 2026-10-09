"""Minimal synchronous Chrome DevTools pipe client (no third-party dependencies)."""
import json
import os
import select
import subprocess
import sys
import time


class ChromePipe:
    def __init__(self, command, stderr):
        # Chrome expects protocol pipes on fd 3/4. Remap in a fresh child rather
        # than preexec_fn, which is unsafe with the HTTP server thread running.
        wrapper = ('import os,sys; os.dup2(0,3); os.dup2(1,4); '
                   'os.dup2(2,1); os.execv(sys.argv[1],sys.argv[1:])')
        self.process = subprocess.Popen([sys.executable, '-c', wrapper, *command,
                                         '--remote-debugging-pipe'],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr)
        self.buffer = b''
        self.sequence = 0

    def call(self, method, params=None, session=None, timeout=15):
        self.sequence += 1
        message = {'id': self.sequence, 'method': method, 'params': params or {}}
        if session:
            message['sessionId'] = session
        self.process.stdin.write(json.dumps(message).encode() + b'\0')
        self.process.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            while b'\0' in self.buffer:
                raw, self.buffer = self.buffer.split(b'\0', 1)
                reply = json.loads(raw)
                if reply.get('id') != self.sequence:
                    continue  # Notifications and other sessions are not replies.
                if 'error' in reply:
                    raise RuntimeError(f'Chrome {method}: {reply["error"]}')
                return reply.get('result', {})
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.process.stdout], [], [], remaining)[0]:
                raise TimeoutError(f'Chrome did not answer {method}')
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError(f'Chrome exited before answering {method}')
            self.buffer += chunk

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process.stdin.close()
        self.process.stdout.close()


def wait_for_result(browser, session, timeout=45):
    """Poll using real elapsed time so file reads and network callbacks can finish."""
    deadline = time.monotonic() + timeout
    expression = """JSON.stringify({
      finished: !!document.getElementById('browser-results'),
      html: document.documentElement.outerHTML,
      status: document.getElementById('profile-status')?.textContent || '',
      errors: window.browserErrors || []})"""
    last = {}
    while time.monotonic() < deadline:
        result = browser.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True}, session,
                              timeout=min(10, max(.1, deadline - time.monotonic())))
        value = result.get('result', {}).get('value')
        if value:
            last = json.loads(value)
            if last['finished']:
                return last['html']
        time.sleep(.1)
    raise TimeoutError(f'Browser tests did not finish after {timeout}s. '
                       f'Private settings status: {last.get("status", "")}; errors: {last.get("errors", [])}')
