import shutil
import uuid
from pathlib import Path

import pymysql
import pytest

import migrate_2_0


@pytest.fixture
def local_tmp_path():
    """Windows-safe temp directory under the repository's writable output."""
    path = Path(__file__).resolve().parents[1] / 'output' / f'.migrate-{uuid.uuid4().hex}'
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class _Cursor:
    def __init__(self, connection):
        self.connection = connection
        self._next_row = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, args=None):
        self.connection.queries.append((query, args))
        if 'INFORMATION_SCHEMA.SCHEMATA' in query:
            self._next_row = (1,) if self.connection.schema_exists else None
        elif 'FROM mysql.user' in query:
            self._next_row = (1,) if self.connection.user_exists else None
        else:
            self._next_row = None
        return 1

    def fetchone(self):
        return self._next_row


class _Connection:
    def __init__(self, *, user_exists=False, schema_exists=True):
        self.user_exists = user_exists
        self.schema_exists = schema_exists
        self.queries = []
        self.closed = False

    def cursor(self):
        return _Cursor(self)

    @staticmethod
    def escape(value):
        return "'" + value.replace("'", "''") + "'"

    def close(self):
        self.closed = True


def _set_migration_environment(monkeypatch):
    values = {
        'MYSQL_ROOT_PASSWORD': 'legacy-root-password',
        'DB_HOST': 'mysql',
        'DB_PORT': '3306',
        'DB_USER': 'root',
        'DB_PASSWORD': 'legacy-root-password',
        'DB_NAME': 'iptv-all-in-one',
        'DB_CHARSET': 'utf8mb4',
        'DB_USER_HOST': '%',
        'IPTV_MIGRATION_DB_USER': 'iptv_app',
        'IPTV_MIGRATION_DB_PASSWORD': 'staged-app-password-1234',
        'IPTV_AUTH_PASSWORD': 'new-auth-password-1234',
        'IPTV_SECRET_KEY': 'stable-migration-secret-' + 'x' * 32,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


def _patch_database_migration(monkeypatch, *, fail_key_migration=False):
    import database.db as database_db
    from scanner_integration import config_bridge

    events = []

    def init_db():
        events.append(
            ('init_db', os_environ_pair())
        )

    def migrate_stored_api_keys():
        events.append(
            ('migrate_stored_api_keys', os_environ_pair())
        )
        if fail_key_migration:
            raise RuntimeError('key migration failed')
        return {}

    def os_environ_pair():
        import os
        return os.environ.get('DB_USER'), os.environ.get('DB_PASSWORD')

    monkeypatch.setattr(database_db, 'init_db', init_db)
    monkeypatch.setattr(database_db, '_reset_thread_conn', lambda: events.append(('reset', None)))
    monkeypatch.setattr(
        config_bridge,
        'migrate_stored_api_keys',
        migrate_stored_api_keys,
    )
    monkeypatch.setattr(config_bridge, '_CONFIG_CACHE', object())
    monkeypatch.setattr(config_bridge, '_CONFIG_CACHE_MTIME', object())
    return events


def _statements(connection):
    return [query for query, _args in connection.queries]


def test_docker_environment_mode_creates_user_runs_schema_and_key_migration(
    monkeypatch, local_tmp_path,
):
    values = _set_migration_environment(monkeypatch)
    missing_env = local_tmp_path / 'does-not-exist.env'
    root_connection = _Connection(user_exists=False)
    verify_connection = _Connection()
    connect_calls = []

    def connect(**kwargs):
        connect_calls.append(kwargs)
        if kwargs['user'] == 'root':
            return root_connection
        assert kwargs['user'] == values['IPTV_MIGRATION_DB_USER']
        assert kwargs['password'] == values['IPTV_MIGRATION_DB_PASSWORD']
        assert kwargs.get('database') == values['DB_NAME']
        return verify_connection

    monkeypatch.setattr(migrate_2_0.pymysql, 'connect', connect)
    events = _patch_database_migration(monkeypatch)

    migrate_2_0.migrate(missing_env, environment_only=True)

    statements = _statements(root_connection)
    assert any(query.startswith('CREATE USER ') for query in statements)
    assert any(query.startswith('GRANT ALL PRIVILEGES ') for query in statements)
    assert not any(query.startswith('ALTER USER ') for query in statements)
    assert not any(query.startswith('DROP USER ') for query in statements)
    assert [event[0] for event in events if event[0] != 'reset'] == [
        'init_db',
        'migrate_stored_api_keys',
    ]
    assert all(
        pair == (
            values['IPTV_MIGRATION_DB_USER'],
            values['IPTV_MIGRATION_DB_PASSWORD'],
        )
        for name, pair in events
        if name in {'init_db', 'migrate_stored_api_keys'}
    )
    assert not missing_env.exists()
    # The migration process restores its legacy active environment and never
    # tries to mutate the host's .env from inside a read-only container.
    import os
    assert os.environ['DB_USER'] == 'root'
    assert os.environ['DB_PASSWORD'] == 'legacy-root-password'
    assert root_connection.closed
    assert verify_connection.closed
    assert len(connect_calls) == 2


def test_existing_user_with_matching_credentials_is_granted_without_alter(
    monkeypatch, local_tmp_path,
):
    values = _set_migration_environment(monkeypatch)
    root_connection = _Connection(user_exists=True)
    credential_connection = _Connection()
    verify_connection = _Connection()
    app_connections = iter((credential_connection, verify_connection))

    def connect(**kwargs):
        if kwargs['user'] == 'root':
            return root_connection
        assert kwargs['user'] == values['IPTV_MIGRATION_DB_USER']
        return next(app_connections)

    monkeypatch.setattr(migrate_2_0.pymysql, 'connect', connect)
    _patch_database_migration(monkeypatch)

    migrate_2_0.migrate(local_tmp_path / 'missing.env')

    statements = _statements(root_connection)
    assert any(query.startswith('GRANT ALL PRIVILEGES ') for query in statements)
    assert not any(query.startswith('CREATE USER ') for query in statements)
    assert not any(query.startswith('ALTER USER ') for query in statements)
    assert not any(query.startswith('DROP USER ') for query in statements)
    assert credential_connection.closed
    assert verify_connection.closed


def test_existing_user_with_conflicting_credentials_is_not_modified(
    monkeypatch, local_tmp_path,
):
    _set_migration_environment(monkeypatch)
    root_connection = _Connection(user_exists=True)

    def connect(**kwargs):
        if kwargs['user'] == 'root':
            return root_connection
        raise pymysql.err.OperationalError(1045, 'access denied')

    monkeypatch.setattr(migrate_2_0.pymysql, 'connect', connect)
    events = _patch_database_migration(monkeypatch)

    with pytest.raises(RuntimeError, match='refusing to alter'):
        migrate_2_0.migrate(local_tmp_path / 'missing.env')

    statements = _statements(root_connection)
    assert not any(query.startswith('GRANT ALL PRIVILEGES ') for query in statements)
    assert not any(query.startswith('ALTER USER ') for query in statements)
    assert not any(query.startswith('DROP USER ') for query in statements)
    assert not events
    assert root_connection.closed


def test_new_user_is_dropped_when_key_migration_fails(monkeypatch, local_tmp_path):
    _set_migration_environment(monkeypatch)
    root_connection = _Connection(user_exists=False)
    verify_connection = _Connection()

    def connect(**kwargs):
        return root_connection if kwargs['user'] == 'root' else verify_connection

    monkeypatch.setattr(migrate_2_0.pymysql, 'connect', connect)
    events = _patch_database_migration(monkeypatch, fail_key_migration=True)

    with pytest.raises(RuntimeError, match='key migration failed'):
        migrate_2_0.migrate(local_tmp_path / 'missing.env')

    statements = _statements(root_connection)
    assert any(query.startswith('CREATE USER ') for query in statements)
    assert any(query.startswith('GRANT ALL PRIVILEGES ') for query in statements)
    assert any(query.startswith('DROP USER IF EXISTS ') for query in statements)
    assert [event[0] for event in events if event[0] != 'reset'] == [
        'init_db',
        'migrate_stored_api_keys',
    ]
    import os
    assert os.environ['DB_USER'] == 'root'
    assert os.environ['DB_PASSWORD'] == 'legacy-root-password'
    assert root_connection.closed
    assert verify_connection.closed


def test_environment_mode_requires_a_complete_staged_or_active_pair(
    monkeypatch, local_tmp_path,
):
    _set_migration_environment(monkeypatch)
    monkeypatch.delenv('IPTV_MIGRATION_DB_PASSWORD')

    with pytest.raises(ValueError, match='both IPTV_MIGRATION_DB_'):
        migrate_2_0.migrate(
            local_tmp_path / 'missing.env',
            environment_only=True,
        )


def test_environment_only_ignores_env_file_and_requires_staged_values(
    monkeypatch, local_tmp_path,
):
    env_path = local_tmp_path / '.env'
    env_path.write_text(
        'MYSQL_ROOT_PASSWORD=file-root-password\n'
        'DB_USER=iptv_app\n'
        'DB_PASSWORD=file-app-password-1234\n'
        'IPTV_AUTH_PASSWORD=file-auth-password-1234\n'
        'IPTV_SECRET_KEY=file-secret-with-at-least-thirty-two-characters\n',
        encoding='utf-8',
    )
    for name in (
        'MYSQL_ROOT_PASSWORD',
        'DB_USER',
        'DB_PASSWORD',
        'IPTV_AUTH_PASSWORD',
        'IPTV_SECRET_KEY',
        'IPTV_MIGRATION_DB_USER',
        'IPTV_MIGRATION_DB_PASSWORD',
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValueError, match='Environment-only migration requires'):
        migrate_2_0.migrate(env_path, environment_only=True)
