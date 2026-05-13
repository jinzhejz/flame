import time
from datetime import datetime, timezone

import pytest

import flamepy.core.client as client
from flamepy.core.types import FlameError, FlameErrorCode


class DummyChannel:
    def __init__(self, location):
        self.location = location

    def close(self):
        pass


class DummyFrontend:
    def __init__(self):
        pass


def test_connection_connect_http(monkeypatch):
    import grpc

    monkeypatch.setattr(grpc, "insecure_channel", lambda loc: DummyChannel(loc))

    class DummyFuture:
        def result(self, timeout=None):
            return None

    monkeypatch.setattr(grpc, "channel_ready_future", lambda ch: DummyFuture())
    monkeypatch.setattr(grpc, "secure_channel", lambda loc, creds=None: DummyChannel(loc))
    monkeypatch.setattr(grpc, "ssl_channel_credentials", lambda root_certificates=None: b"certs")
    monkeypatch.setattr("flamepy.core.client.FrontendStub", lambda channel: DummyFrontend())

    conn = client.Connection.connect("http://localhost:1234")
    assert isinstance(conn, client.Connection)
    conn.close()


def test_connection_connect_https_with_tls(monkeypatch, tmp_path):
    import grpc

    monkeypatch.setattr(grpc, "insecure_channel", lambda loc: DummyChannel(loc))

    class DummyFuture:
        def result(self, timeout=None):
            return None

    monkeypatch.setattr(grpc, "channel_ready_future", lambda ch: DummyFuture())
    monkeypatch.setattr(grpc, "secure_channel", lambda loc, creds=None: DummyChannel(loc))
    called = {"ok": False}

    def fake_ssl_credentials(*args, **kwargs):
        called["ok"] = True
        return b"certs"

    monkeypatch.setattr(grpc, "ssl_channel_credentials", fake_ssl_credentials)
    monkeypatch.setattr("flamepy.core.client.FrontendStub", lambda channel: DummyFrontend())

    tls = client.FlameClientTls(ca_file=str(tmp_path / "ca.pem"))
    (tmp_path / "ca.pem").write_text("CERT")
    tls.ca_file = str(tmp_path / "ca.pem")
    conn = client.Connection.connect("https://localhost:1234", tls_config=tls)
    assert isinstance(conn, client.Connection)
    assert called["ok"]
    conn.close()


def test_session_create_task_with_mocked_frontend(monkeypatch):

    class DummyFrontend:
        def CreateTask(self, req):  # noqa: N802
            class StatusMock:
                state = 0
                creation_time = int(time.time() * 1000)
                completion_time = int(time.time() * 1000)
                events = []

                def HasField(self, name):  # noqa: N802
                    return name == "completion_time"

            class Resp:
                metadata = type("M", (), {"id": "tid-1"})
                status = StatusMock()

            return Resp()

    class DummyConnection:
        def __init__(self):
            self._frontend = DummyFrontend()
            import concurrent.futures

            self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

        def close(self):
            pass

    fake_conn = DummyConnection()
    from flamepy.core.client import Session, SessionState

    s = Session(connection=fake_conn, id="sess-1", application="app", state=SessionState.OPEN, creation_time=datetime.now(timezone.utc), pending=0, running=0, succeed=0, failed=0, completion_time=None)

    t = s.create_task(b"input")
    assert t.session_id == s.id
    assert t.id is not None


class TestConnectionValidation:
    def test_connection_rejects_empty_address(self):
        with pytest.raises(FlameError) as exc_info:
            client.Connection.connect("")
        assert exc_info.value.code == FlameErrorCode.INVALID_CONFIG

    def test_connection_handles_timeout(self, monkeypatch):
        import grpc

        monkeypatch.setattr(grpc, "insecure_channel", lambda loc: DummyChannel(loc))

        class TimeoutFuture:
            def result(self, timeout=None):
                raise grpc.FutureTimeoutError()

        monkeypatch.setattr(grpc, "channel_ready_future", lambda ch: TimeoutFuture())

        with pytest.raises(FlameError) as exc_info:
            client.Connection.connect("http://localhost:1234")
        assert "timeout" in str(exc_info.value).lower()


class TestSessionOperations:
    def create_test_session(self, connection=None):
        from flamepy.core.client import Session, SessionState

        if connection is None:
            connection = type("Conn", (), {"_frontend": DummyFrontend(), "_executor": None, "close": lambda self: None})()

        return Session(
            connection=connection,
            id="sess-test",
            application="test-app",
            state=SessionState.OPEN,
            creation_time=datetime.now(timezone.utc),
            pending=0,
            running=0,
            succeed=0,
            failed=0,
            completion_time=None,
        )

    def test_session_common_data_returns_none_by_default(self):
        session = self.create_test_session()
        assert session.common_data() is None

    def test_session_common_data_returns_bytes(self):
        from flamepy.core.client import Session, SessionState

        connection = type("Conn", (), {"_frontend": DummyFrontend(), "_executor": None, "close": lambda self: None})()
        session = Session(
            connection=connection,
            id="sess-test",
            application="test-app",
            state=SessionState.OPEN,
            creation_time=datetime.now(timezone.utc),
            pending=0,
            running=0,
            succeed=0,
            failed=0,
            completion_time=None,
            common_data=b"test-data",
        )
        assert session.common_data() == b"test-data"

    def test_session_get_task_preserves_empty_optional_bytes(self):
        from flamepy.core.client import Session, SessionState
        from flamepy.proto.types_pb2 import Metadata, Task, TaskSpec, TaskStatus

        class DummyFrontendWithTask:
            def GetTask(self, req):  # noqa: N802
                task = Task(
                    metadata=Metadata(id="task-1"),
                    spec=TaskSpec(session_id=req.session_id, input=b"", output=b""),
                    status=TaskStatus(state=2, creation_time=int(time.time() * 1000)),
                )
                return task

        connection = type("Conn", (), {"_frontend": DummyFrontendWithTask(), "_executor": None, "close": lambda self: None})()
        session = Session(
            connection=connection,
            id="sess-test",
            application="test-app",
            state=SessionState.OPEN,
            creation_time=datetime.now(timezone.utc),
            pending=0,
            running=0,
            succeed=0,
            failed=0,
            completion_time=None,
        )

        task = session.get_task("task-1")

        assert task.input == b""
        assert task.output == b""

    def test_session_create_task_rejects_non_bytes(self):
        session = self.create_test_session()
        with pytest.raises(FlameError) as exc_info:
            session.create_task("not bytes")
        assert exc_info.value.code == FlameErrorCode.INVALID_ARGUMENT


class TestGrpcErrorMapping:
    def test_not_found_error_mapping(self):
        import grpc

        class FakeRpcError(grpc.RpcError):
            def code(self):
                return grpc.StatusCode.NOT_FOUND

            def details(self):
                return "Resource not found"

        error = client.Connection._grpc_error_to_flame_error(FakeRpcError(), "test operation")
        assert error.code == FlameErrorCode.NOT_FOUND

    def test_already_exists_error_mapping(self):
        import grpc

        class FakeRpcError(grpc.RpcError):
            def code(self):
                return grpc.StatusCode.ALREADY_EXISTS

            def details(self):
                return "Already exists"

        error = client.Connection._grpc_error_to_flame_error(FakeRpcError(), "test operation")
        assert error.code == FlameErrorCode.ALREADY_EXISTS

    def test_invalid_argument_error_mapping(self):
        import grpc

        class FakeRpcError(grpc.RpcError):
            def code(self):
                return grpc.StatusCode.INVALID_ARGUMENT

            def details(self):
                return "Invalid argument"

        error = client.Connection._grpc_error_to_flame_error(FakeRpcError(), "test operation")
        assert error.code == FlameErrorCode.INVALID_ARGUMENT

    def test_failed_precondition_error_mapping(self):
        import grpc

        class FakeRpcError(grpc.RpcError):
            def code(self):
                return grpc.StatusCode.FAILED_PRECONDITION

            def details(self):
                return "Precondition failed"

        error = client.Connection._grpc_error_to_flame_error(FakeRpcError(), "test operation")
        assert error.code == FlameErrorCode.INVALID_STATE

    def test_unknown_error_mapping(self):
        import grpc

        class FakeRpcError(grpc.RpcError):
            def code(self):
                return grpc.StatusCode.UNKNOWN

            def details(self):
                return "Unknown error"

        error = client.Connection._grpc_error_to_flame_error(FakeRpcError(), "test operation")
        assert error.code == FlameErrorCode.INTERNAL


class TestApplicationConversion:
    def test_list_applications_preserves_absent_optional_fields(self):
        from flamepy.proto.types_pb2 import Application as ApplicationProto
        from flamepy.proto.types_pb2 import ApplicationList, ApplicationStatus, Metadata

        class Frontend:
            def ListApplication(self, req):  # noqa: N802
                app = ApplicationProto(
                    metadata=Metadata(id="app-1", name="app"),
                    status=ApplicationStatus(state=0, creation_time=int(time.time() * 1000)),
                )
                return ApplicationList(applications=[app])

        conn = client.Connection("http://unused", DummyChannel("unused"), Frontend())
        try:
            apps = conn.list_applications()
        finally:
            conn.close()

        assert len(apps) == 1
        app = apps[0]
        assert app.image is None
        assert app.command is None
        assert app.working_directory is None
        assert app.max_instances is None
        assert app.delay_release is None
        assert app.schema is None
        assert app.url is None
        assert app.installer is None

    def test_get_application_preserves_present_empty_optional_fields(self):
        from flamepy.proto.types_pb2 import Application as ApplicationProto
        from flamepy.proto.types_pb2 import ApplicationSchema, ApplicationStatus, Metadata

        class Frontend:
            def GetApplication(self, req):  # noqa: N802
                app = ApplicationProto(
                    metadata=Metadata(id="app-1", name=req.name),
                    status=ApplicationStatus(state=0, creation_time=int(time.time() * 1000)),
                )
                app.spec.image = ""
                app.spec.schema.CopyFrom(ApplicationSchema(input=""))
                return app

        conn = client.Connection("http://unused", DummyChannel("unused"), Frontend())
        try:
            app = conn.get_application("app")
        finally:
            conn.close()

        assert app.image == ""
        assert app.command is None
        assert app.schema is not None
        assert app.schema.input == ""
        assert app.schema.output is None


class TestTaskWatcher:
    def test_task_watcher_iteration(self):
        from flamepy.core.client import TaskWatcher

        class FakeStream:
            def __init__(self):
                self.items = []
                self.index = 0

            def __next__(self):
                if self.index >= len(self.items):
                    raise StopIteration
                item = self.items[self.index]
                self.index += 1
                return item

        stream = FakeStream()
        watcher = TaskWatcher(stream)
        assert iter(watcher) is watcher

    def test_task_watcher_timeout_check(self):
        from flamepy.core.client import TaskWatcher

        class EmptyStream:
            def __next__(self):
                raise StopIteration

        watcher = TaskWatcher(EmptyStream(), timeout=0.001)
        import time as time_module

        time_module.sleep(0.01)
        with pytest.raises(TimeoutError):
            next(watcher)


class TestTaskIterator:
    def test_task_iterator_is_iterable(self):
        from flamepy.core.client import TaskIterator

        class FakeStream:
            def __next__(self):
                raise StopIteration

        iterator = TaskIterator(FakeStream(), "sess-1")
        assert iter(iterator) is iterator
