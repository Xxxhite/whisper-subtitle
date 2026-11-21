"""Editable literal rules with per-entry translation cache invalidation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


class DictionaryError(ValueError):
    pass


def source_text(segment: dict) -> str:
    return segment.get("translation_text", segment["text"])


def normalize_translation(text: str, source: str = "") -> str:
    original = text
    for escaped in ("\\r\\n", "\\n", "\\r"):
        if escaped not in source:
            text = text.replace(escaped, " ")
    text = " ".join(text.split())
    text = re.sub(r"\uff0c{2,}", "\uff0c", text)
    text = re.sub(r"\u3002{2,}", "\u3002", text)
    if not source.lstrip().startswith(("\uff0c", "\u3002", "\u3001", ",")):
        text = text.lstrip("\uff0c\u3002")
    return text.strip() or " ".join(original.split())


def _matches(text: str, value: str, mode: str) -> bool:
    return text == value if mode == "exact" else value in text


def _signature(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class RuleBook:
    def __init__(self, data: dict | None = None, *, cleanup: bool = True):
        data = {"version": 1, "pre": [], "glossary": [], "post": []} if data is None else data
        if not isinstance(data, dict) or set(data) - {"version", "pre", "glossary", "post"} or type(data.get("version")) is not int or data["version"] != 1:
            raise DictionaryError("Dictionary must be an object with version: 1 and pre/glossary/post arrays.")
        self.cleanup = cleanup
        self.rules = {}
        ids = set()
        for stage in ("pre", "glossary", "post"):
            rules = data.get(stage, [])
            if not isinstance(rules, list):
                raise DictionaryError(f"Dictionary {stage} must be an array.")
            accepted = []
            for rule in rules:
                if not isinstance(rule, dict) or set(rule) - {"id", "enabled", "language", "source", "target", "match", "note", "when"}:
                    raise DictionaryError(f"Invalid {stage} rule fields.")
                for key in ("id", "source", "target"):
                    if not isinstance(rule.get(key), str) or not rule[key].strip():
                        raise DictionaryError(f"Each {stage} rule needs string id, source, and target fields; id/source cannot be empty.")
                if rule["id"] in ids:
                    raise DictionaryError(f"Duplicate dictionary rule id: {rule['id']}")
                ids.add(rule["id"])
                if type(rule.get("enabled", True)) is not bool or rule.get("language", "any") not in {"any", "zh", "ja", "en", "ko"}:
                    raise DictionaryError(f"Invalid enabled/language in rule {rule['id']}.")
                mode = rule.get("match", "contains" if stage == "glossary" else "exact")
                if mode not in {"exact", "contains", "sound"} or not isinstance(rule.get("note", ""), str):
                    raise DictionaryError(f"Invalid match/note in rule {rule['id']}.")
                if mode == 'sound' and (stage != 'glossary' or rule.get('language') != 'ja'
                                        or not re.fullmatch(r'[ぁ-ゖァ-ヺー]{1,8}', rule['source'])):
                    raise DictionaryError('Sound matching requires a Japanese glossary rule with one kana sound unit.')
                conditions = rule.get("when", {})
                allowed = {"source_equals", "source_contains", "translation_equals", "translation_contains"}
                if not isinstance(conditions, dict) or set(conditions) - allowed or any(not isinstance(v, str) or not v for v in conditions.values()):
                    raise DictionaryError(f"Invalid when conditions in rule {rule['id']}.")
                if stage != "post" and conditions:
                    raise DictionaryError("when conditions are supported only for post rules.")
                if stage == "post" and not ({"source_equals", "source_contains"} & set(conditions)):
                    raise DictionaryError(f"Post rule {rule['id']} requires an original-source condition.")
                if stage == "glossary" and not rule["target"].strip():
                    raise DictionaryError("Glossary targets cannot be empty.")
                if stage == "glossary" and any(char in rule[key] for key in ("source", "target", "note") if key in rule for char in ("\r", "\n")):
                    raise DictionaryError("Glossary entries must each fit on one line.")
                if rule.get("enabled", True):
                    accepted.append({**rule, "match": mode})
            self.rules[stage] = accepted

    @classmethod
    def load(cls, path: Path, *, cleanup: bool = True):
        if not path.exists():
            raise DictionaryError(f"Dictionary file not found: {path}")
        try:
            return cls(json.loads(path.read_text(encoding="utf-8-sig")), cleanup=cleanup)
        except (OSError, ValueError) as exc:
            raise DictionaryError(f"Could not load dictionary {path}: {exc}") from exc

    def _active(self, stage: str, language: str):
        return [rule for rule in self.rules[stage] if rule.get("language", "any") in {"any", language}]

    def match_glossary(self, text: str, language: str) -> list[dict]:
        from .subtitle_processing import repeated_kana, kana_unit_key
        sound = repeated_kana(text) if language == 'ja' else None
        matches = []
        for rule in self._active('glossary', language):
            if rule['match'] == 'sound':
                if sound and kana_unit_key(sound[1]) == kana_unit_key(rule['source']):
                    # Supply the spelling present in this entry so isolated model requests retain the hint.
                    matches.append({**rule, 'source': sound[1]})
            elif _matches(text, rule['source'], rule['match']):
                matches.append(rule)
        destinations = {}
        for rule in matches:
            if rule["source"] in destinations and destinations[rule["source"]] != rule["target"]:
                raise DictionaryError(f"Conflicting glossary targets for: {rule['source']}")
            destinations[rule["source"]] = rule["target"]
        covered = [False] * len(text)
        selected = []
        seen = set()
        for rule in sorted(matches, key=lambda item: -len(item["source"])):
            if rule["source"] in seen:
                continue
            seen.add(rule["source"])
            start = 0
            spans = []
            if rule['match'] == 'sound' and not any(covered):
                spans.append((0, len(text)))
            while rule['match'] != 'sound' and (start := text.find(rule["source"], start)) >= 0:
                end = start + len(rule["source"])
                if not any(covered[start:end]):
                    spans.append((start, end))
                start += 1
            if spans:
                selected.append(rule)
                for start, end in spans:
                    covered[start:end] = [True] * (end - start)
        return selected

    def _reviewed_lines(self, cache: dict) -> list[dict]:
        digest = cache.get("file_hash", "")
        if cache.get("language") != "ja" or not re.fullmatch(r"[0-9a-f]{64}", digest):
            return []
        path = Path(__file__).with_name("reviewed_lines") / (digest + ".json")
        if not path.exists():
            return []
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
            return entries
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise DictionaryError(f"Could not load reviewed subtitles {path}: {exc}") from exc

    def prepare(self, cache: dict, *, partial_speech: bool = False) -> int:
        entries = self._reviewed_lines(cache)
        reviewed = {(e["id"], e["asr"]): e for e in entries if "asr" in e}
        gaps = [dict(id=e["id"], start=e["start"], end=e["end"], text=e["source"],
                     zh=e["zh"], reviewed_gap=True, **({"opening_for": e["opening_for"]} if "opening_for" in e else {}))
                for e in entries if e.get("kind") == "gap"]
        if gaps:
            cache["reviewed_gaps"] = gaps
        else:
            cache.pop("reviewed_gaps", None)
        count_parents = {row["count_review"]["split_from"] for row in cache["segments"]
                         if "split_from" in row.get("count_review", {})}
        refreshed = 0
        for row in cache["segments"]:
            working = row["text"]
            hits = {"pre": [], "glossary": [], "post": []}
            for rule in self._active("pre", cache["language"]):
                if _matches(working, rule["source"], rule["match"]):
                    working = rule["target"] if rule["match"] == "exact" else working.replace(rule["source"], rule["target"])
                    hits["pre"].append(rule["id"])
            entry = reviewed.get((row.get("id"), working)) if not hits["pre"] else None
            matched = row
            if not entry and not hits["pre"] and row.get("id") in count_parents and row.get("original_asr"):
                original = row["original_asr"]
                prior = reviewed.get((row["id"], original["text"]))
                # A split count can shorten the source while retaining the reviewed dialogue.
                if prior and "match_span" in prior and "speech_span" in prior:
                    left, right = prior["speech_span"]
                    if row["start"] <= left < right <= row["end"]:
                        entry, matched = prior, original
            if entry and "match_span" in entry and any(
                abs(matched[key] - expected) > 0.01
                for key, expected in zip(("start", "end"), entry["match_span"], strict=True)
            ):
                entry = None
            reviewed_span = entry.get("speech_span") if entry else None
            if entry and entry.get("kind") == "timing":
                entry = None
            omit = entry and entry.get("kind") in {"duplicate", "unsupported"}
            if entry and not omit:
                working = entry["source"]
            fragment = None
            if omit:
                fragment = {"mode": "omit", "source": "", "reason": entry["reason"],
                            "reviewed_omission": entry["kind"], "evidence": []}
            elif partial_speech and cache["language"] == "ja" and not entry and not hits["pre"]:
                from .translation_evidence import assess_translation
                fragment = assess_translation(row, cache["segments"])
            if fragment:
                working = fragment["source"]
                row["translation_fragment"] = fragment
            else:
                row.pop("translation_fragment", None)
            terms = []
            for rule in self.match_glossary(working, cache["language"]) if working else ():
                terms.append({key: rule.get(key, "") for key in ("source", "target", "note")})
                hits["glossary"].append(rule["id"])
            inputs = {"source": working, "terms": terms}
            if fragment:
                inputs["uncertainty_mode"] = fragment["mode"]
            if entry and not omit:
                inputs["reviewed_zh"] = entry["zh"]
            signature = _signature(inputs)
            previous = row.get("rule_input_signature")
            changed = previous != signature if previous is not None else working != row["text"] or bool(terms)
            if changed:
                refreshed += int(bool(row.get("zh")))
                row.pop("zh", None)
                row.pop("model_zh", None)
            row.update(translation_text=working, glossary_terms=terms, rule_input_signature=signature, rule_matches=hits)
            row.pop("review_uncertainty", None)
            row.pop("reviewed_speech_span", None)
            if reviewed_span is not None:
                if not (isinstance(reviewed_span, list) and len(reviewed_span) == 2
                        and all(type(value) in (int, float) for value in reviewed_span)
                        and 0 <= reviewed_span[0] < reviewed_span[1] < float("inf")):
                    raise DictionaryError(f"Invalid reviewed speech span for entry {row['id']}.")
                if row["start"] <= reviewed_span[0] and reviewed_span[1] <= row["end"]:
                    row["reviewed_speech_span"] = reviewed_span
            if entry and not omit:
                if entry.get("uncertainty"):
                    row["review_uncertainty"] = entry["uncertainty"]
                self.store(row, entry["zh"], cache["language"])
                row.pop("model_zh", None)
                row["human_reviewed"] = True
            else:
                row.pop("human_reviewed", None)
            if fragment and fragment["mode"] in {"unclear", "omit"}:
                row.pop("model_zh", None)
                row.pop("needs_audio_review", None)
                if fragment["mode"] == "unclear":
                    row["zh"] = "〔听不清〕"
                else:
                    row.pop("zh", None)
            elif not entry and row.get("zh"):
                self.store(row, row.get("model_zh", row["zh"]), cache["language"])
        return refreshed

    def store(self, row: dict, text: str, language: str) -> None:
        row["model_zh"] = text
        original = row['text'] if row.get('translation_fragment') else source_text(row)
        result = text
        hits = row.setdefault("rule_matches", {"pre": [], "glossary": [], "post": []})
        hits["post"] = []
        for rule in self._active("post", language):
            matches = True
            for key, value in rule["when"].items():
                candidate = original if key.startswith("source_") else result
                matches &= candidate == value if key.endswith("equals") else value in candidate
            if matches and _matches(result, rule["source"], rule["match"]):
                result = rule["target"] if rule["match"] == "exact" else result.replace(rule["source"], rule["target"])
                hits["post"].append(rule["id"])
        cleaned = normalize_translation(result, original) if self.cleanup else result
        row["format_normalized"] = cleaned != result
        fragment = row.get("translation_fragment", {})
        row["zh"] = ("〔听不清〕" if fragment.get("before") else "") + cleaned + ("〔听不清〕" if fragment.get("after") else "")


def batch_glossary(rows: list[dict]) -> str:
    entries = []
    seen = set()
    for row in rows:
        for term in row.get("glossary_terms", []):
            line = term["source"] + "->" + term["target"]
            if term.get("note"):
                line += " # " + term["note"]
            if line not in seen:
                entries.append(line)
                seen.add(line)
    return "\n".join(entries)
