"""Installer defaults — must work without administrator rights."""

from __future__ import annotations

from installer.install_gui import default_install_dir


def test_default_install_dir_is_user_profile():
    path = default_install_dir()
    text = str(path).lower()
    assert "program files" not in text
    assert "overnight edge" in text
