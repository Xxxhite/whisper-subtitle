# whisper-subtitle

[简体中文](README.md) | English

A command-line subtitle tool for one audio or video file at a time. Transcribe Chinese, Japanese, English, and Korean with [faster-whisper](https://github.com/SYSTRAN/faster-whisper), then generate Simplified Chinese subtitles through a translation API or local Sakura. Export LRC or SRT.

- Japanese, English, and Korean use the API by default; Chinese is converted locally to Simplified Chinese.
- Chinese LRC is saved beside the input media by default.
- Supports vocal separation/export, terminology dictionaries, quality reports, and task resumption.
- Offers high and normal recognition presets, with splitting and suspect-region review for high-quality Japanese tasks.

## Quick start

Python 3.10–3.12 is recommended. The commands below use Windows PowerShell.

### 1. Install

From the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config.example.json config.json
.\.venv\Scripts\Activate.ps1
```

Run subsequent commands from the project directory. Without activating the environment, replace `python` with `.\.venv\Scripts\python.exe`.

Missing Whisper models download into `models/` on first use. GPU recognition needs compatible CUDA/cuDNN libraries; use `--device cpu --model small` for CPU inference. PyAV decodes the media, so a separate FFmpeg installation is usually unnecessary.

### 2. Configure the translation API

Enter your key in `translation.api_key` in `config.json`. The template includes DeepSeek settings; change `base_url` and `model` for another compatible provider:

```json
{
  "translation": {
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-flash",
    "api_key": "your-api-key"
  }
}
```

This is a configuration excerpt; retain the remaining template settings. Use a model ID supplied by your provider. You can also supply the key through the `SUBTITLE_API_KEY` environment variable.

The API receives subtitle text and relevant context; audio/video processing stays local. Personal `config.json` is excluded from Git. Transcription-only runs and Chinese audio need no translation API.

### 3. Generate subtitles

```powershell
python main.py "D:\video\sample.mp4"
```

The default command detects the language and writes `sample.zh.lrc` beside the input. Console messages and argument help are in English.

## Common commands

```powershell
# Japanese input to SRT
python main.py "sample.mp4" --language ja --format srt

# Chinese and source-language subtitles in both formats
python main.py "sample.mp4" --format all --original

# Transcribe and export the source language only
python main.py "sample.mp3" --transcribe-only

# Local Sakura Japanese-to-Chinese translation (requires model and runtime)
python main.py "sample.mp4" --translator sakura

# Separate/export vocals and hide sentence logs (requires separation resources)
python main.py "sample.mp4" -v -Q

# Faster recognition preset
python main.py "sample.mp4" -q normal
```

Sakura supports Japanese-to-Chinese translation. Selecting it defaults implicit automatic language selection to `ja`. See [detailed configuration](docs/CONFIGURATION.md#local-sakura) for the required resources.

## Common arguments

| Argument | Purpose |
| --- | --- |
| `--language` | `auto`, `zh`, `ja`, `en`, or `ko` |
| `--format` | `lrc` (default), `srt`, or `all` |
| `--quality` / `-q` | `high` (default) or faster `normal` |
| `--translator` | `api` (default), `auto` (same routing as API), or `sakura` |
| `--original` / `--transcribe-only` | Also export the source / export only the source |
| `--separate` / `-s`, `--vocals` / `-v` | Separate vocals / separate and export vocals |
| `--quiet` / `-Q` | Hide sentence text; retain progress and errors |
| `--output-dir` | Set the output directory |
| `--dict` | Select a terminology dictionary |
| `--report` | Also write a `.quality.csv` review report |

List every argument:

```powershell
python main.py --help
```

`high` defaults to large-v2 and prioritizes quiet speech and word timing; `normal` defaults to the faster turbo model. Focused review adds processing time. See [recognition settings](docs/CONFIGURATION.md#recognition) for models and review requirements. Lowercase `-q` selects the preset; uppercase `-Q` controls logging.

## Output and resumption

Default output location:

```text
D:\audio\sample.mp3
D:\audio\sample.zh.lrc
```

| Option | Files generated |
| --- | --- |
| Default | `.zh.lrc` |
| `--format srt` | `.zh.srt` |
| `--format all --original` | Chinese and source-language LRC/SRT, four files |
| `--transcribe-only` | `.original.*` in the selected format(s), LRC by default |
| `-v` | Also `.vocals.wav` |
| `--report` | Also `.quality.csv` |

Source subtitles retain the input language. Outputs use the input basename and replace files with the same name and format. Change the location with `--output-dir "D:\subtitles"`.

Task progress is saved under the project's `.cache/`. Rerun the same command to reuse recognition and resume translation. Press `Ctrl+C` to stop. The initial transcript is saved when recognition finishes; interrupting it earlier restarts recognition on the next run.

- `--retranslate`: translate again using the existing transcript.
- `--force-transcribe`: transcribe again and reset the task's translations.
- Change output format or directory: reuse recognition and translations.
- Edit the dictionary: rerun the normal command to refresh affected entries only.

Manual edits to exported subtitles affect those files; resumption and retranslation read the task cache.

## More documentation

- [Detailed configuration](docs/CONFIGURATION.md): API, models/GPU, Sakura, vocal separation, and cache behavior.
- [Dictionary and quality reports](docs/DICTIONARY.md): glossary maintenance, candidate extraction/import, and report usage.
- [Project layout](docs/PROJECT.md): source structure, local resources, and version control.
- [Runtime provenance](runtime/README.md) · [Translation guideline sources](prompts/README.md) · [GalTransl dictionary sources](third_party/galtransl/README.md).

## License

Code and original documentation use [GPL-3.0-only](LICENSE). Third-party dictionaries, runtimes, and models retain their own licenses. Supply models and runtimes separately; source and license records are linked above.
