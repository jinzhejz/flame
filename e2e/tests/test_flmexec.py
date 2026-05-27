"""
Copyright 2025 The Flame Authors.
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
    http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import json
import textwrap

import flamepy
import pytest

NODEPS_RESULT_PREFIX = "FLMEXEC_RUNNER_NODEPS_RESULT="
NUMPY_RESULT_PREFIX = "FLMEXEC_RUNNER_NUMPY_RESULT="


@pytest.fixture(scope="module")
def check_flmexec_runner_environment():
    context = flamepy.FlameContext()
    package_config = getattr(context, "package", None)
    cache_config = getattr(context, "cache", None)
    has_package_storage = package_config is not None and getattr(package_config, "storage", None) is not None
    has_cache_endpoint = cache_config is not None
    if not has_package_storage and not has_cache_endpoint:
        pytest.skip("Runner package storage is not configured")

    try:
        if flamepy.get_application("flmexec") is None:
            pytest.skip("flmexec application is not registered")
        if flamepy.get_application("flmrun") is None:
            pytest.skip("flmrun application is not registered")
    except Exception as exc:
        pytest.skip(f"Flame cluster is not available: {exc}")


def _invoke_flmexec_python(script: str, runtime: str | None = None) -> str:
    session = flamepy.create_session("flmexec")
    try:
        request = {"language": "python", "runtime": runtime, "code": script, "input": None}
        raw_response = session.invoke(json.dumps(request).encode("utf-8"))
    finally:
        session.close()

    response = json.loads(raw_response.decode("utf-8"))
    return bytes(response["data"]).decode("utf-8")


@pytest.mark.timeout(600)
def test_flmexec_python_script_starts_runner_without_project_metadata(check_flmexec_runner_environment):
    script = textwrap.dedent(
        f"""
        import json
        import sys
        import traceback
        import uuid

        try:
            from flamepy.runner import Runner

            def test_fn(x):
                return x * x

            app_name = f"test-flmexec-runner-nodeps-{{uuid.uuid4().hex[:8]}}"

            with Runner(app_name) as rr:
                service = rr.service(test_fn)
                result = rr.get([service(10), service(20)])

            print("{NODEPS_RESULT_PREFIX}" + json.dumps(result))
        except BaseException:
            traceback.print_exc(file=sys.stdout)
            sys.stdout.flush()
            raise
        """
    )

    output = _invoke_flmexec_python(script)
    result_line = next((line for line in output.splitlines() if line.startswith(NODEPS_RESULT_PREFIX)), None)
    assert result_line is not None, f"missing result line in flmexec output:\n{output}"

    result = json.loads(result_line.removeprefix(NODEPS_RESULT_PREFIX))
    assert result == [100, 400]


@pytest.mark.timeout(600)
def test_flmexec_python_script_starts_runner_with_numpy_dependency(check_flmexec_runner_environment):
    script = textwrap.dedent(
        f"""
        import json
        import sys
        import traceback
        import uuid

        try:
            from flamepy.runner import Runner

            def numpy_summary(limit):
                import numpy as np

                values = np.arange(1, limit + 1, dtype=np.int64)
                return {{
                    "dtype": str(values.dtype),
                    "shape": list(values.shape),
                    "sum": int(values.sum()),
                }}

            app_name = f"test-flmexec-runner-numpy-{{uuid.uuid4().hex[:8]}}"

            with Runner(app_name, dependencies=["numpy"]) as rr:
                service = rr.service(numpy_summary)
                result = service(5).get()

            print("{NUMPY_RESULT_PREFIX}" + json.dumps(result, sort_keys=True))
        except BaseException:
            traceback.print_exc(file=sys.stdout)
            sys.stdout.flush()
            raise
        """
    )

    output = _invoke_flmexec_python(script)
    result_line = next((line for line in output.splitlines() if line.startswith(NUMPY_RESULT_PREFIX)), None)
    assert result_line is not None, f"missing result line in flmexec output:\n{output}"

    result = json.loads(result_line.removeprefix(NUMPY_RESULT_PREFIX))
    assert result == {"dtype": "int64", "shape": [5], "sum": 15}
