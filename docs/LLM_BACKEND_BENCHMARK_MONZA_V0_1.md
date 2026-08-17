# LLM backend benchmark — Monza v0.1

## Scope

This benchmark compares the current full-session LLM analysis on one real LMU session:

- track: `Autodromo Nazionale Monza`;
- vehicle context: `LMP2_ELMS`;
- deterministic source: session `2026-08-15T20_03_24Z`;
- reference lap: lap 10, `97.500 s`;
- comparisons: 10;
- analyzer contract: `llm_analysis 3.10.8.5.4`;
- local context requested by Race Engineer: 8192 tokens.

This is an operational checkpoint, not a general model benchmark. It measures one session on one machine and must not be generalized to every track or telemetry set.

## Models

| Label | Runtime model |
|---|---|
| DeepSeek Pro | `deepseek-v4-pro` |
| Qwen local 14B | Ollama alias `ingenierov3` |
| Qwen local 27B | Ollama alias `qwen38-27b-iq3m`, built from `hf.co/bartowski/Qwen3.8-27B-GGUF:IQ3_M` |

The 27B model was observed in `ollama ps` as 13 GB and 100% GPU. No CPU offload was present. Local model files and Ollama manifests remain local and are not repository artifacts.

## Full-session results

| Model | Wall time | Summary fallbacks | Episode repairs | Priority findings | Priority regions | Optional global items pruned | Validator |
|---|---:|---:|---:|---:|---:|---:|---|
| DeepSeek Pro | approximately 4 min | 3 | 7 | 19 | 7 | 0 | PASS |
| Qwen local 14B | 8.0 min | 6 | 17 | 25 | 7 | 1 | PASS |
| Qwen local 27B | 33.7 min | 3 | 7 | 17 | 7 | 0 | PASS |

The DeepSeek duration is reconstructed from the first and last saved debug artifacts. Both local durations were measured with a PowerShell stopwatch and include the initial model transition/load.

DeepSeek reported 74 HTTP requests, 176,617 input tokens, 12,272 output tokens and an estimated cost of USD 0.019092 for this run.

## Output parity

All three models converged on the same final three-zone plan:

1. T6 — Lesmo 1: brake approximately 16 m later, with the authorized throttle sequence and release-point cue.
2. T8–T9 — Variante Ascari: reapply throttle approximately 18 m later and sustain the reference reapplication.
3. T11 — Curva Alboreto: release brake approximately 22 m earlier, with the authorized partial/release/reapplication throttle sequence.

Python remained the owner of every numeric target and the final renderer. Model differences affected intermediate prioritization and optional supporting text, not the final authorized cues.

The 27B final render differed from Pro in one supporting episode line. The 14B render added one conservative steering limitation and selected a different supporting episode line. Both local outputs passed `validate_llm_analysis_output.py`.

## H5.2 selection spot-check

The short H5.2 controlled-code test showed:

- Qwen 27B matched the Pro zone selection and priority order 3/3 on Monza;
- Qwen 14B overlapped with Pro on 2/3 Monza zones but ordered the largest temporal change below a smaller one;
- DeepSeek Flash overlapped with Pro on 1/3 Monza zones and 2/3 Imola zones;
- every produced H5.2 artifact passed its dedicated validator.

This spot-check supports Pro and Qwen 27B as the more stable selectors under the current under-specified “relevant zones” prompt. It does not establish general accuracy.

## Recommendation

- Keep DeepSeek Pro as the default general backend: it was fastest here, required limited recovery and had negligible per-session cost.
- Use Qwen 14B (`ingenierov3`) as the recommended local/offline backend. It was four times faster than the local 27B and produced the same final plan, although it relied more heavily on deterministic repairs and fallbacks.
- Keep Qwen 27B as an experimental maximum-quality local backend. Its internal behavior was closer to Pro, but the 33.7-minute wall time did not improve the final authorized plan in this session.
- Do not promote Flash as the default from these tests.
- Repeat the benchmark on independent tracks before treating these rankings as a general model policy.

## Reproduction

The dedicated 27B entry point assumes this local Ollama alias:

```powershell
ollama create qwen38-27b-iq3m -f ".\Modelfile-qwen38"
```

Run the complete 27B analysis:

```powershell
python llm_analysis_qwen3_8_27b_iq3m.py "data\generated\analysis\SESSION.json"
```

Run the normal local 14B analysis:

```powershell
python llm_analysis.py "data\generated\analysis\SESSION.json"
```

Validate either generated output:

```powershell
python validate_llm_analysis_output.py "data\generated\llm_results\SESSION\OUTPUT.json"
```

The `Modelfile` inputs, telemetry, debug traces and generated LLM results remain local/untracked.
