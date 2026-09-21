"""Goal payloads, allocation safety, and actual registered tool authorization."""

import importlib.util
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from graphql import OperationType
from mcp.server.fastmcp import FastMCP

from monarch_mcp_server import security
from monarch_mcp_server.tools import goals

WRITE_CASES = [
    (
        "set_savings_goal_initial_contributions",
        {
            "account_id": "acc",
            "contributions_json": '[{"goalId":"g1","contributionAmount":25}]',
        },
        "createGoalAccountInitialContributions",
        {
            "accountId": "acc",
            "contributedGoals": [{"goalId": "g1", "contributionAmount": 25}],
        },
    ),
    (
        "update_savings_goal",
        {"goal_id": "g1", "name": "Trip"},
        "updateSavingsGoal",
        {"id": "g1", "name": "Trip"},
    ),
    (
        "set_savings_goal_budget_amount",
        {
            "savings_goal_id": "g1",
            "month": "2026-09-01",
            "amount": 25,
            "account_id": "acc",
        },
        "setSavingsGoalBudgetAmount",
        {
            "savingsGoalId": "g1",
            "month": "2026-09-01",
            "amount": 25,
            "applyToFuture": True,
            "accountId": "acc",
        },
    ),
    (
        "set_debt_paydown_budget_amount",
        {"account_id": "acc", "month": "2026-09-01", "amount": 25},
        "setDebtPaydownBudgetAmount",
        {
            "accountId": "acc",
            "month": "2026-09-01",
            "amount": 25,
            "applyToFuture": False,
        },
    ),
    (
        "create_goals_v2",
        {"goals_json": '[{"name":"Trip","targetAmount":100}]'},
        "createGoals",
        {"goals": [{"name": "Trip", "targetAmount": 100}]},
    ),
    (
        "associate_goal_account",
        {"goal_id": "g1", "account_id": "acc", "amount": 25},
        "createGoalAccountAllocation",
        {
            "goalId": "g1",
            "accountId": "acc",
            "amount": 25,
            "useEntireAccountBalance": False,
        },
    ),
    (
        "update_goal_account_amount",
        {"goal_id": "g1", "account_id": "acc", "amount": 25},
        "updateGoalAccountAllocation",
        {
            "goalId": "g1",
            "accountId": "acc",
            "amount": 25,
            "useEntireAccountBalance": False,
        },
    ),
    (
        "update_goal_v2",
        {"goal_id": "g1", "name": "Trip", "target_amount": 100},
        "updateGoalV2",
        {"id": "g1", "name": "Trip", "targetAmount": 100},
    ),
    ("unarchive_goal_v2", {"goal_id": "g1"}, "unarchiveGoal", {"id": "g1"}),
]
WRITE_NAMES = {case[0] for case in WRITE_CASES} | {"sync_savings_goal_allocations"}


@pytest.fixture
def client(monkeypatch):
    client = AsyncMock()
    monkeypatch.setattr(goals, "get_monarch_client", AsyncMock(return_value=client))
    return client


@pytest.mark.parametrize("name,kwargs,field,expected", WRITE_CASES)
async def test_write_payloads(client, name, kwargs, field, expected):
    client.gql_call.return_value = {field: {"success": True}}
    result = json.loads(await getattr(goals, name)(**kwargs))
    assert result == {field: {"success": True}}
    call = client.gql_call.call_args
    operation = getattr(call.args[1], "document", call.args[1]).definitions[0]
    assert operation.operation == OperationType.MUTATION
    assert operation.selection_set.selections[0].name.value == field
    assert operation.name.value == call.args[0]
    assert call.kwargs["variables"] == {"input": expected}


@pytest.mark.parametrize(
    "name,field",
    [
        ("list_goals_v2", "goalsV2"),
        ("list_savings_goals", "savingsGoals"),
        ("list_goal_options", "goalOptions"),
        ("inspect_goal_input_types", "__type"),
        ("inspect_savings_goal_allocation_input_types", "__type"),
    ],
)
async def test_read_queries(client, name, field):
    client.gql_call.return_value = {field: []}
    assert json.loads(await getattr(goals, name)()) == {field: []}
    call = client.gql_call.call_args
    operation = getattr(call.args[1], "document", call.args[1]).definitions[0]
    assert operation.operation == OperationType.QUERY
    assert operation.name.value == call.args[0]
    assert field in {s.name.value for s in operation.selection_set.selections}


@pytest.fixture
def state():
    def goal(id, name, amount):
        return {
            "id": id,
            "name": name,
            "archivedAt": None,
            "allocationAmountsByAccount": [
                {"totalAmount": amount, "account": {"id": "acc"}}
            ],
        }

    return {
        "accounts": [{"id": "acc", "displayName": "Savings", "displayBalance": 100}],
        "savingsGoals": [goal("g1", "Trip", 20), goal("g2", "Reserve", 30)],
    }


async def test_preview_keeps_omitted_allocations(client, state):
    client.gql_call.return_value = state
    result = json.loads(
        await goals.preview_savings_goal_allocations("acc", '{"Trip": 40}')
    )
    assert result["retained_total"] == 30
    assert result["allocated_total"] == 70
    assert result["unallocated_balance"] == 30
    assert result["changes"][0]["change"] == 20
    assert result["applied"] is False
    client.gql_call.assert_awaited_once()
    assert (
        getattr(
            client.gql_call.call_args.args[1],
            "document",
            client.gql_call.call_args.args[1],
        )
        .definitions[0]
        .operation
        == OperationType.QUERY
    )


async def test_overallocation_includes_omitted_goals(client, state):
    client.gql_call.return_value = state
    with pytest.raises(ValueError, match="exceed"):
        await goals.sync_savings_goal_allocations("acc", '{"Trip": 80}', dry_run=False)
    client.gql_call.assert_awaited_once()


async def test_duplicate_names_are_not_silently_selected(client, state):
    state["savingsGoals"].append({**deepcopy(state["savingsGoals"][0]), "id": "g3"})
    client.gql_call.return_value = state
    with pytest.raises(ValueError, match="ambiguous"):
        await goals.preview_savings_goal_allocations("acc", '{"Trip": 10}')


@pytest.mark.parametrize(
    "payload",
    [
        '{"Trip":NaN}',
        '{"Trip":Infinity}',
        '{"Trip":-1}',
        '{"Trip":true}',
        '{"Trip":"20"}',
        '{"Trip":10,"Trip":20}',
        "{}",
        "[]",
    ],
)
async def test_invalid_allocations_never_reach_api(client, payload):
    with pytest.raises(ValueError):
        await goals.sync_savings_goal_allocations("acc", payload, dry_run=False)
    client.gql_call.assert_not_awaited()


@pytest.mark.parametrize("amount,expected", [(0, None), (40, 40)])
async def test_sync_override_payload(client, state, amount, expected):
    client.gql_call.side_effect = [
        state,
        {"createGoalAccountInitialContributions": {"errors": []}},
    ]
    result = json.loads(
        await goals.sync_savings_goal_allocations(
            "acc", json.dumps({"Trip": amount}), dry_run=False
        )
    )
    assert result["applied"] is True
    assert client.gql_call.call_args.kwargs["variables"] == {
        "input": {
            "accountId": "acc",
            "contributedGoals": [
                {
                    "goalId": "g1",
                    "contributionAmount": expected,
                    "overrideInitialContribution": True,
                    "useEntireBalance": False,
                }
            ],
        }
    }


async def test_sync_noop_does_not_mutate(client, state):
    client.gql_call.return_value = state
    result = json.loads(
        await goals.sync_savings_goal_allocations("acc", '{"Trip":20}', dry_run=False)
    )
    assert result["applied"] is False
    client.gql_call.assert_awaited_once()


async def test_sync_reports_upstream_failure(client, state):
    client.gql_call.side_effect = [
        state,
        {
            "createGoalAccountInitialContributions": {
                "errors": [{"message": "Rejected"}]
            }
        },
    ]
    result = json.loads(
        await goals.sync_savings_goal_allocations("acc", '{"Trip":40}', dry_run=False)
    )
    assert result["applied"] is False
    assert result["result"]["createGoalAccountInitialContributions"]["errors"]


@pytest.mark.parametrize(
    "kwargs", [{"amount": float("nan")}, {"amount": -1}, {"month": "2026-09-12"}]
)
async def test_invalid_budget_input(client, kwargs):
    params = {"savings_goal_id": "g1", "month": "2026-09-01", "amount": 25, **kwargs}
    with pytest.raises(ValueError):
        await goals.set_savings_goal_budget_amount(**params)
    client.gql_call.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        "[]",
        "{}",
        '[{"goalId":"g1","contributionAmount":NaN}]',
        '[{"goalId":"g1","contributionAmount":null}]',
        '[{"goalId":"g1","contributionAmount":5,"useEntireBalance":"false"}]',
    ],
)
async def test_invalid_initial_contributions(client, payload):
    with pytest.raises(ValueError):
        await goals.set_savings_goal_initial_contributions("acc", payload)
    client.gql_call.assert_not_awaited()


def load_registered(monkeypatch, read_only):
    server = FastMCP("goal-test")
    monkeypatch.setattr(security, "_mcp", lambda: server)
    monkeypatch.setattr(
        security,
        "config",
        SimpleNamespace(
            read_only=read_only,
            oauth=SimpleNamespace(enabled=True, write_scope="monarch:write"),
        ),
    )
    spec = importlib.util.spec_from_file_location("isolated_goal_tools", goals.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return server, module


def test_actual_registration_in_read_only_mode(monkeypatch):
    server, _ = load_registered(monkeypatch, True)
    tools = {t.name: t for t in server._tool_manager.list_tools()}
    assert not WRITE_NAMES & tools.keys()
    assert "preview_savings_goal_allocations" in tools
    assert "list_savings_goals" in tools
    assert all(t.annotations.readOnlyHint for t in tools.values())
    assert "probe_budget_contribution_mutations" not in tools


@pytest.mark.parametrize("scopes", [None, ["monarch:read"]])
async def test_every_registered_write_requires_scope(monkeypatch, scopes):
    server, module = load_registered(monkeypatch, False)
    token = None if scopes is None else SimpleNamespace(scopes=scopes)
    monkeypatch.setattr(security, "get_access_token", lambda: token)
    client = AsyncMock()
    module.get_monarch_client = AsyncMock(return_value=client)
    tools = {t.name: t for t in server._tool_manager.list_tools()}
    assert WRITE_NAMES <= tools.keys()
    for name in WRITE_NAMES:
        assert tools[name].annotations.readOnlyHint is False
        with pytest.raises(security.WriteScopeRequired):
            await getattr(module, name)()
    module.get_monarch_client.assert_not_awaited()


async def test_registered_write_accepts_write_scope(monkeypatch):
    _, module = load_registered(monkeypatch, False)
    monkeypatch.setattr(
        security,
        "get_access_token",
        lambda: SimpleNamespace(scopes=["monarch:read", "monarch:write"]),
    )
    client = AsyncMock()
    client.gql_call.return_value = {"updateSavingsGoal": {"errors": []}}
    module.get_monarch_client = AsyncMock(return_value=client)
    await module.update_savings_goal("g1", "Trip")
    client.gql_call.assert_awaited_once()
