# Copyright 2021 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# For further info, check https://github.com/canonical/charmcraft

import pathlib
import sys
from subprocess import CalledProcessError, CompletedProcess
from unittest.mock import call, patch

import craft_parts
import pydantic
import pytest
import pytest_subprocess
from craft_parts import plugins
from craft_parts.errors import PluginEnvironmentValidationError

from charmcraft import const
from charmcraft.parts import reactive

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Windows not [yet] supported")


@pytest.fixture()
def charm_exe(tmp_path):
    """Provide a fake charm executable."""
    charm_bin = pathlib.Path(tmp_path, "mock_bin", "charm")
    charm_bin.parent.mkdir(exist_ok=True)
    charm_bin.write_text(
        '#!/bin/sh\necho \'{"charm-tools": {"version": "2.8.4", "git": "+git-7-6126e17", '
        '"gitn": 7, "gitsha": "6126e17", "pre_release": false, "snap": "+snap-x12"}}\''
    )
    charm_bin.chmod(0o755)
    return charm_bin


@pytest.fixture()
def broken_charm_exe(tmp_path):
    """Provide a fake charm executable that fails to run."""
    charm_bin = pathlib.Path(tmp_path, "mock_bin", "charm")
    charm_bin.parent.mkdir(exist_ok=True)
    charm_bin.write_text('#!/bin/sh\nexit 1"')
    charm_bin.chmod(0o755)
    return charm_bin


@pytest.fixture()
def spec(tmp_path):
    """Provide a common spec to build the different artifacts."""
    return {
        "plugin": "reactive",
        "source": str(tmp_path),
        "reactive-charm-build-arguments": [
            "--charm-argument",
            "--charm-argument-with argument",
        ],
    }


@pytest.fixture()
def plugin_properties(spec):
    return reactive.ReactivePluginProperties.unmarshal(spec)


@pytest.fixture()
def plugin(tmp_path, plugin_properties, spec):
    project_dirs = craft_parts.ProjectDirs(work_dir=tmp_path)
    part_spec = plugins.extract_part_properties(spec, plugin_name="reactive")
    part = craft_parts.Part(
        "foo", part_spec, project_dirs=project_dirs, plugin_properties=plugin_properties
    )
    project_info = craft_parts.ProjectInfo(
        application_name="test",
        project_dirs=project_dirs,
        cache_dir=tmp_path,
        project_name="fake-project",
    )
    part_info = craft_parts.PartInfo(project_info=project_info, part=part)

    return plugins.get_plugin(part=part, part_info=part_info, properties=plugin_properties)


def test_get_build_package(plugin):
    assert plugin.get_build_packages() == set()


def test_get_build_snaps(plugin):
    assert plugin.get_build_snaps() == set()


def test_get_build_environment(plugin):
    assert plugin.get_build_environment() == {"CRYPTOGRAPHY_OPENSSL_NO_LEGACY": "true"}


def test_get_build_commands(plugin, tmp_path):
    part_dir = tmp_path / "parts" / "foo"
    build_dir = part_dir / "build"
    charm_output_dir = build_dir / "fake-project"
    install_dir = part_dir / "install"
    assert plugin.get_build_commands() == [
        reactive.RUN_CHARM_FUNCTION,
        "run_charm proof",
        f"ln -sf {install_dir} {charm_output_dir}",
        f"run_charm build --charm-argument --charm-argument-with argument -o {build_dir}",
        f"rm -f {charm_output_dir}"
    ]


def test_invalid_properties(plugin):
    with pytest.raises(pydantic.ValidationError) as raised:
        plugin.properties_class.unmarshal({"source": ".", "reactive-invalid": True})
    err = raised.value.errors()
    assert len(err) == 1
    assert err[0]["loc"] == ("reactive-invalid",)
    assert err[0]["type"] == "value_error.extra"


def test_validate_environment(plugin, plugin_properties, charm_exe):
    validator = plugin.validator_class(
        part_name="my-part",
        env=f"PATH={str(charm_exe.parent)}",
        properties=plugin_properties,
    )
    validator.validate_environment()


def test_validate_environment_with_charm_part(plugin, plugin_properties):
    validator = plugin.validator_class(
        part_name="my-part", env="PATH=/foo", properties=plugin_properties
    )
    validator.validate_environment(part_dependencies=["charm-tools"])


def test_validate_missing_charm(
    fake_process: pytest_subprocess.FakeProcess, plugin, plugin_properties
):
    fake_process.register(["/bin/bash", fake_process.any()], returncode=127)
    validator = plugin.validator_class(
        part_name="my-part", env="/foo", properties=plugin_properties
    )
    with pytest.raises(PluginEnvironmentValidationError) as raised:
        validator.validate_environment()

    assert raised.value.reason == (
        "charm tool not found and part 'my-part' does not depend on a part named 'charm-tools'"
    )


def test_validate_broken_charm(plugin, plugin_properties, broken_charm_exe):
    validator = plugin.validator_class(
        part_name="my-part",
        env=f"PATH={str(broken_charm_exe.parent)}",
        properties=plugin_properties,
    )
    with pytest.raises(PluginEnvironmentValidationError) as raised:
        validator.validate_environment()

    assert raised.value.reason == "charm tools failed with error code 2"
