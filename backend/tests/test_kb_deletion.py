from unittest.mock import AsyncMock

import pytest

from app import db
from app.es import elastic
from app.services import ingestion


def test_delete_missing_kb(api, fake_db):
    fake_db.route("FROM kb_database WHERE id=", None)
    assert api.delete('/api/admin/kb/77').status_code == 404


def test_delete_kb_cleans_only_target(api, fake_db, tmp_path, monkeypatch):
    monkeypatch.setattr(ingestion, 'UPLOAD_DIR', tmp_path)
    target = tmp_path / '77'
    target.mkdir()
    (target / 'resume.txt').write_text('synthetic')
    other = tmp_path / '78'
    other.mkdir()
    (other / 'keep.txt').write_text('keep')
    fake_db.route('FROM kb_database WHERE id=', {'id': 77})
    fake_db.route('status IN', None)
    delete = AsyncMock()
    monkeypatch.setattr(elastic, 'delete_by_kb', delete, raising=False)
    response = api.delete('/api/admin/kb/77')
    assert response.status_code == 200
    assert response.json() == {'deleted': 77}
    delete.assert_awaited_once_with(77)
    assert not target.exists()
    assert (other / 'keep.txt').read_text() == 'keep'
    deletes = [(sql, params) for sql, params in fake_db.calls if sql.startswith('DELETE')]
    assert len(deletes) == 3
    assert all(params == (77,) for _, params in deletes)


def test_delete_processing_kb_rejected(api, fake_db, monkeypatch):
    fake_db.route('FROM kb_database WHERE id=', {'id': 77})
    fake_db.route('status IN', {'id': 3})
    delete = AsyncMock()
    monkeypatch.setattr(elastic, 'delete_by_kb', delete, raising=False)
    assert api.delete('/api/admin/kb/77').status_code == 409
    delete.assert_not_awaited()
    assert not any(sql.startswith('DELETE') for sql in fake_db.sqls())


def test_cannot_delete_active_document_then_bypass_kb_guard(api, fake_db):
    fake_db.route('WHERE id=%s AND kb_id=%s', {'id': 3, 'status': 'embedding'})
    assert api.delete('/api/admin/kb/77/documents/3').status_code == 409
    assert not any(sql.startswith('DELETE') for sql in fake_db.sqls())


@pytest.mark.asyncio
async def test_pending_ingestion_does_not_resurrect_deleted_document(fake_db, monkeypatch):
    rows = iter([{'id': 3, 'kb_id': 77}, None])
    fake_db.route('SELECT * FROM kb_document', lambda _: next(rows))
    parse = AsyncMock()
    monkeypatch.setattr(ingestion, '_parse', parse)
    await ingestion.process_document(3)
    parse.assert_not_awaited()
    assert not any(sql.startswith('UPDATE') for sql in fake_db.sqls())


@pytest.mark.asyncio
async def test_ingestion_lock_timeout_marks_document_retryable(fake_db, monkeypatch):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def busy(kb_id):
        raise TimeoutError('busy')
        yield

    fake_db.route('SELECT * FROM kb_document', {'id': 3, 'kb_id': 77})
    monkeypatch.setattr(db, 'kb_write_lock', busy)
    await ingestion.process_document(3)
    updates = [params for sql, params in fake_db.calls if sql.startswith('UPDATE')]
    assert len(updates) == 1
    assert updates[0][0] == 'failed'


def test_upload_directory_cannot_escape_root(tmp_path, monkeypatch):
    monkeypatch.setattr(ingestion, 'UPLOAD_DIR', tmp_path)
    with pytest.raises(ValueError, match='Invalid'):
        ingestion._remove_upload_directory(-1)
    assert tmp_path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('result', [{'timed_out': True}, {'failures': [{'reason': 'broken'}]}, {'version_conflicts': 1}, {}])
async def test_es_delete_scope_and_partial_failure(result, monkeypatch):
    import httpx
    client = AsyncMock()
    client.post.return_value = httpx.Response(200, json=result, request=httpx.Request('POST', 'http://es/kb_chunks/_delete_by_query'))
    monkeypatch.setattr(elastic, 'client', client)
    if result:
        with pytest.raises(RuntimeError, match='incomplete'):
            await elastic.delete_by_kb(77)
    else:
        await elastic.delete_by_kb(77)
    assert client.post.call_args.kwargs['json'] == {'query': {'term': {'kb_id': 77}}}
    assert client.post.call_args.kwargs['params'] == {'refresh': 'true'}
    assert client.post.call_args_list[0].args == ('/kb_chunks/_refresh',)


@pytest.mark.asyncio
@pytest.mark.parametrize('acquired', [0, 1])
async def test_database_lock_closed_even_on_failure(monkeypatch, acquired):
    from unittest.mock import MagicMock
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = {'acquired': acquired}
    monkeypatch.setattr(db, 'get_conn', lambda: conn)
    if acquired:
        async def operation():
            async with db.kb_write_lock(77):
                assert not conn.close.called
                raise RuntimeError('operation failed')

        with pytest.raises(RuntimeError):
            await operation()
    else:
        with pytest.raises(TimeoutError):
            async with db.kb_write_lock(77):
                pytest.fail('lock must be acquired')
    conn.close.assert_called_once()


@pytest.mark.parametrize('fail', [False, True])
def test_metadata_transaction_commits_or_rolls_back(monkeypatch, fail):
    from unittest.mock import MagicMock
    conn = MagicMock()
    conn.__enter__.return_value = conn
    cursor = conn.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(db, 'get_conn', lambda: conn)
    if fail:
        cursor.execute.side_effect = RuntimeError('SQL failed')
        with pytest.raises(RuntimeError, match='SQL failed'):
            db.execute_transaction([('DELETE', (77,))])
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()
    else:
        db.execute_transaction([('DELETE', (77,))])
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()
    conn.begin.assert_called_once()


@pytest.mark.asyncio
async def test_index_failure_preserves_metadata_and_files(fake_db, tmp_path, monkeypatch):
    monkeypatch.setattr(ingestion, 'UPLOAD_DIR', tmp_path)
    target = tmp_path / '77'
    target.mkdir()
    fake_db.route('FROM kb_database WHERE id=', {'id': 77})
    fake_db.route('status IN', None)
    monkeypatch.setattr(elastic, 'delete_by_kb', AsyncMock(side_effect=RuntimeError('ES unavailable')), raising=False)
    with pytest.raises(RuntimeError, match='ES unavailable'):
        await ingestion.delete_knowledge_base(77)
    assert target.exists()
    assert not any(sql.startswith('DELETE') for sql in fake_db.sqls())
