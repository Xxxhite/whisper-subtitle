"""Human-readable CSV findings; checks do not silently rewrite uncertain text."""
import csv
import io
import re

from .dictionary_rules import source_text
from .subtitle_processing import contains_emoji, is_pure_emoji, sound_key
from .translation_checks import uncertain_source


def findings(cache: dict, exported: list[dict]) -> list[dict]:
    result = []
    restored_openings = {row["opening_for"] for row in exported if row.get("reviewed_gap") and "opening_for" in row}
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
        from .source_checks import artifact, implausible_duplicate
        issue = artifact(row['text'])
        if issue:
            add(row, 'source_' + issue, 'Malformed or nonlexical source text requires audio confirmation; excluded from final subtitles.', 'info')
        safety = row.get('source_review', {})
        if row.get("review_uncertainty"):
            add(row, "partially_reviewed_speech", row["review_uncertainty"])
        elif row.get('human_reviewed'):
            add(row, 'human_reviewed', 'Source wording and Chinese subtitle verified by human review.', 'info')
        if row.get("reviewed_speech_span"):
            start, end = row["reviewed_speech_span"]
            add(row, "reviewed_speech_span", f"Reviewed speech interval: {start:.2f} to {end:.2f} seconds.", "info")
        fragment = row.get('translation_fragment')
        if fragment:
            if fragment.get("reviewed_omission") or fragment.get("reviewed_duplicate"):
                issue = "reviewed_" + fragment.get("reviewed_omission", "duplicate")
                add(row, issue, fragment["reason"], "info")
                continue
            mode = fragment.get("mode", "partial")
            evidence = " | ".join(f"{e['model']}: {e.get('text', e.get('noun', ''))}" for e in fragment["evidence"])
            reason = fragment.get("reason") or f"Disputed noun: {fragment.get('noun', '')}."
            disputed = []
            if fragment.get("before"):
                disputed.append(f"{row['start']:.2f} to {fragment['start']:.2f}s")
            if fragment.get("after"):
                disputed.append(f"{fragment['end']:.2f} to {row['end']:.2f}s")
            location = ("Unclear: " + ", ".join(disputed)) if disputed else f"Interval {row['start']:.2f} to {row['end']:.2f}s"
            add(row, {"partial": "partially_translated_speech", "unclear": "unintelligible_speech",
                      "omit": "unconfirmed_voice"}[mode],
                f"{reason} {location}. {evidence}")
            if mode != "partial":
                continue
        alignment=row.get('alignment_review',{})
        if alignment.get('status')=='recovered':
            add(row,'word_alignment_repaired','Two local models confirmed a weak boundary or collapsed tail correction; raw ASR is retained.','info')
        elif alignment.get('status')=='uncertain':
            add(row,'collapsed_alignment_uncertain','A weak opening or collapsed word tail remains unconfirmed; inspect this source region.')
        if safety.get('status') == 'recovered' and safety.get('reason') == 'contextual_homophones':
            add(row, 'source_spelling_normalized', 'The surrounding words disambiguated an identical reading; original ASR is retained.', 'info')
        elif safety.get('status') == 'recovered':
            add(row, 'source_recovered', 'Acoustic source verification recovered or corrected this entry; original ASR is retained.', 'info')
            if safety.get("reason") == "local_word_evidence" and row.get("refinement", {}).get("part", 1) == 1:
                from .source_review import OPENING_SOUND
                from .source_checks import reading
                opening = OPENING_SOUND.match(safety.get("original_text", ""))
                # A clipped ending (あっ vs あ) still represents the opening sound.
                prefix = reading(opening[1].rstrip("っー")) if opening else ""
                if prefix and row["id"] not in restored_openings and not reading(row["text"]).startswith(prefix):
                    add(row, "opening_sound_missing",
                        f"Initial ASR began with 「{opening[1]}」. Check the audio around the start of this line.")
        elif safety.get('status') == 'unresolved':
            add(row, 'source_verification_uncertain', 'Contextual spelling or audio checks did not provide sufficient agreement; inspect the retained source.')
        if safety.get('remaining_hints'):
            add(row, 'source_verification_partial', 'Some proposed spellings remain unconfirmed; inspect the retained source words.')
        if safety.get('status') == 'retimed':
            add(row, 'source_timing_repaired', 'Two local hypotheses narrowed an implausibly long short phrase to observed word times.', 'info')
        count = row.get('count_review', {})
        if count.get('status') == 'recovered':
            add(row, 'count_recovered', 'Two local models confirmed this count; raw ASR is retained.', 'info')
            if count.get('soft'):
                add(row, 'count_low_confidence', 'Quiet count recovery used weaker acoustic evidence with unprompted corroboration; verify the number.')
        elif count.get('status') == 'uncertain':
            add(row, 'count_uncertain', 'Local count verification did not confirm a replacement; inspect the retained source.')
        if implausible_duplicate(row, cache['segments']):
            add(row, 'implausible_source_duplicate', 'A long repeated source sentence occupies an unusually short time interval.')
        if is_pure_emoji(row["text"]):
            add(row, "filtered_emoji", "Pure emoji recognition result excluded from Chinese subtitles.", "info")
            continue
        review = row.get("audio_review", {})
        if review.get("status") == "omitted":
            add(row, "omitted_audio_region", review.get("note", "Audio review found no usable speech."), "info")
            continue
        if review.get("status") == "unresolved":
            add(row, "unresolved_audio", "Local audio review did not recover reliable replacement text.")
        if row.get('omitted_speech_review', {}).get('status') == 'restored':
            add(row, 'omitted_quiet_speech_restored', 'Two local models re-confirmed previously omitted quiet speech.', 'info')
        elif review.get('status') == 'restored':
            add(row, 'rejected_review_restored', 'Restored the earlier transcript after an invalid replacement.', 'info')
        if review.get("status") == "context_unresolved":
            add(row, "audio_context_uncertain", "A possible homophone/action mismatch remains after local audio review; check the surrounding dialogue.")
        short = row.get('short_review', {})
        if short.get('status') == 'recovered':
            add(row, 'short_speech_recovered', 'Quiet gap speech was confirmed by two local models.', 'info')
        elif short.get('status') == 'revised':
            add(row, 'short_speech_revised', 'Two local models agreed on a replacement for a similar-sounding short line; review the wording.')
        elif short.get('status') == 'supplemented':
            add(row, 'internal_speech_recovered', 'Two local models confirmed a missing phrase near a weak aligned word; original wording was retained.', 'info')
        elif short.get('status') == 'uncertain':
            add(row, 'short_speech_uncertain', 'Short-line review lacked reliable two-model agreement; existing wording was retained.', 'info')
        if row.get("gap_review"):
            add(row, "gap_speech_recovered", "Speech was recovered from an untranscribed gap; verify the new wording.", "info")
            if row["gap_review"].get("avg_logprob", 0) < -.5:
                add(row, "low_confidence_recovery", "Recovered wording has low recognition confidence; review homophones and context.")
        if row.get('sound_review'):
            add(row, 'directional_sound_recovered', 'Two local models confirmed this repeated sound effect in an uncovered stereo interval.', 'info')
        from .transcript_refinement import low_confidence
        refinement = row.get('refinement', {})
        if row.get('weak_sequence_review', {}).get('status') == 'recovered':
            add(row, 'weak_sequence_recovered', 'Two local models recovered speech spanning an unreliable boundary.', 'info')
        if refinement.get('question_restored'):
            add(row, 'question_restored', 'Restored the original question mark for the same recognized words.', 'info')
        if refinement.get('primary_supported_original'):
            add(row, 'refinement_original_restored', 'Restored archived words supported by the primary model.', 'info')
        if row.get('word_padding_trimmed'):
            add(row, 'word_padding_trimmed', 'Removed long timing padding outside the reliably aligned words.', 'info')
        if refinement.get('source_protected') and refinement.get('part', 1) == 1 and short.get('status') != 'supplemented':
            add(row, 'protected_source', 'Reliable initial wording was preserved; only word-based subtitle splitting was applied.', 'info')
        if low_confidence(row):
            add(row, 'low_confidence_asr', 'Recognition scores suggest uncertain wording; review this audio region.')
        if refinement.get('status') == 'uncertain' and row.get('weak_sequence_review', {}).get('status') != 'recovered':
            add(row, 'uncertain_refinement', 'Local re-listening did not provide a reliable replacement; existing wording was retained.')
        if row.get('zh') and uncertain_source(row):
            candidates = [f"{p['model']} ({channel.split(':')[-1]}): " + ' '.join(i['text'] for i in p['items'])
                          for channel, p in safety.get('passes', {}).items() if p.get('items')]
            if not candidates:
                candidates = [f"{refinement.get(model, label)}: " + ' '.join(i['text'] for i in refinement[label])
                              for label, model in [('recognized', 'primary_model'), ('alternate_recognized', 'alternate_model')]
                              if refinement.get(label)]
            weak = [f"{w['word']} ({w['probability']:.2f})" for w in row.get('words', [])
                    if w.get('probability', 1) < .42 and re.search(r'[一-鿿]', w['word'])]
            detail = ['Independent recognition did not confirm the source wording.']
            if weak:
                detail.append('Weak tokens: ' + ', '.join(weak))
            detail.extend(candidates)
            add(row, 'translation_from_uncertain_source', ' | '.join(detail))
        if refinement.get('status') == 'revised':
            add(row, 'revised_asr', f"Local re-listening changed the source; parent ID: {refinement['parent_id']}; similarity: {refinement.get('similarity', 'unknown')}.",
                'warning' if refinement.get('similarity', 1) < .85 else 'info')
        if refinement.get('parts', 1) > 1:
            add(row, 'split_subtitle', f"Split using word timing; parent ID: {refinement['parent_id']}; part {refinement['part']}/{refinement['parts']}.", 'info')
        target = row.get("zh", "")
        if not target:
            add(row, "missing_translation", "No completed Chinese translation.")
            continue
        from .translation_checks import meaning_errors, context_for
        for meaning in meaning_errors(source_text(row), target, context_for(row, cache['segments'])):
            add(row, 'translation_' + meaning, 'A source-conditioned check found a changed relationship or clause type.')
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
    short = cache.get("short_speech", {})
    if short.get("complete") and short.get("distinct_models"):
        passes = short.get("passes", {})
        for index, window in enumerate(short.get("candidates", [])):
            if window.get("kind") != "gap" or not window.get("speech"):
                continue
            start, end = window["speech"]
            if any(s["start"] < end and start < s["end"] for s in exported):
                continue
            evidence = []
            for record in passes.values():
                results = record.get("results", [])
                if index < len(results):
                    words = " / ".join(item["text"] for item in results[index]) or "(no words)"
                    evidence.append(f"{record.get('model', '?')}: {words}")
            if len(evidence) >= 2:
                gap = {"id": f"gap-{index}", "start": start, "end": end, "text": ""}
                add(gap, "unconfirmed_speech_gap", "Uncovered acoustic candidate; " + " | ".join(evidence))
    for previous, row in zip(exported, exported[1:]):
        if previous["end"] > row["start"]:
            add(row, "overlapping_timing", "Export overlaps the preceding subtitle.")
    for row in exported:
        if row.get("reviewed_gap"):
            add(row, "human_reviewed_gap", "Human listening confirmed an utterance in an uncovered interval.", "info")
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
