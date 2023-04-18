"""
    Test that will set up authorino and prepares objects for performance testing.
    Fill necessary data to benchmark template.
    Run the test and assert results.
"""
from importlib import resources
import base64

import pytest
import yaml

from testsuite.hyperfoil import TagSafeLoader
from testsuite.openshift.httpbin import Httpbin
from testsuite.utils import add_port, create_csv_file

# Maximal runtime of test (need to cover all performance stages)
MAX_RUN_TIME = 10 * 60
# Number of distinct tokens used for queries
RHSSO_OPENED_SESSIONS = 10
# Number of pre-allocated connections
SHARED_CONNECTIONS = 100
# Backend replicas
BACKEND_REPLICAS = 1
# Number of hyperfoil agents used
AGENTS = 2
# Target throughput
THROUGHPUT = 10


pytestmark = [pytest.mark.performance]


@pytest.fixture(scope="module")
def name():
    """Name of the benchmark"""
    return "authorino_adv_throughput"


@pytest.fixture(scope="module")
def template():
    """Template path"""
    path = resources.files("testsuite.tests.kuadrant.authorino.performance.templates").joinpath(
        "template_perf_basic_query_rhsso.hf.yaml"
    )
    with path.open("r") as stream:
        return yaml.load(stream, Loader=TagSafeLoader)


@pytest.fixture(scope="module")
def http(rhsso, client):
    """Configures host for the gateway and RHSSO"""
    return {
        "http": [
            {"host": f'http://{add_port(str(client.base_url))}', "sharedConnections": SHARED_CONNECTIONS, "connectionStrategy": "SHARED_POOL"},
        ]
    }


@pytest.fixture(scope='module')
def rhsso_sessions_tokens(rhsso):
    return [rhsso.get_token(rhsso.test_username, rhsso.test_password) for _ in range(RHSSO_OPENED_SESSIONS)]


@pytest.fixture(scope="module")
def files(rhsso, client, rhsso_sessions_tokens):
    """Adds definitions of used queries as a CSV file"""
    client_url = add_port(str(client.base_url))

    a = [(client_url, x.access_token, f'/base64/{base64.encodebytes(f"asdf{i}".encode()).decode().strip()}') for x, i in zip(rhsso_sessions_tokens, range(len(rhsso_sessions_tokens)))]

    return {
        "queries.csv": create_csv_file(a),
    }


@pytest.fixture(scope="module")
def backend(request, openshift, blame, label):
    """Deploys Httpbin backend"""
    httpbin = Httpbin(openshift, blame("httpbin"), label, replicas=BACKEND_REPLICAS)

    request.addfinalizer(httpbin.delete)
    httpbin.commit()
    return httpbin


@pytest.fixture(scope="module")
def agents():
    """Agent configuration for benchmark"""
    return {"agents": [{f"agent-{i}": {"host": "localhost", "port": 22}}] for i in range(AGENTS)}


@pytest.fixture(scope="module")
def params():
    return {
        'RAMP_UP_DURATION': '1m',
        'RAMP_UP_MAX_DURATION': '3m',
        'RAMP_UP_INITIAL_PER_SEC': int(THROUGHPUT/10),
        'RAMP_UP_TARGET_PER_SEC': THROUGHPUT,
        'STEADY_LOAD_DURATION': '5m',
        'STEADY_LOAD_MAX_DURATION': '10m',
        'STEADY_LOAD_REQS_PER_SEC': THROUGHPUT
    }


def test_basic_perf_rhsso(generate_report, client, benchmark, rhsso_auth, blame, params):
    """
    Test checks that authorino is set up correctly.
    Runs the created benchmark.
    Asserts it was successful.
    """
    # assert client.get("/get", auth=rhsso_auth).status_code == 200

    run = benchmark.start(blame("run"), **params)

    obj = run.wait(MAX_RUN_TIME)
    assert obj["completed"], "Ran out of time"

    generate_report(run)
    stats = run.stats()

    assert stats
    info = stats.get("info", {})
    assert len(info.get("errors")) == 0, f"Errors occured: {info.get('errors')}"
    assert stats.get("failures") == []
    assert stats.get("stats", []) != []
