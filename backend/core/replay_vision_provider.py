"""Minimal OpenAI-compatible image API transport with no implicit retries."""
import httpx
import re
import time
from copy import deepcopy
from urllib.parse import urlsplit


def supports_video(settings):
    host = urlsplit(settings.get('base_url','')).hostname or ''
    official = (host in {'dashscope.aliyuncs.com','dashscope-intl.aliyuncs.com'}
                or host.endswith('.maas.aliyuncs.com'))
    model = settings.get('model','').lower()
    return official and api_mode(settings) == 'chat_completions' and model.startswith(
        ('qwen3.8-', 'qwen3.7-', 'qwen3.6-', 'qwen3.5-', 'qwen3-vl-', 'qwen-vl-max', 'qwen-vl-plus'))


class VisionAPIError(RuntimeError):
    def __init__(self, message, *, uncertain=False, diagnostic=None):
        self.uncertain = uncertain
        self.diagnostic = diagnostic or {}
        super().__init__(message)


def rejection_detail(response):
    """Classify upstream errors without persisting echoed input or credentials."""
    try:
        body = response.json()
        error = body.get('error', body) if isinstance(body, dict) else {}
        if not isinstance(error, dict):
            error = {'message': error}
    except (ValueError, TypeError):
        error = {}
    message = str(error.get('message', '')).lower()
    categories = (
        ('image_limit', ('too many images', 'number of images', 'maximum number of image', 'image count'), '分析画面数量超过服务限制'),
        ('context_limit', ('context length', 'context_length', 'too many tokens', 'token limit', 'input tokens'), '分析资料超过模型可接收的长度'),
        ('payload_limit', ('request too large', 'payload', 'body size', 'content length'), '分析资料超过服务接收大小'),
        ('image_format', ('invalid image', 'image format', 'image_url', 'decode image', 'base64'), '服务无法读取分析画面'),
        ('output_limit', ('max_tokens', 'max_completion_tokens', 'max_output_tokens'), '服务不接受当前输出长度'),
        ('unsupported_parameter', ('unsupported parameter', 'response_format', 'json_object'), '服务不支持当前分析请求参数'),
    )
    code = {}
    for key in ('code', 'type', 'param'):
        value = error.get(key)
        if isinstance(value, str) and re.fullmatch(r'[a-zA-Z0-9_.-]{1,80}', value):
            code[key] = value
    for category, needles, reason in categories:
        if any(n in message for n in needles):
            return reason, dict(code, category=category)
    return None, dict(code, category='unclassified')


def api_mode(settings):
    mode = settings.get('api_mode', 'auto')
    if mode != 'auto':
        return mode
    address = settings['base_url'].rstrip('/')
    if address.endswith('/responses'):
        return 'responses'
    if address.endswith('/chat/completions'):
        return 'chat_completions'
    return 'responses' if urlsplit(settings['base_url']).hostname == 'api.openai.com' else 'chat_completions'


class CompatibleVisionProvider:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client

    def __call__(self, *, messages, max_tokens, cancelled, video_url=None, video_fps=2):
        if cancelled():
            raise InterruptedError()
        if video_url:
            if not supports_video(self.settings):
                raise VisionAPIError('当前服务不支持此视频输入，请使用全程画面分析。')
            messages = deepcopy(messages)
            messages[-1]['content'].insert(0, {'type':'video_url','video_url':{'url':video_url},'fps':video_fps})
        mode = api_mode(self.settings)
        model = self.settings['model']
        if mode == 'responses':
            inputs = []
            for message in messages:
                content = message['content']
                if isinstance(content, str):
                    content = [{'type': 'text', 'text': content}]
                parts = []
                for part in content:
                    if part['type'] == 'text':
                        parts.append({'type': 'input_text', 'text': part['text']})
                    elif part['type'] == 'image_url':
                        parts.append({'type': 'input_image', 'image_url': part['image_url']['url']})
                    else:
                        raise VisionAPIError('存在当前接口不支持的输入类型。')
                inputs.append({'role': message['role'], 'content': parts})
            payload = {'model': model, 'input': inputs, 'max_output_tokens': max_tokens,
                       'store': False, 'text': {'format': {'type': 'json_object'}}}
            suffix = '/responses'
        else:
            token_field = 'max_completion_tokens' if model.lower().startswith(('gpt-5', 'gpt-6', 'o1', 'o3', 'o4')) else 'max_tokens'
            payload = {'model': model, 'messages': messages, token_field: max_tokens,
                       'response_format': {'type': 'json_object'}}
            suffix = '/chat/completions'
        owned = self.client is None
        client = self.client or httpx.Client(timeout=httpx.Timeout(180, connect=10), follow_redirects=False)
        started = time.perf_counter()
        stages = []
        def trace(event, info):
            # Transport callbacks include headers/body/exception objects. Keep
            # only known stage names and durations, never their private payloads.
            if re.fullmatch(r'(connection|http11|http2)\.(connect_tcp|connect_unix_socket|start_tls|send_request_headers|send_request_body|receive_response_headers|receive_response_body|response_closed)\.(started|complete|failed)', event):
                if len(stages)<40:
                    stages.append({'event':event,'elapsed_seconds':round(time.perf_counter()-started,3)})
        def transport_diagnostic():
            return {'elapsed_seconds':round(time.perf_counter()-started,3),'stages':deepcopy(stages),
                    'client_policy':'environment_proxy_settings' if owned else 'provided_client'}
        try:
            base = self.settings['base_url'].rstrip('/')
            for ending in ('/chat/completions', '/responses'):
                if base.endswith(ending):
                    base = base[:-len(ending)]
                    break
            response = client.post(base + suffix,
                headers={'Authorization': 'Bearer ' + self.settings['api_key']},
                json=payload, extensions={'trace':trace})
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError()
            if mode == 'responses':
                content = '\n'.join(part['text'] for item in body.get('output', [])
                    if item.get('type') == 'message' for part in item.get('content', [])
                    if part.get('type') == 'output_text' and isinstance(part.get('text'), str))
            else:
                choices = body.get('choices') or []
                content = (choices[0].get('message') or {}).get('content') if choices else None
                if isinstance(content, list):
                    content = '\n'.join(p['text'] for p in content if isinstance(p, dict) and isinstance(p.get('text'), str))
            usage = dict(body.get('usage') or {})
            if mode == 'responses':
                usage['prompt_tokens'] = usage.get('input_tokens')
                usage['completion_tokens'] = usage.get('output_tokens')
            # Billing remains observable even if the request was cancelled in flight.
            return {'content': content, 'raw_response':body, 'usage': usage, 'provider_request_id':body.get('id') or response.headers.get('x-request-id'),
                    'model': body.get('model') or model, 'api_mode': mode,
                    '_transport_diagnostic':transport_diagnostic()}
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            reason, diagnostic = rejection_detail(exc.response)
            reasons = {400: '服务暂时无法接收本次分析资料',
                       401: '服务密钥无效', 403: '账号无权使用该模型',
                       404: '服务地址或模型不存在', 413: '证据画面超过服务大小限制',
                       429: '额度不足或请求过于频繁'}
            raise VisionAPIError(f"AI 服务 HTTP {status}：{reason or reasons.get(status, '服务暂不可用')}。未自动重试。",uncertain=status>=500,
                                 diagnostic=dict(transport_diagnostic(), **diagnostic, http_status=status)) from None
        except httpx.TimeoutException as exc:
            raise VisionAPIError('视觉服务等待超时，扣费与返回状态未知；请先核对服务账单，未自动重试。', uncertain=True,
                                 diagnostic=dict(transport_diagnostic(),category='timeout',exception_type=type(exc).__name__)) from None
        except httpx.TransportError as exc:
            raise VisionAPIError('视觉服务连接中断，返回状态未知；请先核对服务请求记录，未自动重试。', uncertain=True,
                                 diagnostic=dict(transport_diagnostic(),category='connection_interrupted',exception_type=type(exc).__name__)) from None
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError):
            raise VisionAPIError('AI 服务返回无法读取，费用与返回状态尚未确认，请先核对服务记录。未自动重试。',uncertain=True,
                                 diagnostic=dict(transport_diagnostic(),category='unreadable_response')) from None
        finally:
            if owned:
                client.close()
