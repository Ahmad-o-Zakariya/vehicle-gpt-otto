#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

model="${VEHICLEGPT_MODEL_PATH:-models/qwen35-2b/Qwen3.5-2B-Q4_K_M.gguf}"
[[ -f "$model" ]] || { echo "Model file not found: $model" >&2; exit 2; }

runtime=""
if [[ -n "${LLAMA_HOME:-}" ]]; then
  for candidate in "$LLAMA_HOME/llama-server" "$LLAMA_HOME/build/bin/llama-server" "$LLAMA_HOME/bin/llama-server"; do
    if [[ -x "$candidate" ]]; then runtime="$candidate"; break; fi
  done
else
  runtime="$(command -v llama-server || true)"
  if [[ -z "$runtime" && -d "$HOME/.local/opt" ]]; then
    while IFS= read -r candidate; do
      if [[ -x "$candidate" ]]; then runtime="$candidate"; break; fi
    done < <(find "$HOME/.local/opt" -maxdepth 4 -type f -name llama-server -print 2>/dev/null | sort -V)
  fi
fi
[[ -n "$runtime" && -x "$runtime" ]] || {
  echo "Executable llama-server not found. Set LLAMA_HOME or add it to PATH." >&2
  exit 127
}

runtime_dir="$(dirname "$runtime")"
export PATH="$runtime_dir:$PATH"
lib_dirs=("$runtime_dir" "$(dirname "$runtime_dir")/lib")
if [[ -n "${LLAMA_HOME:-}" ]]; then
  lib_dirs+=("$LLAMA_HOME/lib" "$LLAMA_HOME/build/bin")
fi
for lib_dir in "${lib_dirs[@]}"; do
  if [[ -n "$lib_dir" && -d "$lib_dir" ]]; then
    case ":${LD_LIBRARY_PATH:-}:" in *":$lib_dir:"*) ;; *) export LD_LIBRARY_PATH="$lib_dir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" ;; esac
  fi
done

gpu_layers="${LLAMA_GPU_LAYERS:-auto}"
ctx_size="${LLAMA_CTX_SIZE:-2048}"
fit_target="${LLAMA_FIT_TARGET:-768}"
parallel="${LLAMA_PARALLEL:-1}"
host="${LLAMA_HOST:-127.0.0.1}"
port="${LLAMA_PORT:-8080}"
[[ "$host" == "127.0.0.1" || "$host" == "localhost" || "$host" == "::1" ]] || {
  echo "llama-server must remain bound to loopback" >&2; exit 2;
}

echo "Model: $model"
echo "Runtime: $runtime"
echo "GPU offload layers: $gpu_layers (no automatic CPU fallback)"
echo "Context=$ctx_size fit=on fit-target=${fit_target}MiB parallel=$parallel endpoint=http://${host}:${port}"
if [[ "$gpu_layers" == "0" ]]; then echo "Explicit CPU-only fallback selected by LLAMA_GPU_LAYERS=0."; fi

exec "$runtime" \
  --model "$model" \
  --host "$host" \
  --port "$port" \
  --ctx-size "$ctx_size" \
  --n-gpu-layers "$gpu_layers" \
  --fit on \
  --fit-target "$fit_target" \
  --parallel "$parallel" \
  --jinja \
  --reasoning off \
  --reasoning-budget 0 \
  --reasoning-format deepseek
