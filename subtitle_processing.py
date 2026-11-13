"""Conservatively combine adjacent repetitions in final Chinese subtitles."""
import re
import unicodedata


def contains_emoji(text: str) -> bool:
    return any(0x1F000 <= ord(char) <= 0x1FAFF or 0x2600 <= ord(char) <= 0x27BF or char == "\u20e3" for char in text)


def is_pure_emoji(text: str) -> bool:
    visible = re.sub(r"[0-9#*]\ufe0f?\u20e3", "", text)
    return contains_emoji(text) and not any(char.isalpha() or char.isdigit() for char in visible)


def eligible_segments(cache: dict) -> list[dict]:
    return [row for row in cache["segments"] if not is_pure_emoji(row["text"])
            and row.get("audio_review", {}).get("status") != "omitted"]


def prepare_subtitles(segments: list[dict], *, merge_sounds: bool = True, minimum: float = .8) -> list[dict]:
    def ticks(seconds):
        return max(0, int(seconds * 100 + .5))

    limit = ticks(max((row["end"] for row in segments), default=0))
    rows = [dict(row) for row in segments if not contains_emoji(row["text"]) and not contains_emoji(row.get("zh", ""))
            and row.get("audio_review", {}).get("status") != "omitted"]
    if merge_sounds:
        rows = merge_repeated_sounds(rows)
    # Work on centisecond ticks, matching LRC precision and avoiding float carries.
    result = []
    floor = ticks(minimum)
    index = 0
    while index < len(rows):
        row = dict(rows[index])
        start = ticks(row["start"])
        end = ticks(row["end"])
        while end - start < floor and index + 1 < len(rows):
            next_row = rows[index + 1]
            next_start = ticks(next_row["start"])
            if next_start >= start + floor:
                break
            row["text"] += " " + next_row["text"]
            row["zh"] = row.get("zh", "") + " " + next_row.get("zh", "")
            end = max(end, ticks(next_row["end"]))
            index += 1
        next_start = ticks(rows[index + 1]["start"]) if index + 1 < len(rows) else None
        end = max(end, start + floor)
        if next_start is not None:
            end = min(end, next_start)
        row["start"], row["end"] = start / 100, end / 100
        result.append(row)
        index += 1
    if result and ticks(result[-1]["end"]) > limit:
        last = result[-1]
        earlier_start = max(0, limit - floor)
        if len(result) == 1 or ticks(result[-2]["end"]) <= earlier_start:
            last["start"], last["end"] = earlier_start / 100, limit / 100
        else:
            previous = result[-2]
            previous["text"] += " " + last["text"]
            previous["zh"] = previous.get("zh", "") + " " + last.get("zh", "")
            previous["end"] = limit / 100
            result.pop()
    return result


def sound_key(text: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", text)
    kana = "".join(chr(ord(char) - 0x60) if 0x30A1 <= ord(char) <= 0x30F6 else char for char in normalized)
    kana = "".join(char for char in kana if not char.isspace() and not unicodedata.category(char).startswith("P"))
    # Decorated hums/breaths are distinct from plain affirmative or surprised words.
    if re.fullmatch(r"\u3093[\u3093\u30fc\u3063]+", kana):
        return "hum:n"
    if re.fullmatch(r"\u3075[\u3045\u3046\u30fc\u3063]+", kana):
        return "breath:fu"
    if re.fullmatch(r"\u306f[\u3041\u3042\u30fc\u3063]+", kana):
        return "breath:ha"
    kana = kana.replace("\u30fc", "").rstrip("\u3063")
    # Repeated laughter; ordinary acknowledgments and exclamations stay intact.
    laugh = re.fullmatch(r"([\u3075\u306f\u3078\u307b\u3072\u304f])\1+", kana)
    if laugh:
        return "laugh:" + laugh[1]
    laugh = re.fullmatch(r"(?:\u3042\u306f+|[\u3046\u3093]\u3075+|\u3048\u3078+|\u304a\u307b+)", kana)
    if laugh:
        return "laugh:" + kana[-1]
    sound = re.fullmatch(r"(.{1,4})\1+", kana)
    known = {"\u304f\u3059", "\u3051\u3089", "\u3052\u3089", "\u3071\u3061", "\u3068\u3093", "\u3053\u3093", "\u3054\u308d", "\u307a\u308d", "\u3082\u3050", "\u307d\u3093", "\u3053\u3061\u3087"}
    return "sound:" + sound[1] if sound and sound[1] in known else None


def merge_repeated_sounds(segments: list[dict], *, max_gap: float = 1.0, max_span: float = 10.0) -> list[dict]:
    merged = []
    previous_key = None
    for segment in segments:
        key = sound_key(segment["text"])
        if (merged and key is not None and key == previous_key
                and 0 <= segment["start"] - merged[-1]["end"] <= max_gap
                and segment["end"] - merged[-1]["start"] <= max_span):
            merged[-1]["end"] = segment["end"]
        else:
            merged.append(dict(segment))
        previous_key = key
    return merged
