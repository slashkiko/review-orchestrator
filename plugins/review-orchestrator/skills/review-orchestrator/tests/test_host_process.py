from __future__ import annotations

import os
import select
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import run_host_smoke


@unittest.skipUnless(os.name == 'posix', 'host adapters require POSIX process groups')
class HostProcessTest(unittest.TestCase):
    def test_timeout_stops_a_cli_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fifo = root / 'worker-ready'
            os.mkfifo(fifo)
            reader = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
            worker = root / 'worker.py'
            worker.write_text(
                'import signal, sys\n'
                'with open(sys.argv[1], "wb", buffering=0) as pipe:\n'
                '    pipe.write(b"R")\n'
                '    signal.pause()\n'
            )
            parent = root / 'parent.py'
            parent.write_text(
                'import subprocess, sys\n'
                'subprocess.run([sys.executable, sys.argv[1], sys.argv[2]], check=True)\n'
            )
            original_wait = subprocess.Popen.wait
            ready = False
            first = True

            def wait_after_worker_ready(process, timeout=None):
                nonlocal first, ready
                if first:
                    first = False
                    # Force expiry only after the real descendant holds the pipe;
                    # the test does not depend on a sleep or scheduler timing.
                    readable, _, _ = select.select([reader], [], [], 10)
                    ready = bool(readable) and os.read(reader, 1) == b'R'
                    raise subprocess.TimeoutExpired(process.args, timeout)
                return original_wait(process, timeout=timeout)

            try:
                with mock.patch.object(subprocess.Popen, 'wait', wait_after_worker_ready):
                    with self.assertRaises(subprocess.TimeoutExpired):
                        run_host_smoke.run_host_process(
                            [sys.executable, str(parent), str(worker), str(fifo)],
                            root, dict(os.environ), subprocess.DEVNULL, 10,
                        )
                self.assertTrue(ready, 'descendant did not reach the readiness barrier')
                readable, _, _ = select.select([reader], [], [], 10)
                self.assertTrue(readable, 'descendant still holds the pipe after timeout')
                self.assertEqual(b'', os.read(reader, 1))
            finally:
                os.close(reader)

    def test_environment_preserves_login_identity_without_loader_overrides(self) -> None:
        with mock.patch.dict(os.environ, {"USER": "smoke-user", "SECURITYSESSIONID": "123", "NODE_OPTIONS": "--inspect"}, clear=True):
            environment = run_host_smoke.host_environment()
        self.assertEqual("smoke-user", environment["USER"])
        self.assertEqual("123", environment["SECURITYSESSIONID"])
        self.assertNotIn("NODE_OPTIONS", environment)
        self.assertEqual(run_host_smoke.trusted_path(), environment["PATH"])

    def test_success_preserves_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_host_smoke.run_host_process(
                [sys.executable, '-c', 'raise SystemExit(7)'],
                Path(directory), dict(os.environ), subprocess.DEVNULL, 10,
            )
        self.assertEqual(7, result.returncode)


if __name__ == '__main__':
    unittest.main()
