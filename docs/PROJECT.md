# Project layout and version control

```text
whisper-subtitle/
  main.py                  Small launcher; existing command stays available
  whisper_subtitle/
    __init__.py            Application package
    cli.py                 CLI arguments, configuration, and task workflow
    *.py                   Recognition, translation, and subtitle helpers
  requirements.txt         Python dependencies
  config.example.json      Shared configuration template
  dictionary.json          Shared, editable translation glossary
  dictionary.example.json  Disabled examples for custom rules
  docs/                    Configuration, dictionary, and project guides
  prompts/                 Japanese API guidelines and source records
  third_party/             Imported dictionary data, attribution, and license
  runtime/README.md        Local runtime provenance
```

Implementation modules live in `whisper_subtitle/` and use package-relative
imports. The root `main.py` forwards to `whisper_subtitle.cli`. Configuration,
glossaries, prompts, models, runtimes, and cache paths resolve from the project
root. Run the application from the project directory:

```powershell
python main.py "D:\audio\sample.mp3"
```

`word_boundaries.py` maps complete lexical groups back to ASR token times using
Janome and active glossary terms. `context_vocabulary.py` proposes bounded
phonetic vocabulary hints from preceding source topics; `source_review.py`
accepts changes only after independent acoustic confirmation. These helpers use
the existing models and preserve the raw transcript in task backups.
`counting.py` handles explicit numeric rendering; `count_review.py` checkpoints
local acoustic evidence for uncertain counts and numeric clusters.
`alignment_review.py` checks weak prefixes, collapsed tails, and duplicate dialogue
using independent timed hypotheses. Contextual spelling review can inspect the
left and right audio channels separately. `translation_checks.py` supplies shared
source-conditioned meaning checks for translation, cache reuse, and reports.

## Local resources

The following directories and files remain on the local machine and are excluded
from version control:

| Path | Contents |
| --- | --- |
| `config.json` | Personal settings and API key |
| `.venv/` | Installed Python environment |
| `models/` | Downloaded/copied Whisper, Sakura, and separation models |
| `runtime/cuda/`, `runtime/llama/`, `runtime/separate/` | GPU libraries and optional executables |
| `.cache/` | Transcripts, resumable translations, extracted vocals, reports, and local backups |
| `tests/` | Local regression checks and audio-derived fixtures |
| `.idea/`, `.vscode/` | Local editor settings |
| `__pycache__/` | Regenerable Python bytecode |

Generated media/subtitles, candidate term files, quality reports, and automatic
dictionary backups are ignored as well. The shared dictionary and its source/license records are
versioned; review any personal additions before committing them.

On another computer, follow the installation instructions in [README.md](../README.md)
to recreate `.venv/` and `config.json`. Whisper models download into `models/` when
needed. GPU libraries and optional Sakura/separation resources are configured
separately; see [runtime/README.md](../runtime/README.md).
For configuration options and cache behavior, see [CONFIGURATION.md](CONFIGURATION.md).

## Review repository changes

```powershell
git status --short
git ls-files --others --exclude-standard
```

The `.gitignore` file selects source, documentation, and configuration examples
while excluding local resources. `.gitattributes` normalizes source
and documentation to LF. Windows command scripts use CRLF.

Use an empty remote repository for the initial connection. The local repository
uses `main` as its default branch. Configure the remote after its URL is available.
