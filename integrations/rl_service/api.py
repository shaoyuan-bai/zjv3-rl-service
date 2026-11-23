"""FastAPI adapter; use a single worker and the Settings deployment file."""
from contextlib import asynccontextmanager
import logging
import hmac
import os
from pathlib import Path
import uuid

from fastapi import Body, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.openapi.utils import get_openapi
from fastapi.openapi.docs import get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from .core import ApiError, Service, keys
from .settings import Settings


def create_app(settings=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.service = Service(settings)
        try:
            yield
        finally:
            app.state.service.close()

    app = FastAPI(title='ZJ V3 RL Service', version='1.0.0', lifespan=lifespan, docs_url=None, redoc_url=None,
                  description='Local standing training/configuration API. See STANDING_API.md for field definitions.')
    app.mount('/docs-assets', StaticFiles(directory=Path(__file__).with_name('static') / 'swagger'), name='docs-assets')

    @app.get('/docs', include_in_schema=False)
    def swagger_docs():
        return get_swagger_ui_html(
            openapi_url='/openapi.json', title=app.title + ' - Swagger UI',
            swagger_js_url='/docs-assets/swagger-ui-bundle.js',
            swagger_css_url='/docs-assets/swagger-ui.css',
            swagger_favicon_url='/docs-assets/favicon.svg',
            oauth2_redirect_url='/docs/oauth2-redirect',
        )

    @app.get('/docs/oauth2-redirect', include_in_schema=False)
    def swagger_redirect():
        return get_swagger_ui_oauth2_redirect_html()
    app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_methods=['GET', 'POST', 'PUT', 'DELETE'], allow_headers=['Content-Type', 'Authorization', 'X-API-Key', 'Idempotency-Key'], allow_credentials=False)

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
        schema.setdefault('components', {}).setdefault('securitySchemes', {})['ApiToken'] = {
            'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'opaque API token',
            'description': '也可使用 X-API-Key；服务同时检查客户端IP白名单。'
        }
        for path in schema.get('paths', {}).values():
            for operation in path.values():
                if isinstance(operation, dict) and 'responses' in operation:
                    operation['security'] = [{'ApiToken': []}]
        app.openapi_schema = schema
        return schema
    app.openapi = custom_openapi

    @app.middleware('http')
    async def request_id(request, call_next):
        request.state.request_id = 'req_' + uuid.uuid4().hex
        client_ip = request.client.host if request.client else ''
        configured_token = os.getenv(settings.api_token_env, '')
        supplied = request.headers.get('X-API-Key', '')
        auth = request.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            supplied = auth[7:]
        allowed_ip = settings.allows_client(client_ip)
        if not allowed_ip:
            return error(request, 403, 'CLIENT_IP_FORBIDDEN', '客户端IP不在白名单中', [{'path': '/client_ip', 'message': client_ip}])
        # Swagger must load before its Authorize button can send a bearer token.
        # These routes contain API descriptions only; all data/actions require auth.
        if request.url.path in ('/docs', '/docs/oauth2-redirect', '/openapi.json') or request.url.path.startswith('/docs-assets/') or request.method == 'OPTIONS':
            return await call_next(request)
        if not configured_token or not supplied or not hmac.compare_digest(supplied, configured_token):
            return error(request, 401, 'AUTH_REQUIRED', '缺少或无效的API令牌')
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.request_id
        return response

    def ok(request, data, status=200):
        return JSONResponse({'request_id': request.state.request_id, 'data': data}, status_code=status)

    def error(request, status, code, message, details=None):
        return JSONResponse({'request_id': getattr(request.state, 'request_id', None), 'error': {'code': code, 'message': message, 'details': details or []}}, status_code=status)

    @app.exception_handler(ApiError)
    async def api_error(request, exc):
        return error(request, exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        malformed = any(x['type'] == 'json_invalid' for x in exc.errors())
        return error(request, 400 if malformed else 422, 'BAD_REQUEST' if malformed else 'VALIDATION_ERROR', '请求格式或参数错误', [{'path': '/' + '/'.join(str(y) for y in x['loc']), 'message': x['msg']} for x in exc.errors()])

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error(request, exc.status_code, 'NOT_FOUND' if exc.status_code == 404 else 'BAD_REQUEST', str(exc.detail))

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        logging.exception('Request failed')
        return error(request, 500, 'INTERNAL_ERROR', '服务内部错误，请查看服务日志')

    def svc(request):
        return request.app.state.service

    @app.get('/api/v1/health', tags=['environment'])
    def health(request: Request):
        h = svc(request).health()
        if h['status'] != 'ready':
            raise ApiError(503, 'SIMULATOR_UNAVAILABLE', h['message'] or '运行环境不可用', [{'path': '/' + k, 'message': str(v)} for k, v in h.items()])
        return ok(request, h)

    @app.get('/api/v1/standing/schema', tags=['parameters'])
    def schema(request: Request):
        return ok(request, svc(request).schema())

    @app.get('/api/v1/standing/defaults', tags=['parameters'])
    def defaults(request: Request):
        return ok(request, {'task_id': 'Isaac-ZJV3-Stand-v0', 'parameters': svc(request).defaults()})

    @app.post('/api/v1/standing/validate', tags=['parameters'])
    def validate(request: Request, body: dict = Body(...)):
        keys(body, ['parameters'], ['parameters'])
        svc(request).validate(body['parameters'])
        return ok(request, {'valid': True, 'schema_version': 1})

    @app.post('/api/v1/standing/configs', tags=['parameters'], status_code=201)
    def create_config(request: Request, body: dict = Body(...)):
        return ok(request, svc(request).save_config(body), 201)

    @app.get('/api/v1/standing/configs/{config_id}', tags=['parameters'])
    def get_config(request: Request, config_id: str):
        return ok(request, svc(request).config(config_id))

    @app.put('/api/v1/standing/configs/{config_id}', tags=['parameters'])
    def replace_config(request: Request, config_id: str, body: dict = Body(...)):
        return ok(request, svc(request).save_config(body, config_id))

    @app.post('/api/v1/standing/runs', tags=['runs'], status_code=202)
    def start(request: Request, body: dict = Body(...)):
        return ok(request, svc(request).start(body, request.headers.get('Idempotency-Key')), 202)

    @app.get('/api/v1/standing/runs', tags=['runs'])
    def list_runs(request: Request, limit: int = Query(20, ge=1, le=100), cursor: str | None = None, mode: str | None = None, status: str | None = None):
        return ok(request, svc(request).list_runs(limit, cursor, mode, status))

    @app.get('/api/v1/standing/runs/{run_id}', tags=['runs'])
    def get_run(request: Request, run_id: str):
        return ok(request, svc(request).run(run_id))

    @app.post('/api/v1/standing/runs/{run_id}/play', tags=['local playback'], status_code=202)
    def play(request: Request, run_id: str, body: dict = Body(...)):
        """Open the selected checkpoint in a local simulator window (no video streaming).

        Body: artifact_id (required checkpoint ID), seconds (default 300,
        0.02–3600 in steps of 0.02), pushes (off/mild/full, default full),
        seed (integer, default 42). Returns a new run with mode=play;
        query its status/logs and stop it with the existing cancel endpoint.
        Requires the backend to run in an interactive desktop session.
        """
        keys(body, ['artifact_id', 'seconds', 'pushes', 'seed'], ['artifact_id'])
        options = {k: v for k, v in body.items() if k != 'artifact_id'}
        options.update(mode='play', checkpoint={'source_run_id': run_id, 'artifact_id': body['artifact_id']})
        return ok(request, svc(request).start(options, request.headers.get('Idempotency-Key')), 202)

    @app.post('/api/v1/standing/runs/{run_id}/cancel', tags=['runs'], status_code=202)
    def cancel(request: Request, run_id: str):
        return ok(request, svc(request).cancel(run_id), 202)

    @app.post('/api/v1/standing/runs/{run_id}/restart', tags=['runs'], status_code=202)
    def restart(request: Request, run_id: str):
        return ok(request, svc(request).restart(run_id), 202)

    @app.get('/api/v1/standing/runs/{run_id}/logs', tags=['runs'])
    def logs(request: Request, run_id: str, cursor: str | None = None, limit: int = Query(200, ge=1, le=1000)):
        return ok(request, svc(request).logs(run_id, cursor, limit))

    @app.get('/api/v1/standing/runs/{run_id}/result', tags=['results'])
    def result(request: Request, run_id: str):
        return ok(request, svc(request).result(run_id))

    @app.get('/api/v1/standing/runs/{run_id}/artifacts', tags=['results'])
    def artifacts(request: Request, run_id: str):
        return ok(request, svc(request).artifacts(run_id))

    @app.delete('/api/v1/standing/runs/{run_id}/artifacts', tags=['results'])
    def cleanup(request: Request, run_id: str, body: dict | None = Body(None)):
        return ok(request, svc(request).cleanup(run_id, body or {}))

    @app.get('/api/v1/standing/runs/{run_id}/artifacts/{artifact_id}/download', tags=['results'])
    def download(request: Request, run_id: str, artifact_id: str):
        path, artifact = svc(request).artifact_file(run_id, artifact_id)
        return FileResponse(path, filename=path.name, media_type=artifact['content_type'])

    return app
