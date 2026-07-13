import sys
import types

import deepresearch_agent.neo4j_backend as nb


def test_from_env_defaults_password_devpassword(monkeypatch):
    captured = {}

    class _FakeDriver:
        def verify_connectivity(self): pass

    class _FakeGraphDatabase:
        @staticmethod
        def driver(uri, auth):
            captured["uri"] = uri
            captured["auth"] = auth
            return _FakeDriver()

    fake_neo4j = types.ModuleType("neo4j")
    fake_neo4j.GraphDatabase = _FakeGraphDatabase
    monkeypatch.setitem(sys.modules, "neo4j", fake_neo4j)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

    nb.Neo4jBackend.from_env()
    assert captured["auth"] == ("neo4j", "devpassword")
