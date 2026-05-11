"""Unit tests for flamepy.runner.types module.

Tests for SessionContext, RunnerContext, and RunnerRequest dataclasses
including validation, edge cases, and integration scenarios.
"""

import pytest

from flamepy.runner.types import RunnerContext, RunnerRequest, SessionContext


class TestSessionContext:
    """Tests for SessionContext dataclass validation."""

    def test_session_context_default_values(self):
        """Test SessionContext with default values."""
        ctx = SessionContext()
        assert ctx.session_id is None
        assert ctx.application_name is None

    def test_session_context_with_session_id(self):
        """Test SessionContext with valid session_id."""
        ctx = SessionContext(session_id="my-session-001")
        assert ctx.session_id == "my-session-001"
        assert ctx.application_name is None

    def test_session_context_with_application_name(self):
        """Test SessionContext with application_name."""
        ctx = SessionContext(application_name="my-app")
        assert ctx.session_id is None
        assert ctx.application_name == "my-app"

    def test_session_context_with_both_fields(self):
        """Test SessionContext with both fields set."""
        ctx = SessionContext(session_id="sess-001", application_name="app-001")
        assert ctx.session_id == "sess-001"
        assert ctx.application_name == "app-001"

    def test_session_context_invalid_session_id_type(self):
        """Test SessionContext rejects non-string session_id."""
        with pytest.raises(ValueError, match="session_id must be a string"):
            SessionContext(session_id=12345)

    def test_session_context_empty_session_id(self):
        """Test SessionContext rejects empty session_id."""
        with pytest.raises(ValueError, match="session_id cannot be empty"):
            SessionContext(session_id="")

    def test_session_context_session_id_too_long(self):
        """Test SessionContext rejects session_id > 128 chars."""
        long_id = "x" * 129
        with pytest.raises(ValueError, match="session_id too long"):
            SessionContext(session_id=long_id)

    def test_session_context_max_length_session_id(self):
        """Test SessionContext accepts session_id of exactly 128 chars."""
        max_id = "x" * 128
        ctx = SessionContext(session_id=max_id)
        assert len(ctx.session_id) == 128

    def test_session_context_invalid_application_name_type(self):
        """Test SessionContext rejects non-string application_name."""
        with pytest.raises(ValueError, match="application_name must be a string"):
            SessionContext(application_name=42)


class TestRunnerContext:
    """Tests for RunnerContext dataclass."""

    def test_runner_context_default_values(self):
        """Test RunnerContext with default values."""
        ctx = RunnerContext(execution_object=lambda x: x)
        assert ctx.stateful is False
        assert ctx.autoscale is True
        assert ctx.warmup == 0
        assert ctx.min_instances == 0
        assert ctx.max_instances is None

    def test_runner_context_autoscale_true(self):
        """Test RunnerContext with autoscale=True."""
        ctx = RunnerContext(execution_object=lambda x: x, autoscale=True)
        assert ctx.min_instances == 0
        assert ctx.max_instances is None

    def test_runner_context_autoscale_false(self):
        """Test RunnerContext with autoscale=False."""
        ctx = RunnerContext(execution_object=lambda x: x, autoscale=False)
        assert ctx.min_instances == 1
        assert ctx.max_instances == 1

    def test_runner_context_warmup_with_autoscale(self):
        """Test RunnerContext warmup affects min_instances when autoscale=True."""
        ctx = RunnerContext(execution_object=lambda x: x, autoscale=True, warmup=5)
        assert ctx.min_instances == 5
        assert ctx.max_instances is None

    def test_runner_context_warmup_without_autoscale(self):
        """Test RunnerContext warmup affects both min/max when autoscale=False."""
        ctx = RunnerContext(execution_object=lambda x: x, autoscale=False, warmup=3)
        assert ctx.min_instances == 3
        assert ctx.max_instances == 3

    def test_runner_context_stateful_with_instance(self):
        """Test RunnerContext stateful=True is allowed for instances."""

        class MyClass:
            pass

        instance = MyClass()
        ctx = RunnerContext(execution_object=instance, stateful=True)
        assert ctx.stateful is True

    def test_runner_context_stateful_with_function(self):
        """Test RunnerContext stateful=True is allowed for functions."""

        def my_func():
            pass

        ctx = RunnerContext(execution_object=my_func, stateful=True)
        assert ctx.stateful is True

    def test_runner_context_stateful_with_class_raises(self):
        """Test RunnerContext stateful=True raises for classes."""

        class MyClass:
            pass

        with pytest.raises(ValueError, match="Cannot set stateful=True for a class"):
            RunnerContext(execution_object=MyClass, stateful=True)

    def test_runner_context_stateful_false_with_class(self):
        """Test RunnerContext stateful=False is allowed for classes."""

        class MyClass:
            pass

        ctx = RunnerContext(execution_object=MyClass, stateful=False)
        assert ctx.stateful is False


class TestRunnerRequest:
    """Tests for RunnerRequest dataclass."""

    def test_runner_request_default_values(self):
        """Test RunnerRequest with default values."""
        req = RunnerRequest()
        assert req.method is None
        assert req.args is None
        assert req.kwargs is None

    def test_runner_request_with_method(self):
        """Test RunnerRequest with method name."""
        req = RunnerRequest(method="process")
        assert req.method == "process"

    def test_runner_request_with_args(self):
        """Test RunnerRequest with args tuple."""
        req = RunnerRequest(args=(1, 2, 3))
        assert req.args == (1, 2, 3)

    def test_runner_request_with_args_list(self):
        """Test RunnerRequest accepts args as list."""
        req = RunnerRequest(args=[1, 2, 3])
        assert req.args == [1, 2, 3]

    def test_runner_request_with_kwargs(self):
        """Test RunnerRequest with kwargs dict."""
        req = RunnerRequest(kwargs={"a": 1, "b": 2})
        assert req.kwargs == {"a": 1, "b": 2}

    def test_runner_request_complete(self):
        """Test RunnerRequest with all fields."""
        req = RunnerRequest(method="compute", args=(10, 20), kwargs={"scale": 2.0})
        assert req.method == "compute"
        assert req.args == (10, 20)
        assert req.kwargs == {"scale": 2.0}

    def test_runner_request_invalid_method_type(self):
        """Test RunnerRequest rejects non-string method."""
        with pytest.raises(ValueError, match="method must be a string or None"):
            RunnerRequest(method=123)

    def test_runner_request_invalid_args_type(self):
        """Test RunnerRequest rejects non-tuple/list args."""
        with pytest.raises(ValueError, match="args must be a tuple or list"):
            RunnerRequest(args="not a tuple")

    def test_runner_request_invalid_kwargs_type(self):
        """Test RunnerRequest rejects non-dict kwargs."""
        with pytest.raises(ValueError, match="kwargs must be a dict"):
            RunnerRequest(kwargs="not a dict")

    def test_runner_request_empty_args_tuple(self):
        """Test RunnerRequest with empty args tuple."""
        req = RunnerRequest(args=())
        assert req.args == ()

    def test_runner_request_empty_kwargs_dict(self):
        """Test RunnerRequest with empty kwargs dict."""
        req = RunnerRequest(kwargs={})
        assert req.kwargs == {}

    def test_runner_request_complex_args(self):
        """Test RunnerRequest with complex nested args."""
        complex_args = (
            {"nested": [1, 2, 3]},
            [4, 5, 6],
            None,
            "string",
        )
        req = RunnerRequest(args=complex_args)
        assert req.args == complex_args

    def test_runner_request_complex_kwargs(self):
        """Test RunnerRequest with complex nested kwargs."""
        complex_kwargs = {
            "data": {"key": "value"},
            "items": [1, 2, 3],
            "flag": True,
            "nothing": None,
        }
        req = RunnerRequest(kwargs=complex_kwargs)
        assert req.kwargs == complex_kwargs


class TestSessionContextEdgeCases:
    """Additional edge case tests for SessionContext."""

    def test_session_context_whitespace_only_session_id(self):
        """Test SessionContext accepts whitespace-only session_id (not empty)."""
        ctx = SessionContext(session_id="   ")
        assert ctx.session_id == "   "

    def test_session_context_special_characters_in_session_id(self):
        """Test SessionContext with special characters in session_id."""
        ctx = SessionContext(session_id="sess-123_abc.test")
        assert ctx.session_id == "sess-123_abc.test"

    def test_session_context_unicode_session_id(self):
        """Test SessionContext with unicode characters in session_id."""
        ctx = SessionContext(session_id="session-日本語-test")
        assert ctx.session_id == "session-日本語-test"

    def test_session_context_boundary_length_session_id(self):
        """Test SessionContext with session_id at boundary lengths."""
        ctx_1 = SessionContext(session_id="x")
        assert len(ctx_1.session_id) == 1

        ctx_127 = SessionContext(session_id="x" * 127)
        assert len(ctx_127.session_id) == 127

        ctx_128 = SessionContext(session_id="x" * 128)
        assert len(ctx_128.session_id) == 128

    def test_session_context_empty_application_name(self):
        """Test SessionContext with empty application_name (allowed)."""
        ctx = SessionContext(application_name="")
        assert ctx.application_name == ""


class TestRunnerContextEdgeCases:
    """Additional edge case tests for RunnerContext."""

    def test_runner_context_with_lambda(self):
        """Test RunnerContext with lambda as execution_object."""
        ctx = RunnerContext(execution_object=lambda x: x * 2)
        assert callable(ctx.execution_object)

    def test_runner_context_with_builtin_function(self):
        """Test RunnerContext with builtin function as execution_object."""
        ctx = RunnerContext(execution_object=len)
        assert ctx.execution_object is len

    def test_runner_context_warmup_zero(self):
        """Test RunnerContext with warmup=0 and autoscale=True."""
        ctx = RunnerContext(execution_object=lambda x: x, autoscale=True, warmup=0)
        assert ctx.min_instances == 0
        assert ctx.max_instances is None

    def test_runner_context_warmup_zero_no_autoscale(self):
        """Test RunnerContext with warmup=0 and autoscale=False."""
        ctx = RunnerContext(execution_object=lambda x: x, autoscale=False, warmup=0)
        assert ctx.min_instances == 1
        assert ctx.max_instances == 1

    def test_runner_context_large_warmup(self):
        """Test RunnerContext with large warmup value."""
        ctx = RunnerContext(execution_object=lambda x: x, autoscale=True, warmup=1000)
        assert ctx.min_instances == 1000
        assert ctx.max_instances is None

    def test_runner_context_instance_with_state(self):
        """Test RunnerContext with stateful instance."""

        class StatefulService:
            def __init__(self):
                self.counter = 0

            def increment(self):
                self.counter += 1
                return self.counter

        instance = StatefulService()
        ctx = RunnerContext(execution_object=instance, stateful=True)
        assert ctx.stateful is True
        assert ctx.execution_object is instance


class TestRunnerRequestEdgeCases:
    """Additional edge case tests for RunnerRequest."""

    def test_runner_request_none_method_explicit(self):
        """Test RunnerRequest with method explicitly set to None."""
        req = RunnerRequest(method=None, args=(1, 2), kwargs={"a": 1})
        assert req.method is None
        assert req.args == (1, 2)
        assert req.kwargs == {"a": 1}

    def test_runner_request_nested_objectref_in_args(self):
        """Test RunnerRequest with complex nested structures in args."""
        nested_args = ({"nested": {"deep": [1, 2, 3]}}, [{"a": 1}, {"b": 2}])
        req = RunnerRequest(args=nested_args)
        assert req.args == nested_args

    def test_runner_request_large_args(self):
        """Test RunnerRequest with large number of args."""
        large_args = tuple(range(1000))
        req = RunnerRequest(args=large_args)
        assert len(req.args) == 1000

    def test_runner_request_callable_in_kwargs(self):
        """Test RunnerRequest with callable in kwargs."""
        req = RunnerRequest(kwargs={"callback": lambda x: x})
        assert callable(req.kwargs["callback"])

    def test_runner_request_bytes_in_args(self):
        """Test RunnerRequest with bytes in args."""
        req = RunnerRequest(args=(b"binary data", b"\x00\x01\x02"))
        assert req.args[0] == b"binary data"
        assert req.args[1] == b"\x00\x01\x02"
