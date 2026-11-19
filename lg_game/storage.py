"""SQLite assignment, response, and append-only request journal."""
import csv
import hashlib
import json
import math
import random
import sqlite3
from pathlib import Path
from . import prompts, parsing

LEGACY_MODELS = ("qwen", "gemini", "gpt")
FIELDS = ("task_id", "stage", "model", "language", "reveal", "x", "a", "payoff_p", "payoff_a", "D", "c", "C", "predictions", "status_proposer", "status_responder")
SCHEMA = '''
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE tasks (
 task_id TEXT PRIMARY KEY, seq INTEGER NOT NULL UNIQUE, stage TEXT NOT NULL, model TEXT NOT NULL,
 language TEXT, reveal INTEGER, x INTEGER, a INTEGER, payoff_p REAL, payoff_a REAL,
 charged_language TEXT, cost INTEGER, chosen_language TEXT, predictions TEXT,
 status_proposer TEXT NOT NULL DEFAULT 'not_run', status_responder TEXT NOT NULL DEFAULT 'not_run'
);
CREATE TABLE attempts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES tasks(task_id), role TEXT NOT NULL,
 started_at TEXT NOT NULL, finished_at TEXT, model_id TEXT NOT NULL, provider TEXT,
 prompt TEXT NOT NULL, response TEXT, outcome TEXT NOT NULL, error TEXT,
 request_params TEXT NOT NULL, response_metadata TEXT, reserved_cost REAL NOT NULL, accounted_cost REAL,
 input_tokens INTEGER, output_tokens INTEGER
);
CREATE INDEX idx_attempts_task ON attempts(task_id);
'''

def code_hash():
    return hashlib.sha256(Path(prompts.__file__).read_bytes()).hexdigest()

def parser_hash():
    return hashlib.sha256(Path(parsing.__file__).read_bytes()).hexdigest()

def connect(path):
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    return con

def generate(db_path, seed, preset, models_path):
    path = Path(db_path)
    if path.exists():
        raise ValueError(f"Database already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    models = json.loads(Path(models_path).read_text(encoding='utf-8'))
    if not isinstance(models, dict) or len(models) != 3:
        raise ValueError('config must contain exactly three model aliases')
    legacy = set(models) == set(LEGACY_MODELS) and all(
        isinstance(config, dict) and 'stage_iv' not in config for config in models.values()
    )
    stage_iv_models = set()
    for name, config in models.items():
        if not isinstance(config, dict) or not isinstance(config.get('id'), str) or not config['id'].strip():
            raise ValueError(f'invalid model configuration: {name}')
        tokens = config.get('max_tokens')
        prices = [config.get('input_per_million'), config.get('output_per_million')]
        if type(tokens) is not int or tokens <= 0 or any(
            type(price) not in (int, float) or not math.isfinite(price) or price < 0 for price in prices
        ):
            raise ValueError(f'invalid token limit or price for {name}')
        in_stage_iv = config.get('stage_iv', legacy and name in ('gemini', 'gpt'))
        if type(in_stage_iv) is not bool:
            raise ValueError(f'stage_iv must be true or false for {name}')
        if in_stage_iv:
            stage_iv_models.add(name)
    if len(stage_iv_models) != 2 or len({m['id'] for m in models.values()}) != 3:
        raise ValueError('config must have three distinct models, two marked stage_iv')
    n_i, n_ii, n_iii, n_iv = ((50, 250, 100, 75) if preset == 'full' else (1, 1, 1, 1))
    assignments = []
    def add(stage, model, language=None, reveal=None, x=None, D=None, c=None):
        assignments.append((stage, model, language, reveal, x, D, c))
    for model in LEGACY_MODELS if legacy else models:
        for language in ('English', 'Russian'):
            for x in prompts.OFFERS:
                for _ in range(n_i): add('I', model, language, x=x)
            for reveal in (0, 1):
                for _ in range(n_ii): add('II', model, language, reveal)
            for _ in range(n_iii): add('III', model, language)
        if model in stage_iv_models:
            for D in ('English', 'Russian'):
                for c in (0, 2, 5):
                    for _ in range(n_iv): add('IV', model, D=D, c=c)
    random.Random(seed).shuffle(assignments)
    con = connect(path)
    try:
        con.executescript(SCHEMA)
        info = {'seed': seed, 'preset': preset, 'models': models, 'prompt_hash': code_hash(), 'parser_hash': parser_hash(), 'schema_version': 2}
        con.executemany('INSERT INTO metadata(key,value) VALUES (?,?)', [(k,json.dumps(v,ensure_ascii=False)) for k,v in info.items()])
        con.executemany('INSERT INTO tasks(task_id,seq,stage,model,language,reveal,x,charged_language,cost) VALUES (?,?,?,?,?,?,?,?,?)',
                        [(f'task-{i:06d}', i, *row) for i,row in enumerate(assignments, 1)])
        con.commit()
    finally:
        con.close()
    return len(assignments)

def metadata(con):
    return {row['key']:json.loads(row['value']) for row in con.execute('SELECT key,value FROM metadata')}

def export_csv(con, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for row in con.execute('SELECT task_id,stage,model,language,reveal,x,a,payoff_p,payoff_a,charged_language AS D,cost AS c,chosen_language AS C,predictions,status_proposer,status_responder FROM tasks ORDER BY seq'):
            writer.writerow(dict(zip(FIELDS, tuple(row))))
