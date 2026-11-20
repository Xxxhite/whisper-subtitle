# Dictionary and quality reports

[Quick start](../README.en.md) · [Configuration](CONFIGURATION.md)

The application reads `dictionary.json` by default. It contains Japanese-to-Chinese
glossary hints adapted from GalTransl, terms curated during subtitle review, and
standalone repeated-sound hints. The `pre` and `post` stages start empty.
`dictionary.example.json` provides disabled examples for custom rules.

## Included glossary

The glossary covers forms of address, character archetypes, game/fantasy terms,
audio-work vocabulary, and an adult-context subset for ASMR material. Matching
Japanese entries receive the hints with either API or Sakura translation.

Edit preferred translations in `dictionary.json`, set an entry's `enabled` to
`false` to disable it, or replace `glossary` with `[]` to disable all hints. The
GalTransl adult-context entries use IDs beginning with `galtransl-asmr-` or
`galtransl-asmr-alias-`. Curated terms use `review-ja-`; repeated sounds use
`review-sound-`.

The upstream snapshot, attribution, adaptation notes, and license remain in
[third_party/galtransl](../third_party/galtransl/README.md). That snapshot is a
reference copy; edit the active dictionary to change translation. Broad upstream
pre/post replacements remain disabled.

After an edit, rerun the normal subtitle command. Only affected translations are
refreshed; the transcript and unaffected translations are reused. For a separate
empty dictionary, use:

```json
{
  "version": 1,
  "pre": [],
  "glossary": [],
  "post": []
}
```

## Three stages

| Stage | Purpose | Input |
| --- | --- | --- |
| `pre` | Correct recognized spellings before translation | Current transcript, including any local audio review |
| `glossary` | Supply matching names and terms to the model | Text after pre-rules |
| `post` | Apply a deterministic correction after translation | Saved model translation |

Rules run in file order. A rule's `source` is a literal string, never executable code or a regular expression. The original transcript remains available; pre-rules create a separate translation input.

Common fields:

| Field | Meaning |
| --- | --- |
| `id` | Required nonempty ID, unique across all three stages |
| `enabled` | Optional boolean, default `true` |
| `language` | `any` (default), `zh`, `ja`, `en`, or `ko`; matches the recognized language |
| `source` | Required nonempty match string; for post-rules this matches translated text |
| `target` | Required nonempty replacement or preferred translation |
| `match` | `exact` or `contains`; pre/post default to `exact`, glossary defaults to `contains`. Japanese glossary rules also support `sound`. |
| `note` | Optional glossary context, on one line |

With `exact`, the entire text must match. With `contains`, pre/post rules replace literal occurrences within the text. A glossary entry is included only for subtitle entries whose translation input matches it. Conflicting preferred translations for the same matched term are rejected.

Glossary matching checks longer terms first and suppresses shorter terms inside their matched spans. For example, a sentence containing only `ハイエルフ` uses its preferred translation without also adding `エルフ`. If `エルフ` also occurs separately in that sentence, both terms are included. Pre/post replacements continue to run in file order.

### Standalone repeated sounds

`match: "sound"` is available only in `glossary` rules with `language: "ja"`. Its `source` is one kana sound unit (1–8 characters). The entire subtitle must consist of at least two repetitions of that unit, with optional punctuation and a brief vocal prefix. Matching folds katakana and half-width spelling and ignores elongation marks; small `っ` remains distinct. The glossary sent to the model uses the sound unit's spelling from the current input. Single occurrences and ordinary sentences containing the word do not match.

```json
{
  "id": "sample-sound",
  "language": "ja",
  "source": "とん",
  "target": "咚",
  "match": "sound",
  "note": "Repeated tapping sound; keep the translation brief."
}
```

This matches `とんとん` and `トーン、トーン`, while leaving `とん` and `とんとんと聞こえた` unchanged. The included `review-sound-001` and `review-sound-002` entries provide a brief rubbing-sound hint for standalone repetitions of `しこ` and the geminated ASR variant `しっこ`. They supply model hints rather than forced replacements. Disable either entry with `enabled: false`. Adding these hints refreshes only matching translations.

## Generate candidate terms

```powershell
python main.py "D:\video\sample.mp4" --terms
```

This mode extracts terminology from the completed Japanese transcript already saved in the task cache. It uses the configured translation API even when normal Japanese translation uses Sakura. Configure `translation.base_url`, `translation.model`, and your API key or API-key environment variable as usual. No new model or tokenizer is required. If there is no cached transcript, run the normal command or `--transcribe-only` first.

The command generates two files beside the media, or in `--output-dir`:

- `sample.terms.csv`: proposed Japanese terms, Chinese translations, English meaning/type notes, occurrence counts, votes, alternative translations, and up to three timestamped source examples. Votes count extraction batches suggesting the same translation; they are not confidence scores.
- `sample.terms.json`: an editable dictionary containing the candidates, all with `enabled: false`.

The API receives batches of source text and matching existing glossary entries. It is asked to extract distinctive names and specialized terms, rather than everyday words, greetings, or sound effects. Proposed source strings must appear literally in the submitted text. Existing enabled Japanese glossary entries, omitted audio regions, and recognized sound/emoji artifacts are excluded. Source and pre-rule handling use a copy of the task; saved transcripts and translations are unchanged.

Successful batches are checkpointed in `.cache/<file-content-hash>/terms-state.json` without API keys. If extraction fails or is interrupted, rerun the same command to continue completed batches. Changed source text, glossary, API endpoint/model, or extraction prompt refreshes extraction. Existing candidate files are preserved to protect review edits; move/rename them or choose another output directory to generate a fresh set. Generation does not export or update subtitles. Use it separately from subtitle processing flags such as `--transcribe-only`, `--retranslate`, `-s`, and `-v`.

### Review and import

1. Read the CSV and check the source examples.
2. Edit `sample.terms.json`: correct translations/notes and set selected entries to `"enabled": true`.
3. Merge the selected terms:

```powershell
python main.py --add-terms "D:\video\sample.terms.json"
```

Import requires no media argument and uses the default `dictionary.json`, or the file selected with `--dict`. It imports only enabled Japanese glossary candidates. Existing matching terms are skipped; conflicting translations stop the import before changing the dictionary. To change a conflicting preferred translation, edit the active dictionary directly. Each successful import that adds terms saves an exact backup next to the dictionary as `dictionary.before-terms-<timestamp>-<suffix>.json`.

Run the usual subtitle command afterward. Only entries affected by the new glossary are translated again; transcription is reused.

The extraction and matching design takes inspiration from VoiceTransl's [GenDic](https://github.com/shinnpuru/VoiceTransl/blob/main/GalTransl/Backend/GenDic.py) and [Dictionary](https://github.com/shinnpuru/VoiceTransl/blob/main/GalTransl/Dictionary.py). This implementation uses the existing API client and cache instead of adding its tokenizer/model dependencies.

### Post-rule conditions

Every post-rule requires at least one source condition. Source conditions examine the text after pre-rules, while translation conditions examine the current translated text. All supplied conditions must match.

```json
{
  "id": "sample-name-case",
  "language": "en",
  "when": {
    "source_contains": "Nova",
    "translation_contains": "NOVA"
  },
  "source": "NOVA",
  "target": "Nova",
  "match": "contains"
}
```

Supported conditions: `source_equals`, `source_contains`, `translation_equals`, and `translation_contains`. The source requirement keeps a correction tied to the relevant original wording.

## Reprocessing and caching

- Changing a pre-rule queues only entries whose effective translation input changes.
- Changing a matching glossary's source, target, or note queues the affected entries. Adding an unused term does not queue anything.
- Changing, disabling, or removing post-rules reprocesses saved model translations locally. It does not require another translation request.
- The first run with an empty dictionary adopts existing translations without re-translating them.
- Recognition is reused. Switching translation providers or their global prompts retains the existing provider-cache behavior.

Run the normal command again after editing the dictionary. There is no need to add `--retranslate` for dictionary changes.

For selective terminology updates, use this dictionary's `glossary` stage. The legacy `sakura.glossary` setting remains a global backend setting.

```powershell
python main.py "sample.mp4"
python main.py "sample.mp4" --dict "D:\rules\custom.json"
```

`dictionary_file` in `config.json` selects the default file. Configured relative paths are based on the project directory; relative `--dict` paths are based on the terminal directory.

## Conservative formatting

With `format_cleanup: true` (default), translations receive whitespace cleanup, removal of spurious escaped line breaks absent from the source, repeated Chinese comma/full-stop cleanup, and removal of stray leading comma/full-stop characters. Emphatic question/exclamation marks, ellipses, and quote contents are retained. Ambiguous quote pairing is reported rather than automatically reconstructed.

Set `format_cleanup` to `false` to recover the saved model text through the same post-rules on the next run. This does not queue translation requests.

## Optional quality report

```powershell
python main.py "sample.mp4" --report
```

This also writes `sample.quality.csv` to the selected output directory. The UTF-8 report can be opened in Excel and contains IDs, start/end times, severity, issue, source text, translation input, Chinese text, rule IDs, and details.

Checks include missing glossary terms, possible Japanese residue, unexpected English, punctuation pairing, possible repetition and expansion, unresolved local audio checks, and exported timing overlap. Notes record applied rules, formatting cleanup, and filtered recognition artifacts. Protected glossary targets are excluded from the Japanese-residue check.

Warnings are review candidates, not automatic edits. Report IDs follow the transcript; final subtitle entries may combine several transcript entries. Without `--report`, the output selection stays unchanged.

## Uncertain Japanese speech

Before translation, the program compares available local recognition passes and their word times. An independently supported phrase can be translated on its own, with `〔听不清〕` at the missing end or ends. When two timed hypotheses confirm speech but disagree on a meaning-changing detail such as negation, the line can contain only `〔听不清〕`. Unconfirmed voice intervals can instead be omitted from subtitles and listed in the quality CSV. A single low score or an omitted Japanese subject does not by itself trigger a marker.

Run with `--report` to inspect the source, translation input, uncertain interval and model readings. Look for `partially_translated_speech`, `unintelligible_speech`, `unconfirmed_voice`, and `unconfirmed_speech_gap`. The same decisions apply to Sakura and API translation. Per-recording human reviews take priority and a rerun reuses unaffected translations.
