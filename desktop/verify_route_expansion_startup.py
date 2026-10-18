"""Start the installed backend with an isolated empty data root, check, stop."""
import json,subprocess,sys,time,urllib.request
from pathlib import Path
PROJECT=Path(__file__).resolve().parents[1]
PACKAGE=Path('D:/ai_climbing_code/desktop-deliveries/AiClimbing-0.1.14-replay.20261009')
ROOT=PROJECT/'.tmp/hold-expansion-20261014-02/startup-isolated-complete'
ROOT.mkdir(exist_ok=False)
code="import sys;sys.path.insert(0,sys.argv[1]);from desktop.launcher import main;raise SystemExit(main(['--headless','--data-root',sys.argv[2]]))"
child=subprocess.Popen([str(PACKAGE/'runtime/python.exe'),'-c',code,str(PACKAGE),str(ROOT)],
    creationflags=subprocess.CREATE_NO_WINDOW,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
result={'isolated_user_data':True,'user_app_not_restarted':True,'healthy':False}
try:
    for _ in range(100):
        if child.poll() is not None:raise RuntimeError('Isolated installed startup failed')
        instance=ROOT/'instance.json'
        if instance.is_file():
            data=json.loads(instance.read_text('utf8'))
            assert data['pid']==child.pid
            request=urllib.request.Request(f'http://127.0.0.1:{data["port"]}/api/health',headers={'X-Desktop-Token':data['token']})
            with urllib.request.urlopen(request,timeout=3) as response:
                result.update(healthy=response.status==200,http_status=response.status)
            break
        time.sleep(.4)
    assert result['healthy']
finally:
    child.terminate()
    try:child.wait(timeout=10)
    except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
    result['own_test_process_stopped']=child.poll() is not None
    (ROOT/'health-result.json').write_text(json.dumps(result,indent=2),'utf8')
print(json.dumps(result))
