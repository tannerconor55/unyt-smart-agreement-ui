# Unyt Smart Agreement Visualisation

## Design Brief

### 1. Product Goal

Build a universal interface for Unyt Smart Agreements that lets people:

1. **Understand** what an agreement is intended to do.
2. **See** what value and state can change.
3. **Simulate** what the real agreement engine produces.
4. **Explore** different possible outcomes.
5. **Inspect** who has authority to make decisions.
6. **Replay** executions that actually happened.
7. **Verify** whether an execution reproduced the expected result.
8. **Understand failures and uncertainty** without the UI inventing facts.

The product should work for new Smart Agreement templates automatically, without requiring bespoke frontend code for every agreement.

The core product promise is:

> **Understand your Smart Agreement. Simulate what it will do. See the changes. Replay what actually happened. Know whether it worked as intended.**

---

# 2. Product Positioning

This is not primarily a contract dashboard.

It is a:

* Smart Agreement debugger
* simulator
* replay tool
* execution inspector
* value-flow visualiser
* trust/authority analyser

The central design principle is:

> **Run the real agreement. Capture what it depends on. Replay what happened. Derive the facts. Then visualise those facts clearly.**

The UI should be a universal renderer over agreement data, execution data, simulation results, and provenance.

---

# 3. Core Architectural Principle

The frontend must not become a second implementation of the Smart Agreement.

The authoritative behavioural source remains the actual Smart Agreement execution code and engine.

The conceptual pipeline is:

```text
Template
    +
Agreement Instance
    +
Network / Chain State
    +
Execution Inputs
    ↓
Real rave_engine
    ↓
RAVE / Execution Result
    ↓
Fact Deriver
    ↓
Provenance + Trust + Effects
    ↓
Universal UI
```

The UI may interpret and present facts.

It must not independently calculate financial behaviour that could disagree with the agreement.

---

# 4. Evidence and Provenance

Every displayed financial value and every substantive trust statement must have an evidence source.

Provenance should be represented using two separate dimensions.

## 4.1 Attribution

Where did the value or decision come from?

Possible attribution:

* Constant
* Chain-derived
* Role member
* Specific input
* Executor
* `executor_pub_key`
* External/host data
* Unknown

## 4.2 Verification

How strongly can the system establish it?

Possible verification states:

* Enforced by rule
* Re-derived
* Observed
* Authenticated but unverified
* Unverified
* Unknown

This avoids conflating statements such as:

> "The executor supplied this value."

with:

> "This value has been independently verified."

---

# 5. Trust Statement Evidence

Generated trust statements must themselves have provenance.

Every statement belongs to one of three evidence classes:

### Rule-derived

Directly established from agreement-instance rules.

Examples:

> Anyone can execute.

> The spender may also be the executor.

> `condition_met` is supplied by the executor.

### Observed across N explored runs

Established by executing the real engine across controlled inputs.

Example:

> Across 8 explored executions, changing `condition_met` changed the allocation target.

This is evidence, not a universal proof.

### Possible — flagged by lint

A static/schema inspection identifies a potentially important behaviour that has not been observed.

Example:

> The agreement code references the `locked` output. This may create locked value.

This warning may be raised by lint.

It cannot be cleared merely because an exploration did not happen to reach the relevant branch.

**Asymmetric rule:**

> Static analysis and declared schemas may raise a warning. Only rules and observed execution may establish a behavioural fact. Lack of observation must never silently clear a warning.

### Resolving warnings

A warning leaves the "Possible" state in only two ways:

* **Escalated to fact.** An observed or explored run produced the effect. The statement becomes "Observed across N runs".
* **Acknowledged.** A named person records a reason. The acknowledgement has provenance *Authored*, and the warning stays visible as "Acknowledged by \<person\>: \<reason\>". It is never displayed as cleared.

There is no other way to dismiss a warning. This prevents warning fatigue from turning into loosened lint rules.

### Combining evidence

Many useful trust statements combine several facts. For example:

> The spender can execute, and the executor chooses `condition_met`, so the spender can send the value to the return address they supplied.

**A combined conclusion takes the weakest evidence class of the facts it rests on.** Here, two facts are rule-derived but the branch behaviour was only observed across explored runs, so the conclusion is labelled **Observed across N runs**, not **Rule-derived**.

The Trust Inspector should state these combined conclusions directly. Users should not have to combine facts themselves.

---

# 6. Effect Ledger

The primary visualisation should be an **Effect Ledger**.

It shows what the agreement execution actually produces.

Conceptually:

```text
INPUTS
  ↓
RAVE EXECUTION
  ↓
OUTPUTS

Value
 ├── Allocation → recipient   (a "return" is an allocation to the payer)
 ├── Allocation → recipient
 ├── Locked → unit map
 └── ⚠ Consumed without allocation   (spent and lost; a warning, not a category of value)

State
 ├── carryover
 ├── computed_values
 └── other execution state

Inputs not consumed
 ├── Rejected links   (dropped from this execution, still parked)
 └── Redacted links   (dropped and deleted)
```

There is no "unallocated" or "remaining" value. Every consumed input is either cited as a source by an allocation, carried in `locked`, or lost.

The ledger must distinguish:

* Value movement
* State changes
* Inputs consumed
* Inputs rejected or redacted
* Consumed inputs no allocation cites
* Locked value
* Carryover state

`carryover` must never be rendered as money.

---

# 7. Value Conservation

The visualiser should provide a conservation view wherever the execution data allows it.

The documented rule, per unit, is:

```text
Parked sources cited by allocations
+
Previously locked value (this executor's previous RAVE)
=
Allocated value
+
Newly locked value
```

Two consequences the view must make visible:

* **Only cited sources count.** A consumed input that no allocation names as a source is not conserved. It is spent and its value is lost. Show it as **⚠ Consumed without allocation**, never as "remaining".
* **Conservation is enforced by the DNA, not by `rave_engine`.** The simulator does not run the DNA. A conservation result must therefore be labelled:

> **Re-derived from documented validation rules**

never "DNA accepted" or "engine verified".

The calculation must use unit maps with precision-aware decimal arithmetic.

The UI must never imply conservation merely because displayed numbers happen to add up.

---

# 8. Locked Value vs Carryover

These are fundamentally different.

### Locked

`locked` is value.

It participates in unit-level conservation.

It should be shown in the value ledger.

### Carryover

`carryover` is execution state.

It is opaque JSON/state and is not monetary value.

It should be shown separately.

If the engine does not produce a field, the UI must show:

> **None**

rather than inventing an empty field.

---

# 9. Outcome Exploration

The product should provide **Outcome Exploration**.

This executes the real engine across controlled variations.

Potential dimensions include:

* Boolean `ExecutorProvided` inputs
* Different executor-provided values
* Different parked links
* Presence/absence of previous execution
* Relevant captured host state
* Different execution timestamps where relevant

For example:

```text
condition_met = true
        ↓
Receiver receives parked amount

condition_met = false
        ↓
Return address receives parked amount
```

The UI should say:

> **Observed across 2 explored inputs**

not:

> **These are all possible outcomes**

unless exhaustive exploration has actually been established.

Outcome exploration is an evidence-producing feature, not a replacement for execution semantics.

---

# 10. Trust Inspector

Every agreement should have a Trust Inspector.

It should answer:

### Who can execute?

Derived from:

* executor rules
* role qualifications
* agreement instance configuration

### Who can supply inputs?

Show each input and its supplier.

### Which roles can overlap?

For example:

```text
Spender
   ↕
Executor

Qualification: Any
```

This is important because a combination of independently permissive rules can create a security-sensitive authority relationship.

### What decisions can the executor make?

For example:

```text
condition_met
    ↓
Executor supplied
    ↓
Allocation branch changes
```

The UI should distinguish:

* rule-derived authority
* observed behavioural consequences
* lint warnings

---

# 11. Allocation Traceability

A universal property check should not require every allocation target to be a role.

Instead:

> **Every allocation target must be traceable to a source with provenance.**

Valid sources include:

* Role member
* Input value
* Input value plus its supplier
* `executor_pub_key`
* Other explicitly derived chain data

This supports agreements such as:

* `conditional_forward`
* `lockbox`
* `ioen_rec`

without incorrectly treating every recipient as a role.

The trace should make it possible to answer:

> "Why did this address receive this value, and who controlled the address?"

---

# 12. Simulation Modes

Simulation must distinguish three states.

## 12.1 Captured

The execution occurred on a node controlled by the product/instrumentation.

Host-call responses were captured.

The exact execution environment can therefore be replayed.

Suitable for:

> Replay this exact execution.

## 12.2 Chain Replay

The execution was performed elsewhere.

The simulator reconstructs inputs from the RAVE and chain/DHT data and re-runs the engine.

This is the general auditor/participant case.

Required DHT data may not yet be available.

Therefore chain replay has three outcomes:

```text
MATCH
MISMATCH
CANNOT REPLAY YET
```

`CANNOT REPLAY YET` is not a failure.

It means required source data is unavailable.

## 12.3 Assembled

A simulation constructed from data observable by the current participant, with gaps filled by explicit assumptions.

For example:

```text
Known:
  parked link = observed
  agreement instance = observed

Assumed:
  executor = Alice
  condition_met = true
  execution timestamp = 14:30
  previous execution = unknown
```

Every assumption must be displayed.

An assembled simulation cannot receive a full:

> "Matches actual execution"

verdict.

It can later be compared field-by-field with an actual execution.

---

# 13. Simulation Snapshot

Every simulation should have a reproducible snapshot.

The snapshot should identify:

* Agreement instance/version
* Template version
* Parked links included
* Previous RAVE
* Execution timestamp
* Executor-provided inputs
* Host-call responses, where captured
* DNA/version information
* Engine version derived from the DNA where possible
* Simulation mode
* Assumptions
* Snapshot fingerprint

The fingerprint makes it possible to answer:

> "Were these two simulations actually based on the same inputs?"

---

# 14. Host-Call Recording

Host-dependent agreements may read state through Holochain host calls.

For executions performed by our own node:

```text
Host call
   ↓
Real response
   ↓
Capture
   ↓
Execution
```

The captured response becomes replayable evidence.

However, the product cannot capture host calls made by arbitrary third-party nodes.

Therefore:

* Own executions → captured replay
* Third-party executions → chain replay
* Missing DHT information → deferred replay

---

# 15. Replay and Verification

The Verify workflow should start with replay.

## Step 1 — Replay

Re-run the actual agreement with the recorded or reconstructed inputs.

## Step 2 — Compare

Compare:

* RAVE allocations
* locked value
* carryover
* computed values
* relevant execution outputs

## Step 3 — Input Diff

If results differ, compare the inputs first.

```text
Expected:
condition_met = true

Actual:
condition_met = false
```

This is more useful than simply showing:

> Expected output ≠ actual output.

## Step 4 — Explain

Show which input difference caused or correlates with the output difference.

## Step 5 — Property Checks

Run universal and agreement-specific assertions.

---

# 16. Replay Integrity

If identical inputs produce different engine outputs, this should be treated as an alarm.

Possible explanations include:

* incomplete snapshot
* missing host state
* engine/DNA mismatch
* simulator bug
* non-deterministic dependency

It must not automatically be labelled:

> "Agreement bug."

---

# 17. Holochain Execution Observability

The UI should distinguish lifecycle states precisely.

For an execution:

* Executed locally
* Committed by author
* Retrieved from DHT
* Re-executed locally and matched
* Warrant observed
* Failed (no RAVE committed) or Invalid (warrant observed)

Do not use "Rejected" as an execution status. In this design, *rejected* means a parked link dropped from an execution's inputs (§19).
* Unable to replay because required data is unavailable

Avoid vague status labels such as:

> Network accepted ✓

A Holochain client can observe different levels of evidence at different times.

---

# 18. Failure States

The most important immediate execution failure is:

> **No RAVE committed by the author.**

For example:

```text
Execution attempted
      ↓
Rhai threw an error
      ↓
No RAVE committed
```

The UI should clearly distinguish this from:

```text
RAVE committed
      ↓
Later validation problem
```

---

# 19. Agreement Lifecycle

The lifecycle visualisation should support:

```text
Available
   ↓
Parked
   ↓
Consumed
   ↓
Allocated
   ↓
Pending collection
   ↓
Collected
```

Additional states:

* Locked
* Rejected
* Redacted
* Consumed without allocation

`Returned` is not a fundamentally separate value lifecycle state.

It is an allocation back to the payer.

---

# 20. ParkedData

`ParkedData` should have its own lifecycle representation.

It should not be treated as equivalent to parked monetary value.

The UI should distinguish:

```text
Parked Spend
```

from:

```text
Parked Data
```

and show the relevant provenance and consumption state for each.

---

# 21. Collection Visibility

Collection may occur on another participant's chain.

Therefore:

> Collection status may be **Unknown**.

Do not infer collection simply because an allocation exists.

Possible display:

```text
Allocation created
✓ Observed

Collection
? Not observable from this chain
```

---

# 22. Actor-Specific Input Experiences

There should not be one generic input form.

## Creator

Provides:

* Agreement definition input
* Initial configuration

## Participant

Provides:

* Parked spend
* Parked data
* Role-specific values

## Executor

Provides:

* Executor-provided inputs
* Execution selection
* Eligible parked inputs
* Previous execution where available

For example, in `conditional_forward`, the executor should **not** enter the amount or receiver if those values are actually supplied by the spender's parked data.

The UI must represent the real source of each input.

---

# 23. Input Validation

The UI may provide helpful validation.

However:

> UI validation is advisory unless the underlying engine enforces the same constraint.

An adversarial executor will not necessarily use the UI.

Therefore the UI must never imply:

> "This input is impossible"

when the engine would actually accept it.

---

# 24. Amount Representation

Amounts must use the real Unyt unit-map representation.

For example:

```json
{
  "0": "100.5"
}
```

The unit index is the key.

The value is a decimal string.

Precision comes from the network's unit definition.

The implementation must never convert financial values into JavaScript floating-point `Number`.

Equality must use precision-aware normalization.

For example, where the unit precision permits:

```text
"100"
=
"100.00"
```

---

# 25. Units

The frontend needs access to the network's unit registry.

It should know:

* unit index
* precision
* display representation
* relevant metadata

The raw unit map remains authoritative.

---

# 26. Fixtures and Expectations

Fixtures provide assertions without creating a second execution language.

They may assert things such as:

* allocation equality
* allocation sums
* output presence
* role membership
* input/output relationships

Example:

```text
output.allocation(input.receiver)
    ==
input.amount
```

The predicate language must define how it refers to:

* input paths
* roles
* `executor_pub_key`
* units
* RAVE output fields

before fixtures are implemented.

Fixtures should remain declarative.

They must not contain control flow or reproduce Rhai execution logic.

---

# 27. Universal Property Checks

Universal checks should include properties such as:

### Conservation

Per unit, cited parked sources plus previously locked value equal allocated value plus newly locked value (§7). This is the DNA's documented rule; results are labelled **Re-derived from documented validation rules**.

### Allocation traceability

Every allocation target has a provenance-bearing source.

### Input consumption

Every consumed input is cited as a source by an allocation or carried in `locked`. A consumed input with no citation is reported as **⚠ Consumed without allocation**.

If an agreement intentionally consumes an input without paying from it, that exception is declared in a fixture expectation approved by a named person. It is never declared in a template annotation, because annotations cannot define financial behaviour (§33).

### Locked value

Locked value is represented separately from carryover.

### Provenance

No financial value or trust statement is rendered without provenance.

These checks should run over generated/explored inputs, not merely one golden fixture.

---

# 28. Golden Fixtures

Golden fixtures are useful for:

* regression testing
* documentation
* known examples
* template-specific assertions

They are not a substitute for executing the actual engine.

The real engine remains authoritative.

---

# 29. Template Source of Truth

The template should be loaded from the version/reference actually used by the agreement instance.

Do not automatically substitute the latest GitHub template.

The UI may compare the instance's template against a newer repository version and show:

> **Template differs from current repository version**

as a drift warning.

It must not silently use the newer version to explain historical behaviour.

---

# 30. Existing Metadata

Existing agreement metadata should be reused.

For example, existing `other_options.json` tags such as:

* `Public: conditional`
* `Lane: bridging`
* `System: credit`

should be surfaced where useful.

Do not create an unnecessary parallel capability taxonomy.

---

# 31. Permissions vs Authority

Do not collapse these concepts.

`other_options.permissions` and role/executor qualification are different things.

The UI should distinguish:

### Agreement permissions

What agreement-level permission configuration exists?

### Role qualification

Who qualifies for a role?

### Executor authority

Who may execute?

### Input authority

Who supplies each input?

---

# 32. LLM Usage

An LLM may assist with:

* drafting descriptions
* generating annotations
* identifying documentation inconsistencies
* suggesting explanations

It must not:

* determine financial behaviour
* calculate authoritative value movements
* replace the engine
* run during rendering as a source of financial truth
* override provenance
* claim an execution was verified

Generated content must pass validation/binding checks.

---

# 33. Annotation System

Annotations can provide:

* purpose
* context
* human-readable explanations
* documentation

They cannot:

* contradict derived facts
* rename recipients
* hide outputs
* claim verification
* define financial behaviour
* contain arbitrary executable HTML
* override authoritative labels

Binding an annotation to a real field only proves that the field exists.

It does not prove that the prose describing the field is true.

---

# 34. Automatic UI Generation

A new agreement should automatically receive a generic inspector.

The renderer should discover:

* inputs
* suppliers
* outputs
* allocations
* locked value
* carryover
* computed values
* roles
* executor rules
* lifecycle
* provenance
* simulation/replay capabilities

No bespoke frontend is required for normal agreements.

---

# 35. Custom Renderer Escape Hatch

A custom renderer may exist for exceptional cases.

It should be keyed to:

```text
template + version
```

rather than merely a template name.

Custom renderers are primarily intended for:

* system agreements
* lane/operator agreements
* specialised infrastructure workflows

The universal renderer remains the default.

---

# 36. Recommended Actor Views

## Creator

Focus:

* configuration
* role definitions
* executor authority
* dangerous combinations
* fixture results
* warnings

## Participant

Focus:

* what they must park
* who can execute
* who controls relevant inputs
* possible observed outcomes
* lifecycle
* locked value
* assumptions in assembled simulations

## Executor

Focus:

* eligible parked inputs
* required executor inputs
* previous execution
* simulation
* expected RAVE
* replay

## Auditor

Focus:

* actual RAVE
* lineage
* replay
* conservation
* provenance
* warrants
* allocations
* collection where observable

## Beneficiary

A beneficiary is anyone who can receive an allocation without holding a role. Examples: the receiver and return address in `conditional_forward` (addresses the spender supplies), the executor in `lockbox` (paid at `executor_pub_key`), and per-record receivers in `ioen_rec`.

Their questions are often the most security-sensitive:

> "Is my payment guaranteed? Who can redirect it? Has it arrived, and have I collected it?"

Focus:

* allocations traced to them (§11), with who supplied their address
* who can redirect or withhold the allocation, as a combined trust conclusion (§5)
* outcomes in which they receive nothing
* lifecycle and collection status

---

# 37. MVP

## Phase 0 — Execution Feasibility Spike

Before UI implementation, answer:

1. Where can `rave_engine` execute outside normal agreement execution?
2. Who owns/builds that execution hook?
3. Can one locally executed `conditional_forward` be captured?
4. Can the captured execution be replayed byte-for-byte?
5. Can a third-party RAVE be replayed using chain data alone?
6. Can replay correctly defer when required DHT data is unavailable?
7. Can outcome exploration reach the `lockbox` locking branch without hand-tuned inputs?
8. If not, does lint reliably raise the locked-value warning?

### Go/no-go

Phase 0 must produce a clear architecture decision:

```text
A. Conductor execution
        OR
B. External engine + host-response shim
```

No Phase 1 implementation should depend on an unresolved answer here.

---

# 38. Phase 1 — `conditional_forward` + `lockbox`

These two templates deliberately provide different security/authority cases. Phase 1 is split so that a delay in chain replay does not block the first demo.

## Phase 1a — `conditional_forward`

Implement:

* universal inspector
* provenance model
* Effect Ledger
* Trust Inspector, including combined conclusions (§5)
* Beneficiary view
* engine simulation
* captured replay
* lifecycle
* template/version handling

Tests:

* executor-controlled branch decisions
* role/input overlap
* input provenance
* allocation traceability

## Phase 1b — `lockbox`

Implement:

* outcome exploration
* lint-raised warnings and their resolution (§5)
* chain replay
* assembled simulations
* fixtures and the predicate language (§26)
* universal property checks

Tests:

* locked value
* previous-execution lineage
* authority over locked value
* lint-raised security warning (`locked` under `executor_rules: Any`)
* whether exploration reaches the lock branch

The implementation must not rely on the erroneous assumption that `conditional_forward` has fees or carryover value.

---

# 39. Phase 2 — `aggregate_payment`

Add support for:

* aggregate inputs (`aggregate_execution: true`, arrays of parked links)
* multiple parked inputs per execution
* recurring execution (`one_time_run: false`)
* detection of mismatches between `output_signature.json` and real output

`aggregate_payment` is the right test case for the last item: its output signature requires `computed_values`, but its code never produces it. The inspector should report this, with the evidence class "Observed across N runs" (the field never appeared) plus a lint warning from the schema.

`aggregate_payment` does not read `previous_execution`. Previous-execution lineage is covered by `lockbox` in Phase 1b.

---

# 40. Phase 3 — `holo_hosting_proof_of_service`

Add:

* DHT-dependent reads
* host-call replay
* chain replay
* deferred replay
* captured host responses

This validates the full host-dependent simulation architecture.

---

# 41. Phase 4 — Lane Agreement

Add `_lane_bridging_infra` (or `_lane_bridging_yf` / an `hf_2` variant). Do not use `_lane_bridging_unyt`, which does not call `check_cool_down_period`.

This tests:

* lane-specific behaviour
* cool-down host calls
* executor-provided values in an operator workflow
* previous-execution lineage over long histories
* custom renderer escape hatch if required

### Credit limits

None of the `_lane_bridging_*` templates output `credit_limit`. If credit limits are in scope, add `_lane_credit_limit_adjustment_unyt` to this phase.

The inspector must label any `credit_limit` output as:

> **Recorded. Takes effect only if this is the lane's designated credit-limit-adjustment agreement, executed by the lane's bridging agent.**

Otherwise the UI would show credit-limit changes that apply to nobody.

---

# 42. Development Workflow

The development workflow should be:

```text
1. Load actual template
2. Load actual agreement instance
3. Load observable chain state
4. Resolve inputs and provenance
5. Run real rave_engine
6. Capture host dependencies where possible
7. Derive facts
8. Run property checks
9. Record snapshot
10. Render universal UI
11. Explore controlled alternatives
12. Replay actual executions
13. Compare expected vs actual
```

The UI is downstream of this pipeline.

---

# 43. Success Criteria

The product is successful when:

### Correctness

* Replay from capture reproduces 100% of captured MVP RAVEs.
* Every actual-vs-simulated difference begins with an input/environment comparison.
* `carryover` is never represented as monetary value.
* Financial values use real unit-map semantics.

### Provenance

* Zero financial values without provenance.
* Zero substantive trust statements without provenance.
* Every assumption in an assembled simulation is explicitly identified.

### Security

A non-Rhai reader can correctly answer:

> **Can the payer get the money back on their own?**

for each MVP template.

### Generality

A new Smart Agreement receives a useful generic inspector without custom frontend code.

### Replay

The system correctly distinguishes:

```text
MATCH
MISMATCH
CANNOT REPLAY YET
```

and does not treat unavailable DHT state as a failed execution.

### Simulation

Every simulation records sufficient information to reproduce or explain its result:

* template
* instance
* inputs
* host responses where captured
* previous execution
* timestamp
* DNA/engine version
* assumptions
* snapshot identity

---

# 44. Example User Experience

A participant opens an agreement.

They see:

```text
SMART AGREEMENT
Conditional Forward

Purpose
Forward the parked amount to a receiver,
or return it to the specified return address.

────────────────────────────

YOUR VALUE

Parked
100.50 UNIT

Source
Your parked spend

────────────────────────────

WHO CAN EXECUTE?

Anyone

Rule-derived ✓

Can the spender execute?
Yes

Rule-derived ✓

────────────────────────────

WHAT CAN THE EXECUTOR DECIDE?

condition_met

Supplied by
Executor

Rule-derived ✓

Observed effect
Changes allocation target

Observed across 2 explored runs

────────────────────────────

WHAT THIS MEANS

⚠ You (the spender) can execute this agreement
  and choose condition_met = false, sending the
  value to the return address you supplied.

⚠ The receiver has no guarantee of payment.
  Any executor, including you, can choose
  the return address instead.

Observed across 2 explored runs
(weakest evidence among: 2 rule-derived facts,
 1 observed branch effect)

────────────────────────────

OUTCOME EXPLORATION

condition_met = true
→ Receiver receives 100.50 UNIT

condition_met = false
→ Return address receives 100.50 UNIT

Observed across 2 explored inputs

────────────────────────────

SIMULATION

Mode
Assembled

Known
✓ Parked spend
✓ Agreement instance

Assumed
• Executor
• condition_met
• Execution timestamp

This simulation is not a prediction
of the actual future execution.

────────────────────────────

LIFECYCLE

Parked            ← you are here
   ↓
Consumed          (when an execution runs)
   ↓
Allocated         (to receiver or return address)
   ↓
Pending collection
   ↓
Collected

Collection status
Unknown until an execution exists
```

The interface should make the important security/financial consequences understandable without requiring the user to read Rhai.

---

# 44a. What Not To Build

This list collects the prohibitions stated throughout the document, for use as an implementation checklist.

Do not build:

* authored execution flows, conditions, calculations or state changes
* a second behavioural language or visual DSL
* a universal intermediate agreement model with per-agreement adapters
* balance before/after views at execution time
* generic condition nodes without provenance
* a "remaining" or "unallocated" value category
* UI-side financial arithmetic outside precision-aware unit maps
* JavaScript `Number` for amounts
* a single form containing every input
* global execution numbering
* "Network accepted ✓", "Validated ✓" or any status the client did not observe
* conservation labelled as engine- or DNA-verified
* credit-limit changes shown as effective outside the designated lane agreement
* static Rhai analysis as a source of fact (it may only raise warnings)
* warning dismissal without escalation or a named acknowledgement
* annotations that rename recipients, hide outputs, claim verification or contain markup
* runtime LLM interpretation, or LLM output as a source of financial truth
* a parallel capability taxonomy alongside `other_options.json` tags
* explanations of historical RAVEs using a newer template version

---

# 45. Final Product Principle

The product should never attempt to make Smart Agreements look simpler by hiding uncertainty.

Instead:

> **Make the evidence visible.**

The UI should clearly separate:

```text
WHAT THE RULES SAY
        ↓
WHAT THE ENGINE PRODUCED
        ↓
WHAT THE NETWORK OBSERVED
        ↓
WHAT WE REPLAYED
        ↓
WHAT WE ASSUMED
        ↓
WHAT WE ONLY SUSPECT
```

That separation is the foundation of a trustworthy Smart Agreement visualisation system.

## Final Product Promise

> **Understand your Smart Agreement.**
>
> **Simulate what it will do.**
>
> **See the changes.**
>
> **Explore the outcomes.**
>
> **Replay what actually happened.**
>
> **Know what is proven, what is observed, and what remains uncertain.**
