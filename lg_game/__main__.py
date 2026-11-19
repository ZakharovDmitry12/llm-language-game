"""Command line interface for assignment, execution and export."""
import argparse
import json
import sys
from pathlib import Path
from . import runner, storage

def parser():
    p = argparse.ArgumentParser(description='Ultimatum game experiment')
    sub = p.add_subparsers(dest='command',required=True)
    g = sub.add_parser('generate',help='Create a new randomized assignment database')
    g.add_argument('--db',required=True)
    g.add_argument('--seed',type=int,default=20261119)
    g.add_argument('--preset',choices=('full','pilot'),default='full')
    g.add_argument('--config',default=str(Path(__file__).resolve().parent.parent/'config'/'models.json'))
    r = sub.add_parser('run',help='Run a sequential, restartable series')
    r.add_argument('--db',required=True)
    r.add_argument('--budget',type=float,required=True,help='Total USD accounting limit for this database only; not a guarantee of provider billing')
    r.add_argument('--mock',action='store_true',help='Use synthetic local responses; never combine with real runs')
    r.add_argument('--max-requests',type=int)
    r.add_argument('--model',help='Model alias from the database, e.g. qwen, hy4 or luna')
    r.add_argument('--stage',choices=('I','II','III','IV'))
    e = sub.add_parser('export',help='Export all assigned tasks, including incomplete cases')
    e.add_argument('--db',required=True)
    e.add_argument('--out',required=True)
    s = sub.add_parser('status',help='Show task statuses and conservative accounting for this database only')
    s.add_argument('--db',required=True)
    return p

def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'generate':
            n = storage.generate(args.db,args.seed,args.preset,args.config)
            print(json.dumps({'database':args.db,'assignments':n,'preset':args.preset},ensure_ascii=False))
        elif args.command == 'run':
            if not Path(args.db).is_file(): raise ValueError('Database does not exist')
            result = runner.run(args.db,args.budget,args.mock,args.max_requests,args.model,args.stage,
                                progress=lambda line: print(line, file=sys.stderr, flush=True))
            print(json.dumps(result,ensure_ascii=False))
            if result['stopped'] == 'technical_error': return 2
            if result['stopped'] == 'budget': return 3
        elif args.command == 'export':
            if not Path(args.db).is_file(): raise ValueError('Database does not exist')
            con = storage.connect(args.db)
            try: storage.export_csv(con,args.out)
            finally: con.close()
            print(json.dumps({'export':args.out},ensure_ascii=False))
        else:
            if not Path(args.db).is_file(): raise ValueError('Database does not exist')
            con = storage.connect(args.db)
            try:
                groups = [dict(r) for r in con.execute('SELECT stage,model,status_proposer,status_responder,COUNT(*) AS n FROM tasks GROUP BY stage,model,status_proposer,status_responder ORDER BY stage,model')]
                attempts = [dict(r) for r in con.execute('SELECT outcome,COUNT(*) AS n FROM attempts GROUP BY outcome')]
                print(json.dumps({'groups':groups,'attempts':attempts,'accounted_cost_this_database_only':runner.spent(con),'metadata':storage.metadata(con)},ensure_ascii=False,indent=2))
            finally: con.close()
    except (ValueError,RuntimeError,OSError,KeyError) as exc:
        print(f'Error: {exc}',file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Interrupted. Rerun with the same database to continue.', file=sys.stderr)
        return 130
    return 0

if __name__ == '__main__':
    sys.exit(main())
