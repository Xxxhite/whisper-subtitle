# API translation guidelines

`ja_zh_guidelines.txt` is an English adaptation of the local VoiceTransl Japanese-to-Chinese standards. It is loaded automatically when the API backend translates detected or explicitly selected Japanese audio. Edit the file to adjust the style; its complete contents are included in the translation cache signature.

## Sources inspected

- `D:\application\VoiceTransl\_internal\translation_guidelines\Basic.md`.
- The enhanced Japanese-to-Chinese guidelines, v1.0 and v2.0, in that directory.
- The embedded `GalTransl.Backend.Prompts` module in `D:\application\VoiceTransl\_internal\translate\translate.exe`: JSON/TSV translation templates, proofreading templates, the Sakura template, and glossary-generation instructions.
- The `ForGalJsonTranslate` and `ForNovelTranslate` backends, the `prompt2srt` and `srt2prompt` modules, and application-level prompt-related configuration.

The application selected `Basic.md` in its project configuration. The enhanced files were present as additional standards. The inspected GUI configuration selected no custom prompt replacement, and no additional translator-role prompt was found among the main application's static string constants. Archive inspection read serialized constants without running application code.

`source_audit.json` records source locations and hashes so the inspected local versions can be identified. No translation history, API keys, or private transcript contents were imported.

## Adaptation for timed subtitles

The integrated rules preserve meaning, distinct character voices, natural modern Chinese, ACG terminology, context-aware pronouns, cultural setting, compact interjections, terminology consistency, and a final completeness and fluency review.

Restructuring stays within one subtitle ID. Narrative perspective follows the evidence in the source instead of forcing every narrator into a first-person protagonist voice. Dialogue and narration are identified from context, because speech recognition supplies no reliable speaker-name field. Honorifics and personality traits follow the material instead of applying a fixed stereotype.

The original application's wrapper formats have been adapted to this project's `translations` array with `id` and `text`. Proofreading is a final review within the translation request. Glossary-generation instructions contribute terminology consistency; they do not add a separate API call or glossary table to subtitle output. Runtime instruction overrides and disclaimer text were not adopted as translation-quality rules.

The API backend applies these guidelines only to Japanese. English and Korean retain the general translator prompt. Sakura continues to use its dedicated local-model prompt in `whisper_subtitle/sakura.py`.
