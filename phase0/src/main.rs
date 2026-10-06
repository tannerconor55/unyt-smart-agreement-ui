//! Phase 0 harness: runs the real `rave_engine` outside a Holochain conductor.
//!
//! Subcommands:
//!   keys                  -> JSON map of deterministic agent keys and action hashes (for fixtures)
//!   run < scenarios.json  -> runs each scenario through RhaiEngine::execute, prints JSON results
//!
//! A scenario is { "id", "code_path", "input", "ea_id", "executor", "timestamp_micros" }.
//! Hashes and keys are base64 strings as produced by `keys`.
//! Nothing here computes a financial value: every output is what the engine returned.

use hdi::prelude::*;
use rave_engine::prelude::*;
use serde_json::{json, Value};
use std::io::Read;

fn agent(seed: u8) -> AgentPubKey {
    AgentPubKey::from_raw_32(vec![seed; 32])
}
fn action(seed: u8) -> ActionHash {
    ActionHash::from_raw_32(vec![seed; 32])
}

fn keys() -> Value {
    let mut agents = serde_json::Map::new();
    for (name, seed) in [("alice", 11u8), ("bob", 12), ("carol", 13), ("dave", 14), ("executor_x", 15)] {
        agents.insert(name.into(), json!(AgentPubKeyB64::from(agent(seed)).to_string()));
    }
    let mut hashes = serde_json::Map::new();
    for (name, seed) in [
        ("agreement", 100u8),
        ("link_a", 101),
        ("link_b", 102),
        ("link_c", 103),
        ("link_d", 104),
        ("prev_rave_1", 110),
        ("prev_rave_2", 111),
    ] {
        hashes.insert(name.into(), json!(ActionHashB64::from(action(seed)).to_string()));
    }
    json!({ "agents": agents, "hashes": hashes })
}

fn run_one(s: &Value) -> Value {
    let id = s["id"].clone();
    let fail = |stage: &str, e: String| json!({ "id": id, "ok": false, "stage": stage, "error": e });

    let code_path = match s["code_path"].as_str() {
        Some(p) => p,
        None => return fail("scenario", "missing code_path".into()),
    };
    let code = match std::fs::read_to_string(code_path) {
        Ok(c) => c,
        Err(e) => return fail("scenario", e.to_string()),
    };
    let ea_id = match ActionHashB64::from_b64_str(s["ea_id"].as_str().unwrap_or("")) {
        Ok(h) => ActionHash::from(h),
        Err(e) => return fail("scenario", format!("ea_id: {e:?}")),
    };
    let executor = match AgentPubKeyB64::from_b64_str(s["executor"].as_str().unwrap_or("")) {
        Ok(a) => AgentPubKey::from(a),
        Err(e) => return fail("scenario", format!("executor: {e:?}")),
    };
    let ts = Timestamp::from_micros(s["timestamp_micros"].as_i64().unwrap_or(0));
    let ts_string = ts.to_string();

    let script = match rmp_serde::to_vec(&code) {
        Ok(b) => b,
        Err(e) => return fail("encode", e.to_string()),
    };
    let result = RhaiEngine::new().execute(
        &s["input"],
        script,
        Some(PresetVariables { ea_id, executor, executed_timestamp: ts }),
    );
    match result {
        Ok(out) => json!({
            "id": id,
            "ok": true,
            "engine": { "crate": "rave_engine", "version": env!("RAVE_ENGINE_VERSION") },
            "preset": {
                "ea_id": s["ea_id"], "executor_pub_key": s["executor"], "executed_timestamp": ts_string
            },
            "result": serde_json::to_value(&out).unwrap_or(Value::Null),
        }),
        Err(e) => {
            let deferrable = is_deferrable_host_error(&e);
            json!({
                "id": id, "ok": false, "stage": "execute",
                "deferrable": deferrable,
                "error": e.to_string(),
            })
        }
    }
}

/// Engine-side schema checks. Each request: { "id", "kind": "schema"|"inputs"|"json", "schema", "instance"? }.
/// "schema" -> is_valid_schema; "inputs" -> validate_rave_inputs; "json" -> validate_json_schema.
fn check_one(c: &Value) -> Value {
    use rave_engine::prelude::json_schema_validator as v;
    let id = c["id"].clone();
    let schema = &c["schema"];
    let instance = &c["instance"];
    let mismatch = |m: v::SchemaMismatch| {
        json!({ "id": id, "ok": false, "path": m.path(), "reason": m.reason(), "over_budget": m.is_over_budget() })
    };
    match c["kind"].as_str() {
        Some("schema") => match v::is_valid_schema(schema) {
            Ok(()) => json!({ "id": id, "ok": true }),
            Err(e) => json!({ "id": id, "ok": false, "reason": e }),
        },
        Some("inputs") => match v::validate_rave_inputs(schema, instance) {
            Ok(()) => json!({ "id": id, "ok": true }),
            Err(m) => mismatch(m),
        },
        Some("json") => match v::validate_json_schema(schema, instance) {
            Ok(()) => json!({ "id": id, "ok": true }),
            Err(m) => mismatch(m),
        },
        _ => json!({ "id": id, "ok": false, "reason": "unknown kind" }),
    }
}

fn main() {
    let cmd = std::env::args().nth(1).unwrap_or_default();
    match cmd.as_str() {
        "keys" => println!("{}", serde_json::to_string_pretty(&keys()).unwrap()),
        "run" => {
            let mut buf = String::new();
            std::io::stdin().read_to_string(&mut buf).expect("read stdin");
            let scenarios: Value = serde_json::from_str(&buf).expect("scenarios JSON");
            let results: Vec<Value> = scenarios
                .as_array()
                .expect("array of scenarios")
                .iter()
                .map(run_one)
                .collect();
            println!("{}", serde_json::to_string_pretty(&results).unwrap());
        }
        "check" => {
            let mut buf = String::new();
            std::io::stdin().read_to_string(&mut buf).expect("read stdin");
            let checks: Value = serde_json::from_str(&buf).expect("checks JSON");
            let results: Vec<Value> = checks.as_array().expect("array").iter().map(check_one).collect();
            println!("{}", serde_json::to_string_pretty(&results).unwrap());
        }
        _ => {
            eprintln!("usage: harness keys | harness run < scenarios.json | harness check < checks.json");
            std::process::exit(2);
        }
    }
}
