#!/usr/bin/env python3
"""Fact deriver + outcome explorer for the Smart Agreement Inspector (Phase 0 / 1a).

Pipeline (per the design doc, section 42):
  load template + instance -> resolve inputs and provenance -> run real rave_engine
  -> derive facts -> property checks -> record snapshots -> emit inspector data.

Rules this script holds itself to:
  * Every financial value in the output comes from the engine's result or from the
    snapshot that was fed to it. The only arithmetic here is the conservation check,
    which is labelled "Re-derived from documented validation rules" and uses Decimal.
  * Every statement carries an evidence class: rule-derived, observed (N of M runs),
    or possible (lint). Lint can raise warnings; it never states facts.
"""
import copy
import hashlib
import itertools
import json
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARNESS = HERE / "target" / "release" / "harness"
LIBRARY = Path("/tmp/smart_agreement_library")
TIMESTAMP_MICROS = 1790000000000000  # assumed execution time for every hypothetical run
ABSENT = "<absent>"


def sh(args, stdin=None):
    r = subprocess.run(args, input=stdin, capture_output=True, text=True, check=True)
    return r.stdout


def harness(cmd, payload):
    return json.loads(sh([str(HARNESS), cmd], json.dumps(payload)))


KEYS = json.loads(sh([str(HARNESS), "keys"]))
AGENTS = KEYS["agents"]
HASHES = KEYS["hashes"]
NAME_OF = {v: k for k, v in {**AGENTS, **HASHES}.items()}
LIB_COMMIT = sh(["git", "-C", str(LIBRARY), "rev-parse", "HEAD"]).strip()


def resolve(value, ctx):
    """Replace @name tokens with real keys/hashes; @executor with the run's executor."""
    if isinstance(value, str) and value.startswith("@"):
        token = value[1:]
        if token == "executor":
            return ctx["executor_key"]
        if token.endswith(".output"):
            return resolve(ctx["prevs"]["@" + token[: -len(".output")]]["output"], ctx)
        if token in AGENTS:
            return AGENTS[token]
        if token in HASHES:
            return HASHES[token]
        raise KeyError(value)
    if isinstance(value, list):
        return [resolve(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: resolve(v, ctx) for k, v in value.items()}
    return value


def set_path(doc, path, value):
    parts = path.split(".")
    cur = doc
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    if value == ABSENT:
        cur.pop(parts[-1], None)
    else:
        cur[parts[-1]] = copy.deepcopy(value)


def label(key):
    return NAME_OF.get(key, key[:12] + "…" if isinstance(key, str) else str(key))


# --------------------------------------------------------------------------- facts

def load_template(name, instance_file):
    d = LIBRARY / "library" / name
    j = lambda f: json.loads((d / f).read_text())
    code = (d / "execution_code.rhai").read_text()
    return {
        "name": name,
        "dir": d,
        "code": code,
        "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
        "definition": j("agreement_definition_input.json"),
        "signature": j("runtime_input_signature.json"),
        "output_signature": j("output_signature.json"),
        "options": j("other_options.json"),
        "instance": j(instance_file),
        "instance_file": instance_file,
    }


def expected_roles(t):
    items = t["definition"]["properties"]["expected_roles"]["items"]
    items = items if isinstance(items, list) else [items]
    return [i["const"] for i in items if "const" in i]


def link_type_label(plt):
    if plt == "ParkedSpendBalance":
        return ("Parked spend (balance)", True)
    if plt == "ParkedSpendCredit":
        return ("Parked spend (credit)", True)
    if isinstance(plt, dict) and "ParkedData" in plt:
        return ("Parked data" + (" (consumed)" if plt["ParkedData"] else " (not consumed)"), plt["ParkedData"])
    return (str(plt), None)


def qualification_text(q):
    if "Any" in q:
        return "Anyone"
    if "Authorized" in q:
        return "Listed agents: " + ", ".join(label(a) for a in q["Authorized"])
    return json.dumps(q)


def executor_text(r):
    if "Any" in r:
        return "Anyone"
    if "AuthorizedExecutor" in r:
        return "Only " + label(r["AuthorizedExecutor"])
    return json.dumps(r)


def describe_input(name, branch, schema, rule, roles_by_id):
    instr = rule["instruction"] if rule else None
    is_spend_payload = (
        isinstance(schema, dict)
        and (
            {"amount", "source"} <= set(schema.get("properties", {}))
            or {"amount", "source"} <= set(schema.get("items", {}).get("properties", {}) if isinstance(schema.get("items"), dict) else {})
        )
    )
    out = {"name": name, "branch": branch, "schema_type": schema.get("type") if isinstance(schema, dict) else None,
           "instruction": instr}
    if instr is None:
        out.update(supplier="No input rule", attribution="Unknown", verification="Unknown",
                   note="Declared in the runtime signature but no input rule names it.")
    elif "Fixed" in instr:
        out.update(supplier="Constant in the agreement", attribution="Constant", verification="Enforced by rule",
                   value=instr["Fixed"], note="Every peer checks the recorded value equals this constant.")
    elif "ProvidedBy" in instr:
        role = instr["ProvidedBy"]
        r = roles_by_id.get(role, {})
        if is_spend_payload:
            out.update(supplier=f"{r.get('display_name', role)} (role member)", attribution="Role member",
                       verification="Enforced by rule",
                       note="Parked spend. Its amount and source are bound by conservation.")
        else:
            out.update(supplier=f"{r.get('display_name', role)} (role member)", attribution="Role member",
                       verification="Authenticated but unverified",
                       note="Data from the role member's parked link. Who wrote it is known; whether it is true is not checked.")
    elif "ExecutorProvided" in instr:
        out.update(supplier="Executor", attribution="Executor", verification="Unverified",
                   note="Chosen by whoever executes. Validation checks its shape only.")
    elif "Custom" in instr:
        c = instr["Custom"]
        if c == "GetPreviousExecution":
            out.update(supplier="Executor's own chain", attribution="Chain-derived", verification="Re-derived",
                       note="Re-derived by peers from the executor's own previous RAVE of this agreement.")
        elif c == "GetExecutorsParkedSpend":
            out.update(supplier="Executor", attribution="Executor", verification="Unverified",
                       note="Exempt from re-derivation: the engine treats this value as a claim.")
        else:
            out.update(supplier="Chain", attribution="Chain-derived", verification="Re-derived", note=f"Custom: {json.dumps(c)}")
    elif "Query" in instr:
        out.update(supplier="Chain query", attribution="Chain-derived", verification="Re-derived",
                   note="Re-executed and compared during validation.")
    else:
        out.update(supplier=json.dumps(instr), attribution="Unknown", verification="Unknown", note="")
    return out


def derive_facts(t):
    inst = t["instance"]
    roles_by_id = {r["ct_role_id"]: r for r in inst.get("roles", [])}
    roles = []
    for er in expected_roles(t):
        r = roles_by_id.get(er["id"], {})
        lt, consumed = link_type_label(er["parked_link_type"])
        roles.append({
            "id": er["id"], "display_name": r.get("display_name", er["id"]),
            "description": r.get("description", ""), "parks": lt, "consumed": consumed,
            "qualification": qualification_text(r.get("qualification", {})),
            "qualification_raw": r.get("qualification"),
        })
    rules = {r["name"]: r for r in inst.get("input_rules", [])}
    inputs = []
    sigp = t["signature"]["properties"]
    for branch in ("consumed_inputs", "inputs"):
        for name, schema in sigp.get(branch, {}).get("properties", {}).items():
            inputs.append(describe_input(name, branch, schema, rules.get(name), roles_by_id))
    return {
        "roles": roles,
        "executor_rule": executor_text(inst["executor_rules"]),
        "executor_rule_raw": inst["executor_rules"],
        "inputs": inputs,
        "options": t["options"],
        "outputs_declared": list(t["output_signature"].get("properties", {}).keys()),
        "outputs_required": t["output_signature"].get("required", []),
    }


def rule_statements(t, facts):
    out = []
    ex_any = "Any" in facts["executor_rule_raw"]
    out.append({"text": f"Who can execute: {facts['executor_rule']}.", "evidence": "rule",
                "basis": f"executor_rules = {json.dumps(facts['executor_rule_raw'])}"})
    for r in facts["roles"]:
        out.append({"text": f"Who can be {r['display_name']}: {r['qualification']}.", "evidence": "rule",
                    "basis": f"role {r['id']} qualification = {json.dumps(r['qualification_raw'])}"})
        if ex_any:
            out.append({"text": f"A {r['display_name']} can also be the executor.", "evidence": "rule", "severity": "warn",
                        "basis": "executor_rules = Any includes every role member"})
    for i in facts["inputs"]:
        if i["attribution"] == "Executor":
            out.append({"text": f"{i['name']} is chosen by the executor. Only its shape is checked.", "evidence": "rule",
                        "severity": "warn", "basis": f"input rule {i['name']} = {json.dumps(i['instruction'])}"})
        if i["instruction"] == {"Custom": "GetPreviousExecution"} and ex_any:
            out.append({"text": "Previous execution is read from each executor's own chain. With anyone able to execute, "
                                "each executor sees only their own history, so a carried lock is invisible to other executors.",
                        "evidence": "rule", "severity": "warn",
                        "basis": "GetPreviousExecution is derived from the executor's chain; executor_rules = Any"})
        if i["verification"] == "Authenticated but unverified":
            out.append({"text": f"{i['name']} is written by the {i['supplier']}. The agreement does not check it is true.",
                        "evidence": "rule", "basis": f"input rule {i['name']} = {json.dumps(i['instruction'])}"})
    return out


def lint(t, facts):
    """Possible-class warnings. These may only raise suspicion."""
    w = []
    code = t["code"]
    ex_any = "Any" in facts["executor_rule_raw"]
    if re.search(r'(\.locked\s*=|"locked"\s*:|locked\[)', code) and re.search(r"output\.locked\s*=|\"locked\"", code):
        w.append({"id": "locked_output", "text": "The code writes a `locked` output, so it may create locked value."
                  + (" Under executor_rules Any, a lock is only visible to the executor who created it." if ex_any else ""),
                  "basis": "lint: execution_code.rhai assigns output.locked", "severity": "warn" if ex_any else "info"})
    for r in facts["roles"]:
        if ex_any and re.search(r"authori[sz]ed executor|sole (authori[sz]ed )?executor", r["description"], re.I):
            w.append({"id": "description_drift", "text": f"The {r['display_name']} role description says it must be the sole "
                      f"authorized executor, but executor_rules is Any.",
                      "basis": f"agreement description vs executor_rules in {t['instance_file']}", "severity": "warn"})
    return w


# --------------------------------------------------------------------------- scenarios

def build_scenarios(t, fx):
    prevs = fx.get("previous_executions", {})
    dims = fx["dimensions"]
    fixed = {}
    sig = t["signature"]["properties"]
    for r in t["instance"].get("input_rules", []):
        if "Fixed" in r["instruction"]:
            branch = "inputs" if r["name"] in sig.get("inputs", {}).get("properties", {}) else "consumed_inputs"
            fixed[(branch, r["name"])] = r["instruction"]["Fixed"]
    scenarios, excluded = [], []
    for combo in itertools.product(*[d["values"] for d in dims]):
        choice = {d["name"]: v for d, v in zip(dims, combo)}
        doc = copy.deepcopy(fx["base"])
        for d, v in zip(dims, combo):
            set_path(doc, d["path"], v)
        executor_name = doc["executor"][1:]
        # Constraint: a previous execution belongs to the chain of the agent who authored it.
        pe = doc.get("inputs", {}).get("previous_execution", {})
        pe_id = pe.get("data", {}).get("id") if isinstance(pe.get("data"), dict) else None
        if pe_id and prevs[pe_id]["author"] != executor_name:
            excluded.append({"choice": choice, "reason": f"Impossible: {pe_id[1:]} is on {prevs[pe_id]['author']}'s chain, "
                                                         f"but {executor_name} is executing."})
            continue
        ctx = {"executor_key": AGENTS[executor_name], "prevs": prevs}
        inp = {"consumed_inputs": doc.get("consumed_inputs", {}), "inputs": doc.get("inputs", {})}
        for (branch, name), val in fixed.items():
            inp[branch][name] = {"data": val}
        inp = resolve(inp, ctx)
        sid = f"{t['name']}-{len(scenarios) + 1:03d}"
        scenarios.append({
            "id": sid, "choice": {k: describe_choice(v) for k, v in choice.items()},
            "executor_name": executor_name, "prev_id": pe_id[1:] if pe_id else None,
            "prev_output": resolve(prevs[pe_id]["output"], ctx) if pe_id else None,
            "run": {"id": sid, "code_path": str(t["dir"] / "execution_code.rhai"), "input": inp,
                    "ea_id": HASHES["agreement"], "executor": AGENTS[executor_name],
                    "timestamp_micros": TIMESTAMP_MICROS},
        })
    return scenarios, excluded


def describe_choice(v):
    if v == ABSENT:
        return "absent"
    if isinstance(v, str) and v.startswith("@"):
        return v[1:]
    if isinstance(v, dict) and "data" in v:
        d = v["data"]
        if d is None:
            return "none"
        if isinstance(d, dict) and "id" in d:
            return d["id"][1:] if isinstance(d["id"], str) else "previous RAVE"
        return describe_choice(d) if isinstance(d, str) else json.dumps(d)
    if isinstance(v, list):
        if not v:
            return "nothing parked"
        return " + ".join(f"{a['data']['amount'].get('0')} (unit 0)" for a in v)
    return json.dumps(v)


# --------------------------------------------------------------------------- ledger

def dec_map(m):
    return {k: Decimal(v) for k, v in (m or {}).items()}


def spend_inputs(inp):
    """Parked spend payloads in consumed_inputs: (input name, amount map, source hash)."""
    out = []
    for name, env in inp["consumed_inputs"].items():
        envs = env if isinstance(env, list) else [env]
        for e in envs:
            d = e.get("data") if isinstance(e, dict) else None
            if isinstance(d, dict) and "amount" in d and "source" in d:
                out.append((name, d["amount"], d["source"]))
    return out


def trace_receiver(key, run, facts):
    """Every input or preset that equals this receiver key, with its provenance."""
    hits = []
    if key == run["executor"]:
        hits.append({"source": "executor_pub_key", "attribution": "Executor", "verification": "Enforced by rule",
                     "note": "The agent who executed this run."})
    by_name = {i["name"]: i for i in facts["inputs"]}
    for branch in ("consumed_inputs", "inputs"):
        for name, env in run["input"][branch].items():
            envs = env if isinstance(env, list) else [env]
            for e in envs:
                if isinstance(e, dict) and e.get("data") == key:
                    i = by_name.get(name, {})
                    hits.append({"source": f"input {name}", "attribution": i.get("attribution", "Unknown"),
                                 "verification": i.get("verification", "Unknown"), "supplier": i.get("supplier", "")})
    return hits


def build_ledger(sc, res, facts, parked_by):
    run = sc["run"]
    out = res["result"]["output"]
    allocs = out.get("unyt_allocation") or []
    cited = {s for a in allocs for s in a.get("sources", [])}
    consumed = []
    for name, amount, source in spend_inputs(run["input"]):
        consumed.append({"input": name, "amounts": amount, "source": label(source),
                         "parked_by": parked_by.get(label(source), "unknown"),
                         "cited": source in cited})
    prev_locked = (sc["prev_output"] or {}).get("locked") or {}
    allocations = []
    for a in allocs:
        allocations.append({
            "receiver": label(a["receiver"]), "receiver_key": a["receiver"],
            "amounts": a["amounts"], "name_only": not a["amounts"],
            "sources": [label(s) for s in a.get("sources", [])],
            "trace": trace_receiver(a["receiver"], run, facts),
        })
    # Conservation, re-derived from the documented rule (per unit):
    #   cited parked sources + previously locked == allocated + newly locked
    units = set()
    cin, cout = {}, {}
    for c in consumed:
        if c["cited"]:
            for u, v in dec_map(c["amounts"]).items():
                cin[u] = cin.get(u, Decimal(0)) + v
                units.add(u)
    for u, v in dec_map(prev_locked).items():
        cin[u] = cin.get(u, Decimal(0)) + v
        units.add(u)
    for a in allocs:
        for u, v in dec_map(a["amounts"]).items():
            cout[u] = cout.get(u, Decimal(0)) + v
            units.add(u)
    for u, v in dec_map(out.get("locked")).items():
        cout[u] = cout.get(u, Decimal(0)) + v
        units.add(u)
    conservation = [{
        "unit": u,
        "cited_parked": str(sum((Decimal(c["amounts"].get(u, "0")) for c in consumed if c["cited"]), Decimal(0))),
        "previously_locked": prev_locked.get(u, "0"),
        "allocated": str(sum((Decimal(a["amounts"].get(u, "0")) for a in allocs), Decimal(0))),
        "newly_locked": (out.get("locked") or {}).get(u, "0"),
        "holds": cin.get(u, Decimal(0)) == cout.get(u, Decimal(0)),
    } for u in sorted(units)]
    return {
        "consumed": consumed,
        "uncited": [c for c in consumed if not c["cited"]],
        "previous_execution": sc["prev_id"],
        "previously_locked": prev_locked or None,
        "allocations": allocations,
        "locked": out.get("locked"),
        "carryover": out.get("carryover"),
        "computed_values": out.get("computed_values"),
        "credit_limit": out.get("credit_limit"),
        "rejected_links": res["result"].get("rejected_links", []),
        "redacted_links": res["result"].get("redacted_links", []),
        "conservation": conservation,
    }


def outcome_key(run):
    if not run["ok"]:
        return "FAIL: " + re.sub(r"\(line \d+, position \d+\)", "", run["error"])[:160]
    led = run["ledger"]
    parts = []
    for a in led["allocations"]:
        amt = ", ".join(f"{v} (unit {u})" for u, v in a["amounts"].items()) or "name only, no value"
        parts.append(f"{a['receiver']}: {amt}")
    if led["locked"]:
        parts.append("locked " + ", ".join(f"{v} (unit {u})" for u, v in led["locked"].items()))
    return " · ".join(parts) or "No allocation, nothing locked"


# --------------------------------------------------------------------------- conclusions

def conclusions(t, facts, runs, fx):
    ok = [r for r in runs if r["ok"]]
    M = len(runs)
    ex_any = "Any" in facts["executor_rule_raw"]
    payers = set(fx.get("parked_by", {}).values())
    exec_dims = {i["name"] for i in facts["inputs"] if i["attribution"] == "Executor"}
    out = []

    def obs(text, support, premises, severity="warn"):
        out.append({"text": text, "evidence": "observed", "support": sorted(r["id"] for r in support),
                    "n": len(support), "m": M, "premises": premises, "severity": severity})

    # C1 (counterfactual): the receiver follows the executor. Two runs identical except for who executes,
    # where each run pays value to its own executor. An address that merely happens to equal the executor
    # (e.g. a receiver named by the spender who then executes) does not count.
    def paid_to_self(r):
        return any(not a["name_only"] and a["receiver"] == r["executor_name"] for a in r["ledger"]["allocations"])

    def others(r):
        return json.dumps({k: v for k, v in r["choice"].items() if k != "executor"}, sort_keys=True)

    by_rest = {}
    for r in ok:
        by_rest.setdefault(others(r), []).append(r)
    s = []
    for g in by_rest.values():
        selfpaid = [r for r in g if paid_to_self(r)]
        if len({r["executor_name"] for r in selfpaid}) > 1:
            s += [r for r in selfpaid if r["executor_name"] not in payers
                  and any(c["cited"] and c["parked_by"] != r["executor_name"] for c in r["ledger"]["consumed"])]
    if s:
        names = sorted({r["executor_name"] for r in s})
        obs(f"An executor who did not park the value can pay it to themselves ({', '.join(names)} did in the explored runs). "
            "Changing only who executes changed who was paid.",
            s, ["rule: " + facts["executor_rule"] + " can execute",
                "observed: with all other inputs equal, the receiver changed with the executor"])
        out[-1]["caveats"] = ["Engine output only. Whether the DNA lets one agent consume links parked for another "
                              "executor is not visible from the engine."]

    # C2: the payer, acting as executor, can choose between destinations.
    groups = {}
    for r in ok:
        if r["executor_name"] in payers:
            key = json.dumps({k: v for k, v in r["choice"].items() if k not in exec_dims}, sort_keys=True)
            groups.setdefault(key, []).append(r)
    s, dests = [], set()
    for g in groups.values():
        recv = {tuple(sorted(a["receiver"] for a in r["ledger"]["allocations"] if not a["name_only"])) for r in g}
        if len(recv) > 1:
            s += g
            dests |= {x for t_ in recv for x in t_}
    if s:
        obs(f"The payer, acting as executor, can change where the value goes (destinations seen: {', '.join(sorted(dests))}).",
            s, ["rule: a role member can also be the executor", "rule: executor-provided inputs exist",
                "observed: changing only executor-provided inputs changed the receiver"])

    # C3: addresses supplied as role data are not guaranteed payment.
    by_name = {i["name"]: i for i in facts["inputs"]}
    for i in facts["inputs"]:
        if i["verification"] != "Authenticated but unverified" or i["schema_type"] != "string":
            continue
        miss = []
        for r in ok:
            env = r["input"]["consumed_inputs"].get(i["name"]) or r["input"]["inputs"].get(i["name"])
            key = env.get("data") if isinstance(env, dict) else None
            if key and r["ledger"]["allocations"] and not any(a["receiver_key"] == key and not a["name_only"]
                                                              for a in r["ledger"]["allocations"]):
                miss.append(r)
        if miss:
            obs(f"Whoever is named in {i['name']} is not guaranteed payment: in {len(miss)} runs the value went elsewhere.",
                miss, [f"rule: {i['name']} is data from the {i['supplier']}",
                       "observed: runs where that address received nothing"])

    # C4: locked value under executor_rules Any (escalates the lint warning).
    s = [r for r in ok if r["ledger"]["locked"]]
    if s and ex_any:
        obs("This agreement does create locked value while anyone can execute it. The lock is carried only on the "
            "executing agent's own chain.", s, ["lint: code writes output.locked", "rule: executor_rules = Any",
                                                 "observed: runs with a non-empty locked output"])
        out[-1]["caveats"] = ["The DNA is documented to reject a lock created under executor_rules Any. "
                              "These are engine outputs; they may never commit as RAVEs."]

    # C5: parked value consumed without allocation (lost).
    s = [r for r in ok if r["ledger"]["uncited"]]
    if s:
        obs("Parked value can be consumed without any allocation citing it. That value is lost.", s,
            ["rule: only cited sources are conserved", "observed: consumed inputs not cited by any allocation"], "danger")
    else:
        out.append({"text": f"No run consumed parked value without citing it (0 of {len(ok)} successful runs). "
                            "This is not a guarantee: it covers only the explored inputs.",
                    "evidence": "observed", "n": 0, "m": M, "premises": ["observed: every consumed source cited"],
                    "severity": "info", "support": []})
    return out


# --------------------------------------------------------------------------- main

def process(fixture_path):
    fx = json.loads(Path(fixture_path).read_text())
    t = load_template(fx["template"], fx["instance_file"])
    facts = derive_facts(t)
    scenarios, excluded = build_scenarios(t, fx)
    results = {r["id"]: r for r in harness("run", [s["run"] for s in scenarios])}

    # Engine-side schema checks: inputs against the runtime signature, outputs against the output signature.
    checks = []
    for s in scenarios:
        checks.append({"id": s["id"] + ":in", "kind": "inputs", "schema": t["signature"], "instance": s["run"]["input"]})
        res = results[s["id"]]
        if res["ok"]:
            o = {k: v for k, v in res["result"]["output"].items() if v is not None}
            checks.append({"id": s["id"] + ":out", "kind": "json", "schema": t["output_signature"], "instance": o})
    for f in ("agreement_definition_input.json", "runtime_input_signature.json", "output_signature.json"):
        checks.append({"id": "schema:" + f, "kind": "schema", "schema": json.loads((t["dir"] / f).read_text())})
    chk = {c["id"]: c for c in harness("check", checks)}

    runs = []
    parked_by = fx.get("parked_by", {})
    for s in scenarios:
        res = results[s["id"]]
        fp = hashlib.sha256(json.dumps({"template": t["name"], "library_commit": LIB_COMMIT,
                                        "code_sha256": t["code_sha256"], "run": s["run"],
                                        "engine": "rave_engine 0.13.0"}, sort_keys=True).encode()).hexdigest()
        run = {
            "id": s["id"], "choice": s["choice"], "executor_name": s["executor_name"],
            "executor": s["run"]["executor"], "input": s["run"]["input"], "ok": res["ok"],
            "fingerprint": fp[:16],
            "input_check": chk.get(s["id"] + ":in"),
        }
        if res["ok"]:
            run["ledger"] = build_ledger(s, res, facts, parked_by)
            run["output_check"] = chk.get(s["id"] + ":out")
            run["raw_output"] = res["result"]
            run["executed_timestamp"] = res["preset"]["executed_timestamp"]
        else:
            run["error"] = res["error"]
            run["deferrable"] = res.get("deferrable", False)
        run["outcome"] = outcome_key(run)
        runs.append(run)

    outcomes = {}
    for r in runs:
        outcomes.setdefault(r["outcome"], []).append(r["id"])
    observed_fields = sorted({k for r in runs if r["ok"] for k, v in r["raw_output"]["output"].items()
                              if v not in (None, [], {})})
    never_produced = [f for f in facts["outputs_required"] if f not in observed_fields]

    beneficiaries = {}
    for r in runs:
        if not r["ok"]:
            continue
        for a in r["ledger"]["allocations"]:
            b = beneficiaries.setdefault(a["receiver"], {"name": a["receiver"], "received_in": [], "name_only_in": [],
                                                          "traces": {}})
            (b["name_only_in"] if a["name_only"] else b["received_in"]).append(r["id"])
            for tr in a["trace"]:
                b["traces"][tr["source"]] = tr
    for b in beneficiaries.values():
        b["traces"] = list(b["traces"].values())
        b["nothing_in"] = [r["id"] for r in runs if r["ok"] and r["id"] not in b["received_in"]]

    warnings = lint(t, facts)
    if never_produced:
        warnings.append({"id": "required_never_produced", "severity": "warn",
                         "text": f"The output signature requires {', '.join(never_produced)}, but no explored run produced it.",
                         "basis": "output_signature.json required vs observed outputs"})
    concl = conclusions(t, facts, runs, fx)
    # Escalation: a lint warning becomes an observed fact when exploration produced the effect.
    for w in warnings:
        if w["id"] == "locked_output" and any(c["text"].startswith("This agreement does create locked value") for c in concl):
            w["status"] = "escalated"
        else:
            w.setdefault("status", "open")

    return {
        "template": t["name"],
        "title": t["instance"].get("title", t["name"]),
        "source": {"library": "unytco/smart_agreement_library", "commit": LIB_COMMIT,
                   "template_dir": f"library/{t['name']}", "instance_file": fx["instance_file"],
                   "code_sha256": t["code_sha256"]},
        "snapshot": {"mode": fx["mode"], "note": fx["note"], "people": fx["people"], "parked_by": parked_by,
                     "assumed_timestamp": runs[0].get("executed_timestamp") if runs and runs[0]["ok"] else TIMESTAMP_MICROS,
                     "previous_executions": {k[1:]: {"author": v["author"], "output": v["output"]}
                                             for k, v in fx.get("previous_executions", {}).items()}},
        "facts": facts,
        "rule_statements": rule_statements(t, facts),
        "warnings": warnings,
        "conclusions": concl,
        "exploration": {
            "dimensions": [{"name": d["name"], "label": d["label"], "values": [describe_choice(v) for v in d["values"]]}
                           for d in fx["dimensions"]],
            "excluded": excluded,
            "runs_total": len(runs), "runs_ok": sum(r["ok"] for r in runs),
            "outcomes": [{"outcome": k, "runs": v} for k, v in sorted(outcomes.items(), key=lambda kv: -len(kv[1]))],
        },
        "outputs": {"declared": facts["outputs_declared"], "required": facts["outputs_required"],
                    "observed": observed_fields, "required_never_produced": never_produced},
        "schema_checks": {f: chk["schema:" + f] for f in ("agreement_definition_input.json",
                                                          "runtime_input_signature.json", "output_signature.json")},
        "beneficiaries": list(beneficiaries.values()),
        "runs": runs,
    }


def main():
    data = {
        "engine": {"crate": "rave_engine", "version": "0.13.0", "where": "Native build, outside a Holochain conductor"},
        "agents": AGENTS,
        "templates": [process(HERE / "fixtures" / f) for f in sys.argv[1:]],
    }
    out = HERE / "inspector_data.json"
    out.write_text(json.dumps(data, indent=1))
    for t in data["templates"]:
        e = t["exploration"]
        print(f"{t['template']}: {e['runs_ok']}/{e['runs_total']} runs ok, {len(e['outcomes'])} outcomes, "
              f"{len(e['excluded'])} excluded, {len(t['conclusions'])} conclusions, {len(t['warnings'])} warnings")


if __name__ == "__main__":
    main()
