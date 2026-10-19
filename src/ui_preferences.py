"""Small persistent interface preferences, kept outside application installs."""
import json
import updater


def load():
    try:
        value = json.loads((updater.data_directory() / 'interface.json').read_text(encoding='utf-8'))
        return {'save_success_prompt': value.get('save_success_prompt', True) is not False}
    except (OSError, ValueError, AttributeError):
        return {'save_success_prompt': True}


def save_success_prompt(enabled):
    target = updater.data_directory() / 'interface.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps({'save_success_prompt': bool(enabled)}), encoding='utf-8')
    temporary.replace(target)
