# whisper-subtitle

[简体中文](README.md) | English

A minimal command-line tool for one local audio or video file at a time. Transcribe Chinese, Japanese, English, or Korean with faster-whisper, then produce Simplified Chinese subtitles. Export Chinese LRC subtitles by default, with optional SRT and source-language subtitles.

Japanese, English, and Korean use a Chat Completions-compatible API by default. Chinese is converted to Simplified Chinese locally without a translation model. Select `--translator sakura` to use a local Japanese-to-Chinese model.

See [Project layout and version control](docs/PROJECT.md) for the folder structure and local-resource rules, and [Dictionary guide](docs/DICTIONARY.md) for terminology configuration.

## 1. Installation

Python 3.10-3.12 is recommended. Run in Windows PowerShell:

```powershell
cd C:\path\to\whisper-subtitle
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config.example.json config.json
.\.venv\Scripts\Activate.ps1
```

The commands below use `python main.py` from the project directory with the virtual environment activated. To run without activation, use `.\.venv\Scripts\python.exe main.py` instead. Audio is decoded with PyAV, so a separate FFmpeg installation is usually unnecessary.

Dependencies are constrained to faster-whisper 1.2.1 and PyAV <19 to avoid the incompatible `metadata_errors` change in PyAV 19.

Relative input paths are resolved against the terminal's current directory. The application always reads its default `config.json` from the project directory and keeps downloaded models in `models/`.

## 2. Translation API

Edit `translation` in `config.json`. DeepSeek is preconfigured; fill in your own key:

```json
"base_url": "https://api.deepseek.com",
"model": "deepseek-flash",
"api_key": ""
```

See the [DeepSeek API documentation](https://api-docs.deepseek.com/) for endpoint and model information.

| Option | Description |
| --- | --- |
| `backend` | `api` (default): Japanese/English/Korean API translation, Chinese local conversion. `auto` uses the same routing; `sakura` selects local Japanese translation. |
| `base_url` | API base URL. The application appends `/chat/completions`; a full endpoint URL is also accepted. Include `/v1` when required by your provider. |
| `model` | The provider's model ID. |
| `api_key` | Your API key. Leave empty to enter it at runtime. |
| `api_key_env` | Environment variable to read, default `SUBTITLE_API_KEY`. Priority: environment variable, configured key, interactive hidden input. |
| `instructions` | Optional terminology or name conventions, such as `Preserve honorifics and use consistent character names.` |
| `batch_size` | Subtitle entries per request, default 20. |
| `context_lines` | Context entries before and after each batch, default 3. |
| `timeout_seconds` | API request timeout, default 120 seconds. |
| `max_retries` | Additional attempts per batch, default 3. |

Only subtitle text is sent to the translation service; media transcription runs locally. Keys are excluded from caches and exported subtitles. `config.json` is ignored by Git; keep the key empty in `config.example.json`.

The service must accept `model`, `messages`, and `stream: false`, and return text at `choices[0].message.content`. The application validates subtitle IDs, requests omitted entries again, retries malformed responses, and saves completed translations.

### Japanese-to-Chinese API quality guidelines

Japanese audio uses the API by default and automatically loads `prompts/ja_zh_guidelines.txt`, an English adaptation of VoiceTransl's Basic and enhanced v1/v2 standards, plus its GalTransl translation and proofreading requirements. The rules cover natural Chinese, character voices, context-aware pronouns and omitted subjects, rhythm, honorifics, terminology, cultural setting, compact interjections, and a final silent review.

The program retains one translation per subtitle ID and the existing JSON contract. Natural clause restructuring stays within each subtitle entry. Edit the guideline file to adjust its style, and use `translation.instructions` for additional terminology preferences. Guidelines are included in the cache signature: updating them refreshes Japanese API translations while keeping the transcript. English, Korean, and the local Sakura backend keep their existing prompts.

See [prompts/README.md](prompts/README.md) for the source audit and adaptation details. A normal Japanese API command automatically applies the rules:

```powershell
python main.py "sample.wav" --language ja --translator api
```

### Local Sakura translation

The existing Sakura-Galtransl-7B-v3.7 Q6_K model and llama.cpp runtime have been copied into the project:

- `models/Sakura-Galtransl-7B-v3.7.gguf`
- `runtime/llama/llama-server.exe` and its runtime DLLs

Use Sakura for Japanese audio:

```powershell
python main.py "D:\audio\japanese.wav" --translator sakura
```

The program starts its own hidden llama.cpp server on a temporary loopback port, translates locally without an API key, and stops that process when finished or interrupted. Switching translators reuses the transcript and refreshes the Chinese translation. Default and automatic selection use the API for Japanese, English, and Korean; Chinese is always converted locally, including when an explicit translator is selected.

`translation.backend` defaults to `api` in `config.json`. Japanese, English, and Korean use the API, including when the language is detected automatically. `--translator auto` follows the same routing for compatibility with existing configurations. Explicit `--translator sakura` selects local Japanese translation; English and Korean require `auto` or `api`. Choosing `auto` or `api` shares the same translation cache. Switching a previous Sakura task to the default API reuses the transcript and refreshes its translation. Chinese conversion does not use API keys or start Sakura.

When Sakura is selected, an automatic source language defaults to `ja` if `--language` is omitted. Explicit language arguments and specific configured languages take precedence; use `--language auto` to keep language detection. Existing Japanese transcripts are reused when other recognition settings match.

The `sakura` configuration section contains:

| Option | Default / meaning |
| --- | --- |
| `server_path` | `runtime/llama/llama-server.exe`, relative to the project |
| `model_path` | `models/Sakura-Galtransl-7B-v3.7.gguf`, relative to the project |
| `gpu_layers` | 24 layers offloaded to the GPU; use 0 for CPU only |
| `device` | `Vulkan0`, the NVIDIA GPU in this installation |
| `context_size` | 4096 tokens |
| `batch_size` | 8 subtitle entries per request |
| `startup_timeout_seconds` | 180 seconds |
| `timeout_seconds` | 180 seconds per translation request |
| `glossary` | Optional terms, one `source->translation # note` per line |

Sakura uses a dedicated translation prompt with plain text lines, rather than the API backend's JSON instructions. If a batch changes the number of lines, the program retries that batch one subtitle per request to preserve timestamps, then resumes normal batches. Completed translations are cached after every successful request. Runtime logs are written to `.cache/sakura-server-<process-id>.log`.

Sakura uses a short Chinese internal task template suited to its fine-tuning; the console and configuration help remain English. Optional glossary and previous translations are supplied as reference material. Single-entry requests omit previous translations and use temperature 0 to reduce continuation of earlier dialogue. Responses containing known instructions, translated system-message instructions, or excessive expansion of short inputs are rejected before saving or printing. Retries omit history and use a lower temperature. Existing caches from earlier Sakura prompts are migrated on the next Sakura run: detected invalid entries are translated again, while the transcript and other completed entries are retained. The original cache is backed up as `task.before-sakura-prompt-v3.json`. Run the same command again to refresh exported files; use `--retranslate` to refresh every translation instead. See the [model's prompt guidance](https://huggingface.co/SakuraLLM/Sakura-GalTransl-7B-v3.7).

These additional resources occupy about 5.91 GiB. Sakura-GalTransl is distributed under CC BY-NC-SA 4.0 for noncommercial use; see the [model card and license](https://huggingface.co/SakuraLLM/Sakura-GalTransl-7B-v3.7).

## 3. Usage

Editable pre-translation, glossary, and source-conditioned post-translation rules are stored in `dictionary.json`. It includes 76 Japanese-only glossary hints: 52 GalTransl-derived terms and spelling variants, plus 24 terms and variants curated from subtitle review. Pre/post rules start empty. Matching terms are supplied to Sakura or API translation. The [source snapshot and license](third_party/galtransl/README.md) are included. Dictionary changes refresh only affected translations; post-rule changes reuse saved model text. Use `--dict "custom.json"` to choose another file and `--report` to also export a quality-review CSV. See [DICTIONARY.md](docs/DICTIONARY.md) for the schema, examples, caching, formatting, and report fields.

Glossary matching gives longer terms priority while retaining shorter terms that occur independently in the same sentence. Pre/post replacements keep their configured order.

From the project directory:

```powershell
python main.py "D:\video\sample.mp4"
```

Omit the file argument to enter a path interactively. Language is detected automatically by default. The default ASR preset is `high`; model and device overrides come from `config.json` or command-line arguments.

```powershell
# Japanese video to Chinese LRC
python main.py "D:\video\sample.mp4" --language ja

# Japanese-to-Chinese translation with the local Sakura model
python main.py "D:\video\sample.mp4" --language ja --translator sakura

# Chinese SRT only
python main.py "sample.mp4" --format srt

# Chinese LRC and SRT
python main.py "sample.mp4" --format all

# Also export source-language subtitles
python main.py "sample.mp4" --original

# Transcribe Chinese and convert to Simplified Chinese locally
python main.py "sample.wav" --language zh

# Source-language LRC only, without translation
python main.py "sample.mp3" --language en --transcribe-only

# CPU inference with a smaller model
python main.py "sample.mp3" --language en --device cpu --model small

# Faster, lower-resource ASR preset
python main.py "sample.mp3" --quality normal

# Keep the faster preset but preserve quiet speech by disabling VAD
python main.py "sample.mp3" -q normal --no-vad

# Separate vocals before recognition
python main.py "sample.mp4" -s

# Separate and export vocals, hiding sentence text in the console
python main.py "sample.mp4" -v -Q

# All available arguments
python main.py --help
```

### Candidate terminology

Use the API to generate a terminology review from an already cached Japanese transcript:

```powershell
python main.py "D:\video\sample.mp4" --terms
```

This writes `sample.terms.csv` with proposed translations, counts, alternatives, and source examples, plus `sample.terms.json` with all candidates disabled. It uses the configured API even when Japanese subtitle translation uses Sakura. Completed batches are saved so a failed extraction can resume. If the transcript is missing, run the media file normally or with `--transcribe-only` first. Existing candidate files are preserved; choose another `--output-dir` to generate another set.

Review the CSV, edit translations in the JSON as needed, and set approved entries to `"enabled": true`. Then merge them into the active dictionary:

```powershell
python main.py --add-terms "D:\video\sample.terms.json"
python main.py "D:\video\sample.mp4"
```

Import backs up the dictionary, skips existing terms, and stops on conflicting preferred translations. Only affected subtitle translations refresh on the next normal run. Use `--dict "custom.json"` with either terminology command to select a custom dictionary. See [DICTIONARY.md](docs/DICTIONARY.md#generate-candidate-terms) for details.

Supported language codes: `zh` (Chinese), `ja` (Japanese), `en` (English), `ko` (Korean), and `auto`. The application targets files with one primary spoken language.

### Console output

Each recognized sentence is printed immediately with its ID and start time. Chinese translations are printed as each request returns:

```text
[ASR 001 00:01] <recognized source sentence>
[ZH  001 00:01] <Simplified Chinese translation>
```

`ASR` marks the original transcript; `ZH` marks the Chinese result. Cached sentences are shown again when resuming. Successful entries are printed once per run, including when missing translations require another request. Console messages, help, and the translation prompt are in English; documentation is available in Chinese and English. Recognized speech and subtitle contents keep their source language and Simplified Chinese translation.

Console timestamps use `mm:ss`, or `hh:mm:ss` from one hour onward. IDs are padded to at least three digits. Subtitle files retain their full start/end timestamps and precision.

Normal translation output shows a start message, the translated sentences, and a final `Translation completed: 702/702.` summary. It does not insert a progress message after every request, including when Sakura falls back to one entry per request.

Use `--quiet` / `-Q` to hide recognized and translated sentence text, including cached sentences. While translation is running, `Translating: 128/702 (18%)` refreshes every five seconds on the same terminal line. Redirected output uses a new line for each refresh. Retries and errors are shown immediately; the progress line is cleared before diagnostic messages, completion, and cancellation. Stage messages and output paths remain visible. Set `quiet: true` in `config.json` to use this behavior by default. Lowercase `-q` selects ASR quality; uppercase `-Q` controls sentence logging.

### Repeated sound-only subtitles

Final Chinese subtitles also filter pure emoji-only recognition artifacts and use a minimum display duration of 0.8 seconds. Short entries extend into available gaps; when there is no room, they join adjacent text without overlapping the next subtitle. Original recognition timings remain in the task cache. `minimum_subtitle_seconds` controls the minimum (0 disables timing adjustment).

With `review_audio: true` (default), mixed emoji/text regions, unchanged Japanese translations, and suspicious early closing phrases before an opening greeting receive a local audio check. Review uses a low-threshold speech detector only for these suspect regions; the normal ASR preset is unchanged. Regions with recoverable speech are re-transcribed and only their translations are refreshed. Confirmed non-speech intro artifacts are omitted from final subtitles. The cache stores `original_asr` and `audio_review` details; its first review snapshot is `task.before-audio-review.json`. Pure emoji entries are skipped before translation and kept in the raw cache. API/Sakura unchanged Japanese responses are retried; exhausted retries request at most one additional audio-review pass in the current run. Unresolved translations stop with saved progress rather than being accepted as Chinese.

Final Chinese subtitles combine adjacent repetitions of recognized laughter and common sound effects by default. The entries must be consecutive, use the same sound, have gaps of at most one second, and span at most ten seconds in total. The combined entry keeps the first translation and covers the group's full time range. Dialogue, acknowledgments, exclamations, long pauses, and unrecognized sounds remain separate. Raw transcripts, source-language exports, translation caches, and sentence logs retain every entry.

Use `--sounds keep` to disable repeated-sound grouping, or `--sounds merge` to combine repetitions. Emoji filtering and minimum-duration cleanup still apply. The configuration default is `merge_repeated_sounds: true`. Switching this option reuses recognition and translation caches. For example:

```powershell
python main.py "sample.mp4" --sounds keep
```

Code updates apply when a new command starts. A task that was already running continues with its previously loaded code; stop it and rerun the same command to use an update and resume saved progress.

### Optional vocal separation

Use `--separate` / `-s` to remove accompaniment before recognition with the copied `UVR_MDXNET_KARA_2.onnx` model. Separation is off by default and can be combined with either ASR preset and either translator. It can help speech masked by music; review the result for very quiet voices, whispers, and overlapping speakers, where separation may remove useful details.

Use `--vocals` / `-v` to also export `<stem>.vocals.wav` as stereo 44.1 kHz PCM16. This automatically enables separation. The WAV is saved beside the input media, or in `--output-dir` when specified. Subtitles retain the original media basename and timing. The vocal file is exported before recognition and translation begin, so it is available even if a later stage stops.

```powershell
python main.py "D:\video\sample.mp4" -s --language ja
python main.py "D:\video\sample.mp4" -v -Q --translator sakura --language ja
python main.py "sample.mp4" -v --output-dir "D:\subtitles" --format srt
```

The `separation` configuration section contains:

| Option | Default / meaning |
| --- | --- |
| `enabled` | `false`; separate before recognition when enabled |
| `export_vocals` | `false`; export the WAV and automatically enable separation |
| `executable_path` | `runtime/separate/separate.exe`, relative to the project |
| `model_path` | `models/UVR_MDXNET_KARA_2.onnx`, relative to the project |
| `denoise` | `false`; optional extra denoising, at additional processing cost |
| `chunks` | 15 seconds per processing chunk |
| `margin` | 44100 overlap samples |

Audio decoding uses PyAV. The hidden separator process runs to completion before Whisper starts, and is stopped on cancellation. Its bundled Python runtime is isolated from the project's environment. A shared Numba cache in `runtime/separate/numba-cache/` avoids frozen-runtime cache path problems and can be reused across media files. The copied model and runtime occupy about 0.78 GiB. Initial startup may take longer while compiling audio processing functions.

Separated vocals, their validation manifest, and `separator.log` are stored under `.cache/<source-hash>/separation/<settings-hash>/`. Successful runs remove the extracted mixture and unused accompaniment. Reruns validate and reuse the vocal WAV. Model, executable, and separation settings participate in cache matching; changing them or switching separation on/off triggers fresh recognition. `-v`, `-Q`, output format, and output location reuse completed recognition. `--force-transcribe` reruns recognition while retaining reusable separated audio.

### Models and GPU libraries

The default `high` preset uses the local `large-v2` model. With `whisper_model: "auto"`, `normal` selects `turbo`. Use `--model large-v3` or another name/path to override the preset's model. Missing models are downloaded from Hugging Face into `models/`. A local CTranslate2 model directory can also be passed as an absolute path. English-only `.en` models are intended for English audio.

`device: auto` selects an available NVIDIA GPU, otherwise CPU. GPU inference requires compatible CUDA libraries. Use `--device cpu` for CPU inference.

### ASR quality presets

| Setting | `high` (default) | `normal` |
| --- | --- | --- |
| Automatic model | large-v2 | turbo |
| Automatic GPU precision | FP16 | INT8/FP16 |
| Automatic CPU precision | FP32 | INT8 |
| Pre-recognition VAD | Off: process the full audio | On, speech threshold 0.5 |
| Word-level timing | On | Off |
| Previous-text conditioning | Off, to reduce error propagation | On |
| Beam size | 5 | 5 |
| Decoder no-speech threshold | 0.6 | 0.6 |

`high` prioritizes retaining quiet speech and detailed timestamps, using more time and resources. The decoder still applies its own no-speech check. With pre-filtering off, background sounds can occasionally produce spurious text; review quiet passages when checking a transcript.

```powershell
# Default recall-focused preset
python main.py "sample.wav" --language ja

# Explicit preset selection (short form: -q)
python main.py "sample.wav" --quality high
python main.py "sample.wav" -q normal

# Optional overrides
python main.py "sample.wav" --quality high --vad --vad-threshold 0.25
python main.py "sample.wav" --quality normal --no-vad
python main.py "sample.wav" --compute-type float16 --model large-v2
```

Configuration options: `quality` is `high` or `normal`; `whisper_model: "auto"` and `compute_type: "auto"` follow the selected preset. Set either to a specific value to override it. `vad_filter: null` follows the preset; `true` or `false` overrides it. `vad_threshold` applies when VAD is enabled.

The console reports the selected preset, model, precision, and retained audio duration. Low VAD retention produces a suggestion to disable filtering for quiet speech. The resolved model, preset, precision policy, device, and decoder options are included in the recognition cache signature. Changing them triggers fresh transcription automatically, including replacing results from the earlier fixed-VAD implementation. Export format and output directory changes continue to reuse completed recognition.

The following resources have been copied from the local VoiceTransl installation:

- `models/faster-whisper-large-v2/`: complete large-v2 model, configuration, tokenizer, and vocabulary.
- `runtime/cuda/`: CUDA 12 cuBLAS, cuBLASLt, and CUDA Runtime libraries, loaded automatically for this process.

Together these copied resources occupy about 3.47 GiB. Select the local model without downloading it again:

```powershell
python main.py "sample.mp3" --model large-v2
```

Both presets can use existing local resources: `high` selects the copied large-v2 directory, and `normal` selects the downloaded turbo cache. See [runtime/README.md](runtime/README.md) for runtime provenance.

## 4. Output and task resumption

By default, only the Chinese LRC is written next to the input file:

```text
D:\audio\sample.mp3
D:\audio\sample.zh.lrc
```

| Argument | Files exported |
| --- | --- |
| Default / `--format lrc` | Chinese `.zh.lrc` |
| `--format srt` | Chinese `.zh.srt` |
| `--format all` | Chinese LRC and SRT |
| `--original` | Also export `.original.*` in the selected format(s) |
| `--transcribe-only` | Export only source-language subtitles; default `.original.lrc` |
| `--vocals` / `-v` | Also export `.vocals.wav`; enables separation |

`python main.py "sample.mp3" --format all --original` exports four files. SRT stores each entry's start and end. LRC uses sentence-level start times, with blank timestamp entries for gaps and the end of the media. Display behavior depends on the player.

`output_dir: "source"` means the input file's directory. Change it in `config.json`, or use `--output-dir "D:\subtitles"` for a specific run. Selected files with the same name are updated; existing files in other formats are kept.

Caches are stored separately in `.cache/<file-content-hash>/task.json` inside the project. They contain transcripts and translation progress, without API keys. Switching output directory or format reuses the cache.

Run the same command to reuse a completed transcript and resume unfinished translation. Transcription is saved when it finishes; interrupting it earlier restarts transcription on the next run. Press `Ctrl+C` to stop.

- `--retranslate`: translate again using the existing transcript.
- `--force-transcribe`: transcribe again and reset this task's translations.
- `--config "D:\settings\config.json"`: use a specific configuration file.

Changing the API endpoint, translation model, translation instructions, or built-in translation prompt refreshes translations while keeping the transcript. Relative model and configured output paths are based on the project directory, except `output_dir: "source"`. Relative command-line input, `--config`, and `--output-dir` paths are based on the terminal's current directory.

Review names, overlapping speech, and passages with strong background music. Exported subtitles can be edited as final deliverables. Retranslation reads the transcript in `task.json`; edits to exported LRC/SRT files are not imported into the cache.

## License

The project's code and original documentation are licensed under the [GNU General Public License v3.0](LICENSE) (`GPL-3.0-only`). Use, modification, and distribution are subject to its terms.

Third-party resources retain their respective copyrights and licenses:

- GalTransl dictionary sources, adaptation records, and the GPL-3.0 license are preserved in [third_party/galtransl](third_party/galtransl/README.md).
- References used for the Japanese translation guidelines are recorded in [prompts/README.md](prompts/README.md).
- Python dependencies, optional runtimes, and models follow their own licenses. Model and runtime binaries are not included in this repository. See the [Sakura model card](https://huggingface.co/SakuraLLM/Sakura-GalTransl-7B-v3.7) for its terms and [runtime/README.md](runtime/README.md) for local runtime provenance.

## References

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [Whisper](https://github.com/openai/whisper)
- [OpenCC Python](https://pypi.org/project/opencc-python-reimplemented/)
- [Sakura-GalTransl](https://huggingface.co/SakuraLLM/Sakura-GalTransl-7B-v3.7)
- [llama.cpp server](https://github.com/ggml-org/llama.cpp/tree/master/tools/server)
