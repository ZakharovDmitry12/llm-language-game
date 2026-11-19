"""Safe, restartable sequential experiment runner."""
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import time
from contextlib import contextmanager
from pathlib import Path
from . import api, parsing, prompts, storage


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def reserve(config, prompt):
    # Conservative local accounting only; providers may change rates/charge differently.
    in_bound = len(prompt.encode('utf-8')) + 2048
    return (in_bound * config['input_per_million'] + config['max_tokens'] * config['output_per_million']) / 1_000_000

def spent(con):
    return con.execute('SELECT COALESCE(SUM(COALESCE(accounted_cost,reserved_cost)),0) FROM attempts').fetchone()[0]

@contextmanager
def db_lock(db_path):
    # Prevent two runners from dispatching the same assignment concurrently.
    path = str(Path(db_path).resolve())+'.lock'
    with open(path, 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another runner holds the database lock') from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)

def reconcile_interrupted(con):
    rows = list(con.execute("SELECT id,task_id,role FROM attempts WHERE outcome='in_flight'"))
    for row in rows:
        field = 'status_'+row['role']
        con.execute(f"UPDATE tasks SET {field}='technical_error' WHERE task_id=?", (row['task_id'],))
        con.execute("UPDATE attempts SET outcome='technical_error', finished_at=?, error='Interrupted; outcome and cost unknown. Not retried.', accounted_cost=reserved_cost WHERE id=?", (now(),row['id']))
    con.commit()
    return len(rows)

def next_role(task):
    stage, p, a = task['stage'], task['status_proposer'], task['status_responder']
    if stage == 'I':
        return 'responder' if a == 'not_run' else None
    if stage == 'III':
        return 'proposer' if p == 'not_run' else None
    if p == 'not_run': return 'proposer'
    if p == 'valid' and a == 'not_run': return 'responder'
    return None

def prompt_for(task, role):
    if role == 'proposer':
        return prompts.proposer(task['stage'], task['language'], task['reveal'], task['charged_language'], task['cost'])
    language = task['chosen_language'] if task['stage'] == 'IV' else task['language']
    return prompts.responder(task['stage'], language, task['x'])

def mock_response(task, role):
    val = int.from_bytes(hashlib.sha256((task['task_id']+role).encode()).digest()[:4], 'big')
    if role == 'responder': return '1' if task['x'] >= 30 or val % 3 else '0'
    if task['stage'] == 'III': return '[0.15,0.3,0.5,0.7,0.85,0.9,0.95,0.97,0.99]'
    if task['stage'] == 'IV': return f"{(val % 9 + 1)*10}, {'English' if val % 2 else 'Russian'}"
    return str((val % 9 + 1)*10)

def parsed_values(task, role, text):
    if role == 'responder':
        result = parsing.parse_decision(text)
        return None if result is None else {'a':result}
    if task['stage'] == 'III':
        result = parsing.parse_forecast(text)
        return None if result is None else {'predictions':json.dumps(result)}
    if task['stage'] == 'IV':
        result = parsing.parse_offer_language(text)
        return None if result is None else {'x':result[0], 'chosen_language':result[1]}
    result = parsing.parse_offer(text)
    return None if result is None else {'x':result}

def save_outcome(con, task, role, attempt_id, result=None, error=None, mock=False):
    field = 'status_'+role
    if error is not None:
        con.execute(f"UPDATE tasks SET {field}='technical_error' WHERE task_id=?", (task['task_id'],))
        con.execute("UPDATE attempts SET outcome='technical_error',finished_at=?,error=?,accounted_cost=reserved_cost WHERE id=?", (now(), error[:500], attempt_id))
        con.commit()
        return 'technical_error', None
    text = result.get('text','')
    values = None if result.get('finish_reason') == 'length' else parsed_values(task,role,text)
    outcome = 'valid' if values is not None else 'invalid'
    values = values or {}
    values[field] = outcome
    # Stage I is an independent decision, not a played match.
    if role == 'responder' and values.get('a') is not None and task['stage'] in ('II','IV'):
        a, x = values['a'], task['x']
        values['payoff_p'] = (100-x)*a - (task['cost'] if task['stage']=='IV' and task['chosen_language']==task['charged_language'] else 0)
        values['payoff_a'] = x*a
    assignments = ','.join(f'{column}=?' for column in values)
    con.execute(f'UPDATE tasks SET {assignments} WHERE task_id=?', (*values.values(),task['task_id']))
    usage = result.get('usage') or {}
    actual = usage.get('cost')
    # Unknown charge remains reserved. Trust only non-negative finite numeric charges.
    if isinstance(actual,bool) or not isinstance(actual,(float,int)) or not 0 <= actual < float('inf'):
        actual = None
    if mock: actual = 0.0
    meta = {k:result.get(k) for k in ('id','model','finish_reason')}
    con.execute('''UPDATE attempts SET outcome=?,finished_at=?,response=?,provider=?,response_metadata=?,
                   accounted_cost=COALESCE(?,reserved_cost),input_tokens=?,output_tokens=? WHERE id=?''',
                (outcome,now(),text,result.get('provider'),json.dumps(meta),actual,usage.get('prompt_tokens'),usage.get('completion_tokens'),attempt_id))
    con.commit()
    return outcome, actual

def run(db_path, budget, mock=False, max_requests=None, model=None, stage=None, progress=None):
    if not math.isfinite(budget) or budget < 0 or (max_requests is not None and max_requests < 0): raise ValueError('budget must be finite and non-negative; max-requests must be non-negative')
    key = os.environ.get('OPENROUTER_API_KEY','').strip()
    if not mock and not key: raise ValueError('Set OPENROUTER_API_KEY in the environment')
    with db_lock(db_path):
        con = storage.connect(db_path)
        try:
            info = storage.metadata(con)
            if model is not None and model not in info['models']:
                raise ValueError(f"Unknown model alias {model!r} for this database. Available: {', '.join(info['models'])}")
            if info['prompt_hash'] != storage.code_hash():
                raise ValueError('Prompts changed since schedule creation; create a new database or restore frozen prompts')
            if info.get('parser_hash') != storage.parser_hash():
                raise ValueError('Parser is missing a recorded hash or has changed since schedule creation; create a new database or restore frozen parser')
            mode = 'mock' if mock else 'live'
            old_mode = info.get('run_mode')
            if old_mode is not None and old_mode != mode:
                raise ValueError('Cannot mix mock and live requests in one database')
            if old_mode is None:
                con.execute('INSERT INTO metadata(key,value) VALUES (?,?)', ('run_mode', json.dumps(mode)))
                con.commit()
            interrupted = reconcile_interrupted(con)
            clauses, args = [], []
            if model: clauses.append('model=?'); args.append(model)
            if stage: clauses.append('stage=?'); args.append(stage)
            where = ' WHERE '+' AND '.join(clauses) if clauses else ''
            ids = [r['task_id'] for r in con.execute('SELECT task_id FROM tasks'+where+' ORDER BY seq',args)]
            count = 0
            valid = invalid = 0
            reason = 'completed'
            last_error = None
            total_cost = spent(con)
            last_progress = time.monotonic()
            if progress is not None:
                progress(f'Started: {len(ids)} assignments in selection, ${total_cost:.5f} / ${budget:.2f} accounted')
            for task_id in ids:
                while True:
                    task = con.execute('SELECT * FROM tasks WHERE task_id=?',(task_id,)).fetchone()
                    role = next_role(task)
                    if role is None: break
                    if max_requests is not None and count >= max_requests:
                        reason = 'max_requests'; break
                    config = info['models'][task['model']]
                    text_prompt = prompt_for(task,role)
                    expected = 0.0 if mock else reserve(config,text_prompt)
                    if total_cost + expected > budget + 1e-12:
                        reason = 'budget'; break
                    params = {k:v for k,v in config.items() if k != 'api_key'}
                    cur = con.execute('''INSERT INTO attempts(task_id,role,started_at,model_id,prompt,outcome,request_params,reserved_cost)
                                         VALUES (?,?,?,?,?,'in_flight',?,?)''',
                                      (task_id,role,now(),config['id'],text_prompt,json.dumps(params),expected))
                    con.execute(f"UPDATE tasks SET status_{role}='in_flight' WHERE task_id=?",(task_id,))
                    con.commit()  # Durable marker BEFORE the paid call.
                    count += 1
                    try:
                        response = {'text':mock_response(task,role),'usage':{}} if mock else api.request_openrouter(key,config,text_prompt)
                    except Exception as exc:
                        last_error = f'{type(exc).__name__}: {exc}'
                        if key:
                            last_error = last_error.replace(key, '[REDACTED]')
                        last_error = last_error[:500]
                        save_outcome(con,task,role,cur.lastrowid,error=last_error,mock=mock)
                        total_cost += expected
                        reason = 'technical_error'
                        break
                    else:
                        outcome, actual = save_outcome(con,task,role,cur.lastrowid,result=response,mock=mock)
                        total_cost += expected if actual is None else actual
                        valid += outcome == 'valid'
                        invalid += outcome == 'invalid'
                    if progress is not None and time.monotonic() - last_progress >= 30:
                        progress(f'{count} requests this run ({valid} valid, {invalid} invalid), '
                                 f'${total_cost:.5f} / ${budget:.2f} accounted')
                        last_progress = time.monotonic()
                if reason != 'completed': break
            summary = {'requests_this_run':count,'valid_this_run':valid,'invalid_this_run':invalid,
                       'accounted_cost':round(spent(con),8),'stopped':reason,'interrupted_reconciled':interrupted}
            if last_error is not None:
                summary['last_error'] = last_error
            return summary
        finally:
            con.close()
