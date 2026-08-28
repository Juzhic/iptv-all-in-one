import base64
import importlib.util
import json
import os
import shutil
import sys
import types
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

import generate_env as env_generator
from engine import test_engine


def _load_web_modules_without_startup():
    """Load route modules without executing web/__init__.py or touching PostgreSQL."""
    root = Path(__file__).resolve().parents[1]
    module_names = (
        'web', 'web.state', 'web.scheduler', 'web.routes',
        'web.routes.params', 'web.routes.config', 'web.app',
    )
    previous = {name: sys.modules.get(name) for name in module_names}

    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    try:
        web_package = types.ModuleType('web')
        web_package.__path__ = [str(root / 'web')]
        sys.modules['web'] = web_package

        routes_package = types.ModuleType('web.routes')
        routes_package.__path__ = [str(root / 'web' / 'routes')]
        sys.modules['web.routes'] = routes_package
        web_package.routes = routes_package

        state = load('web.state', root / 'web' / 'state.py')
        web_package.state = state
        scheduler = load('web.scheduler', root / 'web' / 'scheduler.py')
        web_package.scheduler = scheduler
        params = load('web.routes.params', root / 'web' / 'routes' / 'params.py')
        routes_package.params = params
        config_module = load(
            'web.routes.config', root / 'web' / 'routes' / 'config.py'
        )
        app_module = load('web.app', root / 'web' / 'app.py')
        return app_module, config_module
    finally:
        for name in reversed(module_names):
            sys.modules.pop(name, None)
            if previous[name] is not None:
                sys.modules[name] = previous[name]


web_app_module, config_routes = _load_web_modules_without_startup()


@pytest.fixture
def local_tmp_path():
    """Windows-safe temp directory that avoids pytest's restrictive chmod."""
    path = Path(__file__).resolve().parents[1] / 'output' / f'.security-v2-{uuid.uuid4().hex}'
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _auth_headers(**extra):
    credentials = (
        f'{web_app_module.BASIC_AUTH_USER}:'
        f'{web_app_module.BASIC_AUTH_PASSWORD}'
    ).encode('utf-8')
    headers = {
        'Authorization': 'Basic ' + base64.b64encode(credentials).decode('ascii'),
    }
    headers.update(extra)
    return headers


def _mutation_headers(**extra):
    headers = {
        'Origin': 'http://localhost',
        'X-IPTV-Request': '1',
    }
    headers.update(extra)
    return _auth_headers(**headers)


def _make_app(monkeypatch):
    monkeypatch.delenv('IPTV_REQUIRE_STRONG_CREDENTIALS', raising=False)
    monkeypatch.delenv('IPTV_TRUSTED_ORIGINS', raising=False)
    app = web_app_module.create_app()
    app.config.update(TESTING=True)
    return app


def test_development_credentials_warn_without_blocking_startup(monkeypatch, caplog):
    monkeypatch.setenv('DB_USER', 'postgres')
    monkeypatch.setenv('DB_PASSWORD', 'weak')
    monkeypatch.setenv('IPTV_SECRET_KEY', '')
    monkeypatch.delenv('IPTV_REQUIRE_STRONG_CREDENTIALS', raising=False)
    monkeypatch.setattr(web_app_module, 'BASIC_AUTH_PASSWORD', 'legacy')
    monkeypatch.setattr(web_app_module, 'BASIC_AUTH_TEMPORARY_PASSWORD', False)

    problems = web_app_module._validate_runtime_credentials()

    assert 'DB_USER 必须是专用的非 PostgreSQL 管理员用户' in problems
    assert 'IPTV_AUTH_PASSWORD 必须是至少 16 位的强密码' in problems
    assert 'IPTV_SECRET_KEY 必须是至少 32 位的强随机值' in problems
    assert '开发模式继续启动' in caplog.text


def test_explicit_strict_credentials_fail_closed(monkeypatch):
    monkeypatch.setenv('DB_USER', 'postgres')
    monkeypatch.setenv('DB_PASSWORD', 'legacy')
    monkeypatch.setenv('IPTV_SECRET_KEY', '')
    monkeypatch.setenv('IPTV_REQUIRE_STRONG_CREDENTIALS', '1')
    monkeypatch.setattr(web_app_module, 'BASIC_AUTH_PASSWORD', 'legacy')
    monkeypatch.setattr(web_app_module, 'BASIC_AUTH_TEMPORARY_PASSWORD', False)

    with pytest.raises(RuntimeError, match='严格凭据校验失败'):
        web_app_module._validate_runtime_credentials()


def test_missing_basic_auth_uses_temporary_password_even_with_stale_strict_flag(
    monkeypatch, local_tmp_path, caplog,
):
    missing_file = local_tmp_path / 'missing-basic-auth.json'
    monkeypatch.setattr(web_app_module, 'BASIC_AUTH_CONFIG_FILE', str(missing_file))
    monkeypatch.setenv('IPTV_REQUIRE_STRONG_CREDENTIALS', '1')
    monkeypatch.delenv('IPTV_AUTH_USERNAME', raising=False)
    monkeypatch.delenv('IPTV_AUTH_PASSWORD', raising=False)

    config = web_app_module._load_basic_auth_config()

    assert config['username'] == 'admin'
    assert len(config['password']) >= 32
    assert config['_temporary_password'] is True
    assert '本次进程使用临时凭据' in caplog.text


def test_temporary_basic_auth_is_reported_as_unconfigured(monkeypatch):
    monkeypatch.setenv('DB_USER', 'iptv_app')
    monkeypatch.setenv('DB_PASSWORD', 'strong-app-password-1234')
    monkeypatch.setenv('IPTV_SECRET_KEY', 'stable-secret-' + 'x' * 40)
    monkeypatch.setattr(web_app_module, 'BASIC_AUTH_PASSWORD', 'random-temporary-password-1234')
    monkeypatch.setattr(web_app_module, 'BASIC_AUTH_TEMPORARY_PASSWORD', True)

    problems = web_app_module._runtime_credential_problems()

    assert problems == ['IPTV_AUTH_PASSWORD 必须是至少 16 位的强密码']


def test_docker_assets_enforce_postgresql_production_contract():
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / 'Dockerfile').read_text(encoding='utf-8')
    compose = (root / 'docker-compose.yml').read_text(encoding='utf-8')
    ci_workflow = (root / '.github' / 'workflows' / 'ci.yml').read_text(
        encoding='utf-8'
    )

    assert 'USER 10001:10001' in dockerfile
    assert 'generate_env.py' not in dockerfile
    assert 'migrate_2_0.py' not in dockerfile
    assert 'mysql' not in dockerfile.casefold()

    assert 'image: postgres:18' in compose
    assert '- postgres_data:/var/lib/postgresql' in compose
    assert '127.0.0.1:5432:5432' in compose
    assert 'APP_DB_USER: iptv_app' in compose
    assert 'CREATE EXTENSION IF NOT EXISTS pgcrypto' in compose
    assert 'image: juzhic/iptv-all-in-one:3.0.0' in compose
    assert 'DB_HOST: postgres' in compose
    assert 'DB_PORT: "5432"' in compose
    assert 'DB_USER: iptv_app' in compose
    assert 'IPTV_REQUIRE_STRONG_CREDENTIALS: "1"' in compose
    assert 'IPTV_REQUIRE_DATABASE: "1"' in compose
    assert 'user: "10001:10001"' in compose
    assert 'read_only: true' in compose
    assert 'cap_drop:\n      - ALL' in compose
    assert 'db_internal:\n    internal: true' in compose
    assert all(token in compose for token in (
        '__POSTGRES_ADMIN_PASSWORD__',
        '__POSTGRES_APP_PASSWORD__',
        '__IPTV_AUTH_PASSWORD__',
        '__IPTV_SECRET_KEY__',
    ))
    assert 'mysql' not in compose.casefold()
    assert 'frpc' not in compose.casefold()
    assert 'iptv_backup.sql' not in compose

    auth_username_line = next(
        line for line in compose.splitlines()
        if line.strip().startswith('IPTV_AUTH_USERNAME:')
    )
    auth_username = auth_username_line.split(':', 1)[1].strip().strip('"\'')
    smoke_credential = (
        f'--user {auth_username}:ci-basic-auth-password-with-32-bytes-3.0'
    )
    assert ci_workflow.count(smoke_credential) == 3


def test_wsgi_startup_fails_closed_when_database_is_required():
    root = Path(__file__).resolve().parents[1]
    startup = (root / 'web' / '__init__.py').read_text(encoding='utf-8')

    assert "os.environ.get('IPTV_REQUIRE_DATABASE'" in startup
    assert 'db.init_db()' in startup
    init_handler = startup.split('db.init_db()', 1)[1].split('else:', 1)[0]
    assert 'if _database_required:' in init_handler
    assert '\n        raise' in init_handler
    assert 'PostgreSQL 初始化失败' in init_handler
    assert '数据库内容迁移或读取失败' in startup


def test_output_paths_are_fixed_and_web_fields_are_removed(monkeypatch, local_tmp_path):
    monkeypatch.setenv('IPTV_OUTPUT_DIR', str(local_tmp_path))
    paths = test_engine.get_output_paths()

    assert 'output_txt' not in test_engine.DEFAULT_CONFIG
    assert 'output_m3u' not in test_engine.DEFAULT_CONFIG
    assert paths == {
        'directory': str(local_tmp_path),
        'txt': str(local_tmp_path / 'result.txt'),
        'm3u': str(local_tmp_path / 'result.m3u'),
        'history': str(local_tmp_path / 'history.json'),
    }

    with pytest.raises(config_routes.ConfigValidationError):
        config_routes._normalize_config_payload({'output_txt': 'elsewhere.pth'})


@pytest.mark.parametrize(
    'key,value',
    [
        ('logo_base_url', 'file:///tmp/logo'),
        ('logo_base_url', 'https://example.com/\nimport os'),
        ('logo_base_url', ' https://example.com'),
        ('epg_url', 'javascript:alert(1)'),
        ('epg_url', 'https://example.com/' + 'a' * 2048),
    ],
)
def test_config_url_validation_rejects_unsafe_values(key, value):
    with pytest.raises(config_routes.ConfigValidationError):
        config_routes._normalize_config_payload({key: value})


def test_config_url_validation_normalizes_logo_and_schema():
    result = config_routes._normalize_config_payload({
        'logo_base_url': 'https://example.com/logos///',
        'epg_url': '',
    })
    assert result['schema_version'] == 2
    assert result['logo_base_url'] == 'https://example.com/logos'


def test_config_route_rejects_entire_invalid_payload_without_write(monkeypatch):
    app = _make_app(monkeypatch)
    app.register_blueprint(config_routes.config_bp)
    saved = []
    monkeypatch.setattr(
        config_routes, 'get_config', lambda defaults: dict(defaults)
    )
    monkeypatch.setattr(config_routes, 'db_save_config', saved.append)

    response = app.test_client().post(
        '/api/config',
        json={'max_workers': 8, 'output_m3u': 'site-packages/boot.pth'},
        headers=_mutation_headers(),
    )

    assert response.status_code == 422
    assert saved == []


def test_import_validation_is_all_or_nothing(monkeypatch):
    app = _make_app(monkeypatch)
    app.register_blueprint(config_routes.config_bp)
    writes = []
    monkeypatch.setattr(
        config_routes, '_write_import_entries_atomically', writes.append
    )

    response = app.test_client().post(
        '/api/config/import',
        json={
            'schema_version': 2,
            'subscribe': 'https://example.com/list.m3u',
            'config': {'output_txt': 'arbitrary.txt'},
        },
        headers=_mutation_headers(),
    )

    assert response.status_code == 422
    assert writes == []


def test_scan_config_import_encrypts_keys_before_transaction(monkeypatch):
    from scanner_integration import config_bridge

    monkeypatch.setenv('IPTV_SECRET_KEY', 's' * 48)
    monkeypatch.setattr(config_bridge, 'get_scan_config', lambda: {})

    entries = config_routes._prepare_import_entries({
        'schema_version': 2,
        'scan_config': {
            'quake_api_keys': ['plain-quake-secret'],
            'hunter_api_key': 'plain-hunter-secret',
        },
    })
    stored = json.loads(dict(entries)['scan_config'])

    serialized = json.dumps(stored)
    assert 'plain-quake-secret' not in serialized
    assert 'plain-hunter-secret' not in serialized
    assert stored['quake_api_keys'][0].startswith('enc:v1:')
    assert stored['hunter_api_keys'][0].startswith('enc:v1:')


def test_scan_config_import_preserves_legacy_keys_without_secret(monkeypatch):
    from scanner_integration import config_bridge

    monkeypatch.setenv('IPTV_SECRET_KEY', '')
    monkeypatch.setattr(config_bridge, 'get_scan_config', lambda: {
        'quake_api_keys': ['legacy-plain-key'],
        'quake_api_key': 'legacy-plain-key',
    })

    entries = config_routes._prepare_import_entries({
        'schema_version': 2,
        'scan_config': {'quake_size': 321},
    })
    stored = json.loads(dict(entries)['scan_config'])

    assert stored['quake_api_keys'] == ['legacy-plain-key']
    assert stored['quake_size'] == 321


def test_scan_config_export_contains_counts_but_no_key_material(monkeypatch):
    from scanner_integration import config_bridge

    monkeypatch.setattr(config_bridge, 'get_scan_config', lambda: {
        'quake_api_keys': ['quake-secret'],
        'quake_api_key': 'quake-secret',
        'quake_key': 'quake-secret',
        'hunter_api_keys': ['one', 'two'],
        'province': '北京',
    })

    exported = config_routes._export_scan_config_without_keys()
    serialized = json.dumps(exported, ensure_ascii=False)

    assert 'quake-secret' not in serialized
    assert 'quake_api_keys' not in exported
    assert exported['province'] == '北京'
    assert exported['api_key_metadata']['counts']['quake'] == 1
    assert exported['api_key_metadata']['counts']['hunter'] == 2


def test_atomic_import_uses_one_transaction(monkeypatch):
    class FakeConnection:
        def __init__(self):
            self.in_transaction = False
            self.executed = []

        @contextmanager
        def transaction(self):
            assert not self.in_transaction
            self.in_transaction = True
            try:
                yield self
            finally:
                self.in_transaction = False

        def execute(self, query, args):
            assert self.in_transaction
            self.executed.append((query, args))

    connection = FakeConnection()
    monkeypatch.setattr(config_routes._database_db, '_get_conn', lambda: connection)
    monkeypatch.setattr(config_routes._database_db, 'now_str', lambda: 'now')

    config_routes._write_import_entries_atomically([
        ('subscribe', 'one'),
        ('demo', 'two'),
    ])

    assert [args[0] for _, args in connection.executed] == ['subscribe', 'demo']
    assert all('ON CONFLICT ("key") DO UPDATE' in query for query, _ in connection.executed)
    assert all('REPLACE INTO' not in query for query, _ in connection.executed)
    assert not connection.in_transaction


def test_mutation_guard_requires_header_origin_and_json(monkeypatch):
    app = _make_app(monkeypatch)

    @app.post('/api/probe')
    def probe():
        return {'ok': True}

    client = app.test_client()
    auth = _auth_headers()
    assert client.post('/api/probe', json={}, headers=auth).status_code == 403
    assert client.post(
        '/api/probe', json={}, headers=_auth_headers(**{'X-IPTV-Request': '1'})
    ).status_code == 403
    assert client.post(
        '/api/probe', json={}, headers=_mutation_headers(Origin='https://evil.test')
    ).status_code == 403
    assert client.post(
        '/api/probe', data='x', headers=_mutation_headers()
    ).status_code == 415
    assert client.post(
        '/api/probe', data='{', content_type='application/json',
        headers=_mutation_headers(),
    ).status_code == 400
    assert client.post(
        '/api/probe', json={}, headers=_mutation_headers()
    ).status_code == 200


def test_request_and_import_body_limits(monkeypatch):
    app = _make_app(monkeypatch)

    @app.post('/api/probe')
    def probe():
        return {'ok': True}

    client = app.test_client()
    oversized = json.dumps('x' * (2 * 1024 * 1024 + 1))
    response = client.post(
        '/api/probe', data=oversized, content_type='application/json',
        headers=_mutation_headers(),
    )
    assert response.status_code == 413

    import_body = json.dumps('x' * (1024 * 1024 + 1))
    response = client.post(
        '/api/config/import', data=import_body, content_type='application/json',
        headers=_mutation_headers(),
    )
    assert response.status_code == 413


def test_anonymous_feed_cache_headers_and_etag_are_preserved(monkeypatch):
    app = _make_app(monkeypatch)

    @app.get('/api/download/txt')
    def public_feed():
        response = web_app_module.Response('feed', content_type='text/plain')
        response.headers['Cache-Control'] = 'public, max-age=30'
        response.set_etag('feed-v1')
        return response

    response = app.test_client().get('/api/download/txt')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'public, max-age=30'
    assert response.headers['ETag'] == '"feed-v1"'


def test_request_teardown_closes_thread_database_connection(monkeypatch):
    import database

    app = _make_app(monkeypatch)
    calls = []
    monkeypatch.setattr(database, 'close_thread_connection', lambda: calls.append(1))

    @app.get('/probe')
    def probe():
        return {'ok': True}

    assert app.test_client().get('/probe', headers=_auth_headers()).status_code == 200
    assert calls == [1]


def test_insecure_tls_status_exposes_only_filtered_hosts(monkeypatch):
    app = _make_app(monkeypatch)
    app.register_blueprint(config_routes.config_bp)
    # The route imports these helpers lazily. Keep this isolated module loader
    # from importing the real web package and triggering WSGI/database startup.
    monkeypatch.setitem(sys.modules, 'web.app', web_app_module)
    monkeypatch.setenv(
        'IPTV_INSECURE_TLS_HOSTS',
        'Example.COM, bad/path, example.com, 10.0.0.8',
    )

    response = app.test_client().get(
        '/api/config/security-status', headers=_auth_headers()
    )
    assert response.status_code == 200
    data = response.get_json()['data']
    assert data['insecure_tls_hosts_enabled'] is True
    assert data['insecure_tls_hosts'] == ['10.0.0.8', 'example.com']


def test_m3u_output_cannot_inject_attributes_or_lines(local_tmp_path):
    channel = 'CCTV"1\n#INJECT'
    output = local_tmp_path / 'result.m3u'
    test_engine.save_result_m3u(
        [('新闻"组', [channel])],
        {channel: ['https://stream.example/live\n#URL-INJECT']},
        output_file=str(output),
        show_update_time=False,
        config={
            'logo_base_url': 'https://logo.example/"\n#LOGO-INJECT',
            'epg_url': 'https://epg.example/"\n#EPG-INJECT',
        },
    )

    content = output.read_text(encoding='utf-8')
    assert '\n#INJECT' not in content
    assert '\n#URL-INJECT' not in content
    assert '\n#LOGO-INJECT' not in content
    assert '\n#EPG-INJECT' not in content
    assert 'tvg-id="CCTV1#INJECT"' in content


def test_subscription_limits_and_channel_name_boundaries(monkeypatch):
    too_many_lines = '\n'.join('x' for _ in range(50_001))
    with pytest.raises(ValueError, match='行数'):
        test_engine.parse_iptv_addresses(too_many_lines)

    long_name = '频' * 257
    valid_name = '道' * 256
    parsed = test_engine.parse_iptv_addresses(
        f'{long_name},https://example.com/too-long\n'
        f'{valid_name},https://example.com/valid'
    )
    assert len(parsed) == 1
    assert parsed[0][0]['name'] == valid_name

    class FakeResponse:
        encoding = 'utf-8'

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            del chunk_size
            yield b'x' * (5 * 1024 * 1024)
            yield b'x'

    monkeypatch.setattr(test_engine, 'http_get', lambda *_a, **_kw: FakeResponse())
    assert test_engine.fetch_m3u_playlist('https://example.com/list') is None


def test_each_cycle_resets_timed_out_regex_rules(monkeypatch):
    import database

    calls = []
    monkeypatch.setattr(test_engine, 'reset_regex_timeout_rules', lambda: calls.append(1))
    monkeypatch.setattr(database, 'clear_run_progress', lambda: None)
    monkeypatch.setattr(database, 'update_run_progress', lambda *_a, **_kw: None)
    monkeypatch.setattr(test_engine, 'load_config', lambda: dict(test_engine.DEFAULT_CONFIG))
    monkeypatch.setattr(test_engine, 'load_aliases', lambda: ({}, {}, []))
    monkeypatch.setattr(test_engine, 'parse_demo_file', lambda: [])

    test_engine.run_test_cycle()
    assert calls == [1]


def test_generate_env_stages_legacy_upgrade_then_finalizes_atomically(
    monkeypatch, local_tmp_path,
):
    env_path = local_tmp_path / '.env'
    example_path = local_tmp_path / '.env.example'
    example_path.write_text(
        'DB_HOST=mysql\nDB_USER=root\nDB_PASSWORD=\n'
        'MYSQL_ROOT_PASSWORD=\nIPTV_AUTH_PASSWORD=\nIPTV_SECRET_KEY=\n',
        encoding='utf-8',
    )
    env_path.write_text(
        'DB_HOST=db.internal\nDB_USER=root\nDB_PASSWORD=existing-db-password-123\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(env_generator, 'ENV_PATH', env_path)
    monkeypatch.setattr(env_generator, 'EXAMPLE_PATH', example_path)

    original = env_path.read_text(encoding='utf-8')
    untouched = env_generator.generate_env_values()
    assert untouched['DB_USER'] == 'root'
    assert untouched['DB_PASSWORD'] == 'existing-db-password-123'
    assert env_path.read_text(encoding='utf-8') == original

    first = env_generator.generate_env_values(upgrade=True)
    second = env_generator.generate_env_values()

    assert first == second
    assert first['MYSQL_ROOT_PASSWORD'] == 'existing-db-password-123'
    assert first['DB_PASSWORD'] == 'existing-db-password-123'
    assert first['DB_USER'] == 'root'
    assert first['IPTV_MIGRATION_DB_USER'] == 'iptv_app'
    assert first['IPTV_MIGRATION_DB_PASSWORD'] != first['DB_PASSWORD']
    assert len(first['IPTV_MIGRATION_DB_PASSWORD']) >= 32
    assert first['MYSQL_INIT_USER'] == 'iptv_app'
    assert first['MYSQL_INIT_PASSWORD'] == first['IPTV_MIGRATION_DB_PASSWORD']
    assert first['IPTV_REQUIRE_STRONG_CREDENTIALS'] == '0'
    assert first['IPTV_CONTAINER_USER'] == 'root'
    assert first['IPTV_HARDENED_CONTAINER'] == 'false'
    assert len(first['IPTV_AUTH_PASSWORD']) >= 32
    assert len(first['IPTV_SECRET_KEY']) >= 48
    assert 'DB_HOST=db.internal' in env_path.read_text(encoding='utf-8')
    assert not list(local_tmp_path.glob('..env.*'))

    finalized = env_generator.finalize_upgrade()
    assert finalized['DB_USER'] == first['IPTV_MIGRATION_DB_USER']
    assert finalized['DB_PASSWORD'] == first['IPTV_MIGRATION_DB_PASSWORD']
    assert finalized['MYSQL_ROOT_PASSWORD'] == 'existing-db-password-123'
    assert finalized['IPTV_MIGRATION_DB_USER'] == ''
    assert finalized['IPTV_MIGRATION_DB_PASSWORD'] == ''
    assert finalized['IPTV_REQUIRE_STRONG_CREDENTIALS'] == '1'
    assert finalized['IPTV_CONTAINER_USER'] == 'root'
    assert finalized['IPTV_HARDENED_CONTAINER'] == 'false'
    assert finalized['IPTV_SECRET_KEY'] == first['IPTV_SECRET_KEY']

    stable = env_generator.generate_env_values()
    assert stable == finalized

    forced = env_generator.generate_env_values(force=True)
    assert forced['IPTV_SECRET_KEY'] == first['IPTV_SECRET_KEY']
    assert forced['DB_PASSWORD'] != finalized['DB_PASSWORD']
    assert forced['MYSQL_ROOT_PASSWORD'] != forced['DB_PASSWORD']

    if os.name != 'nt':
        assert env_path.stat().st_mode & 0o777 == 0o600


def test_finalize_upgrade_rejects_missing_staged_credentials_without_writing(
    monkeypatch, local_tmp_path,
):
    env_path = local_tmp_path / '.env'
    env_path.write_text(
        'DB_USER=root\nDB_PASSWORD=legacy-root-password\n'
        'IPTV_REQUIRE_STRONG_CREDENTIALS=0\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(env_generator, 'ENV_PATH', env_path)
    original = env_path.read_text(encoding='utf-8')

    with pytest.raises(RuntimeError, match='No staged application account'):
        env_generator.finalize_upgrade()

    assert env_path.read_text(encoding='utf-8') == original


def test_finalize_upgrade_refuses_to_enable_strict_mode_with_weak_secrets(
    monkeypatch, local_tmp_path,
):
    env_path = local_tmp_path / '.env'
    env_path.write_text(
        'MYSQL_ROOT_PASSWORD=legacy-root-password\n'
        'DB_USER=root\nDB_PASSWORD=legacy-root-password\n'
        'IPTV_MIGRATION_DB_USER=iptv_app\n'
        'IPTV_MIGRATION_DB_PASSWORD=staged-app-password-1234\n'
        'IPTV_AUTH_PASSWORD=short\nIPTV_SECRET_KEY=short\n'
        'IPTV_REQUIRE_STRONG_CREDENTIALS=0\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(env_generator, 'ENV_PATH', env_path)
    original = env_path.read_text(encoding='utf-8')

    with pytest.raises(RuntimeError, match='Cannot enable strict mode'):
        env_generator.finalize_upgrade()

    assert env_path.read_text(encoding='utf-8') == original


def test_recover_interrupted_early_upgrade_restages_without_rotating_secrets(
    monkeypatch, local_tmp_path,
):
    env_path = local_tmp_path / '.env'
    env_path.write_text(
        'MYSQL_ROOT_PASSWORD=legacy-root-password\n'
        'DB_USER=iptv_app\nDB_PASSWORD=premature-app-password-1234\n'
        'IPTV_AUTH_PASSWORD=stable-auth-password-1234\n'
        'IPTV_SECRET_KEY=stable-secret-' + 'x' * 40 + '\n'
        'IPTV_REQUIRE_STRONG_CREDENTIALS=1\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(env_generator, 'ENV_PATH', env_path)

    recovered = env_generator.recover_interrupted_early_upgrade()

    assert recovered['DB_USER'] == 'root'
    assert recovered['DB_PASSWORD'] == 'legacy-root-password'
    assert recovered['IPTV_MIGRATION_DB_USER'] == 'iptv_app'
    assert recovered['IPTV_MIGRATION_DB_PASSWORD'] == 'premature-app-password-1234'
    assert recovered['MYSQL_INIT_PASSWORD'] == 'premature-app-password-1234'
    assert recovered['IPTV_REQUIRE_STRONG_CREDENTIALS'] == '0'
    assert recovered['IPTV_CONTAINER_USER'] == 'root'
    assert recovered['IPTV_HARDENED_CONTAINER'] == 'false'
    assert recovered['IPTV_SECRET_KEY'] == 'stable-secret-' + 'x' * 40


def test_recover_interrupted_upgrade_rejects_unrecognized_state_without_write(
    monkeypatch, local_tmp_path,
):
    env_path = local_tmp_path / '.env'
    env_path.write_text(
        'DB_USER=root\nDB_PASSWORD=legacy-root-password\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(env_generator, 'ENV_PATH', env_path)
    original = env_path.read_text(encoding='utf-8')

    with pytest.raises(RuntimeError, match='Cannot recognize'):
        env_generator.recover_interrupted_early_upgrade()

    assert env_path.read_text(encoding='utf-8') == original


def test_enable_container_hardening_requires_migrated_credentials(
    monkeypatch, local_tmp_path,
):
    env_path = local_tmp_path / '.env'
    env_path.write_text(
        'DB_USER=iptv_app\nDB_PASSWORD=strong-app-password-1234\n'
        'IPTV_AUTH_PASSWORD=strong-auth-password-1234\n'
        'IPTV_SECRET_KEY=stable-secret-' + 'x' * 40 + '\n'
        'IPTV_CONTAINER_USER=root\nIPTV_HARDENED_CONTAINER=false\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(env_generator, 'ENV_PATH', env_path)

    hardened = env_generator.enable_container_hardening()

    assert hardened['IPTV_CONTAINER_USER'] == '10001:10001'
    assert hardened['IPTV_HARDENED_CONTAINER'] == 'true'
    assert hardened['IPTV_REQUIRE_STRONG_CREDENTIALS'] == '1'
