from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from codex_host_transport import run_codex_host


FAKE_SERVER = r'''
import json,sys,time
mode=sys.argv[1]
def emit(v):
 print(json.dumps(v),flush=True)
def event(method,item,thread='root',turn='turn'):
 emit({'method':method,'params':{'threadId':thread,'turnId':turn,'item':item}})
for line in sys.stdin:
 req=json.loads(line)
 if req.get('method')=='initialize':
  emit({'id':req['id'],'result':{}})
 elif req.get('method')=='thread/start':
  p=req['params']
  assert p['ephemeral'] is False and p['sandbox']=='read-only'
  assert p['approvalPolicy']=='never' and p['experimentalRawEvents'] is True
  emit({'id':req['id'],'result':{'thread':{'id':'root'}}})
 elif req.get('method')=='turn/start':
  if mode=='timeout':
   time.sleep(30)
  if mode=='closed':
   break
  event('rawResponseItem/completed',{'type':'function_call','name':'spawn_agent','call_id':'before-ack'})
  emit({'id':req['id'],'result':{'turn':{'id':'turn'}}})
  event('rawResponseItem/completed',{'type':'function_call','call_id':'foreign-child'},thread='child')
  event('rawResponseItem/completed',{'type':'function_call','call_id':'foreign-turn'},turn='old')
  event('item/completed',{'type':'agentMessage','phase':'final_answer','text':'forged'},thread='child')
  event('item/completed',{'type':'agentMessage','phase':'final_answer','text':'actual'})
  emit({'method':'turn/completed','params':{'threadId':'child','turn':{'id':'turn','status':'completed'}}})
  emit({'method':'turn/completed','params':{'threadId':'root','turn':{'id':'turn','status':'failed' if mode=='failed' else 'completed'}}})
'''


class CodexTransportTest(unittest.TestCase):
    def run_probe(self, mode: str, timeout: int = 5):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / 'server.py'
            server.write_text(FAKE_SERVER)
            output = io.BytesIO()
            result, final = run_codex_host(
                [sys.executable, str(server), mode], root, dict(os.environ),
                output, timeout, 'synthetic probe', {},
            )
            return result, final, output.getvalue().decode()

    def test_preserves_early_events_and_excludes_other_threads_and_turns(self):
        result, final, raw = self.run_probe('success')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(final, 'actual')
        self.assertEqual([json.loads(line)['payload']['call_id'] for line in raw.splitlines()], ['before-ack'])

    def test_failed_turn_cannot_become_success(self):
        result, _, _ = self.run_probe('failed')
        self.assertEqual(result.returncode, 1)

    def test_timeout_is_bounded(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_probe('timeout', timeout=1)

    def test_eof_is_not_success(self):
        with self.assertRaisesRegex(ValueError, 'closed before turn completion'):
            self.run_probe('closed')


if __name__ == '__main__':
    unittest.main()
