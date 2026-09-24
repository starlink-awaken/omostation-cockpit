import argparse
import json
from unittest.mock import patch
import pytest

from cockpit.commands.panorama import cmd_panorama
from cockpit.commands.dashboard import cmd_dashboard


def test_panorama_sunset_json(capsys):
    args = argparse.Namespace(
        sunset=True,
        web=False,
        wallboard=False,
        tab=None,
        port=5173,
        json=True,
        global_output="json",
    )
    code = cmd_panorama(args)
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["action"] == "sunset_check"


def test_panorama_web_dispatch():
    args = argparse.Namespace(
        sunset=False,
        web=True,
        wallboard=True,
        tab="guardian",
        port=5173,
        json=False,
        global_output="text",
    )
    with patch("webbrowser.open") as mock_open:
        code = cmd_panorama(args)
        assert code == 0
        mock_open.assert_called_once_with("http://localhost:5173/panorama?tab=guardian")


def test_panorama_web_json(capsys):
    args = argparse.Namespace(
        sunset=False,
        web=True,
        wallboard=False,
        tab="gates",
        port=5173,
        json=True,
        global_output="json",
    )
    code = cmd_panorama(args)
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["ok"] is True
    assert data["target_url"] == "http://localhost:5173/panorama?tab=gates"


def test_dashboard_with_panorama_flag():
    args = argparse.Namespace(
        port=5173,
        host="127.0.0.1",
        panorama=True,
        tab="topology",
        status_only=True,
        dry_run=False,
        no_open=True,
        json=True,
        global_output="json",
    )
    with patch("cockpit.commands.dashboard.is_dashboard_alive", return_value=True):
        code = cmd_dashboard(args)
        assert code == 0
