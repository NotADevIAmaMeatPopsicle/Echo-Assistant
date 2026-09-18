"""Prepare a local-only Pocket configuration; run inside the isolated TTS environment."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def expected_config(root=ROOT):
    folder = root/'local/models/pocket-tts-english-official'
    config = yaml.safe_load((folder/'upstream-english.yaml').read_text(encoding='utf-8'))
    weights = str((folder/'languages/english/model.safetensors').resolve())
    config['weights_path'] = weights
    config['weights_path_without_voice_cloning'] = weights
    config['flow_lm']['lookup_table']['tokenizer_path'] = str((folder/'languages/english/tokenizer.model').resolve())
    return config


def prepare(root=ROOT):
    config = expected_config(root)
    output = yaml.safe_dump(config, sort_keys=False)
    if 'hf://' in output or 'https://' in output: raise ValueError('Unexpected remote model dependency')
    (root/'local/pocket-english-local.yaml').write_text(output,encoding='utf-8')


if __name__ == '__main__': prepare()
