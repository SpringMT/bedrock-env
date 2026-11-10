from bedrock_env import cli


def test_run_passes_options_after_double_dash_to_command(monkeypatch):
    seen = {}

    class FakeRunner:
        def __init__(self, command, *_args, **_kwargs):
            seen["command"] = command

        def run(self):
            return -15

    monkeypatch.setattr(cli, "Runner", FakeRunner)
    code = cli.main(["run", "--profile", "p", "--", "app", "--profile", "x"])
    assert seen["command"] == ["app", "--profile", "x"]
    assert code == 128 + 15


def test_run_without_command(capsys):
    assert cli.main(["run"]) == 2
