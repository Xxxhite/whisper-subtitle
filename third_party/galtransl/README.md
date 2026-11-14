# GalTransl dictionary source

Source: [GalTransl/GalTransl](https://github.com/GalTransl/GalTransl), `Dict/GPT字典.txt`.

The upstream dictionary is preserved in `gpt-dictionary.txt` (54 pairs). The source repository's GNU GPL version 3 license is included in `LICENSE`. Credit belongs to the GalTransl contributors. See `source.json` for the source URL, Git blob hashes, import date, and adaptation details.

Adapted on 2026-11-14: 32 general pairs and 17 adult-context pairs were converted into Japanese-only glossary hints in the project's `dictionary.json`, with the original target translations and added English context notes. Three kana/width spelling variants use the corresponding upstream targets, bringing the GalTransl-derived subset to 52 entries. These adapted dictionary entries are provided under GNU GPL version 3. The default selection omits five ambiguous/style-specific entries from the general section. All original pairs remain available in the source snapshot for review.

The adult-context subset was enabled at the user's request for ASMR material. ASMR itself covers many subjects; this subset addresses adult vocabulary rather than providing a complete ASMR terminology collection. Context notes keep model translation sensitive to the source register and meaning.

VoiceTransl's [default configuration](https://github.com/shinnpuru/VoiceTransl/blob/main/GalTransl/DefaultProjectConfig.py) references GalTransl's glossary and slurred-speech correction filenames. Its inspected `main` tree does not contain the `Dict` data directory. The [ASMR fork's glossary](https://github.com/ygsbzr/GalTransl-for-ASMR/blob/main/Dict/GPT%E5%AD%97%E5%85%B8.txt) contains eight pairs, mostly already covered by this glossary. No additional data from that fork is bundled here. The source of the imported pairs remains the official GalTransl snapshot recorded in `source.json`.

No upstream pre/post replacement files are enabled. This avoids importing game-script cleanup and example replacements into speech transcripts. The runtime reads the editable root `dictionary.json`; this directory provides source records and is not loaded separately.
