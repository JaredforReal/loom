# Out‑of‑the‑box Examples

Zero‑background path (≈10 minutes):

1. Build core (release)
2. Run basic pub/sub example
3. Switch router policy (local vs cloud) and observe latency/privacy differences
4. Add a Python gRPC plugin without writing Rust

Example set

- Voice assistant: Mic → wake‑word (WASM) → Router → cloud LLM → TTS action
- Camera pipeline: Camera → local detector (WASM/local ML) → annotated events → UI/TTS
- Workflow bridge: Loom topic ↔ n8n → email/calendar task
- Memory agent: dialog events → short‑term context + long‑term memory → action selection
- Desktop automation: system events → rules/LLM tools → safe actions
- Hybrid routing demo: local small model + cloud LLM, policy‑driven switching

Locations

- Minimal examples: `core/examples/`
- End‑to‑end demos: `examples/`

## Minimal: ActionBroker + Echo TTS

A tiny example that registers a native capability `tts.echo` and invokes it through the ActionBroker.

Run:

```bash
cd core
cargo run --example echo_tts
```

Expected output:

```
[EchoTts] speaking: Hello Loom!
ActionResult: status=0, error=None, output={"spoken":"Hello Loom!"}
```

If you see a build error mentioning libclang (bindgen), install the system packages (Debian/Ubuntu):

```bash
sudo apt-get update
sudo apt-get install -y clang libclang-dev pkg-config build-essential
```

Then re-run the example command.
