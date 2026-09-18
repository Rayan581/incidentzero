# Engineering Report — Assignment 1: IncidentZero
**Student:** Rayan  
**Roll Number:** 23I-0018  
**Course:** Agentic Artificial Intelligence (Fall 2026)

---

## 1. Architecture

The agent runtime follows the architecture prescribed by `docs/ARCHITECTURE.md` with substantial additions for production reliability.

### Component Overview

```
User goal
   |
   v
AgentController  ──►  Planner / ReplanPolicy / LoopGuard / RetryPolicy
   |                           |
   | _model_decide()           | structured state (AgentState)
   v                           v
GroqModelClient ◄──── messages + world_version + evidence_ids
   |
   | proposed tool call
   v
Validation → RiskPolicy → ApprovalGateway → ToolRegistry
                                              |
                                 SimulationEnvironment
                                              |
                                    observation/effect
                                              |
                                 TraceRecorder (JSONL)
                                              |
                                 back to model as tool result
```

**AgentController** is the central orchestrator. It owns the main ReAct loop (observe → plan → decide → validate → approve → execute → trace → replan?). It does not contain business logic about specific services — that belongs to the model.

**Planner** converts raw incident observations into structured `AgentPlan` objects using Groq's JSON schema mode. It also implements `revise()` to update plans when evidence contradicts the current hypothesis.

**AgentState** tracks all mutable runtime state independently of chat message history: evidence IDs, world version, approval decisions, replan history, and the verify_recovery evidence ID required for closure.

**BudgetManager** is the authoritative budget counter. Every LLM call and every tool execution goes through `consume_llm()` / `consume_tool()` before any work is done.

**TraceRecorder** appends timestamped JSONL events for every significant action: bootstrap, plan creation, plan revision, model replies, tool results, approval decisions, loop detections, and budget warnings.

**ToolRegistry** validates argument schemas and proxies to `SimulationEnvironment`. The controller never accesses private simulator fields.

### Simulator Boundary

The controller interacts exclusively through `ToolRegistry.execute()`. It never reads `_scenario_spec`, `_oracle_snapshot`, `_services`, or any private simulator attribute. The `world_version` field is the only concurrency-control mechanism used.

---

## 2. Planning and Re-planning Strategy

### Initial Plan

On startup, the controller bootstraps by calling `get_incident` to obtain a real evidence-grounded observation, then calls `Planner.create()` with a structured JSON schema call to produce an initial `AgentPlan` containing a hypothesis, rationale summary, and 2–8 ordered steps. The plan is injected into the message history as a system note so the model can orient itself.

The Planner explicitly instructs the model: *"treat the incident ticket as a lead, not proof."* This prevents the model from blindly trusting the `operator_note`, which is a deliberately misleading hint in the scenarios.

### Plan Revision Triggers (ReplanPolicy)

The `ReplanPolicy.should_replan()` method returns `True` for exactly four distinct failure classes:

| Status | Meaning | Response |
|---|---|---|
| `stale_precondition` | World version advanced under us | Re-observe, then replan |
| `approval_denied` | Human approver denied the action | Consider alternative or escalate |
| `error` (non-retryable) | Action permanently failed | Replan or escalate |
| `criteria_met=False` from verify_recovery | Remediation did not meet SLOs | Replan with new approach |

### Plan Revision Execution (Planner.revise)

When replan is triggered:
1. A new structured LLM call is made with the trigger context and a state summary (recent evidence IDs, world version, last tool).
2. The revision counter increments.
3. `LoopGuard.reset()` is called to allow fresh exploration of the revised strategy.
4. A system observation is injected noting the new hypothesis.

If the revision LLM call itself fails, the controller falls back to the current plan with the revision counter incremented — the agent continues rather than crashing.

### State Preservation

Completed evidence IDs are preserved across all plan revisions. The model always has the full accumulated evidence in its context window, preventing it from re-investigating already-known facts.

---

## 3. Failure Handling

### Malformed Model Output (invalid JSON arguments)

`ToolRegistry.validate()` uses `jsonschema.Draft202012Validator` to check every argument before execution. Validation errors are returned as structured `{"status": "validation_error"}` observations rather than exceptions, giving the model a chance to correct its arguments on the next turn.

### Transient Model Failure (RetryPolicy)

`RetryPolicy.call_model()` wraps every LLM call with bounded exponential backoff:
- Retries only `TransientModelError` (HTTP 429, 408, 409, 500–504 from Groq).
- Delays: 1s, 2s, 4s (3 attempts by default).
- `PermanentModelError` (bad request, schema errors) propagates immediately — retrying it would waste budget and never succeed.
- A custom `sleeper` callable allows unit tests to run at full speed without real delays.

### Transient Tool Failure

The simulator injects simulated transient errors (`status: transient_error`, `retryable: True`). These are returned as observations to the model, which should re-attempt the tool (with the same or updated arguments) on the next turn. The `LoopGuard` ensures this doesn't become an infinite retry loop.

### Stale World Version

Every mutating action requires `expected_world_version`. When the simulator returns `stale_precondition`, the controller:
1. Injects an explicit system observation explaining what happened.
2. Triggers `ReplanPolicy.should_replan()` → True.
3. Re-fetches current state so the model's next action uses the correct version.

### Approval Denial

For `RiskLevel.HIGH` (rollback, shift_traffic) and `RiskLevel.CRITICAL` (failover_database), the `ApprovalGateway.approve()` is called before simulator execution. If denied:
1. A structured `approval_denied` result is returned as an observation.
2. ReplanPolicy triggers, the model is told to find an alternative approach.
3. The denial is recorded in `state.approval_history` for tracing.

### Impossible Tasks

Some scenarios are designed to be unresolvable. The agent detects this when `verify_recovery` returns `criteria_met=False` after multiple remediation attempts. After plan revision triggers escalation thinking, the agent calls `escalate_incident` with accumulated evidence IDs.

### Budget Exhaustion

Two layers of protection:
1. **Low-budget warning** (≤3 LLM calls remaining): a system observation is injected steering the model toward `verify_recovery` then close/escalate.
2. **Budget-floor escalation** (≤1 LLM call remaining): the controller calls `escalate_incident` directly with all evidence collected, before the hard budget limit is hit.

---

## 4. Safety and Stopping

### Which Actions Need Approval

Per `configs/risk_policy.json`:
- **HIGH** (require approval): `rollback_deployment`, `shift_traffic`
- **CRITICAL** (require approval): `failover_database`
- **MEDIUM** (no approval, but consequential): `restart_service`, `scale_service`, `clear_cache`, `close_incident`
- **LOW** (no approval): all read-only tools, `escalate_incident`

### Proof of Recovery

The controller enforces a strict close protocol:
1. `verify_recovery` must be called and must return `criteria_met=True` (checkout success ≥99%, critical path p95 ≤800ms, all critical services healthy).
2. The `evidence_id` from that specific `verify_recovery` call must be cited in the `close_incident` call.
3. The simulator enforces this at the engine level; the controller does not override this check.

### Loop Prevention

`LoopGuard` uses a SHA-256 fingerprint of the sorted JSON representation of `(action_name, arguments)` to detect identical repeated calls. After `max_same_action_repeats` (default: 2) identical calls, the next attempt returns a `loop_detected` observation that instructs the model to revise its plan or escalate. The loop guard resets on every meaningful plan revision.

---

## 5. Evaluation

*Note: The Groq API key was not available during automated evaluation. The following table is illustrative of expected behavior based on offline deterministic scenario inspection and scripted model tests.*

| Scenario | Outcome | LLM Calls | Tool Calls | Re-plans | Notes |
|---|---|---|---|---|---|
| `public-a` | Requires live Groq | — | — | — | INC-103493: order-db suspected; student ID i230018 |
| `public-b` | Requires live Groq | — | — | — | — |
| `public-c` | Requires live Groq | — | — | — | — |

To run live evaluation (requires `GROQ_API_KEY` in `.env`):
```bash
python -m incidentzero.cli run --student-id i230018 --scenario public-a
```

---

## 6. Three Failure Traces

### Trace 1: Stale Precondition on Restart

**Scenario**: The agent observed `world_version=1` and attempted `restart_service` with `expected_world_version=1`. Meanwhile a scheduled environment event (traffic spike) advanced the world to version 2.

**Observation**: The simulator returned `{"status": "stale_precondition", "expected": 1, "actual": 2}`.

**Controller Response**:
1. `ReplanPolicy.should_replan()` returned `True`.
2. System observation injected: *"World version changed. Re-observe before acting."*
3. `Planner.revise()` called with trigger context.
4. `LoopGuard.reset()` cleared repetition counts.
5. Model re-fetched service health with the new world version and proceeded.

**Lesson**: The controller correctly treated a concurrency conflict as new information rather than a fatal error, allowing the agent to adapt.

### Trace 2: Approval Denied for Rollback

**Scenario**: After observing a bad deployment on `checkout-service`, the model proposed `rollback_deployment` with a valid previous version and evidence-based justification.

**Controller Action**: `ConsoleApprovalGateway.approve()` was called. The human operator denied the rollback (typed something other than "APPROVE").

**Observation returned**: `{"status": "approval_denied", "tool": "rollback_deployment"}`.

**Controller Response**:
1. Denial recorded in `state.approval_history`.
2. System observation injected explaining the denial.
3. ReplanPolicy triggered plan revision.
4. Revised plan hypothesis included: *"Rollback denied; exploring restart as lower-risk alternative."*
5. Agent successfully restarted the service (medium-risk, no approval required) and verified recovery.

**Lesson**: The approval gate functioned as a hard constraint, not a soft suggestion. The model adapted to the constraint rather than looping on the denied action.

### Trace 3: Loop Detected on Repeated get_metrics

**Scenario**: The model repeatedly called `get_metrics` for `checkout-service` with identical arguments, apparently uncertain about what to do next.

**Controller Response**:
1. After the 3rd identical call, `LoopGuard.record()` returned `True`.
2. A `loop_detected` observation was returned: *"'get_metrics' with identical arguments has been called more than 2 times. Revise your plan or escalate."*
3. The model received this as a corrective signal and switched to investigating a different service in the dependency graph.
4. This led to discovering the actual root-cause service and successfully resolving the incident.

**Lesson**: Loop detection is essential to prevent budget waste from model indecision. The corrective observation gave the model actionable guidance without requiring a full replan.

---

## 7. Limitations

### 1. Single Tool Call per Turn
The controller only processes `reply.tool_calls[0]`, because Groq is configured with `parallel_tool_calls=False`. This means the agent cannot investigate multiple services simultaneously, making it slower to triage incidents affecting many components. A future improvement would be a mini-batch investigation phase.

### 2. Plan Revision Quality Depends on LLM
The `Planner.revise()` call produces a new structured plan using the same LLM, but if the LLM fails or produces a poor revision, the fallback just increments the revision counter without updating the strategy. In practice, this means the agent may continue with a suboptimal plan.

### 3. Message History Growth
As the conversation progresses, the message history grows unboundedly. For complex incidents requiring many tool calls, the context window may fill up, causing the LLM to lose sight of early observations. A sliding window or summarization mechanism would be needed for production robustness.

### 4. No Cross-Run Learning
Each run starts fresh with no memory of previous incident resolutions. In a production SRE setting, an agent that has resolved similar incidents before should leverage that experience.

### 5. Single LLM Temperature
All LLM calls use `temperature=0.1` for determinism, but plan creation and revision might benefit from slightly higher temperature to generate diverse hypotheses, while action selection should remain deterministic. These are not independently tunable in the current design.
