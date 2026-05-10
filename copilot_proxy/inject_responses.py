from copilot_proxy.utils import (generate_epoch_15min_later, generate_fake_asn,
                                 generate_fake_ip, generate_random_string)
import time

MODELS_TO_INJECT = {
    "data": [
        {
            "capabilities": {
                "family": "qwen3",
                "limits": {"max_prompt_tokens": 128000},
                "object": "model_capabilities",
                "supports": {"tool_calls": True},
                "tokenizer": "cl100k_base",
                "type": "chat",
            },
            "id": "qwen3.6-plus",
            "name": "Qwen 3.6 Plus",
            "object": "model",
            "model_picker_enabled": True,
            "version": "qwen3.6-plus",
        },
    ],
    "object": "list",
}

# Generate fresh token every time the module is loaded or requested?
# Better to make it valid for a long time.
LONG_EXPIRE_TIME = int(time.time()) + (365 * 24 * 60 * 60) # 1 year
tid = generate_random_string()

def get_token_inject():
    """Return fresh token dict to avoid expiration issues during long sessions."""
    return {
        "annotations_enabled": False,
        "chat_enabled": True,
        "chat_jetbrains_enabled": True,
        "code_quote_enabled": True,
        "codesearch": False,
        "copilot_ide_agent_chat_gpt4_small_prompt": False,
        "copilotignore_enabled": False,
        "endpoints": {
            "api": "https://api.githubcopilot.com",
            "origin-tracker": "https://origin-tracker.githubusercontent.com",
            "proxy": "https://copilot-proxy.githubusercontent.com",
            "telemetry": "https://copilot-telemetry-service.githubusercontent.com",
        },
        "expires_at": LONG_EXPIRE_TIME,
        "individual": True,
        "nes_enabled": False,
        "prompt_8k": True,
        "public_suggestions": "disabled",
        "refresh_in": 999999,
        "sku": "monthly_subscriber",
        "snippy_load_test_enabled": False,
        "telemetry": "disabled",
        "token": f"tid={tid};exp={LONG_EXPIRE_TIME};sku=monthly_subscriber;st=dotcom;chat=1;8kp=1;ip={generate_fake_ip()};asn={generate_fake_asn()}",
        "id": "copilot-token-id",
        "tracking_id": tid,
        "vsc_electron_fetcher": False,
    }

# Backwards compatibility
TOKEN_TO_INJECT = get_token_inject()
