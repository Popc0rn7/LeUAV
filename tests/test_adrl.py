"""Offline migration tests; no Docker, simulator, network or board operations."""
import ast
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import yaml

from leuav.adrl import cli, runtime
from leuav.adrl.config import load_profile
from leuav.runtime import processes
from leuav.simulation.airsim import adrl_compat
from leuav.teleop.bundle import bundle
from leuav.teleop.protocol import namespace


class MigrationTests(unittest.TestCase):
    def test_profile_and_resource_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            scene=root/'package'
            for relative in ('Engine','ADRL/Content','ADRL/Binaries/Linux'):
                (scene/relative).mkdir(parents=True, exist_ok=True)
            (scene/'ADRL/Binaries/Linux/ADRL').touch()
            (root/'resources.local.yaml').write_text('resources:\n  adrl_package:\n    path: package\n')
            data=dict(case='adrl',scene_resource='adrl_package',px4_image='px4',ros_image='ros',ros_domain_id=23,namespace='/uav/test/teleop',containers=dict(px4='p',ros='r'),output='output')
            profile=root/'profile.yaml'
            profile.write_text(yaml.safe_dump(data))
            parsed=load_profile(profile,root)
            self.assertEqual(parsed['scene'],scene)
            with patch.object(processes, 'command', side_effect=AssertionError('plan must be offline')), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['--profile',str(profile),'--workspace',str(root),'plan']),0)
            for field,value in [('ros_domain_id',True),('namespace','bad'),('output','package/cache')]:
                broken={**data,field:value}
                profile.write_text(yaml.safe_dump(broken))
                with self.assertRaises(ValueError):load_profile(profile,root)

    def test_unknown_elf_rejected(self):
        with self.assertRaisesRegex(ValueError,'摘要'):
            adrl_compat.patch(b'unknown ELF',disable_lockstep=True)

    def test_foreign_container_is_never_executed(self):
        state=dict(container='same-name',container_id='ours',owner='owner')
        with patch.object(processes,'inspect_container',return_value=dict(Id='foreign',Config=dict(Labels={}),State=dict(Running=True))), patch.object(processes,'command') as command:
            with self.assertRaises(RuntimeError):processes.px4(state,'commander','land')
            command.assert_not_called()

    def test_computer_has_no_agent_and_records_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp)/'run';run.mkdir()
            state=dict(owner='owner',run_dir=str(run),config=dict(ros_container='test-agent',ros_image='sha256:ros',ros_domain_id=23))
            with patch.object(processes,'command',return_value=SimpleNamespace(stdout='agent-id\n')) as command:
                runtime.start_computer(state)
            argv=command.call_args.args
            self.assertIn('ROS_DOMAIN_ID=23',argv)
            self.assertIn('FASTRTPS_DEFAULT_PROFILES_FILE=/leuav-src/leuav/contracts/fastdds_udp.xml',argv)
            self.assertEqual('exec sleep infinity',argv[-1])
            self.assertNotIn('teleop.flight',argv[-1])
            self.assertEqual(state['ros_container_id'],'agent-id')

    def test_native_start_persists_uncertainty(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            state=dict(race=dict(phase='prepared'))
            with patch.object(processes,'px4',return_value=SimpleNamespace(stdout='arming_state: 1')), patch.object(runtime,'ready',return_value=True), patch.object(runtime,'rpc',side_effect=RuntimeError('lost reply')) as rpc:
                with self.assertRaisesRegex(RuntimeError,'lost reply'):cli.start_race(state,directory)
                self.assertEqual(json.loads((directory/'state.json').read_text())['race']['phase'],'starting')
                with self.assertRaises(RuntimeError):cli.start_race(state,directory)
                rpc.assert_called_once()

    def test_startup_failure_reclaims_owned_resources(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,DISPLAY=':test'):
            root=Path(tmp);executable=root/'package/ADRL/Binaries/Linux/ADRL'
            executable.parent.mkdir(parents=True);executable.touch()
            options=SimpleNamespace(image='px4',ros_image='ros',domain=23,namespace='/uav/test/teleop',profile='profile',settings=runtime.HERE/'settings.json',scene=root/'source',window_mode=None,display=None)
            task=Mock();task.verify.side_effect=RuntimeError('verify failed')
            with patch.object(runtime,'STATE_DIR',root,create=True), patch.object(runtime,'PX4_CONTAINER','test-px4',create=True), patch.object(runtime,'ROS_CONTAINER','test-ros',create=True), patch.object(runtime,'check_conflicts'), patch.object(runtime,'prepare',return_value=executable), patch.object(runtime.subprocess,'Popen',return_value=Mock(pid=123,poll=Mock(return_value=None))), patch.object(processes,'command',return_value=SimpleNamespace(stdout='[{"Id":"image-id","Config":{"Labels":{"io.leuav.flight-board.version":"1"}}}]')), patch.object(processes,'start_ticks',return_value='ticks'), patch.object(processes,'listen_owned',return_value=True), patch.object(runtime,'ready',return_value=True), patch.object(runtime,'start_computer'), patch.object(runtime,'agent_running',return_value=True), patch.object(runtime,'shutdown') as shutdown:
                with self.assertRaisesRegex(RuntimeError,'verify failed'):runtime.up(options,task)
                shutdown.assert_called_once()
                self.assertTrue(shutdown.call_args.kwargs['force'])
                self.assertTrue(list(root.glob('*/startup-error.json')))

    def test_bundle_is_repeatable_and_has_no_pc_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=(tmp,23,'/uav/test/teleop','/sys_prod/robot/install','/data/local/workspace/ros/install','/sys_prod/robot/out')
            directory=bundle(*args)
            self.assertEqual(bundle(*args),directory)
            manifest=json.loads((directory/'manifest.json').read_text())
            for name,digest in manifest['files'].items():
                self.assertEqual(hashlib.sha256((directory/name).read_bytes()).hexdigest(),digest)
            self.assertNotIn('leuav/resources.py',manifest['files'])
            self.assertIn('LEUAV_NAMESPACE=/uav/test/teleop',(directory/'ros_env.sh').read_text())

    def test_namespace_is_explicit(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(ValueError):namespace()
        with patch.dict(os.environ,LEUAV_NAMESPACE='/uav/demo/teleop'):
            self.assertEqual(namespace(),'/uav/demo/teleop')

    def test_migrated_imports_have_no_course_dependency(self):
        root=Path(__file__).resolve().parents[1]/'src/leuav'
        for path in root.rglob('*.py'):
            tree=ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom):
                    self.assertFalse((node.module or '').startswith(('stage1','stage2','stage3','stage4','src.')),str(path))


if __name__=='__main__':unittest.main()

class DeploymentTests(unittest.TestCase):
    def test_invalid_bundle_never_contacts_device(self):
        from leuav.deployment.hdc import deploy
        with tempfile.TemporaryDirectory() as tmp:
            directory=bundle(tmp,23,'/uav/test/teleop','/ros','/messages','/python')
            (directory/'leuav/teleop/flight.py').write_text('changed')
            with patch('leuav.deployment.hdc.shell') as shell:
                with self.assertRaises(ValueError):deploy(directory,'test-device')
                shell.assert_not_called()

    def test_upload_is_targeted_and_does_not_start_process(self):
        from leuav.deployment.hdc import deploy
        with tempfile.TemporaryDirectory() as tmp:
            directory=bundle(tmp,23,'/uav/test/teleop','/ros','/messages','/python')
            with patch('leuav.deployment.hdc.shell') as shell, patch('leuav.deployment.hdc.subprocess.run') as run, contextlib.redirect_stdout(io.StringIO()):
                remote=deploy(directory,'chosen-device')
            self.assertIn('test ! -e',shell.call_args_list[0].args[1])
            self.assertEqual(shell.call_args_list[-1].args[1],f'cd {remote} && sha256sum -c SHA256SUMS')
            for call in run.call_args_list:
                self.assertEqual(call.args[0][:5],['hdc','-t','chosen-device','file','send'])
            self.assertFalse(any('kill' in c.args[1] or 'start.sh' in c.args[1] for c in shell.call_args_list))

    def test_remote_exit_status_is_required(self):
        from leuav.deployment.hdc import shell
        with patch('leuav.deployment.hdc.subprocess.run',return_value=SimpleNamespace(stdout='apparent success',stderr='')):
            with self.assertRaises(RuntimeError):shell('target','true')


class KeyboardTests(unittest.TestCase):
    def test_complete_mapping_and_input_expiry(self):
        from test_teleop_controller import load_controller
        keyboard=load_controller('keyboard.py')
        self.assertEqual(keyboard.map_keys({'w','a','up','left'},1),(1,1,1,1))
        self.assertEqual(keyboard.map_keys({'w','s','a','d','up','down','left','right'}),(0,0,0,0))
        self.assertEqual(keyboard.map_keys({'w','space'}),(0,0,0,0))
        self.assertEqual(keyboard.command_for('k'),'land')
        keys=keyboard.RecentKeys();keys.press('w',10)
        self.assertFalse(keys.active(10.21))
