"""Recover independently confirmed Japanese sound effects in directional audio gaps."""
from pathlib import Path
from typing import Iterator

VERSION = 1
SAMPLE_RATE = 16000
PADDING = .2


def plan(source: Path, rows: list[dict]) -> Iterator[dict]:
    import numpy as np
    from faster_whisper.vad import get_speech_timestamps
    from .audio_review import decode_window
    from .counting import sessions

    counting = sessions(rows)
    end = 0.0
    for row in sorted(rows, key=lambda item: item['start']):
        start, end = end, max(end, row['end'])
        stop = row['start']
        if not 8 <= stop - start <= 120 or any(left < stop and right > start for left, right in counting):
            continue
        channels = [decode_window(source, start, stop, channel=channel) for channel in ('left', 'right')]
        peaks = [float(np.percentile(np.abs(audio), 99.5)) for audio in channels]
        loudest = int(peaks[1] > peaks[0])
        peak = peaks[loudest]
        # The second channel provides evidence that this is localized audio.
        if peak < .005 or peak < 4 * min(peaks):
            continue
        gain = min(16, .3 / peak)
        enhanced = np.clip(channels[loudest] * gain, -.85, .85)
        speech = get_speech_timestamps(enhanced, threshold=.25, min_speech_duration_ms=140,
                                      min_silence_duration_ms=260, speech_pad_ms=0)
        groups = []
        for region in speech:
            left, right = (round(start + region[key] / SAMPLE_RATE, 2) for key in ('start', 'end'))
            if min(left - start, stop - right) < .35:
                continue
            if groups and left - groups[-1][1] < 2.1 and right - groups[-1][0] <= 5.5:
                groups[-1][1] = right
                groups[-1][2] += 1
            else:
                groups.append([left, right, 1])
        for left, right, size in groups:
            if size < 2:
                continue
            center = (left + right) / 2
            yield {'left': max(start, min(left - .7, center - 1.8)),
                   'right': min(stop, max(right + .7, center + 1.8)),
                   'speech': [left, right], 'channel': ('left', 'right')[loudest], 'gain': gain}


def hypothesis(items: list[dict], window: dict) -> dict | None:
    from .source_checks import word_confidence
    from .subtitle_processing import kana_unit_key, repeated_kana, sound_key

    if len(items) != 1:
        return None
    row = items[0]
    sound = sound_key(row['text'])
    repeated = repeated_kana(kana_unit_key(row['text']))
    if (not sound or not sound.startswith('sound:') or not repeated or not 2 <= repeated[2] <= 6
            or row['avg_logprob'] < -.85 or row['no_speech_prob'] >= .5
            or row.get('compression_ratio', 0) > 2.4 or word_confidence(row) < .55):
        return None
    offset = window['left'] - PADDING
    left = max(window['left'], window['speech'][0] - .25, offset + row['start'])
    right = min(window['right'], window['speech'][1] + .25, offset + row['end'])
    if right - left < .8:
        return None
    return {'text': row['text'], 'start': left, 'end': right, 'sound': sound, 'repeats': repeated[2]}


def review_sounds(source: Path, cache: dict, path: Path, config: dict) -> None:
    import numpy as np
    from . import cli
    from .audio_review import ReviewRecognizer, decode_window, normalize_review_audio
    from .short_speech import alternate_available
    from .subtitle_processing import eligible_segments
    from .transcript_refinement import VERSION as REFINEMENT_VERSION

    if (cache.get('language') != 'ja' or config.get('quality', 'high') != 'high'
            or cli.asr_settings(config)['model'] != 'large-v2'):
        return
    state = cache.get('sound_review', {})
    if state.get('version') == VERSION and state.get('complete'):
        return
    if not alternate_available(config):
        return
    if state.get('version') != VERSION:
        state = {'version': VERSION, 'windows': list(plan(source, eligible_segments(cache))),
                 'passes': {}, 'complete': False}
        cache['sound_review'] = state
        cli.save_json(path, cache)
    for label, alternate in [('primary', False), ('alternate', True)]:
        recognizer = ReviewRecognizer(config, alternate=alternate)
        progress = state['passes'].setdefault(label, {'items': [], 'model': None})
        try:
            for i in range(len(progress['items']), len(state['windows'])):
                window = state['windows'][i]
                print(f"Checking directional sounds {i + 1}/{len(state['windows'])} ({label}; "
                      f"{cli.console_time(window['left'])})...", flush=True)
                audio = decode_window(source, window['left'], window['right'], channel=window['channel'])
                audio = np.clip(audio * window['gain'], -.85, .85)
                pad = round(PADDING * SAMPLE_RATE)
                audio = normalize_review_audio(np.pad(audio, (pad, pad)), peak_target=.25,
                                               max_gain=8, amplify_only=True)
                progress['items'].append(recognizer.short_clip(audio))
                progress['model'] = recognizer.model_name
                cli.save_json(path, cache)
        finally:
            recognizer.model = None
    primary, alternate = (state['passes'][label] for label in ('primary', 'alternate'))
    if primary['model'] and alternate['model'] and primary['model'] != alternate['model']:
        for i, window in enumerate(state['windows']):
            a = hypothesis(primary['items'][i], window)
            b = hypothesis(alternate['items'][i], window)
            if not a or not b or a['sound'] != b['sound']:
                continue
            left, right = max(a['start'], b['start']), min(a['end'], b['end'])
            if right - left < .8 or any(row['start'] < right and row['end'] > left
                                        for row in eligible_segments(cache)):
                continue
            identifier = max([row['id'] for row in cache['segments']]
                             + [int(key) for key in cache.get('refinement', {}).get('originals', {})],
                             default=0) + 1
            spoken = min((a, b), key=lambda item: item['repeats'])
            cache['segments'].append({'id': identifier, 'start': left, 'end': right, 'text': spoken['text'],
                                      'sound_review': {'window': i, 'channel': window['channel']},
                                      'refinement': {'version': REFINEMENT_VERSION, 'parent_id': identifier,
                                                     'status': 'unchanged'}})
    cache['segments'].sort(key=lambda row: (row['start'], row['end'], row['id']))
    state['complete'] = True
    cli.save_json(path, cache)
