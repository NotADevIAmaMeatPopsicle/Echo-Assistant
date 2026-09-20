"""Regenerate the local CC-BY-SA-4.0 swipe lexicon; not a runtime dependency."""
from importlib.metadata import version
import json
from pathlib import Path
import re


def main():
    if version('wordfreq') != '3.1.1':
        raise SystemExit('Use wordfreq==3.1.1; see THIRD_PARTY_NOTICES.md.')
    from wordfreq import top_n_list
    words = [w for w in top_n_list('en', 25000) if re.fullmatch('[a-z]{1,20}', w)][:16000]
    for word in ['echo', 'spotify', 'thermostat', 'bedroom', 'patio']:
        if word not in words:
            words.append(word)
    data = {'source': 'wordfreq 3.1.1 English frequency list; Robyn Speer and credited sources',
            'license': 'CC-BY-SA-4.0', 'words': words}
    path = Path(__file__).resolve().parents[1] / 'web/display/keyboard-words.json'
    path.write_text(json.dumps(data, separators=(',', ':')) + '\n', encoding='utf-8')
    print(f'Wrote {len(words)} words. Retain the wordfreq attribution and data license.')


if __name__ == '__main__':
    main()
