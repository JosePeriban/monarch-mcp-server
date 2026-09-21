"""Savings Goals, legacy Goal V2, and contribution budget tools.

Ported from the local goal helper. All mutations use the shared write gate;
read tools work with either stdio or authenticated Streamable HTTP.
"""

import json
import math
from collections import Counter
from datetime import date

from gql import gql
from mcp.types import ToolAnnotations

from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.security import read_tool, write_tool

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True)


def _amount(value: float, label: str = "amount") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite non-negative number")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{label} must be a finite non-negative number")
    return round(value, 2)


def _month(value: str) -> str:
    parsed = date.fromisoformat(value)
    if parsed.day != 1 or parsed.isoformat() != value:
        raise ValueError("month must be YYYY-MM-01")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


@read_tool(annotations=READ)
async def list_accounts_compact() -> str:
    """List live Monarch accounts with IDs, balances, and types."""
    client = await get_monarch_client()
    data = await client.get_accounts()
    accounts = data.get("accounts", data) if isinstance(data, dict) else data
    rows = []
    for account in accounts or []:
        rows.append(
            {
                "id": account.get("id"),
                "name": account.get("displayName") or account.get("name"),
                "balance": (
                    account.get("currentBalance")
                    if account.get("currentBalance") is not None
                    else account.get("balance")
                ),
                "type": (
                    (account.get("type") or {}).get("name")
                    if isinstance(account.get("type"), dict)
                    else account.get("type")
                ),
                "subtype": (
                    (account.get("subtype") or {}).get("name")
                    if isinstance(account.get("subtype"), dict)
                    else account.get("subtype")
                ),
            }
        )
    return json.dumps(rows, indent=2)


def _type_name(node):
    parts = []
    while node:
        parts.append(node.get("name") or node.get("kind") or "")
        node = node.get("ofType")
    return " > ".join(part for part in parts if part)


@read_tool(annotations=READ)
async def discover_goal_graphql() -> str:
    """Return GraphQL query and mutation fields whose name contains goal."""
    client = await get_monarch_client()
    query = gql(
        """
        query GoalSchemaIntrospection {
          __schema {
            queryType {
              fields {
                name
                args { name type { kind name ofType { kind name ofType { kind name ofType { kind name } } } } }
                type { kind name ofType { kind name ofType { kind name ofType { kind name } } } }
              }
            }
            mutationType {
              fields {
                name
                args { name type { kind name ofType { kind name ofType { kind name ofType { kind name } } } } }
                type { kind name ofType { kind name ofType { kind name ofType { kind name } } } }
              }
            }
          }
        }
        """
    )
    result = await client.gql_call("GoalSchemaIntrospection", query)
    schema = result["__schema"]
    output = {}
    for root in ("queryType", "mutationType"):
        rows = []
        for field in schema[root]["fields"]:
            if "goal" not in field["name"].lower():
                continue
            rows.append(
                {
                    "name": field["name"],
                    "return_type": _type_name(field["type"]),
                    "args": [
                        {"name": arg["name"], "type": _type_name(arg["type"])}
                        for arg in field["args"]
                    ],
                }
            )
        output[root] = rows
    return json.dumps(output, indent=2)


@read_tool(annotations=READ)
async def list_goal_options() -> str:
    """List the legacy Goal V2 templates accepted by createGoalV2."""
    client = await get_monarch_client()
    query = gql(
        """
        query GoalOptions {
          goalOptions {
            defaultName
            objective
            type
            allowMultiSelect
            defaultImageStorageProvider
            defaultImageStorageProviderId
          }
        }
        """
    )
    result = await client.gql_call("GoalOptions", query)
    return json.dumps(result, indent=2)


@read_tool(annotations=READ)
async def inspect_goal_input_types() -> str:
    """Inspect the fields accepted by Monarch goal create/update inputs."""
    client = await get_monarch_client()
    query = gql(
        """
        query FinanceCommandCenterGoalInputTypes {
          create: __type(name: "CreateGoalInput") {
            name
            inputFields { name type { kind name ofType { kind name ofType { kind name } } } }
          }
          update: __type(name: "UpdateGoalInput") {
            name
            inputFields { name type { kind name ofType { kind name ofType { kind name } } } }
          }
        }
        """
    )
    result = await client.gql_call("FinanceCommandCenterGoalInputTypes", query)
    return json.dumps(result, indent=2)


@read_tool(annotations=READ)
async def inspect_savings_goal_allocation_input_types() -> str:
    """Inspect current Savings Goal account-allocation mutation input fields."""
    client = await get_monarch_client()
    query = gql(
        """
        query FinanceCommandCenterSavingsGoalAllocationInputTypes {
          initial: __type(name: "GoalAccountInitialContributionInput") {
            name
            inputFields { name type { kind name ofType { kind name ofType { kind name } } } }
          }
          contribution: __type(name: "ContributedGoalInput") {
            name
            inputFields { name type { kind name ofType { kind name ofType { kind name } } } }
          }
        }
        """
    )
    result = await client.gql_call(
        "FinanceCommandCenterSavingsGoalAllocationInputTypes", query
    )
    return json.dumps(result, indent=2)


@read_tool(annotations=READ)
async def list_goals_v2() -> str:
    """List active legacy Goal V2 records and their key tracking fields."""
    client = await get_monarch_client()
    query = gql(
        """
        query FinanceCommandCenterGoalsV2 {
          goalsV2 {
            id
            name
            objective
            type
            targetAmount
            startingAmount
            currentAmount
            plannedMonthlyContribution
            archivedAt
            accountAllocations {
              id
              amount
              currentAmount
              useEntireAccountBalance
              account { id displayName currentBalance }
            }
          }
        }
        """
    )
    result = await client.gql_call("FinanceCommandCenterGoalsV2", query)
    return json.dumps(result, indent=2)


@read_tool(annotations=READ)
async def list_savings_goals() -> str:
    """List the current Savings Goals model and legacy-to-new migration mapping."""
    client = await get_monarch_client()
    query = gql(
        """
        query FinanceCommandCenterSavingsGoals {
          migratedToSavingsGoals
          currentTotalBalanceForGoals
          goalsBalanceThisMonth
          savingsGoals {
            id
            type
            name
            archivedAt
            status
            progress
            currentBalance
            targetAmount
            targetDate
            plannedMonthlyContribution
            currentMonthActualBudgetAmount
            currentMonthPlannedContributionAmount
            spendingTotal
            netContribution
            balanceThisMonth
            isSinkingFund
            priority
            allocationAmountsByAccount {
              goalId
              adjustmentAmount
              totalAmount
              spendingAmount
              contributionsAmount
              withdrawalsAmount
              account { id displayName displayBalance }
            }
          }
          goalsV2 { id name newGoalId archivedAt currentAmount }
        }
        """
    )
    result = await client.gql_call("FinanceCommandCenterSavingsGoals", query)
    return json.dumps(result, indent=2)


@write_tool(annotations=WRITE)
async def set_savings_goal_initial_contributions(
    account_id: str, contributions_json: str
) -> str:
    """Set or override initial contributions for current Savings Goals on one account."""
    contributions = json.loads(contributions_json, object_pairs_hook=_unique_object)
    if not isinstance(contributions, list) or not contributions:
        raise ValueError("contributions_json must be a non-empty JSON array")
    ids = set()
    allowed = {
        "goalId",
        "contributionAmount",
        "overrideInitialContribution",
        "useEntireBalance",
    }
    for row in contributions:
        if not isinstance(row, dict) or set(row) - allowed:
            raise ValueError("invalid contribution fields")
        goal_id = row.get("goalId")
        if not isinstance(goal_id, str) or not goal_id.strip() or goal_id in ids:
            raise ValueError("contributions require unique non-empty goalId values")
        ids.add(goal_id)
        for key in ("overrideInitialContribution", "useEntireBalance"):
            if key in row and not isinstance(row[key], bool):
                raise ValueError(f"{key} must be boolean")
        if "contributionAmount" not in row:
            raise ValueError("contributionAmount is required")
        if row["contributionAmount"] is None:
            if (
                row.get("overrideInitialContribution") is not True
                or row.get("useEntireBalance") is not False
            ):
                raise ValueError(
                    "null amounts require overrideInitialContribution=true and useEntireBalance=false"
                )
        else:
            row["contributionAmount"] = _amount(row["contributionAmount"])
    client = await get_monarch_client()
    mutation = gql(
        """
        mutation FinanceCommandCenterSetSavingsGoalBalances($input: GoalAccountInitialContributionInput!) {
          createGoalAccountInitialContributions(input: $input) {
            userNotice
            goalAccountForInitialContribution {
              account { id displayName }
              contributedGoals {
                accountId
                amount
                goal { id name currentBalance netContribution spendingTotal }
              }
            }
            errors { message }
          }
        }
        """
    )
    result = await client.gql_call(
        "FinanceCommandCenterSetSavingsGoalBalances",
        mutation,
        variables={
            "input": {"accountId": account_id, "contributedGoals": contributions}
        },
    )
    return json.dumps(result, indent=2)


@read_tool(annotations=READ)
async def preview_savings_goal_allocations(
    account_id: str, allocations_json: str
) -> str:
    """Preview named Savings Goal allocations without writing, including retained allocations."""
    return await _sync_savings_goal_allocations(
        account_id, allocations_json, dry_run=True
    )


@write_tool(annotations=WRITE)
async def sync_savings_goal_allocations(
    account_id: str, allocations_json: str, dry_run: bool = True
) -> str:
    """Preview or apply allocations for exact active goal names; omitted goals stay unchanged.

    allocations_json maps unique goal names to non-negative monetary amounts.
    Defaults to preview. Set dry_run=false to apply; zero removes an allocation.
    Requires writes enabled and the OAuth write scope, even for preview. Use
    preview_savings_goal_allocations for a read-only preview instead.
    """
    return await _sync_savings_goal_allocations(account_id, allocations_json, dry_run)


async def _sync_savings_goal_allocations(
    account_id: str,
    allocations_json: str,
    dry_run: bool = True,
) -> str:
    """Preview or replace one account's Savings Goal allocations by goal name.

    allocations_json must be a JSON object mapping exact active Savings Goal
    names to non-negative dollar amounts. A dry run validates names, totals,
    and the live account balance without mutating Monarch.
    """
    requested = json.loads(allocations_json, object_pairs_hook=_unique_object)
    if not isinstance(requested, dict) or not requested:
        raise ValueError("allocations_json must be a non-empty JSON object")
    normalized = {}
    for name, amount in requested.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("every goal name must be a non-empty string")
        normalized[name] = _amount(amount, f"allocation for {name}")

    client = await get_monarch_client()
    query = gql(
        """
        query FinanceCommandCenterSavingsGoalAllocationState {
          savingsGoals {
            id name archivedAt currentBalance
            allocationAmountsByAccount {
              totalAmount
              account { id displayName displayBalance }
            }
          }
          accounts { id displayName displayBalance }
        }
        """
    )
    state = await client.gql_call(
        "FinanceCommandCenterSavingsGoalAllocationState", query
    )
    active_goals = [
        g for g in state.get("savingsGoals", []) if g.get("archivedAt") is None
    ]
    name_counts = Counter(g["name"] for g in active_goals)
    ambiguous = sorted(name for name in normalized if name_counts[name] > 1)
    if ambiguous:
        raise ValueError(f"ambiguous Savings Goal names: {ambiguous}")
    goals_by_name = {goal["name"]: goal for goal in active_goals}
    missing = sorted(set(normalized) - set(goals_by_name))
    if missing:
        raise ValueError(f"active Savings Goals not found: {missing}")
    account = next(
        (row for row in state.get("accounts", []) if row.get("id") == account_id),
        None,
    )
    if account is None:
        raise ValueError(f"account not found: {account_id}")
    account_balance = _amount(account.get("displayBalance"), "account balance")
    requested_total = round(sum(normalized.values()), 2)
    # Omitted goals are not changed by this mutation. Include their allocations
    # (including archived goals) when checking the available account balance.
    selected_ids = {goals_by_name[name]["id"] for name in normalized}
    retained_total = 0.0
    for goal in state.get("savingsGoals", []):
        if goal["id"] not in selected_ids:
            for allocation in goal.get("allocationAmountsByAccount") or []:
                if (allocation.get("account") or {}).get("id") == account_id:
                    retained_total += _amount(
                        allocation.get("totalAmount"), "retained allocation"
                    )
    retained_total = round(retained_total, 2)
    allocated_total = round(requested_total + retained_total, 2)
    if allocated_total > account_balance:
        raise ValueError(
            f"requested plus retained allocations ${allocated_total:.2f} exceed "
            f"account balance ${account_balance:.2f}"
        )

    preview = []
    contributions = []
    for name, amount in normalized.items():
        goal = goals_by_name[name]
        before = 0.0
        for allocation in goal.get("allocationAmountsByAccount") or []:
            if (allocation.get("account") or {}).get("id") == account_id:
                before = _amount(allocation.get("totalAmount"), "existing allocation")
                break
        preview.append(
            {
                "goal_id": goal["id"],
                "name": name,
                "before": before,
                "after": amount,
                "change": round(amount - before, 2),
            }
        )
        if amount == before:
            continue
        if amount == 0:
            # Monarch's current web app removes an existing allocation by
            # nullifying the initial contribution and forcing an override.
            contributions.append(
                {
                    "goalId": goal["id"],
                    "contributionAmount": None,
                    "overrideInitialContribution": True,
                    "useEntireBalance": False,
                }
            )
        else:
            # Explicitly override the account's initial contribution. Without
            # this flag Monarch accepts the mutation but preserves an existing
            # migrated allocation instead of changing it.
            contributions.append(
                {
                    "goalId": goal["id"],
                    "contributionAmount": amount,
                    "overrideInitialContribution": True,
                    "useEntireBalance": False,
                }
            )

    response = {
        "dry_run": dry_run,
        "account": {
            "id": account_id,
            "name": account.get("displayName"),
            "balance": account_balance,
        },
        "requested_total": requested_total,
        "retained_total": retained_total,
        "allocated_total": allocated_total,
        "unallocated_balance": round(account_balance - allocated_total, 2),
        "changes": preview,
    }
    if dry_run or not contributions:
        response["applied"] = False
        return json.dumps(response, indent=2)

    mutation = gql(
        """
        mutation FinanceCommandCenterSyncSavingsGoalBalances($input: GoalAccountInitialContributionInput!) {
          createGoalAccountInitialContributions(input: $input) {
            userNotice
            goalAccountForInitialContribution {
              account { id displayName displayBalance }
              contributedGoals {
                accountId amount
                goal { id name currentBalance netContribution spendingTotal }
              }
            }
            errors { message }
          }
        }
        """
    )
    result = await client.gql_call(
        "FinanceCommandCenterSyncSavingsGoalBalances",
        mutation,
        variables={
            "input": {
                "accountId": account_id,
                "contributedGoals": contributions,
            }
        },
    )
    payload = result.get("createGoalAccountInitialContributions") or {}
    response["applied"] = bool(payload) and not bool(payload.get("errors"))
    response["result"] = result
    return json.dumps(response, indent=2)


@write_tool(annotations=WRITE)
async def update_savings_goal(goal_id: str, name: str) -> str:
    """Rename a current Savings Goal."""
    if not name.strip():
        raise ValueError("name must not be empty")
    client = await get_monarch_client()
    mutation = gql(
        """
        mutation FinanceCommandCenterUpdateSavingsGoal($input: UpdateSavingsGoalInput!) {
          updateSavingsGoal(input: $input) {
            savingsGoal { id name currentBalance }
            errors { code message }
          }
        }
        """
    )
    result = await client.gql_call(
        "FinanceCommandCenterUpdateSavingsGoal",
        mutation,
        variables={"input": {"id": goal_id, "name": name}},
    )
    return json.dumps(result, indent=2)


@read_tool(annotations=READ)
async def summarize_budget_month(start_date: str, end_date: str) -> str:
    """Return a compact named-category and goal budget summary for a month."""
    client = await get_monarch_client()
    data = await client.get_budgets(start_date=start_date, end_date=end_date)
    category_names = {}
    for group in data.get("categoryGroups", []):
        for category in group.get("categories", []):
            category_names[category["id"]] = category.get("name")
    rows = []
    budget_data = data.get("budgetData", {})
    for item in budget_data.get("monthlyAmountsByCategory", []):
        category_id = item.get("category", {}).get("id")
        for monthly in item.get("monthlyAmounts", []):
            planned = monthly.get("plannedCashFlowAmount") or 0
            actual = monthly.get("actualAmount") or 0
            remaining = monthly.get("remainingAmount") or 0
            rollover = monthly.get("previousMonthRolloverAmount") or 0
            if any(
                abs(value) > 0.005 for value in (planned, actual, remaining, rollover)
            ):
                rows.append(
                    {
                        "id": category_id,
                        "name": category_names.get(category_id, category_id),
                        "month": monthly.get("month"),
                        "planned": planned,
                        "actual": actual,
                        "remaining": remaining,
                        "rollover": rollover,
                        "rolloverType": monthly.get("rolloverType"),
                    }
                )
    extra = {
        key: data.get(key)
        for key in data.keys()
        if key not in {"budgetData", "categoryGroups", "goalsV2"}
        and isinstance(data.get(key), (str, int, float, bool, type(None)))
    }
    return json.dumps(
        {
            "topLevelKeys": list(data.keys()),
            "budgetDataKeys": list(budget_data.keys()),
            "categories": sorted(rows, key=lambda row: row["name"] or ""),
            "extra": extra,
        },
        indent=2,
    )


@read_tool(annotations=READ)
async def diagnose_budget_rollups(start_date: str, end_date: str) -> str:
    """Return Monarch fixed/flexible/non-monthly rollups and contributing categories."""
    client = await get_monarch_client()
    data = await client.get_budgets(start_date=start_date, end_date=end_date)
    category_meta = {}
    for group in data.get("categoryGroups", []):
        for category in group.get("categories", []):
            category_meta[category["id"]] = {
                "name": category.get("name"),
                "group": group.get("name"),
                "variability": category.get("budgetVariability")
                or group.get("budgetVariability"),
            }
    rows = []
    budget_data = data.get("budgetData", {})
    for item in budget_data.get("monthlyAmountsByCategory", []):
        category_id = item.get("category", {}).get("id")
        meta = category_meta.get(category_id, {})
        for monthly in item.get("monthlyAmounts", []):
            planned = monthly.get("plannedCashFlowAmount") or 0
            actual = monthly.get("actualAmount") or 0
            remaining = monthly.get("remainingAmount") or 0
            rollover = monthly.get("previousMonthRolloverAmount") or 0
            if any(
                abs(value) > 0.005 for value in (planned, actual, remaining, rollover)
            ):
                rows.append(
                    {
                        "month": monthly.get("month"),
                        "id": category_id,
                        **meta,
                        "planned": planned,
                        "actual": actual,
                        "remaining": remaining,
                        "rollover": rollover,
                    }
                )
    return json.dumps(
        {
            "budgetSystem": data.get("budgetSystem"),
            "totalsByMonth": budget_data.get("totalsByMonth", []),
            "flexRollups": budget_data.get("monthlyAmountsForFlexExpense", []),
            "categories": sorted(
                rows,
                key=lambda row: (row.get("variability") or "", row.get("name") or ""),
            ),
        },
        indent=2,
    )


@write_tool(annotations=WRITE)
async def set_savings_goal_budget_amount(
    savings_goal_id: str,
    month: str,
    amount: float,
    apply_to_future: bool = True,
    account_id: str | None = None,
) -> str:
    """Set a monthly Savings Goal contribution in Monarch's current budget model."""
    amount = _amount(amount)
    month = _month(month)
    client = await get_monarch_client()
    mutation = gql(
        """
        mutation FinanceCommandCenterSetSavingsGoalBudget($input: SetSavingsGoalBudgetAmountInput!) {
          setSavingsGoalBudgetAmount(input: $input) {
            success
            errors { code message }
          }
        }
        """
    )
    input_data = {
        "month": month,
        "savingsGoalId": savings_goal_id,
        "amount": amount,
        "applyToFuture": apply_to_future,
    }
    if account_id is not None:
        input_data["accountId"] = account_id
    result = await client.gql_call(
        "FinanceCommandCenterSetSavingsGoalBudget",
        mutation,
        variables={"input": input_data},
    )
    return json.dumps(result, indent=2)


@write_tool(annotations=WRITE)
async def set_debt_paydown_budget_amount(
    account_id: str,
    month: str,
    amount: float,
    apply_to_future: bool = False,
) -> str:
    """Set a monthly debt-account contribution in Monarch's current budget model."""
    amount = _amount(amount)
    month = _month(month)
    client = await get_monarch_client()
    mutation = gql(
        """
        mutation FinanceCommandCenterSetDebtPaydownBudget($input: SetDebtPaydownBudgetAmountInput!) {
          setDebtPaydownBudgetAmount(input: $input) {
            success
            errors { code message }
          }
        }
        """
    )
    result = await client.gql_call(
        "FinanceCommandCenterSetDebtPaydownBudget",
        mutation,
        variables={
            "input": {
                "month": month,
                "accountId": account_id,
                "amount": amount,
                "applyToFuture": apply_to_future,
            }
        },
    )
    return json.dumps(result, indent=2)


@read_tool(annotations=READ)
async def list_budget_contributions(start_month: str, end_month: str) -> str:
    """List current savings-goal and debt-paydown budget contributions."""
    client = await get_monarch_client()
    query = gql(
        """
        query FinanceCommandCenterBudgetContributions($startMonth: Date!, $endMonth: Date!) {
          savingsGoalMonthlyBudgetAmounts(startMonth: $startMonth, endMonth: $endMonth) {
            id
            savingsGoal { id name }
            monthlyAmounts {
              id month plannedAmount actualAmount remainingAmount
              totalPlannedAmount totalActualAmount totalRemainingAmount
              accountBreakdown {
                id plannedAmount actualAmount remainingAmount
                account { id displayName displayBalance }
              }
            }
          }
          debtPaydownMonthlyBudgetAmounts(startMonth: $startMonth, endMonth: $endMonth) {
            id
            account { id displayName displayBalance }
            monthlyAmounts { id month plannedAmount actualAmount remainingAmount }
          }
        }
        """
    )
    result = await client.gql_call(
        "FinanceCommandCenterBudgetContributions",
        query,
        variables={"startMonth": start_month, "endMonth": end_month},
    )
    compact = {}
    for key in ("savingsGoalMonthlyBudgetAmounts", "debtPaydownMonthlyBudgetAmounts"):
        compact[key] = []
        for item in result.get(key, []):
            months = []
            for monthly in item.get("monthlyAmounts", []):
                values = [
                    monthly.get(name) or 0
                    for name in (
                        "plannedAmount",
                        "actualAmount",
                        "remainingAmount",
                        "totalPlannedAmount",
                        "totalActualAmount",
                        "totalRemainingAmount",
                    )
                ]
                breakdown = monthly.get("accountBreakdown") or []
                if any(abs(value) > 0.005 for value in values) or breakdown:
                    months.append(monthly)
            if months:
                compact[key].append(
                    {
                        "id": item.get("id"),
                        "name": (
                            item.get("savingsGoal") or item.get("account") or {}
                        ).get("name")
                        or (item.get("account") or {}).get("displayName"),
                        "monthlyAmounts": months,
                    }
                )
    return json.dumps(compact, indent=2)


@write_tool(annotations=WRITE)
async def create_goals_v2(goals_json: str) -> str:
    """Create Goal V2 records from a JSON array of CreateGoalInput objects."""
    goals = json.loads(goals_json, object_pairs_hook=_unique_object)
    if not isinstance(goals, list) or not goals:
        raise ValueError("goals_json must be a non-empty JSON array")
    for goal in goals:
        if (
            not isinstance(goal, dict)
            or not isinstance(goal.get("name"), str)
            or not goal["name"].strip()
        ):
            raise ValueError("each goal must be an object with a non-empty name")
        for key in ("targetAmount", "startingAmount", "plannedMonthlyContribution"):
            if key in goal and goal[key] is not None:
                goal[key] = _amount(goal[key], key)
    client = await get_monarch_client()
    mutation = gql(
        """
        mutation FinanceCommandCenterCreateGoals($input: CreateGoalsInput!) {
          createGoals(input: $input) {
            goals {
              id
              name
              objective
              type
              targetAmount
              startingAmount
              currentAmount
              plannedMonthlyContribution
            }
            errors {
              code
              message
            }
          }
        }
        """
    )
    result = await client.gql_call(
        "FinanceCommandCenterCreateGoals",
        mutation,
        variables={"input": {"goals": goals}},
    )
    return json.dumps(result, indent=2)


@write_tool(annotations=WRITE)
async def associate_goal_account(
    goal_id: str, account_id: str, amount: float = 0.0
) -> str:
    """Associate one account with a Goal V2 without claiming the entire balance."""
    amount = _amount(amount)
    client = await get_monarch_client()
    mutation = gql(
        """
        mutation FinanceCommandCenterAssociateGoalAccount($input: CreateGoalAccountAllocationInput!) {
          createGoalAccountAllocation(input: $input) {
            goalAccountAllocation {
              id
              amount
              currentAmount
              useEntireAccountBalance
              account { id displayName }
            }
            goal { id name currentAmount }
            errors { code message }
          }
        }
        """
    )
    result = await client.gql_call(
        "FinanceCommandCenterAssociateGoalAccount",
        mutation,
        variables={
            "input": {
                "goalId": goal_id,
                "accountId": account_id,
                "amount": amount,
                "useEntireAccountBalance": False,
            }
        },
    )
    return json.dumps(result, indent=2)


@write_tool(annotations=WRITE)
async def update_goal_account_amount(
    goal_id: str, account_id: str, amount: float
) -> str:
    """Set the amount of an account allocated to a Goal V2."""
    amount = _amount(amount)
    client = await get_monarch_client()
    mutation = gql(
        """
        mutation FinanceCommandCenterUpdateGoalAccount($input: UpdateGoalAccountAllocationInput!) {
          updateGoalAccountAllocation(input: $input) {
            goalAccountAllocation { id amount currentAmount useEntireAccountBalance account { id displayName } }
            goal { id name currentAmount }
            errors { code message }
          }
        }
        """
    )
    result = await client.gql_call(
        "FinanceCommandCenterUpdateGoalAccount",
        mutation,
        variables={
            "input": {
                "goalId": goal_id,
                "accountId": account_id,
                "amount": amount,
                "useEntireAccountBalance": False,
            }
        },
    )
    return json.dumps(result, indent=2)


@write_tool(annotations=WRITE)
async def update_goal_v2(
    goal_id: str, name: str | None = None, target_amount: float | None = None
) -> str:
    """Update the name and optional target amount of a Goal V2."""
    values = {"id": goal_id}
    if name is not None:
        if not name.strip():
            raise ValueError("name must not be empty")
        values["name"] = name
    if target_amount is not None:
        values["targetAmount"] = _amount(target_amount)
    if len(values) == 1:
        raise ValueError("provide name or target_amount")
    client = await get_monarch_client()
    mutation = gql(
        """
        mutation FinanceCommandCenterUpdateGoal($input: UpdateGoalInput!) {
          updateGoalV2(input: $input) {
            goal { id name targetAmount currentAmount plannedMonthlyContribution }
            errors { code message }
          }
        }
        """
    )
    result = await client.gql_call(
        "FinanceCommandCenterUpdateGoal", mutation, variables={"input": values}
    )
    return json.dumps(result, indent=2)


@write_tool(annotations=WRITE)
async def unarchive_goal_v2(goal_id: str) -> str:
    """Restore an archived Goal V2 so it appears in the active goals UI."""
    client = await get_monarch_client()
    mutation = gql(
        """
        mutation FinanceCommandCenterUnarchiveGoal($input: UnarchiveGoalInput!) {
          unarchiveGoal(input: $input) {
            goal { id name archivedAt currentAmount }
            errors { code message }
          }
        }
        """
    )
    result = await client.gql_call(
        "FinanceCommandCenterUnarchiveGoal",
        mutation,
        variables={"input": {"id": goal_id}},
    )
    return json.dumps(result, indent=2)
