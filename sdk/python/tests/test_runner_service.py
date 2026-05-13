"""Tests for flamepy.runner.runner module - ObjectFuture, RunnerService, Runner."""

from concurrent.futures import Future
from unittest.mock import MagicMock, patch

import pytest


class DummyObjectRef:
    """Mock ObjectRef for testing."""

    def __init__(self, data=b"ref-data"):
        self._data = data

    @classmethod
    def decode(cls, data: bytes) -> "DummyObjectRef":
        return cls(data)

    def encode(self) -> bytes:
        return self._data


def test_objectfuture_ref_decodes_bytes():
    """Test ObjectFuture.ref() decodes bytes to ObjectRef."""
    from flamepy.runner.runner import ObjectFuture

    future = Future()
    future.set_result(b"encoded-ref")

    with patch("flamepy.runner.runner.ObjectRef", DummyObjectRef):
        of = ObjectFuture(future)
        ref = of.ref()
        assert isinstance(ref, DummyObjectRef)
        assert ref._data == b"encoded-ref"


def test_objectfuture_ref_returns_existing_objectref():
    """Test ObjectFuture.ref() returns ObjectRef if already decoded."""
    from flamepy.runner.runner import ObjectFuture

    dummy_ref = DummyObjectRef(b"already-ref")
    future = Future()
    future.set_result(dummy_ref)

    with patch("flamepy.runner.runner.ObjectRef", DummyObjectRef):
        of = ObjectFuture(future)
        ref = of.ref()
        assert ref is dummy_ref


def test_objectfuture_get_retrieves_object():
    """Test ObjectFuture.get() retrieves actual object from cache."""
    from flamepy.runner.runner import ObjectFuture

    future = Future()
    future.set_result(b"encoded-ref")

    with patch("flamepy.runner.runner.ObjectRef", DummyObjectRef):
        with patch("flamepy.runner.runner.get_object", return_value={"key": "value"}):
            of = ObjectFuture(future)
            result = of.get()
            assert result == {"key": "value"}


def test_objectfuture_wait_blocks_until_done():
    """Test ObjectFuture.wait() blocks until future completes."""
    from flamepy.runner.runner import ObjectFuture

    future = Future()
    future.set_result(b"done")

    of = ObjectFuture(future)
    of.wait()


def test_objectfuture_iterator_yields_in_completion_order():
    """Test ObjectFutureIterator yields futures as they complete."""
    from flamepy.runner.runner import ObjectFuture, ObjectFutureIterator

    f1 = Future()
    f2 = Future()
    f1.set_result(b"first")
    f2.set_result(b"second")

    of1 = ObjectFuture(f1)
    of2 = ObjectFuture(f2)

    iterator = ObjectFutureIterator([of1, of2])
    results = list(iterator)

    assert len(results) == 2
    assert of1 in results
    assert of2 in results


def test_runner_should_exclude_matches_patterns():
    """Test Runner._should_exclude() matches exclusion patterns."""
    from flamepy.runner.runner import Runner

    runner = object.__new__(Runner)

    assert runner._should_exclude("__pycache__", ["__pycache__"])
    assert runner._should_exclude("test.pyc", ["*.pyc"])
    assert runner._should_exclude(".git", [".git", ".venv"])
    assert not runner._should_exclude("main.py", ["*.pyc", "__pycache__"])


def test_runner_should_exclude_handles_nested_paths():
    """Test Runner._should_exclude() handles nested path patterns."""
    from flamepy.runner.runner import Runner

    runner = object.__new__(Runner)

    assert runner._should_exclude("src/__pycache__/module.pyc", ["*.pyc"])
    assert runner._should_exclude("tests/data/file.tmp", ["*.tmp"])


def test_runnerservice_generates_method_wrappers():
    """Test RunnerService generates wrappers for public methods."""
    from flamepy.runner.runner import RunnerService

    class Calculator:
        def add(self, a, b):
            return a + b

        def multiply(self, a, b):
            return a * b

        def _private(self):
            pass

    calc = Calculator()
    rs = object.__new__(RunnerService)
    rs._app = "test-app"
    rs._execution_object = calc
    rs._function_wrapper = None

    mock_session = MagicMock()
    mock_session.run = MagicMock(return_value=Future())
    rs._session = mock_session

    rs._generate_wrappers()

    assert hasattr(rs, "add")
    assert hasattr(rs, "multiply")
    assert not hasattr(rs, "_private")


def test_runnerservice_callable_for_function():
    """Test RunnerService is callable when execution object is a function."""
    from flamepy.runner.runner import RunnerService

    def my_func(x):
        return x * 2

    rs = object.__new__(RunnerService)
    rs._app = "test-app"
    rs._execution_object = my_func
    rs._function_wrapper = None

    mock_session = MagicMock()
    f = Future()
    f.set_result(b"result")
    mock_session.run = MagicMock(return_value=f)
    rs._session = mock_session

    rs._generate_wrappers()

    assert rs._function_wrapper is not None
    assert callable(rs)


def test_runnerservice_not_callable_for_class():
    """Test RunnerService raises TypeError when called but object is class."""
    from flamepy.runner.runner import RunnerService

    class MyClass:
        def method(self):
            pass

    rs = object.__new__(RunnerService)
    rs._app = "test-app"
    rs._execution_object = MyClass()
    rs._function_wrapper = None

    mock_session = MagicMock()
    rs._session = mock_session

    rs._generate_wrappers()

    with pytest.raises(TypeError):
        rs()


def test_runnerservice_close_closes_session():
    """Test RunnerService.close() closes the underlying session."""
    from flamepy.runner.runner import RunnerService

    rs = object.__new__(RunnerService)
    rs._app = "test-app"

    mock_session = MagicMock()
    rs._session = mock_session

    rs.close()

    mock_session.close.assert_called_once()


def test_runnerservice_does_not_overwrite_close_with_user_method():
    """Test generated wrappers do not replace RunnerService lifecycle methods."""
    from flamepy.runner.runner import RunnerService

    class ServiceWithClose:
        def close(self):
            return "user-close"

    rs = object.__new__(RunnerService)
    rs._app = "test-app"
    rs._execution_object = ServiceWithClose()
    rs._function_wrapper = None
    rs._session = MagicMock()

    rs._generate_wrappers()
    rs.close()

    rs._session.close.assert_called_once()


def test_runpy_resolves_object_ref_to_cached_none():
    """Test cached None is a valid ObjectRef value, not a retrieval miss."""
    from flamepy.core.cache import ObjectRef
    from flamepy.runner.runpy import FlameRunpyService

    svc = FlameRunpyService()
    ref = ObjectRef(endpoint="grpc://host:9090", key="app/session/object", version=1)

    with patch("flamepy.runner.runpy.get_object", return_value=None):
        assert svc._resolve_object_ref(ref) is None
        args, kwargs = svc._resolve_object_refs_parallel((ref,), {"value": ref})
        assert args == (None,)
        assert kwargs == {"value": None}


def test_runner_get_resolves_futures():
    """Test Runner.get() resolves multiple ObjectFutures."""
    from flamepy.runner.runner import ObjectFuture, Runner

    runner = object.__new__(Runner)

    f1 = Future()
    f2 = Future()
    f1.set_result(b"ref1")
    f2.set_result(b"ref2")

    with patch("flamepy.runner.runner.ObjectRef", DummyObjectRef):
        with patch("flamepy.runner.runner.get_object", side_effect=[{"a": 1}, {"b": 2}]):
            of1 = ObjectFuture(f1)
            of2 = ObjectFuture(f2)

            results = runner.get([of1, of2])
            assert results == [{"a": 1}, {"b": 2}]


def test_runner_wait_waits_for_all_futures():
    """Test Runner.wait() waits for all futures to complete."""
    from flamepy.runner.runner import ObjectFuture, Runner

    runner = object.__new__(Runner)

    f1 = Future()
    f2 = Future()
    f1.set_result(b"done1")
    f2.set_result(b"done2")

    of1 = ObjectFuture(f1)
    of2 = ObjectFuture(f2)

    runner.wait([of1, of2])


def test_runner_ref_returns_objectrefs():
    """Test Runner.ref() returns ObjectRefs for all futures."""
    from flamepy.runner.runner import ObjectFuture, Runner

    runner = object.__new__(Runner)

    f1 = Future()
    f2 = Future()
    f1.set_result(b"ref1")
    f2.set_result(b"ref2")

    with patch("flamepy.runner.runner.ObjectRef", DummyObjectRef):
        of1 = ObjectFuture(f1)
        of2 = ObjectFuture(f2)

        refs = runner.ref([of1, of2])
        assert len(refs) == 2
        assert all(isinstance(r, DummyObjectRef) for r in refs)
