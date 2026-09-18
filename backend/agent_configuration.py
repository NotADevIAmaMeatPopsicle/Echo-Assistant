"""Map Echo's saved provider to the pinned Hermes runtime's native API modes."""

def model_profile(settings, keys):
    profiles = {
        'azure': ('azure-foundry', settings.azure_url, 'codex_responses', 'AZURE_FOUNDRY_API_KEY'),
        'openai': ('openai-api', 'https://api.openai.com/v1', 'codex_responses', 'OPENAI_API_KEY'),
        'anthropic': ('anthropic', 'https://api.anthropic.com', 'anthropic_messages', 'ANTHROPIC_API_KEY'),
        'local': ('custom', settings.local_url, 'chat_completions', 'OPENAI_API_KEY'),
    }
    if settings.provider not in profiles or not settings.model:
        raise ValueError('Choose a provider and model before applying Echo settings')
    key=keys.get(settings.provider,'')
    if not key and settings.provider!='local':
        raise ValueError('Save a key for the selected provider before applying Echo settings')
    provider,url,mode,secret=profiles[settings.provider]
    return {'model_config':{'provider':provider,'default':settings.model,'base_url':url,'api_mode':mode},
            'secret_name':secret,'provider_key':key or 'echo-local-no-key'}
