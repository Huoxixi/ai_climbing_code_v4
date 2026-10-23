"""Meaningful checks for destructive retirement and full-app archive privacy."""
import contextlib
import importlib.util
import io
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from desktop.archive_installed_app import archive
spec=importlib.util.spec_from_file_location('retire',ROOT/'deploy/browser/retire_legacy_project.py')
retire=importlib.util.module_from_spec(spec)
spec.loader.exec_module(retire)
model_spec=importlib.util.spec_from_file_location('model_installer',ROOT/'backend/scripts/install_replay_rtmw.py')
model_installer=importlib.util.module_from_spec(model_spec)
model_spec.loader.exec_module(model_installer)
installer_spec=importlib.util.spec_from_file_location('installer_download',ROOT/'deploy/browser/download_installer.py')
installer_download=importlib.util.module_from_spec(installer_spec)
installer_spec.loader.exec_module(installer_download)

class DeliverySafetyTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'.tmp').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'.tmp')
        self.root=Path(self.temp.name).resolve()
    def tearDown(self):self.temp.cleanup()
    def file(self,path,body=b'test'):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body);return path

    def test_installed_program_archive_preserves_runtime_models_and_excludes_private_files(self):
        app=self.root/'app'
        for name in ['ClimbingAssistant.exe','runtime/python.exe','models/model.pt','backend/app.py','LICENSE']:
            self.file(app/name)
        for name in ['.setup-owned.json','installation.json','.env','backend/data/video.mp4','.local/settings.json','runtime/cache/secret.json']:
            self.file(app/name,b'private-test-only-must-not-ship')
        output=self.root/'program.zip'
        with contextlib.redirect_stdout(io.StringIO()):archive(app,output,'0.1.17-local.20261017.2','a'*40)
        with zipfile.ZipFile(output) as bundle:
            names=bundle.namelist()
            self.assertTrue(any(name.endswith('/models/model.pt') for name in names))
            self.assertTrue(any(name.endswith('/runtime/python.exe') for name in names))
            self.assertFalse(any('backend/data/' in name or '.setup-owned' in name or 'installation.json' in name or '.env' in name or '/cache/' in name or '/.local/' in name for name in names))
            for name in names:self.assertNotIn(b'private-test-only-must-not-ship',bundle.read(name))
            update=json.loads(bundle.read(next(name for name in names if name.endswith('/local-update.json'))))
            self.assertNotIn('validated_source',update)

    def test_release_guards_preserve_active_release_and_actual_data_directory(self):
        releases=self.root/'releases';current=releases/retire.OLD_TAGS[-1];old=releases/retire.OLD_TAGS[0]
        self.file(current/'RELEASE_SHA');self.file(old/'RELEASE_SHA')
        with patch.object(retire,'RELEASES',releases):
            with self.assertRaises(RuntimeError):retire.validate_release(current,current)
            self.file(old/'backend/data/private.json')
            with self.assertRaises(RuntimeError):retire.validate_release(old,current)
        self.assertTrue((old/'backend/data/private.json').is_file())

    def test_installer_parallel_ranges_reassemble_and_verify_the_exact_public_file(self):
        body=b'fixed public installer'*150
        profile={'url':'https://example.test/fixed.exe','bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}
        target=self.root/'installer.exe';calls=[]
        def fetch(request,timeout):
            first,last=map(int,request.get_header('Range').split('=')[1].split('-'))
            calls.append((first,last))
            response=io.BytesIO(body[first:last+1]);response.status=206
            response.headers={'Content-Range':f'bytes {first}-{last}/{len(body)}'}
            return response
        with patch.object(installer_download,'CHUNK_BYTES',128),patch.object(installer_download.urllib.request,'urlopen',side_effect=fetch):
            with contextlib.redirect_stdout(io.StringIO()):installer_download.download(profile,target)
        self.assertEqual(target.read_bytes(),body)
        self.assertEqual(sorted(calls),[(start,min(start+128,len(body))-1) for start in range(0,len(body),128)])
        self.assertFalse(target.with_suffix('.partial').exists())

    def test_asset_api_is_resolved_once_before_parallel_verified_ranges(self):
        body=b'fixed public installer'*150
        api='https://api.github.com/repos/Huoxixi/climbing-assistant-local/releases/assets/667783015'
        resolved='https://release-assets.githubusercontent.com/fixed-test-asset?signature=test'
        profile={'url':'https://github.com/fixed.exe','asset_api_url':api,
                 'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}
        calls=[]
        def fetch(request,timeout):
            calls.append(request.full_url)
            first,last=map(int,request.get_header('Range').split('=')[1].split('-'))
            if request.full_url==api:
                self.assertEqual(request.get_header('Accept'),'application/octet-stream')
                self.assertEqual((first,last),(0,0))
            else:self.assertEqual(request.full_url,resolved)
            response=io.BytesIO(body[first:last+1]);response.status=206
            response.headers={'Content-Range':f'bytes {first}-{last}/{len(body)}'}
            response.geturl=lambda:resolved
            return response
        target=self.root/'api.exe'
        with patch.object(installer_download,'CHUNK_BYTES',128),patch.object(installer_download.urllib.request,'urlopen',side_effect=fetch):
            with contextlib.redirect_stdout(io.StringIO()):installer_download.download(profile,target)
        self.assertEqual(target.read_bytes(),body)
        self.assertEqual(calls.count(api),1)
        self.assertEqual(calls.count(resolved),(len(body)+127)//128)

    def test_asset_api_rejects_unexpected_endpoint_host_or_range(self):
        api='https://api.github.com/repos/Huoxixi/climbing-assistant-local/releases/assets/667783015'
        profile={'url':'https://github.com/fixed.exe','asset_api_url':api,'bytes':42}
        for kind in ['endpoint','host','range','body']:
            candidate={**profile,'asset_api_url':'https://example.test/asset'} if kind=='endpoint' else profile
            response=io.BytesIO(b'xx' if kind=='body' else b'M');response.status=206
            response.headers={'Content-Range':'bytes 0-0/43' if kind=='range' else 'bytes 0-0/42'}
            response.geturl=lambda:'https://example.test/asset' if kind=='host' else 'https://release-assets.githubusercontent.com/fixed'
            with self.subTest(kind=kind),patch.object(installer_download.urllib.request,'urlopen',return_value=response),self.assertRaises(RuntimeError):
                installer_download.asset_source(candidate)

    def test_asset_api_network_failure_falls_back_to_pinned_public_url(self):
        profile={'url':'https://github.com/fixed.exe','asset_api_url':
                 'https://api.github.com/repos/Huoxixi/climbing-assistant-local/releases/assets/667783015','bytes':42}
        with patch.object(installer_download.urllib.request,'urlopen',side_effect=OSError('network unavailable')) as fetch,patch.object(installer_download.time,'sleep'):
            self.assertEqual(installer_download.asset_source(profile),profile['url'])
            self.assertEqual(fetch.call_count,3)

    def test_installer_rejects_ignored_ranges_truncation_and_wrong_digest(self):
        body=b'expected installer'
        profile={'url':'https://example.test/fixed.exe','bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}
        for kind in ['ignored','offset','truncated','digest']:
            target=self.root/(kind+'.exe')
            def fetch(request,timeout):
                data=body[:-1] if kind=='truncated' else (b'x'*len(body) if kind=='digest' else body)
                response=io.BytesIO(data);response.status=200 if kind=='ignored' else 206
                response.headers={'Content-Range':f'bytes {1 if kind=="offset" else 0}-{len(body)-1}/{len(body)}'}
                return response
            with self.subTest(kind=kind),patch.object(installer_download.urllib.request,'urlopen',side_effect=fetch),patch.object(installer_download.time,'sleep'):
                with contextlib.redirect_stdout(io.StringIO()),self.assertRaises(RuntimeError):installer_download.download(profile,target)
                self.assertFalse(target.exists());self.assertFalse(target.with_suffix('.partial').exists())

    def test_installer_existing_valid_cache_is_reused_and_invalid_cache_is_preserved(self):
        body=b'expected installer';target=self.file(self.root/'installer.exe',body)
        profile={'url':'https://example.test/fixed.exe','bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}
        with patch.object(installer_download.urllib.request,'urlopen') as fetch:
            installer_download.download(profile,target);fetch.assert_not_called()
            target.write_bytes(b'keep this failed cache for diagnosis')
            with self.assertRaises(RuntimeError):installer_download.download(profile,target)
            self.assertEqual(target.read_bytes(),b'keep this failed cache for diagnosis');fetch.assert_not_called()

    def test_active_public_installer_is_copied_without_network_and_source_is_preserved(self):
        body=b'fixed public installer';cached=self.file(self.root/'active/public.exe',body)
        target=self.root/'new/installer.exe'
        profile={'url':'https://example.test/fixed.exe','bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}
        with patch.object(installer_download,'CURRENT_PUBLIC_INSTALLER',cached),patch.object(installer_download.urllib.request,'urlopen') as fetch:
            with contextlib.redirect_stdout(io.StringIO()):installer_download.download(profile,target)
        self.assertEqual(cached.read_bytes(),body);self.assertEqual(target.read_bytes(),body)
        self.assertFalse(target.with_suffix('.partial').exists());fetch.assert_not_called()

    def test_mismatched_active_installer_is_preserved_and_pinned_download_is_used(self):
        body=b'fixed public installer'
        profile={'url':'https://example.test/fixed.exe','bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}
        for old in [b'older version',b'x'*len(body)]:
            cached=self.file(self.root/'active/public.exe',old);target=self.root/('new-'+str(len(old))+'.exe')
            def fetch(request,timeout):
                self.assertEqual(request.full_url,profile['url'])
                response=io.BytesIO(body);response.status=206
                response.headers={'Content-Range':f'bytes 0-{len(body)-1}/{len(body)}'}
                return response
            with patch.object(installer_download,'CURRENT_PUBLIC_INSTALLER',cached),patch.object(installer_download.urllib.request,'urlopen',side_effect=fetch) as network:
                with contextlib.redirect_stdout(io.StringIO()):installer_download.download(profile,target)
            self.assertEqual(cached.read_bytes(),old);self.assertEqual(target.read_bytes(),body);network.assert_called_once()

    def test_active_installer_copy_is_verified_again_before_publishing(self):
        body=b'fixed public installer';cached=self.file(self.root/'active/public.exe',body);target=self.root/'new/installer.exe'
        profile={'url':'https://example.test/fixed.exe','bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}
        def corrupt(source,destination):Path(destination).write_bytes(b'x'*len(body))
        with patch.object(installer_download,'CURRENT_PUBLIC_INSTALLER',cached),patch.object(installer_download.shutil,'copyfile',side_effect=corrupt),patch.object(installer_download.urllib.request,'urlopen') as network:
            with self.assertRaises(RuntimeError):installer_download.download(profile,target)
        self.assertEqual(cached.read_bytes(),body);self.assertFalse(target.exists())
        self.assertFalse(target.with_suffix('.partial').exists());network.assert_not_called()

    def test_fresh_model_install_accepts_verified_root_and_nested_archives(self):
        import hashlib
        models=self.root/'backend/model_assets/rtmw-l-384x288'
        models.mkdir(parents=True)
        cache=self.root/'downloads';cache.mkdir()
        entries=[];assets=[]
        for name,member in [('rtmw.onnx','end2end.onnx'),('detector.onnx','sdk/model/end2end.onnx')]:
            content=('fixed public model '+name).encode()
            entries.append({'file':name,'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()})
            archive=cache/(name+'.zip')
            with zipfile.ZipFile(archive,'w') as bundle:bundle.writestr(member,content)
            assets.append((name,archive.name,'unused-cached-public-url',model_installer.sha(archive)))
        (models/'manifest.json').write_text(json.dumps({'files':entries}),encoding='utf-8')
        with patch.object(model_installer,'ROOT',self.root),patch.object(model_installer,'ASSETS',assets),contextlib.redirect_stdout(io.StringIO()):
            model_installer.install(cache)
            for item in entries:self.assertEqual(model_installer.sha(models/item['file']),item['sha256'])
            (models/'rtmw.onnx').write_bytes(b'damaged-existing-model')
            with self.assertRaises(RuntimeError):model_installer.install(cache)
            self.assertEqual((models/'rtmw.onnx').read_bytes(),b'damaged-existing-model')

    def retirement_fixture(self):
        releases=self.root/'releases';current=releases/retire.OLD_TAGS[-1];old=releases/retire.OLD_TAGS[0]
        self.file(current/'RELEASE_SHA',retire.OLD_SHA.encode());self.file(old/'RELEASE_SHA',b'b'*40)
        source=self.root/'source'
        (source/'.git').mkdir(parents=True)
        self.file(source/'app.py');self.file(source/'.env',b'private-config')
        self.file(source/'backend/data/record.json',b'private-history')
        self.file(source/'frontend/node_modules/generated.js')
        ops=self.root/'ops';self.file(ops/'last-backup.env',b'RESULT=success\nREMOTE_VERIFIED=true\n')
        patches=contextlib.ExitStack()
        patches.enter_context(patch.object(retire,'RELEASES',releases))
        patches.enter_context(patch.object(retire,'CURRENT'))
        retire.CURRENT.resolve.return_value=current
        patches.enter_context(patch.object(retire,'SOURCE',source))
        patches.enter_context(patch.object(retire,'RECEIPTS',self.root/'receipts'))
        patches.enter_context(patch.object(retire,'OPS',ops))
        patches.enter_context(patch.object(retire,'LOCK',self.root/'deployment.lock'))
        patches.enter_context(patch.object(retire.os,'geteuid',return_value=0,create=True))
        response=patches.enter_context(patch.object(retire.urllib.request,'urlopen'))
        response.return_value.__enter__.return_value=io.BytesIO(b'{"status":"success"}')
        patches.enter_context(patch.object(retire.shutil,'disk_usage',return_value=type('Space',(),{'free':10*1024**3})()))
        patches.enter_context(patch.object(retire,'run',side_effect=lambda *args:retire.OLD_SHA if 'rev-parse' in args else '' if 'status' in args else 'app.py\0.env\0backend/data/record.json\0'))
        commands=patches.enter_context(patch.object(retire.subprocess,'run'))
        commands.return_value.returncode=1
        return patches,current,old,source,commands

    def test_retirement_does_not_delete_any_code_when_verified_backup_fails(self):
        patches,current,old,source,commands=self.retirement_fixture()
        with patches,contextlib.redirect_stdout(io.StringIO()):
            def failed_backup(args,**kwargs):
                if args[0].endswith('backup_data.sh'):raise RuntimeError('backup failed')
                return type('Result',(),{'returncode':1})()
            commands.side_effect=failed_backup
            with self.assertRaises(RuntimeError):retire.main('prepare')
        self.assertTrue(current.is_dir());self.assertTrue(old.is_dir());self.assertTrue((source/'.git').is_dir())

    def test_prepare_removes_only_inactive_program_and_keeps_data_config_and_current(self):
        patches,current,old,source,commands=self.retirement_fixture()
        with patches,contextlib.redirect_stdout(io.StringIO()):retire.main('prepare')
        self.assertTrue(current.is_dir());self.assertFalse(old.exists())
        self.assertTrue((source/'.env').is_file());self.assertTrue((source/'backend/data/record.json').is_file())
        self.assertTrue((source/'app.py').is_file());self.assertFalse((source/'frontend/node_modules').exists())
        self.assertTrue(list((self.root/'receipts').glob('*/old-build-source.tar.gz')))

    def test_finish_requires_browser_activation(self):
        patches,current,old,source,commands=self.retirement_fixture()
        with patches,contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):retire.main('finish')
        self.assertTrue(current.is_dir());self.assertTrue(old.is_dir())

if __name__=='__main__':unittest.main()
