import json
from datetime import datetime, timezone

from flamepy.core.types import (
    Application,
    ApplicationAttributes,
    ApplicationSchema,
    ApplicationState,
    Event,
    FlameContext,
    FlameError,
    FlameErrorCode,
    SessionAttributes,
    SessionState,
    Shim,
    Task,
    TaskState,
    short_name,
)


def test_enums_and_flame_error():
    # Enums should be int-like and have expected values
    assert int(SessionState.OPEN) == 0
    assert int(TaskState.PENDING) == 0
    assert int(ApplicationState.ENABLED) == 0
    assert int(Shim.HOST) == 0
    assert int(FlameErrorCode.INVALID_ARGUMENT) == 2

    # FlameError
    err = FlameError(FlameErrorCode.INVALID_ARGUMENT, "bad arg")
    assert err.code == FlameErrorCode.INVALID_ARGUMENT
    assert "bad arg" in str(err)


def test_dataclass_defaults_and_instantiation():
    t = Event(code=1)
    sa = SessionAttributes(application="app", slots=2)
    ap_schema = ApplicationSchema()
    ap_attrs = ApplicationAttributes()
    dt = datetime.now(timezone.utc)
    task = Task(id="tid", session_id="sid", state=TaskState.PENDING, creation_time=dt)
    app = Application(id="aid", name="n", state=ApplicationState.ENABLED, creation_time=dt)
    assert t.code == 1
    assert sa.application == "app" and sa.slots == 2
    assert ap_schema.input is None
    assert ap_attrs.image is None
    assert task.input is None
    assert app.name == "n"


def test_short_name_generation():
    s1 = short_name("foo", length=8)
    s2 = short_name("bar", length=8)
    assert s1.startswith("foo-")
    assert s2.startswith("bar-")
    assert len(s1) >= len("foo-") + 8
    assert len(s2) >= len("bar-") + 8


def test_flame_context_env_overrides(tmp_path, monkeypatch):
    # Build a fake flame.yaml in a temp home and override with env vars
    fake_home = tmp_path / ".home"
    fake_home.mkdir()
    # Monkeypatch Path.home() via env var in FlameContext by setting HOME to tmp
    monkeypatch.setenv("HOME", str(fake_home))

    flame_yaml = {
        "current-context": "flame",
        "contexts": [
            {
                "name": "flame",
                "cluster": {"endpoint": "http://localhost:8080"},
            }
        ],
    }
    conf_dir = fake_home / ".flame"
    conf_dir.mkdir()
    (conf_dir / "flame.yaml").write_text(json.dumps(flame_yaml))

    # No env override: endpoint should come from config
    ctx = FlameContext()
    assert ctx.endpoint == "http://localhost:8080"

    # Override with FLAME_ENDPOINT
    monkeypatch.setenv("FLAME_ENDPOINT", "http://override:1234")
    ctx2 = FlameContext()
    assert ctx2.endpoint == "http://override:1234"
