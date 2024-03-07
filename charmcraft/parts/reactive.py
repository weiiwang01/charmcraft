# Copyright 2021-2024 Canonical Ltd.
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

"""Charmcraft's reactive plugin for craft-parts."""
import itertools
import json
import shlex
import subprocess
from typing import Any, cast

from craft_parts import plugins
from craft_parts.errors import PluginEnvironmentValidationError

RUN_CHARM_FUNCTION = """\
run_charm(){
    set +e
    charm $@
    retcode=$?
    set -e
    if (( $retcode == 0 )); then
        echo "charm $1 result: SUCCESS"
        return 0
    elif (( 100 <= $retcode && $retcode < 200 )); then
        echo "charm $1 result: WARNING ($retcode)" >&2
        return 0
    else
        echo "charm $1 result: ERROR ($retcode)" >&2
        return $retcode
    fi
}
"""


class ReactivePluginProperties(plugins.PluginProperties, plugins.PluginModel):
    """Properties used to pack reactive charms using charm-tools."""

    source: str
    reactive_charm_build_arguments: list[str] = []

    @classmethod
    def unmarshal(cls, data: dict[str, Any]):
        """Populate reactive plugin properties from the part specification.

        :param data: A dictionary containing part properties.

        :return: The populated plugin properties data object.

        :raise pydantic.ValidationError: If validation fails.
        """
        plugin_data = plugins.extract_plugin_properties(
            data, plugin_name="reactive", required=["source"]
        )
        return cls(**plugin_data)


class ReactivePluginEnvironmentValidator(plugins.validator.PluginEnvironmentValidator):
    """Check the execution environment for the Reactive plugin.

    :param part_name: The part whose build environment is being validated.
    :param env: A string containing the build step environment setup.
    """

    def validate_environment(self, *, part_dependencies: list[str] | None = None):
        """Ensure the environment contains dependencies needed by the plugin.

        :param part_dependencies: A list of the parts this part depends on.

        :raises PluginEnvironmentValidationError: If the environment is invalid.
        """
        try:
            version_data = json.loads(self._execute("charm version --format json"))

            tool_name = "charm-tools"
            if not (
                tool_name in version_data
                and "version" in version_data[tool_name]
                and "git" in version_data[tool_name]
            ):
                raise PluginEnvironmentValidationError(
                    part_name=self._part_name,
                    reason=f"invalid charm tools version {version_data}",
                )
            tools_version = (
                f"{tool_name} {version_data[tool_name]['version']} "
                f"({version_data[tool_name]['git']})"
            )
            print(f"found {tools_version}")
        except ValueError as err:
            raise PluginEnvironmentValidationError(
                part_name=self._part_name,
                reason="invalid charm tools installed",
            ) from err
        except subprocess.CalledProcessError as err:
            if err.returncode != plugins.validator.COMMAND_NOT_FOUND:
                raise PluginEnvironmentValidationError(
                    part_name=self._part_name,
                    reason=f"charm tools failed with error code {err.returncode}",
                ) from err

            if part_dependencies is None or "charm-tools" not in part_dependencies:
                raise PluginEnvironmentValidationError(
                    part_name=self._part_name,
                    reason=(
                        f"charm tool not found and part {self._part_name!r} "
                        f"does not depend on a part named 'charm-tools'"
                    ),
                ) from err


class ReactivePlugin(plugins.Plugin):
    """Build a reactive charm using charm-tools."""

    properties_class = ReactivePluginProperties
    validator_class = ReactivePluginEnvironmentValidator

    @classmethod
    def get_build_snaps(cls) -> set[str]:
        """Return a set of required snaps to install in the build environment."""
        return set()

    def get_build_packages(self) -> set[str]:
        """Return a set of required packages to install in the build environment."""
        return set()

    def get_build_environment(self) -> dict[str, str]:
        """Return a dictionary with the environment to use in the build step."""
        return {
            # Cryptography fails to load OpenSSL legacy provider in some circumstances.
            # Since we don't need the legacy provider, this works around that bug.
            "CRYPTOGRAPHY_OPENSSL_NO_LEGACY": "true"
        }

    def get_build_commands(self) -> list[str]:
        """Return a list of commands to run during the build step."""
        options = cast(ReactivePluginProperties, self._options)

        # The YAML List[str] schema would colocate any options with arguments
        # in the same string. This is not what we want as we need to send
        # these separately when calling out to the command later.
        #
        # Expand any such strings as we add them to the command.
        args = itertools.chain.from_iterable(
            shlex.split(arg) for arg in options.reactive_charm_build_arguments
        )
        command_args = " ".join(shlex.quote(i) for i in args)

        output_dir =  self._part_info.part_build_dir / self._part_info.project_name

        return [
            RUN_CHARM_FUNCTION,
            "run_charm proof",
            f"ln -sf {self._part_info.part_install_dir} {output_dir}",
            f"run_charm build {command_args} -o {self._part_info.part_build_dir}",
            f"rm -f {output_dir}"
        ]
