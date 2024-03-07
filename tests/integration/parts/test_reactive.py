# Copyright 2024 Canonical Ltd.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License version 3 as published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""Integration tests for the reactive plugin."""
import os
import shutil
import subprocess
import textwrap

import pytest

from craft_providers import bases
from craft_application import models

from charmcraft import env, utils


@pytest.mark.skipif(not os.getenv("CI") and not shutil.which("charm"), reason="charm tool not installed")
def test_reactive_charm(new_path, service_factory, simple_charm):
    subprocess.run(["charm", "create", "charmy-mccharmface"], check=True)
    shutil.move(new_path / "charmy-mccharmface", new_path / "src")
    service_factory.project = simple_charm
    os_platform = utils.get_os_platform()
    service_factory.set_kwargs(
        "lifecycle",
        work_dir=new_path,
        cache_dir=new_path,
        build_plan=[
            models.BuildInfo(
                platform="my-platform",
                build_on=utils.get_host_architecture(),
                build_for=utils.get_host_architecture(),
                base=bases.BaseName(os_platform.system, os_platform.release),
            )
        ]
    )

    service_factory.lifecycle.run("build")

    install_dir = new_path / "parts" / "charm" / "install"
    assert install_dir.is_dir()
    dispatch_file = install_dir / "dispatch"
    hooks_dir = install_dir / "hooks"
    install_hook = hooks_dir / "install"
    start_hook = hooks_dir / "start"
    upgrade_hook = hooks_dir / "upgrade-charm"
    for file in (dispatch_file, install_hook, start_hook, upgrade_hook):
        assert "JUJU_DISPATCH_PATH=" in file.read_text(), f"Incorrect file {file}"
