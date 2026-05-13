import gc
import logging
import os

import pytest

import flamepy.core.service as service
from flamepy.proto.types_pb2 import Result as ResultProto
from flamepy.proto.types_pb2 import TaskResult as TaskResultProto


class DummyContext:
    pass


def test_tracefn_logs_enter_and_exit(caplog):
    caplog.set_level(logging.DEBUG)
    name = "TraceTest"
    t = service.TraceFn(name)
    # Enter log should appear on creation
    assert any(f"{name} Enter" in rec.getMessage() for rec in caplog.records)
    # Force destruction to trigger __del__ and Exit log
    del t
    gc.collect()
    assert any(f"{name} Exit" in rec.getMessage() for rec in caplog.records)


def test_dataclasses_fields_and_methods():
    app = service.ApplicationContext("my-app", image="my-image:latest", command="run", working_directory="/work", url="http://example/")
    assert app.name == "my-app"
    assert app.image == "my-image:latest"
    assert app.command == "run"
    assert app.working_directory == "/work"
    assert app.url == "http://example/"

    sess = service.SessionContext(_common_data=b"ABC", session_id="sess-1", application=app)
    assert sess.session_id == "sess-1"
    assert sess.application is app
    assert sess.common_data() == b"ABC"

    task = service.TaskContext(task_id="task-1", session_id="sess-1", input=b"in")
    assert task.task_id == "task-1"
    assert task.session_id == "sess-1"
    assert task.input == b"in"


def test_flame_service_abstract_minimal_implementation():
    class MyService(service.FlameService):
        def __init__(self):
            self.called = {}

        def on_session_enter(self, context: service.SessionContext):
            self.called["enter"] = context
            return True

        def on_task_invoke(self, context: service.TaskContext):
            self.called["invoke"] = context
            return b"OUT"

        def on_session_leave(self):
            self.called["leave"] = True
            return True

    svc = MyService()
    servicer = service.FlameInstanceServicer(svc)

    # Build simple mock request for OnSessionEnter
    class MockAppCtx:
        def __init__(self):
            self.name = "app"
            self.image = "img"
            self.command = "cmd"
            self.working_directory = "/work"
            self.url = "http://url"

        def HasField(self, field):  # noqa: N802
            return field == "image" and self.image is not None

    class MockSessionEnterRequest:
        def __init__(self):
            self.session_id = "sess-123"
            self.application = MockAppCtx()
            self.common_data = b"C"

        def HasField(self, field):  # noqa: N802
            if field == "common_data":
                return self.common_data is not None
            return False

    req = MockSessionEnterRequest()
    resp = servicer.OnSessionEnter(req, DummyContext())
    assert isinstance(resp, ResultProto)
    assert resp.return_code == 0
    # Verify service received a SessionContext with the right fields
    assert svc.called["enter"].session_id == "sess-123"

    # OnTaskInvoke path
    class MockTaskRequest:
        def __init__(self):
            self.task_id = "t1"
            self.session_id = "sess-123"
            self.input = b"in"

        def HasField(self, field):  # noqa: N802
            return field == "input" and self.input is not None

    req2 = MockTaskRequest()
    resp2 = servicer.OnTaskInvoke(req2, DummyContext())
    assert isinstance(resp2, TaskResultProto)
    assert resp2.return_code == 0
    assert resp2.output == b"OUT"
    assert svc.called["invoke"].task_id == "t1"

    # OnSessionLeave path
    resp3 = servicer.OnSessionLeave(None, DummyContext())
    assert isinstance(resp3, ResultProto)
    assert resp3.return_code == 0


def test_on_session_enter_exception_path_returns_error():  # noqa: N802
    class FailService(service.FlameService):
        def on_session_enter(self, context: service.SessionContext):
            raise RuntimeError("boom")

        def on_task_invoke(self, context: service.TaskContext):
            return b"X"

        def on_session_leave(self):
            return True

    svc = FailService()
    servicer = service.FlameInstanceServicer(svc)

    class MockAppCtx:
        def __init__(self):
            self.name = "app"
            self.image = "img"

        def HasField(self, field):  # noqa: N802
            return field == "image" and self.image is not None

    class MockSessionEnterRequest:
        def __init__(self):
            self.session_id = "sess-1"
            self.application = MockAppCtx()
            self.common_data = None

        def HasField(self, field):  # noqa: N802
            return False

    req = MockSessionEnterRequest()
    resp = servicer.OnSessionEnter(req, DummyContext())
    assert resp.return_code == -1


def test_on_task_invoke_exception_path():  # noqa: N802
    class FailService(service.FlameService):
        def on_session_enter(self, context: service.SessionContext):
            return True

        def on_task_invoke(self, context: service.TaskContext):
            raise ValueError("bad task")

        def on_session_leave(self):
            return True

    svc = FailService()
    servicer = service.FlameInstanceServicer(svc)

    class MockTaskRequest:
        def __init__(self):
            self.task_id = "tid"
            self.session_id = "sess"
            self.input = b"in"

        def HasField(self, field):  # noqa: N802
            return field == "input" and self.input is not None

    req = MockTaskRequest()
    resp = servicer.OnTaskInvoke(req, DummyContext())
    assert resp.return_code == -1
    assert not resp.HasField("output")


def test_service_preserves_empty_optional_bytes():  # noqa: N802
    class CaptureService(service.FlameService):
        def __init__(self):
            self.session_context = None
            self.task_context = None

        def on_session_enter(self, context: service.SessionContext):
            self.session_context = context
            return True

        def on_task_invoke(self, context: service.TaskContext):
            self.task_context = context
            return None

        def on_session_leave(self):
            return True

    svc = CaptureService()
    servicer = service.FlameInstanceServicer(svc)

    class MockAppCtx:
        name = "app"
        image = None
        command = None
        working_directory = None
        url = None

        def HasField(self, field):  # noqa: N802
            return False

    class MockSessionEnterRequest:
        session_id = "sess"
        application = MockAppCtx()
        common_data = b""

        def HasField(self, field):  # noqa: N802
            return field == "common_data"

    class MockTaskRequest:
        task_id = "task"
        session_id = "sess"
        input = b""

        def HasField(self, field):  # noqa: N802
            return field == "input"

    enter_resp = servicer.OnSessionEnter(MockSessionEnterRequest(), DummyContext())
    invoke_resp = servicer.OnTaskInvoke(MockTaskRequest(), DummyContext())

    assert enter_resp.return_code == 0
    assert svc.session_context.common_data() == b""
    assert invoke_resp.return_code == 0
    assert not invoke_resp.HasField("output")
    assert svc.task_context.input == b""


def test_flame_instance_server_start_and_stop(monkeypatch, tmp_path):
    # Fake grpc server and helper to intercept calls
    started = {"start": False, "stop": False}

    class FakeServer:
        def __init__(self, *args, **kwargs):
            self._stopped = False

        def add_insecure_port(self, addr):
            # Accept the unix socket address; just store for verification
            self._port = addr

        def start(self):
            started["start"] = True

        def wait_for_termination(self):
            # Immediately return to avoid blocking
            return None

        def stop(self, grace=None):
            started["stop"] = True
            self._stopped = True

    fake_grpc = type("fake_grpc", (), {})()
    fake_grpc.server = lambda executor=None: FakeServer()

    # Patch grpc in the service module
    monkeypatch.setattr(service, "grpc", fake_grpc)
    # Patch add_InstanceServicer_to_server to a no-op
    called = {"added": None}
    monkeypatch.setattr(service, "add_InstanceServicer_to_server", lambda servicer, srv: called.__setitem__("added", (servicer, srv)))

    # Ensure endpoint is set
    os.environ[service.FLAME_INSTANCE_ENDPOINT] = "/tmp/flame.sock"

    class DummyService(service.FlameService):
        def on_session_enter(self, context):
            return True

        def on_task_invoke(self, context):
            return b"OUT"

        def on_session_leave(self):
            return True

    s = service.FlameInstanceServer(DummyService())
    s.start()
    # Verify server was started and added to server
    assert started["start"] is True
    # Stop should call server.stop
    s.stop()
    assert started["stop"] is True


def test_flame_instance_server_start_without_endpoint_raises():
    # Ensure the environment does not provide the endpoint
    if service.FLAME_INSTANCE_ENDPOINT in os.environ:
        del os.environ[service.FLAME_INSTANCE_ENDPOINT]

    class DummyService(service.FlameService):
        def on_session_enter(self, context):
            return True

        def on_task_invoke(self, context):
            return b""

        def on_session_leave(self):
            return True

    with pytest.raises(Exception):
        service.FlameInstanceServer(DummyService()).start()
