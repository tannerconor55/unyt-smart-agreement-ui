fn main() {
    let lock = std::fs::read_to_string("Cargo.lock").unwrap_or_default();
    let mut ver = "unknown".to_string();
    let mut it = lock.lines();
    while let Some(l) = it.next() {
        if l.trim() == "name = \"rave_engine\"" {
            if let Some(v) = it.next() { ver = v.trim().trim_start_matches("version = ").trim_matches('"').to_string(); }
        }
    }
    println!("cargo:rustc-env=RAVE_ENGINE_VERSION={ver}");
    println!("cargo:rerun-if-changed=Cargo.lock");
}
