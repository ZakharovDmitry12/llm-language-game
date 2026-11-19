"""Minimal OpenRouter client. Secrets never enter stored request parameters."""
import json
import urllib.error
import urllib.request

URL = 'https://openrouter.ai/api/v1/chat/completions'

def request_openrouter(key, model_config, prompt):
    params = {'model': model_config['id'], 'messages': [{'role':'user','content':prompt}],
              'max_tokens': model_config['max_tokens'],
              'usage': {'include': True}}
    if model_config.get('temperature') is not None:
        params['temperature'] = model_config['temperature']
    if model_config.get('reasoning') is not None:
        params['reasoning'] = model_config['reasoning']
    if model_config.get('provider'):
        params['provider'] = {'order': [model_config['provider']], 'allow_fallbacks': False}
    body = json.dumps(params, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(URL, data=body, headers={'Authorization': 'Bearer '+key, 'Content-Type':'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        # Do not persist HTTP bodies: they can include authentication or personal information.
        raise RuntimeError(f'HTTP {exc.code}') from exc
    error = data.get('error')
    if error:
        code = error.get('code') if isinstance(error, dict) else None
        suffix = f' ({code})' if type(code) is int else ''
        raise RuntimeError(f'OpenRouter returned an API error in the response{suffix}')
    choices = data.get('choices') or []
    if not choices:
        raise RuntimeError('OpenRouter returned no completion choices')
    choice = choices[0]
    if choice.get('error') or choice.get('finish_reason') == 'error':
        raise RuntimeError('OpenRouter reported an error for the completion')
    content = (choice.get('message') or {}).get('content')
    if isinstance(content, list):
        content = ''.join(part.get('text','') for part in content if isinstance(part,dict) and part.get('type')=='text')
    usage = data.get('usage') or {}
    return {'text':content if isinstance(content,str) else '', 'usage':usage,
            'provider':data.get('provider'), 'id':data.get('id'), 'model':data.get('model'),
            'finish_reason':choice.get('finish_reason')}
