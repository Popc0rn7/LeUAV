"""Critical-child failure and normal shutdown own both process groups."""
import importlib.util
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from leuav.adrl import runtime

SOURCE = Path(__file__).resolve().parents[1]/'environments/flight_board/supervisor.py'
spec = importlib.util.spec_from_file_location('flight_board_supervisor', SOURCE)
board = importlib.util.module_from_spec(spec)
spec.loader.exec_module(board)


class SupervisorTests(unittest.TestCase):
    def test_agent_exit_stops_px4_and_returns_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);state=root/'state.json'
            result=board.run([sys.executable,'-c','import time; time.sleep(30)'],
                agent_command=[sys.executable,'-c','import time; time.sleep(.15)'],path=state,log_dir=root)
            data=json.loads(state.read_text())
            self.assertEqual(result,1)
            self.assertEqual(data['phase'],'stopped')
            self.assertFalse(board.alive(data['px4']))
            self.assertFalse(board.alive(data['agent']))

    def test_px4_exit_stops_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);state=root/'state.json'
            self.assertEqual(board.run([sys.executable,'-c','import time; time.sleep(.15)'],
                agent_command=[sys.executable,'-c','import time; time.sleep(30)'],path=state,log_dir=root),1)
            self.assertFalse(board.alive(json.loads(state.read_text())['agent']))

    def test_sigterm_stops_both_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);state=root/'state.json'
            code=f'''import importlib.util
from pathlib import Path
import sys
spec=importlib.util.spec_from_file_location('board',{str(SOURCE)!r})
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
raise SystemExit(b.run([sys.executable,'-c','import time; time.sleep(30)'],agent_command=[sys.executable,'-c','import time; time.sleep(30)'],path=Path({str(state)!r}),log_dir=Path({tmp!r})))
'''
            process=subprocess.Popen([sys.executable,'-c',code])
            try:
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    if state.exists() and json.loads(state.read_text()).get('phase')=='running':break
                    time.sleep(.02)
                else:self.fail('supervisor did not start')
                process.send_signal(signal.SIGTERM)
                self.assertEqual(process.wait(timeout=8),0)
                data=json.loads(state.read_text())
                self.assertFalse(board.alive(data['agent']))
                self.assertFalse(board.alive(data['px4']))
            finally:
                if process.poll() is None:process.kill();process.wait()

    def test_status_requires_agent_own_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.json';path.write_text(json.dumps(dict(phase='running',px4={},agent={})))
            with patch.object(board,'alive',return_value=True),patch.object(board,'udp_bound',return_value=False):
                self.assertFalse(board.status(path)['healthy'])

    def test_agent_health_comes_from_flight_board_not_computer(self):
        state=dict(config=dict(agent_location='flight_board'))
        with patch.object(runtime.process_manager,'owned_container',return_value=dict(Id='flight-board-id',State=dict(Running=True))),patch.object(runtime.process_manager,'owned_ros',side_effect=AssertionError('must not consult computer')),patch.object(runtime.process_manager,'command',return_value=type('Result',(),dict(returncode=0,stdout='{"agent_running": true}'))()) as command:
            self.assertTrue(runtime.agent_running(state))
            self.assertIn('flight-board-id',command.call_args.args)

    def test_agent_private_environment_does_not_leak_into_px4(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def command(path, seconds):
                code='import json,os,time; from pathlib import Path; Path('+repr(str(path))+').write_text(json.dumps(dict(library=os.environ.get("LD_LIBRARY_PATH"),profile=os.environ.get("FASTRTPS_DEFAULT_PROFILES_FILE")))); time.sleep('+str(seconds)+')'
                return [sys.executable,'-c',code]
            with patch.dict('os.environ',LD_LIBRARY_PATH='/host/runtime',FASTRTPS_DEFAULT_PROFILES_FILE='/host/profile.xml'):
                board.run(command(root/'px4.json',.3),agent_command=command(root/'agent.json',30),path=root/'state.json',log_dir=root)
            agent=json.loads((root/'agent.json').read_text());px4=json.loads((root/'px4.json').read_text())
            self.assertEqual(agent,dict(library='/opt/flight-board/lib',profile='/opt/flight-board/fastdds.xml'))
            self.assertEqual(px4,dict(library='/host/runtime',profile='/host/profile.xml'))
