"""Native EdgeChromium probe using only generated pixels and a silent clip."""
import base64
import json
import subprocess
import tempfile
import time
from pathlib import Path


def run(window, report_path):
    report_path.parent.mkdir(parents=True, exist_ok=True)
    import webview
    from imageio_ffmpeg import get_ffmpeg_exe
    report = {'renderer': None, 'page_loaded': False, 'api_authenticated': False,
              'video_decoded': False, 'video_played': False, 'speed': None, 'cloud_requests': 0}
    try:
        report['renderer'] = webview.guilib.renderer
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if window.evaluate_js("document.querySelector('#app').innerText.length > 30"):
                report['page_loaded'] = True
                break
            time.sleep(.2)
        window.evaluate_js("""(() => {
            window.__desktopProbe = {api:false, width:0, time:0, speed:0};
            fetch('/api/health').then(r => {window.__desktopProbe.api=r.ok});
            const v=document.createElement('video'); v.muted=true; v.controls=true;
            v.style='position:fixed;right:20px;bottom:20px;width:320px;z-index:99999';
            v.src='/desktop/probe-video';
            v.playbackRate=.75;
            v.addEventListener('loadeddata',()=>{window.__desktopProbe.width=v.videoWidth; v.play()});
            v.addEventListener('timeupdate',()=>{window.__desktopProbe.time=v.currentTime;window.__desktopProbe.speed=v.playbackRate});
            document.body.appendChild(v);
        })()""")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = window.evaluate_js('window.__desktopProbe')
            if state and state.get('time', 0) > .3:
                report.update(api_authenticated=state['api'], video_decoded=state['width'] == 320,
                              video_played=True, speed=state['speed'])
                break
            time.sleep(.2)
        report['window_title'] = window.title
        report['page_title'] = window.evaluate_js('document.title')
        # Verify download bytes through the real native handler with a constructed
        # save-choice callback. The interactive chooser itself remains manual.
        from System.Windows.Forms import MethodInvoker
        form = webview.guilib.BrowserView.instances[window.uid]
        download_path = report_path.with_suffix('.mp4')
        def choose(sender, args):
            args.ResultFilePath = str(download_path)
            args.Handled = True
        def install_choice():
            form.webview.CoreWebView2.DownloadStarting -= form.browser.on_download_starting
            form.webview.CoreWebView2.DownloadStarting += choose
        form.Invoke(MethodInvoker(install_choice))
        window.evaluate_js("(() => {const a=document.createElement('a');a.href='/desktop/probe-video?download=true';a.download='constructed.mp4';document.body.appendChild(a);a.click()})()")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and (not download_path.is_file() or download_path.stat().st_size == 0):
            time.sleep(.1)
        report['download_with_constructed_save_choice'] = download_path.is_file() and download_path.stat().st_size > 0
        window.evaluate_js("location.hash='#/settings'")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            window.evaluate_js("document.querySelectorAll('.settings-tabs button').forEach(b=>{if(b.textContent.includes('AI 服务'))b.click()})")
            if window.evaluate_js("Boolean(document.querySelector('#replay-vision-title')) && document.querySelector('.replay-vision-settings').offsetHeight > 0"):
                report['desktop_settings_visible'] = window.evaluate_js("Boolean(document.querySelector('#desktop-settings-title'))")
                report['legacy_vision_config_hidden'] = not window.evaluate_js("Boolean(document.querySelector('#api-title'))")
                report['replay_vision_settings_visible'] = window.evaluate_js("Boolean(document.querySelector('#replay-vision-title')) && document.querySelector('.replay-vision-settings').offsetHeight > 0")
                report['protocol_choice_hidden'] = not window.evaluate_js("Boolean(document.querySelector('.replay-vision-settings select'))")
                break
            time.sleep(.2)
        window.evaluate_js("location.hash='#/photo-routes'")
        time.sleep(.5)
        # Capture only this WebView surface, never the user's desktop screen.
        try:
            import clr
            from System.IO import FileStream, FileMode
            from System.Windows.Forms import MethodInvoker
            from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
            form = webview.guilib.BrowserView.instances[window.uid]
            state = {}
            def capture():
                state['stream'] = FileStream(str(report_path.with_suffix('.png')), FileMode.CreateNew)
                state['task'] = form.webview.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, state['stream'])
            form.Invoke(MethodInvoker(capture))
            deadline = time.monotonic() + 10
            while not state['task'].IsCompleted and time.monotonic() < deadline:
                time.sleep(.1)
            if not state['task'].IsCompleted or state['task'].IsFaulted:
                raise RuntimeError('Window capture did not complete')
            state['stream'].Dispose()
            report['screenshot'] = str(report_path.with_suffix('.png'))
        except Exception as exc:
            report['screenshot_error_type'] = type(exc).__name__
    except Exception as exc:
        report['error_type'] = type(exc).__name__
    finally:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        window.destroy()
