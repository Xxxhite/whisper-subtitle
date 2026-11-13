# Project layout and version control

```text
whisper-subtitle/
  main.py                  CLI entry point and task workflow
  *.py                     Recognition, translation, and subtitle helpers
  requirements.txt         Python dependencies
  config.example.json      Shared configuration template
  dictionary.json          Shared, editable translation glossary
  dictionary.example.json  Disabled examples for custom rules
  docs/                    Dictionary guide and project layout
  prompts/                 Japanese API guidelines and source records
  third_party/             Imported dictionary data, attribution, and license
  runtime/README.md        Local runtime provenance
```

Application modules stay at the project root so configuration resolution and
imports remain stable. Run the application from the project directory:

```powershell
python main.py "D:\audio\sample.mp3"
```

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
| `.idea/`, `.vscode/` | Local editor settings |
| `__pycache__/` | Regenerable Python bytecode |

Generated media/subtitles, candidate term files, quality reports, and automatic
dictionary backups are ignored as well. The shared dictionary and its source/license records are
versioned; review any personal additions before committing them.

On another computer, follow the installation instructions in [README.md](../README.md)
to recreate `.venv/` and `config.json`. Whisper models download into `models/` when
needed. GPU libraries and optional Sakura/separation resources are configured
separately; see [runtime/README.md](../runtime/README.md).

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
