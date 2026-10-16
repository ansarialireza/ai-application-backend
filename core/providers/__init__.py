from .openai_compatible import OpenAICompatibleProvider


def get_provider(name: str):
    if name == "openai_compatible":
        return OpenAICompatibleProvider()
    raise ValueError(f"Unsupported provider: {name}")
