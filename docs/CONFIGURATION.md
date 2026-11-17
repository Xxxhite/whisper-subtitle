# Configuration guide

[简体中文 quick start](../README.md) · [English quick start](../README.en.md)

Copy `config.example.json` to `config.json` and edit the settings you need. The
example lists all supported configuration keys. Command-line options override
their corresponding settings for the current run.

## Translation API

Settings under `translation`:

| Key | Default / meaning |
| --- | --- |
| `backend` | `api`; `auto` uses the same routing; `sakura` selects local Japanese translation |
| `base_url` | Provider URL; the example uses `https://api.deepseek.com` |
| `model` | Provider model ID; the example uses `deepseek-flash` |
| `api_key` | Your key; empty in the shared template |
| `api_key_env` | `SUBTITLE_API_KEY` |
| `instructions` | Additional translation preferences, terminology, or tone |
| `batch_size` | 20 subtitle entries per request |
| `context_lines` | 3 preceding and 3 following entries |
| `timeout_seconds` | 120 seconds per request |
| `max_retries` | 3 extra attempts after a failed request |

Use the model ID and URL required by your provider. The client appends
`/chat/completions` unless the URL already ends with it. Include `/v1` yourself if
your provider requires it. Remote endpoints must use HTTPS; local services can
use HTTP on a loopback address.

The API must accept Chat Completions requests with `model`, `messages`, and
`stream: false`, returning text in `choices[0].message.content`. Subtitle text and
context are sent to the API; recognition and media processing stay local.

Keys are read from the configured environment variable first, then `api_key`,
then a hidden prompt in an interactive terminal. For the current PowerShell session:

```powershell
$env:SUBTITLE_API_KEY = "your-api-key"
```

Chinese input is always converted locally to Simplified Chinese. API translation
supports Japanese, English, and Korean. Candidate-term extraction with `--terms`
uses the API even when normal translation uses Sakura; see the
[dictionary guide](DICTIONARY.md#generate-candidate-terms).

### Japanese translation style

Japanese API requests automatically include `prompts/ja_zh_guidelines.txt` for
natural wording, tone, pronouns, terminology, and subtitle completeness. Edit that
file for shared style rules or use `translation.instructions` for personal
preferences. Changes refresh Japanese API translations while retaining recognition.
Adaptation and attribution are recorded in [prompts/README.md](../prompts/README.md).

## Recognition

Settings at the top level of `config.json`:

| Key | Default / meaning |
| --- | --- |
| `quality` | `high` or `normal`; default `high` |
| `whisper_model` | `auto`, a model name, or a local CTranslate2 model directory |
| `language` | `auto`, `zh`, `ja`, `en`, or `ko` |
| `device` | `auto`, `cpu`, or `cuda` |
| `compute_type` | `auto` or a supported inference precision |
| `download_root` | `models`; download/cache location |
| `vad_filter` | `null` follows the preset; `true`/`false` overrides it |
| `vad_threshold` | 0.5; applies when pre-recognition VAD is enabled |
| `review_audio` | `true`; enables focused audio review and subtitle refinement |

### Presets

| Setting | `high` (default) | `normal` |
| --- | --- | --- |
| Automatic model | large-v2 | turbo |
| Automatic GPU precision | FP16 | INT8/FP16 |
| Automatic CPU precision | FP32 | INT8 |
| Pre-recognition VAD | Off | On |
| Word timing | On | Off |
| Previous-text conditioning | Off | On |

`high` prioritizes quiet speech and detailed timing at a higher processing cost.
`normal` is faster. A specific model, precision, or VAD setting overrides the preset.

```powershell
# Faster preset with pre-recognition VAD disabled for quiet speech
python main.py "sample.mp4" -q normal --no-vad

# Override VAD or inference precision
python main.py "sample.mp4" --vad --vad-threshold 0.25
python main.py "sample.mp4" --model large-v2 --compute-type float16
```

High-quality review can split long entries, check suspect source words and
boundaries, recover quiet speech, and filter recognition artifacts. Japanese
cross-model checks require large-v2 and an existing local turbo model. These
checks use local resources and add processing time; missing alternate models
leave the corresponding checks pending. Use `--report` to inspect remaining
uncertainties, `-q normal` to skip focused refinement, or `review_audio: false` to
disable audio review.

### Models and GPU libraries

Missing Whisper models download from Hugging Face to `download_root`. A complete
local `models/faster-whisper-large-v2/` directory is preferred for `large-v2`.
Use `--model "D:\models\my-model"` to select another CTranslate2 directory.
English-only `.en` models are intended for English input.

`device: auto` selects an available NVIDIA GPU, otherwise CPU. CUDA inference
requires compatible CUDA/cuDNN libraries. Local libraries can be placed in
`runtime/cuda/`; see [runtime provenance](../runtime/README.md). The application
loads them for its own process. For CPU inference:

```powershell
python main.py "sample.mp3" --device cpu --model small
```

## Local Sakura

Prepare these resources, or change their paths under `sakura`:

- `models/Sakura-Galtransl-7B-v3.7.gguf` from the
  [Sakura model page](https://huggingface.co/SakuraLLM/Sakura-GalTransl-7B-v3.7).
- `runtime/llama/llama-server.exe` and its matching libraries from
  [llama.cpp](https://github.com/ggml-org/llama.cpp/tree/master/tools/server).

| Key | Default / meaning |
| --- | --- |
| `server_path` | `runtime/llama/llama-server.exe` |
| `model_path` | `models/Sakura-Galtransl-7B-v3.7.gguf` |
| `gpu_layers` | 24; set to 0 for CPU inference |
| `device` | `Vulkan0`; adjust for the installed runtime and hardware |
| `context_size` | 4096 tokens |
| `batch_size` | 8 subtitle entries |
| `startup_timeout_seconds` | 180 seconds |
| `timeout_seconds` | 180 seconds per request |
| `glossary` | Legacy global hints, one `source->translation # note` per line; prefer the shared dictionary for routine edits |

```powershell
python main.py "sample.mp4" --translator sakura
```

Sakura translates Japanese into Chinese locally. When the language is still
implicit `auto`, selecting Sakura changes recognition to `ja`. Explicit
`--language` or a specific configured language takes precedence; use
`--language auto` to request detection explicitly. Chinese remains local
conversion, and English/Korean require the API backend.

The application starts its own background server and closes it when the task
finishes or stops. Invalid output and generation limits trigger bounded retries;
a persistent failure saves translation progress and pauses the task. Rerun the
same command to continue. To translate every entry again, use `--retranslate`.

Models and runtimes are separate local resources with their own licenses. See
the model page and [runtime notes](../runtime/README.md) for source records.

## Vocal separation

Prepare `runtime/separate/separate.exe` with its matching runtime and
`models/UVR_MDXNET_KARA_2.onnx`. These resources are excluded from Git. Their local
source and runtime setup are recorded in [runtime/README.md](../runtime/README.md).

Settings under `separation`:

| Key | Default / meaning |
| --- | --- |
| `enabled` | `false`; separate vocals before recognition |
| `export_vocals` | `false`; export vocals and automatically enable separation |
| `executable_path` | `runtime/separate/separate.exe` |
| `model_path` | `models/UVR_MDXNET_KARA_2.onnx` |
| `denoise` | `false`; optional extra denoising |
| `chunks` | 15 seconds per processing chunk |
| `margin` | 44100 overlap samples |

```powershell
python main.py "sample.mp4" -s
python main.py "sample.mp4" -v -Q
```

`-s` separates vocals before recognition; `-v` also exports `.vocals.wav` beside
the subtitles as stereo 44.1 kHz PCM16. Subtitles retain the original media name
and timeline. The separator finishes before recognition starts; cached vocals
are reused on later runs. First use can take longer while processing functions
are compiled.

Separation can help with background music. Check the exported vocals for quiet
speech, whispers, or overlapping speakers, where useful details may be lost.

## Output and cleanup

Top-level settings:

| Key | Default / meaning |
| --- | --- |
| `output_dir` | `source`; use the input media directory, or set a directory path |
| `quiet` | `false`; `true` hides sentence logs while keeping progress and errors |
| `dictionary_file` | `dictionary.json`; see the [dictionary guide](DICTIONARY.md) |
| `merge_repeated_sounds` | `true`; combine adjacent repetitions of recognized sound effects |
| `minimum_subtitle_seconds` | 0.8; set to 0 to disable minimum-duration extension |
| `format_cleanup` | `true`; clean whitespace and redundant punctuation in translations |

Use `--sounds keep` to keep repeated sound entries separate. With `--report`,
the application writes a UTF-8 `.quality.csv` containing review findings; see
[report usage](DICTIONARY.md#optional-quality-report).

SRT records start and end times. LRC uses sentence-level timestamps and blank
entries for gaps and the end. Manual edits to exported subtitles stay in those
files; future runs read the cached transcript and translations.

## Paths and caching

Configured relative paths resolve from the project root, including paths in an
alternate config file. `output_dir: "source"` selects the media directory.
Relative command-line input, `--config`, `--dict`, and `--output-dir` paths resolve
from the terminal's current directory.

Tasks are stored in `.cache/<file-content-hash>/task.json`. Recognition is saved
when the initial transcription finishes; translation and local review save
progress as they run. The same command resumes completed work.

| Change | Effect on the next run |
| --- | --- |
| Model, quality preset, device, precision, or decoder settings | Transcribe again and refresh translation |
| Enable/disable separation or change its processing settings | Transcribe using the selected audio and refresh translation |
| API endpoint/model, translation instructions, or Japanese API guidelines | Reuse recognition; refresh translation |
| Switch API/Sakura | Reuse recognition; refresh translation |
| Dictionary | Refresh affected entries; post-rules can reuse saved model text |
| Output format/directory, quiet mode, vocal export, or repeated-sound grouping | Reuse recognition and translation |

`--retranslate` requests fresh translations using the current transcript.
`--force-transcribe` resets recognition and translation for that task. Backups
and review evidence stay in the task directory for inspection.
