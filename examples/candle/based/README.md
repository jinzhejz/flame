# Candle Based Example

This example runs the HazyResearch Based language model through a Flame Rust service. It is adapted from the current Hugging Face Candle `candle-examples/examples/based` example and uses the current Flame Rust typed API.

Based is a completion model, not an instruction-tuned chat model. The client defaults use sampled decoding (`--temperature 0.8 --top-p 0.95 --repeat-penalty 1.3`) because deterministic argmax decoding can fall into repeated text. Use `--temperature 0` when deterministic output is required.

## Binaries

- `candle-based-example-service` loads the model once per Flame service instance and serves typed generation requests.
- `candle-based-example` creates a Flame session, sends model options as typed common data, invokes one generation task, prints the generated text, and closes the session.

## Build

```bash
cargo build -p candle-based-example --release
```

## Run

Register or deploy `candle-based-example.yaml` so the `candle-based-example` application starts `/usr/local/flame/examples/candle/based/candle-based-example-service`, then run:

```bash
cargo run -p candle-based-example --bin candle-based-example --release -- \
  --app candle-based-example \
  --prompt "The future of distributed inference is" \
  --sample-len 64 \
  --which 360m
```

The first service start downloads the model config, safetensors file, and GPT-2 tokenizer from Hugging Face unless local files are provided with `--config-file`, `--weight-files`, and `--tokenizer-file`.
