import argparse
import json

from .settings import Settings


def main():
    p = argparse.ArgumentParser(description='Portable local RL service')
    p.add_argument('--config', help='Deployment JSON; paths resolve relative to this file')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('serve')
    sub.add_parser('doctor')
    imp = sub.add_parser('import-run')
    imp.add_argument('directory')
    pack = sub.add_parser('bundle')
    pack.add_argument('--output', required=True)
    pack.add_argument('--include-runs', action='store_true')
    args = p.parse_args()
    settings = Settings(args.config)
    if args.command == 'serve':
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(settings), host=settings.host, port=settings.port, workers=1, proxy_headers=False)
    elif args.command == 'bundle':
        from .packaging import bundle
        print(bundle(settings, args.output, args.include_runs))
    else:
        from .core import Service
        service = Service(settings)
        try:
            result = service.health(refresh=True) if args.command == 'doctor' else service.import_run(args.directory)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if args.command == 'doctor' and result['status'] != 'ready':
                p.exit(1)
        finally:
            service.close()


if __name__ == '__main__':
    main()
