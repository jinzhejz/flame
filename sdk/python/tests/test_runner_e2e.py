"""Tests for the Runner end-user cluster verification command."""

import json
from types import SimpleNamespace

import pytest

from flamepy.runner import e2e as runner_e2e


class _FakeFuture:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value

    def wait(self):
        return None


def _resolve(value):
    if isinstance(value, _FakeFuture):
        return value.get()
    return value


class _FakeService:
    def __init__(self, execution_object):
        if isinstance(execution_object, type):
            self._target = execution_object()
        else:
            self._target = execution_object

    def __call__(self, *args, **kwargs):
        resolved_args = [_resolve(arg) for arg in args]
        resolved_kwargs = {key: _resolve(value) for key, value in kwargs.items()}
        return _FakeFuture(self._target(*resolved_args, **resolved_kwargs))

    def __getattr__(self, name):
        attr = getattr(self._target, name)

        def method(*args, **kwargs):
            resolved_args = [_resolve(arg) for arg in args]
            resolved_kwargs = {key: _resolve(value) for key, value in kwargs.items()}
            return _FakeFuture(attr(*resolved_args, **resolved_kwargs))

        return method


class _FakeRunner:
    instances = []

    def __init__(self, name, dependencies=None, python_version=None):
        self.name = name
        self.dependencies = dependencies
        self.python_version = python_version
        self.services = []
        type(self).instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return None

    def service(self, execution_object, **kwargs):
        service = _FakeService(execution_object)
        self.services.append((execution_object, kwargs))
        return service

    def get(self, futures):
        return [future.get() for future in futures]


@pytest.fixture
def fake_cluster(monkeypatch):
    _FakeRunner.instances = []
    monkeypatch.setattr(runner_e2e.flamepy, "FlameContext", lambda: SimpleNamespace(runner=SimpleNamespace(template="flmrun")))
    monkeypatch.setattr(runner_e2e.flamepy, "get_application", lambda name: SimpleNamespace(name=name))
    monkeypatch.setattr(runner_e2e, "Runner", _FakeRunner)
    return _FakeRunner


def test_run_runner_e2e_returns_expected_result(fake_cluster, tmp_path):
    result = runner_e2e.run_runner_e2e(
        name="runner-smoke",
        tasks=3,
        python_version="3.12",
        dependencies=["requests"],
        workdir=tmp_path,
    )

    assert result.app_name == "runner-smoke"
    assert result.template == "flmrun"
    assert result.workdir == str(tmp_path)
    assert result.function_results == [0, 1, 4]
    assert result.chained_result == 25
    assert result.stateful_result == 6

    assert len(fake_cluster.instances) == 1
    assert fake_cluster.instances[0].dependencies == ["requests"]
    assert fake_cluster.instances[0].python_version == "3.12"


def test_run_runner_e2e_defaults_template_when_runner_config_missing(monkeypatch, tmp_path):
    _FakeRunner.instances = []
    seen = {}

    def get_application(name):
        seen["name"] = name
        return SimpleNamespace(name=name)

    monkeypatch.setattr(runner_e2e.flamepy, "FlameContext", lambda: SimpleNamespace(runner=None))
    monkeypatch.setattr(runner_e2e.flamepy, "get_application", get_application)
    monkeypatch.setattr(runner_e2e, "Runner", _FakeRunner)

    result = runner_e2e.run_runner_e2e(name="runner-default-template", tasks=1, workdir=tmp_path)

    assert seen["name"] == "flmrun"
    assert result.template == "flmrun"


def test_run_runner_e2e_preserves_existing_readme(fake_cluster, tmp_path):
    readme_path = tmp_path / "README.md"
    readme_path.write_text("user docs\n", encoding="utf-8")

    runner_e2e.run_runner_e2e(name="runner-readme", tasks=1, workdir=tmp_path)

    assert readme_path.read_text(encoding="utf-8") == "user docs\n"


def test_main_outputs_json(fake_cluster, capsys, tmp_path):
    exit_code = runner_e2e.main(["--name", "runner-json", "--tasks", "2", "--workdir", str(tmp_path), "--json"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["app_name"] == "runner-json"
    assert output["function_results"] == [0, 1]
    assert output["chained_result"] == 13
    assert output["stateful_result"] == 6


def test_main_reports_template_error(monkeypatch, capsys):
    monkeypatch.setattr(runner_e2e.flamepy, "FlameContext", lambda: SimpleNamespace(runner=SimpleNamespace(template="missing-template")))
    monkeypatch.setattr(runner_e2e.flamepy, "get_application", lambda name: None)

    exit_code = runner_e2e.main(["--name", "runner-fail"])

    assert exit_code == 1
    assert "missing-template" in capsys.readouterr().err


def test_parser_rejects_zero_tasks():
    with pytest.raises(SystemExit):
        runner_e2e.build_parser().parse_args(["--tasks", "0"])
