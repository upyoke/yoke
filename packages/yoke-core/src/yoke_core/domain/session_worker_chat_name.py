"""Format the native name of an item-assigned worker chat."""


def format_worker_chat_name(item_ref: str, item_title: str) -> str:
    return f"{item_ref}: {' '.join(item_title.split())}"[:160]
