"""The gate: doing-tools are refused in the chat home, the drill's own tools are not."""
from ariadne_gate import gate


def test_doing_tools_are_blocked():
    for name in ("terminal", "write_file", "read_file", "search_files", "patch", "browser_navigate",
                 "code_execution", "delegate_task", "mcp__files__write_file"):
        assert gate.decide(name), name


def test_read_only_internet_is_conversation_and_is_allowed():
    # "What is the stock price" must be answerable in chat; the model is local, so a lookup spends no tokens.
    for name in ("web_search", "web_extract", "web_fetch", "x_search"):
        assert gate.decide(name) is None, name


def test_the_drill_is_allowed():
    for name in ("mcp__ariadne_tasks__submit_task", "mcp__ariadne_tasks__wait_task",
                 "mcp__ariadne_tasks__get_status", "submit_task", "clarify", "skill_view", "memory_recall"):
        assert gate.decide(name) is None, name


def test_the_message_tells_the_model_what_to_do_instead():
    reason = gate.decide("terminal")
    assert reason and "submit_task" in reason and "cannot do the work" in reason
