from app.commands import HELP_TEXT, parse_command


def test_parse_non_command_returns_none():
    assert parse_command("hello world") is None


def test_parse_folder_command_with_arg():
    assert parse_command("/folder ProjectX") == ("folder", "ProjectX")


def test_parse_folder_command_trims_and_keeps_spaces_in_name():
    assert parse_command("/folder  My Project  ") == ("folder", "My Project")


def test_parse_help_command_no_arg():
    assert parse_command("/help") == ("help", "")


def test_parse_is_case_insensitive_on_verb():
    assert parse_command("/HELP") == ("help", "")


def test_help_text_is_nonempty():
    assert HELP_TEXT.strip()
