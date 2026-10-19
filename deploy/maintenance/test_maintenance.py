"""Isolated filesystem/permission/rollback tests; never access production paths."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

HERE=Path(__file__).resolve().parent
TEMP=HERE.parents[1]/'.tmp'
TEMP.mkdir(exist_ok=True)
def module(name):
    spec=importlib.util.spec_from_file_location('maintenance_'+name,HERE/(name+'.py'))
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
ops=module('maintenance');installer=module('install')


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=TEMP)
        self.root=Path(self.temp.name).resolve()
        self.worker=ops.Maintenance(self.root,owner=self.root.stat().st_uid)
        self.patches=contextlib.ExitStack()
        # Windows cannot model POSIX mode bits or symlink-safe rmtree. The CI
        # suite exercises the actual Linux guards and lock in addition to these.
        if os.name=='nt':
            self.patches.enter_context(patch.object(self.worker,'secure',side_effect=self.portable_secure))
            self.patches.enter_context(patch.object(self.worker,'locked',contextlib.nullcontext))
        self.patches.enter_context(patch.object(self.worker,'health',return_value={'status':'success'}))
        self.patches.enter_context(patch.object(ops.shutil.rmtree,'avoids_symlink_attacks',True,create=True))
        self.worker.releases.mkdir(parents=True,mode=0o700)
        for path in [self.worker.current.parent,self.worker.releases]:path.chmod(0o700)
        self.file(self.worker.path('/var/lib/ai-climbing/ops/last-backup.env'),b'RESULT=success\nREMOTE_VERIFIED=true\n')
    def tearDown(self):self.patches.close();self.temp.cleanup()
    def file(self,path,body=b'test'):
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        path.write_bytes(body);path.chmod(0o600);return path
    def portable_secure(self,path,directory=False):
        if path.is_symlink() or path.resolve()!=path or not (path.is_dir() if directory else path.is_file()):
            raise RuntimeError('Unexpected path; preserved')
        return path
    def release(self,rc):
        path=self.worker.releases/f'pilot-v2026.10.19-rc{rc}'
        self.file(path/'RELEASE_SHA',(f'{rc:040x}\n').encode())
        self.file(path/'BROWSER_RELEASE.json',b'{"mode":"browser-only"}')
        self.file(path/'backend/main.py')
        self.file(path/'backend/.venv/bin/python')
        self.file(path/'frontend/dist/index.html')
        for directory in [path,path/'backend',path/'backend/.venv',path/'frontend',path/'frontend/dist']:
            directory.chmod(0o700)
        return path
    def active(self,path):
        # Windows CI/local may not permit symlink creation. Mock only the current
        # link; tests with malicious release links use Linux's real filesystem.
        self.patches.enter_context(patch.object(self.worker,'active',return_value=path))
        self.patches.enter_context(patch.object(self.worker.current.__class__,'resolve',autospec=True,side_effect=self.resolver(path)))
    def resolver(self,active):
        original=self.worker.current.__class__.resolve
        return lambda path,*args,**kwargs: active if path==self.worker.current else original(path,*args,**kwargs)

    def test_cleanup_plan_keeps_current_even_after_rollback_and_two_newest_other_releases(self):
        releases=[self.release(rc) for rc in [1,2,3,4,10]]
        self.active(releases[0])
        result=self.worker.cleanup()
        self.assertEqual(set(result['keep']),{releases[i].name for i in [0,3,4]})
        self.assertEqual({r['tag'] for r in result['remove']},{releases[1].name,releases[2].name})
        self.assertTrue(all(p.exists() for p in releases))

    def test_cleanup_deletes_only_reviewed_inactive_browser_programs_and_keeps_data_and_backups(self):
        releases=[self.release(rc) for rc in [1,2,3,4]];self.active(releases[-1])
        business=self.file(self.worker.path('/var/lib/ai-climbing/data/private.sqlite3'),b'untouched')
        config=self.file(self.worker.path('/etc/ai-climbing/backend.env'),b'untouched')
        backup=self.file(self.worker.path('/var/backups/ai-climbing/daily/private.tar.gz'),b'untouched')
        result=self.worker.cleanup(execute=True)
        self.assertFalse(releases[0].exists());self.assertTrue(all(p.exists() for p in releases[1:]))
        self.assertTrue(all(p.read_bytes()==b'untouched' for p in [business,config,backup]))
        self.assertEqual(json.loads(Path(result['receipt']).read_text())['state'],'complete')

    def test_cleanup_refuses_user_data_legacy_unknown_or_incomplete_releases_before_any_deletion(self):
        current=self.release(4);self.active(current)
        old=self.release(1)
        scenarios=[(old/'backend/data/private.sqlite3',b'private'),
                   (old/'BROWSER_RELEASE.json',b'{"mode":"legacy"}'),
                   (self.worker.releases/'.pilot-v2026.10.19-rc5.building/private',b'staging')]
        for path,body in scenarios:
            previous=path.read_bytes() if path.is_file() else None
            self.file(path,body)
            with self.subTest(path=path),self.assertRaises((RuntimeError,KeyError)):
                self.worker.cleanup(execute=True)
            self.assertTrue(current.exists());self.assertTrue(old.exists());self.assertEqual(path.read_bytes(),body)
            if previous is not None:path.write_bytes(previous)
            else:
                path.unlink()
                if path.parent.name in ('data','.pilot-v2026.10.19-rc5.building'):path.parent.rmdir()

    def test_missing_remote_backup_or_unhealthy_current_prevents_cleanup(self):
        current=self.release(4);old=self.release(1);self.active(current)
        self.file(self.worker.path('/var/lib/ai-climbing/ops/last-backup.env'),b'RESULT=failed\n')
        with self.assertRaises(RuntimeError):self.worker.cleanup(execute=True)
        self.worker.health.side_effect=RuntimeError('unhealthy')
        with self.assertRaises(RuntimeError):self.worker.cleanup(execute=True)
        self.assertTrue(current.exists());self.assertTrue(old.exists())

    def test_secure_path_refuses_writable_symlink_or_nonroot_objects(self):
        path=Mock();path.resolve.return_value=path;path.is_symlink.return_value=False
        worker=ops.Maintenance()
        for uid,mode,link in [(1000,stat.S_IFREG|0o600,False),(0,stat.S_IFREG|0o622,False),(0,stat.S_IFREG|0o600,True)]:
            path.lstat.return_value=Mock(st_uid=uid,st_mode=mode);path.is_symlink.return_value=link
            with self.assertRaises(RuntimeError):worker.secure(path)

    def test_cancel_matches_only_exact_root_download_identity(self):
        args=[b'python3.12',b'deploy/browser/download_installer.py'];cwd='/tmp/ai-climbing-release.Abc123/source'
        self.assertTrue(ops.download_identity(0,args,cwd,0))
        for values in [(1000,args,cwd,0),(0,args,cwd,1000),(0,args,cwd+'/other',0),
                       (0,args,'/root/project',0),(0,[b'python3.12',b'other.py'],cwd,0),
                       (0,args+[b'; rm -rf /'],cwd,0)]:
            self.assertFalse(ops.download_identity(*values))

    def test_extra_arguments_and_unknown_actions_never_dispatch(self):
        for args in [[],['maintenance-status','/etc/passwd'],['maintenance-cleanup; id'],['shell'],['maintenance-cleanup','--force']]:
            with self.assertRaises(RuntimeError):ops.main(args)


@unittest.skipIf(os.name=='nt','POSIX installer integration runs in the Linux release gate')
class InstallerTests(unittest.TestCase):
    def test_transaction_rolls_back_dispatcher_sudoers_and_launcher_if_probe_fails(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            root=Path(folder).resolve();source=HERE.parents[1];sha='a'*40
            dispatcher=root/'usr/local/sbin/codex-ssh-dispatch';dispatcher.parent.mkdir(parents=True)
            dispatcher.write_text('#!/bin/bash\necho original\n')
            launcher=dispatcher.parent/'ai-climbing-maintenance';launcher.write_text('old launcher')
            sudoers=root/'etc/sudoers.d/ai-climbing-maintenance';sudoers.parent.mkdir(parents=True);sudoers.write_text('old sudoers')
            originals={p:p.read_bytes() for p in [dispatcher,launcher,sudoers]}
            def run(command,**kwargs):
                if command[0]=='/usr/sbin/runuser':raise subprocess.CalledProcessError(1,command)
                return subprocess.CompletedProcess(command,0,stdout='')
            with patch.object(installer,'secure'),self.assertRaises(subprocess.CalledProcessError):
                installer.install_files(source,sha,root,run)
            for path,body in originals.items():self.assertEqual(path.read_bytes(),body)

    def test_installer_uses_exact_sudo_commands_preserves_original_dispatch_and_is_repeatable(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            root=Path(folder).resolve();source=HERE.parents[1];sha='a'*40
            dispatcher=root/'usr/local/sbin/codex-ssh-dispatch';dispatcher.parent.mkdir(parents=True)
            dispatcher.write_text('#!/bin/bash\necho original\n');original=dispatcher.read_bytes()
            def run(command,**kwargs):
                if command[0]=='/usr/bin/bash':return subprocess.run(command,**kwargs)
                return subprocess.CompletedProcess(command,0,stdout=json.dumps({'source_sha':sha}))
            with patch.object(installer,'secure'):
                installer.install_files(source,sha,root,run);installer.install_files(source,sha,root,run)
            self.assertEqual((root/'usr/local/lib/ai-climbing/maintenance-base/ssh-dispatch').read_bytes(),original)
            text=(root/'etc/sudoers.d/ai-climbing-maintenance').read_text()
            self.assertNotIn('*',text);self.assertNotIn('ALL=(ALL)',text)
            for action in ops.ACTIONS:self.assertIn('/usr/local/sbin/ai-climbing-maintenance '+action,text)
            self.assertEqual(set(ops.ACTIONS),set(installer.ACTIONS))
            wrapper=dispatcher.read_text();self.assertIn('Invalid fixed maintenance action',wrapper)
            self.assertNotIn('eval',wrapper)
            fake_sudo=root/'fake-sudo';fake_legacy=root/'fake-legacy'
            fake_sudo.write_text('#!/bin/bash\nprintf "SUDO:%s\\n" "$*"\n');fake_sudo.chmod(0o700)
            fake_legacy.write_text('#!/bin/bash\nprintf "LEGACY:%s\\n" "$SSH_ORIGINAL_COMMAND"\n');fake_legacy.chmod(0o700)
            check=root/'dispatch-test'
            check.write_text(wrapper.replace('/usr/bin/sudo',str(fake_sudo)).replace('/usr/local/lib/ai-climbing/maintenance-base/ssh-dispatch',str(fake_legacy)))
            for action in ops.ACTIONS:
                output=subprocess.run(['/bin/bash',str(check)],env={**os.environ,'SSH_ORIGINAL_COMMAND':action},capture_output=True,text=True)
                self.assertEqual(output.returncode,0);self.assertIn('SUDO:-n /usr/local/sbin/ai-climbing-maintenance '+action,output.stdout)
            for action in ['maintenance-status extra','maintenance-status\nid','maintenance-cleanup; id','maintenance-tools$(id)']:
                output=subprocess.run(['/bin/bash',str(check)],env={**os.environ,'SSH_ORIGINAL_COMMAND':action},capture_output=True,text=True)
                self.assertEqual(output.returncode,64);self.assertNotIn('SUDO:',output.stdout);self.assertNotIn('LEGACY:',output.stdout)
            for action in ['status','logs 20','deploy pilot-v2026.10.18-rc3']:
                output=subprocess.run(['/bin/bash',str(check)],env={**os.environ,'SSH_ORIGINAL_COMMAND':action},capture_output=True,text=True)
                self.assertEqual(output.returncode,0);self.assertEqual(output.stdout.strip(),'LEGACY:'+action)


if __name__=='__main__':unittest.main()
