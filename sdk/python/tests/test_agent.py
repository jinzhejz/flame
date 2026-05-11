import cloudpickle
import pytest

import flamepy.agent.client as agent_client


class FakeSession:
    def __init__(self):
        self.application = "myapp"
        self.id = "sess-1"

    def invoke(self, input_bytes):
        return cloudpickle.dumps("OK")

    def common_data(self):
        return None

    def close(self):
        pass


def test_agent_init_and_invoke(monkeypatch):
    # Patch create_session to return fake session
    monkeypatch.setattr(agent_client, "create_session", lambda **kwargs: FakeSession())
    a = agent_client.Agent(name="myapp")
    # Patch the session to return a known value on invoke
    result = a.invoke("hello")
    assert result == "OK"


def test_cloudpickle_serialization_of_callable():
    def f(x):
        return x * 2

    s = cloudpickle.dumps(f)
    f2 = cloudpickle.loads(s)
    assert f2(3) == 6


class TestAgentInitialization:
    def test_agent_requires_name_or_session_id(self):
        with pytest.raises(ValueError, match="Either 'name' or 'session_id' must be provided"):
            agent_client.Agent()

    def test_agent_rejects_both_name_and_session_id(self):
        with pytest.raises(ValueError, match="Cannot provide both"):
            agent_client.Agent(name="myapp", session_id="sess-1")

    def test_agent_with_session_id_opens_existing(self, monkeypatch):
        fake_session = FakeSession()
        monkeypatch.setattr(agent_client, "open_session", lambda session_id: fake_session)
        agent = agent_client.Agent(session_id="sess-1")
        assert agent._name == "myapp"
        assert agent._session is fake_session

    def test_agent_with_name_creates_new_session(self, monkeypatch):
        monkeypatch.setattr(agent_client, "create_session", lambda **kwargs: FakeSession())
        agent = agent_client.Agent(name="myapp")
        assert agent._name == "myapp"
        assert agent._session is not None

    def test_agent_with_dict_resreq(self, monkeypatch):
        captured_kwargs = {}

        def capture_create_session(**kwargs):
            captured_kwargs.update(kwargs)
            return FakeSession()

        monkeypatch.setattr(agent_client, "create_session", capture_create_session)
        agent_client.Agent(name="myapp", resreq={"cpu": 4, "memory": "8g", "gpu": 1})
        assert captured_kwargs.get("resreq") is not None
        assert captured_kwargs["resreq"].cpu == 4
        assert captured_kwargs["resreq"].gpu == 1


class TestAgentOperations:
    def test_agent_id_returns_session_id(self, monkeypatch):
        monkeypatch.setattr(agent_client, "create_session", lambda **kwargs: FakeSession())
        agent = agent_client.Agent(name="myapp")
        assert agent.id() == "sess-1"

    def test_agent_id_returns_none_when_no_session(self, monkeypatch):
        monkeypatch.setattr(agent_client, "create_session", lambda **kwargs: FakeSession())
        agent = agent_client.Agent(name="myapp")
        agent._session = None
        assert agent.id() is None

    def test_agent_invoke_raises_when_no_session(self, monkeypatch):
        monkeypatch.setattr(agent_client, "create_session", lambda **kwargs: FakeSession())
        agent = agent_client.Agent(name="myapp")
        agent._session = None
        with pytest.raises(RuntimeError, match="not initialized"):
            agent.invoke("test")

    def test_agent_invoke_returns_none_for_none_output(self, monkeypatch):
        class NoneOutputSession(FakeSession):
            def invoke(self, input_bytes):
                return None

        monkeypatch.setattr(agent_client, "create_session", lambda **kwargs: NoneOutputSession())
        agent = agent_client.Agent(name="myapp")
        result = agent.invoke("test")
        assert result is None

    def test_agent_context_returns_none_when_no_session(self, monkeypatch):
        monkeypatch.setattr(agent_client, "create_session", lambda **kwargs: FakeSession())
        agent = agent_client.Agent(name="myapp")
        agent._session = None
        assert agent.context() is None

    def test_agent_context_returns_none_when_no_common_data(self, monkeypatch):
        monkeypatch.setattr(agent_client, "create_session", lambda **kwargs: FakeSession())
        agent = agent_client.Agent(name="myapp")
        assert agent.context() is None


class TestAgentContextManager:
    def test_agent_context_manager_enter(self, monkeypatch):
        monkeypatch.setattr(agent_client, "create_session", lambda **kwargs: FakeSession())
        agent = agent_client.Agent(name="myapp")
        result = agent.__enter__()
        assert result is agent

    def test_agent_context_manager_exit_closes_session(self, monkeypatch):
        closed = {"called": False}

        class TrackingSession(FakeSession):
            def close(self):
                closed["called"] = True

        monkeypatch.setattr(agent_client, "create_session", lambda **kwargs: TrackingSession())
        agent = agent_client.Agent(name="myapp")
        agent.__exit__(None, None, None)
        assert closed["called"]

    def test_agent_with_statement(self, monkeypatch):
        closed = {"called": False}

        class TrackingSession(FakeSession):
            def close(self):
                closed["called"] = True

        monkeypatch.setattr(agent_client, "create_session", lambda **kwargs: TrackingSession())
        with agent_client.Agent(name="myapp") as agent:
            assert agent._session is not None
        assert closed["called"]

    def test_agent_close_is_idempotent(self, monkeypatch):
        close_count = {"count": 0}

        class CountingSession(FakeSession):
            def close(self):
                close_count["count"] += 1

        monkeypatch.setattr(agent_client, "create_session", lambda **kwargs: CountingSession())
        agent = agent_client.Agent(name="myapp")
        agent.close()
        agent.close()
        assert close_count["count"] == 1
