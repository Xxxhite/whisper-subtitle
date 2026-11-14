"""Human-readable CSV findings; checks do not silently rewrite uncertain text."""
import csv
import io
import re

from dictionary_rules import source_text
from subtitle_processing import contains_emoji, is_pure_emoji, sound_key


def findings(cache: dict, exported: list[dict]) -> list[dict]:
    result = []
    def add(row, issue, detail, severity="warning"):
        hits = row.get("rule_matches", {})
        result.append({"id": row["id"], "start": row["start"], "end": row["end"],
                       "severity": severity, "issue": issue, "source": row["text"],
                       "translation_input": source_text(row), "translation": row.get("zh", ""),
                       "rule_ids": "; ".join(stage + ":" + item for stage, ids in hits.items() for item in ids),
                       "detail": detail})
    from opencc import OpenCC
    converter = OpenCC("t2s")
    for row in cache["segments"]:
        if is_pure_emoji(row["text"]):
            add(row, "filtered_emoji", "Pure emoji recognition result excluded from Chinese subtitles.", "info")
            continue
        review = row.get("audio_review", {})
        if review.get("status") == "omitted":
            add(row, "omitted_audio_region", review.get("note", "Audio review found no usable speech."), "info")
            continue
        if review.get("status") == "unresolved":
            add(row, "unresolved_audio", "Local audio review did not recover reliable replacement text.")
        if review.get("status") == "context_unresolved":
            add(row, "audio_context_uncertain", "A possible homophone/action mismatch remains after local audio review; check the surrounding dialogue.")
        if row.get("gap_review"):
            add(row, "gap_speech_recovered", "Speech was recovered from an untranscribed gap; verify the new wording.", "info")
            if row["gap_review"].get("avg_logprob", 0) < -.5:
                add(row, "low_confidence_recovery", "Recovered wording has low recognition confidence; review homophones and context.")
        from transcript_refinement import low_confidence
        refinement = row.get('refinement', {})
        if low_confidence(row):
            add(row, 'low_confidence_asr', 'Recognition scores suggest uncertain wording; review this audio region.')
        if refinement.get('status') == 'uncertain':
            add(row, 'uncertain_refinement', 'Local re-listening did not provide a reliable replacement; existing wording was retained.')
        if refinement.get('status') == 'revised':
            add(row, 'revised_asr', f"Local re-listening changed the source; parent ID: {refinement['parent_id']}; similarity: {refinement.get('similarity', 'unknown')}.",
                'warning' if refinement.get('similarity', 1) < .85 else 'info')
        if refinement.get('parts', 1) > 1:
            add(row, 'split_subtitle', f"Split using word timing; parent ID: {refinement['parent_id']}; part {refinement['part']}/{refinement['parts']}.", 'info')
        target = row.get("zh", "")
        if not target:
            add(row, "missing_translation", "No completed Chinese translation.")
            continue
        if any(row.get("rule_matches", {}).values()):
            add(row, "dictionary_rules_applied", "See rule_ids for the matching rules.", "info")
        if row.get("format_normalized"):
            add(row, "format_normalized", "Whitespace or redundant comma/full-stop formatting was cleaned.", "info")
        protected = []
        for term in row.get("glossary_terms", []):
            protected.extend((term["target"], converter.convert(term["target"])))
            if not any(value in target for value in (term["target"], converter.convert(term["target"]))):
                add(row, "glossary_not_used", f"Expected term: {term['source']} -> {term['target']}")
        residual = target
        for value in protected:
            residual = residual.replace(value, "")
        if re.search(r"[\u3041-\u3096\u30a1-\u30fa\u30fc]", residual):
            add(row, "possible_japanese_remaining", "Japanese characters remain outside protected glossary targets.")
        english = re.findall(r"[A-Za-z]{3,}", residual)
        introduced = [word for word in english if word.casefold() not in source_text(row).casefold()]
        if len(introduced) >= 2 or sum(map(len, introduced)) >= 12:
            add(row, "possible_extra_english", "English outside the source or glossary: " + ", ".join(introduced))
        for left, right in (("\u201c", "\u201d"), ("\u300c", "\u300d"), ("\u300e", "\u300f"), ("(", ")"), ("\uff08", "\uff09"), ("[", "]"), ("\u3010", "\u3011")):
            if target.count(left) != target.count(right):
                add(row, "unbalanced_punctuation", f"Check the {left}{right} pair.")
        if target.count('"') % 2:
            add(row, "unbalanced_punctuation", "Check the double-quote pair.")
        repetition = re.compile(r"(.{1,6})\1{2,}")
        def repeats_words(value):
            return any(any(char.isalnum() for char in match[1]) for match in repetition.finditer("".join(value.split())))
        if repeats_words(target) and not repeats_words(source_text(row)) and sound_key(row["text"]) is None:
            add(row, "possible_repetition", "Repeated translation pattern not present in the source.")
        if contains_emoji(target):
            add(row, "emoji_in_translation", "Emoji remains in the translation.")
        if len(target) > max(60, len(source_text(row)) * 4):
            add(row, "possible_expansion", "Translation is unusually long for its source.")
    for previous, row in zip(exported, exported[1:]):
        if previous["end"] > row["start"]:
            add(row, "overlapping_timing", "Export overlaps the preceding subtitle.")
    for row in exported:
        if row['end'] - row['start'] > 15:
            add(row, 'long_subtitle', 'Subtitle lasts more than 15 seconds; reliable word boundaries may be unavailable.')
    return result


def render_csv(rows: list[dict]) -> str:
    columns = ["id", "start", "end", "severity", "issue", "source", "translation_input", "translation", "rule_ids", "detail"]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        # Avoid spreadsheet formulas being evaluated when a report is opened.
        safe = {key: ("'" + value if isinstance(value, str) and value[:1] in {"=", "+", "-", "@"} else value) for key, value in row.items()}
        writer.writerow(safe)
    return "\ufeff" + output.getvalue()
