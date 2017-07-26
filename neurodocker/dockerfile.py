"""Functions and classes to generate Dockerfiles."""
# Author: Jakub Kaczmarzyk <jakubk@mit.edu>

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import os

import neurodocker
from neurodocker import interfaces
from neurodocker.utils import indent, manage_pkgs


def _base_add_copy(list_srcs_dest, cmd):
    srcs = list_srcs_dest[:-1]
    dest = list_srcs_dest[-1]

    for src in srcs:
        if os.path.isabs(src):
            raise ValueError("Path for {} cannot be absolute: {}"
                             "".format(cmd, src))
    srcs = '", "'.join(srcs)
    return '{} ["{}", "{}"]'.format(cmd, srcs, dest)


def _add_add(list_srcs_dest, **kwargs):
    """Return Dockerfile ADD instruction to add file or directory to Docker
    image.

    See https://docs.docker.com/engine/reference/builder/#add.

    Parameters
    ----------
    list_srcs_dest : list of str
        All of the items except the last one are paths on local machine or a
        URL to a file to be copied into the Docker container. Paths on the
        local machine must be within the build context. The last item is the
        destination in the Docker image for these file or directories.
    """
    return _base_add_copy(list_srcs_dest, "ADD")


def _add_base(base, **kwargs):
    """Return Dockerfile FROM instruction to specify base image.

    Parameters
    ----------
    base : str
        Base image.
    """
    return "FROM {}".format(base)


def _add_copy(list_srcs_dest, **kwargs):
    """Return Dockerfile COPY instruction to add files or directories to Docker
    image.

    See https://docs.docker.com/engine/reference/builder/#add.

    Parameters
    ----------
    list_srcs_dest : list of str
        All of the items except the last one are paths on local machine to be
        copied into the Docker container. These paths must be within the build
        context. The last item is the destination in the Docker image for these
        file or directories.
    """
    return _base_add_copy(list_srcs_dest, "COPY")


def _add_exposed_ports(exposed_ports, **kwargs):
    """Return Dockerfile EXPOSE instruction to expose ports.

    Parameters
    ----------
    exposed_ports : str, list, tuple
        Port(s) in the container to expose.
    """
    if not isinstance(exposed_ports, (list, tuple)):
        exposed_ports = [exposed_ports]
    return "EXPOSE " + " ".join((str(p) for p in exposed_ports))


def _add_entrypoint(entrypoint, **kwargs):
    """Return Dockerfile ENTRYPOINT instruction to set image entrypoint.

    Parameters
    ----------
    entrypoint : str
        The entrypoint.
    """
    import json

    escaped = json.dumps(entrypoint)
    return "ENTRYPOINT [{}]".format('", "'.join(escaped.split()))


def _add_env_vars(env_vars, **kwargs):
    """Return Dockerfile ENV instruction to set environment variables.

    Parameters
    ----------
    env_vars : dict
        Environment variables where keys are the environment variables names,
        and values are the values assigned to those environment variable names.
    """
    import json
    out = ""
    for k, v in env_vars.items():
        newline = "\n" if out else ""
        v = json.dumps(v)  # Escape double quotes and other things.
        out += '{}{}={}'.format(newline, k, v)
        print(out)
    return indent("ENV", out)


def _add_install(kwargs):
    """Return Dockerfile RUN instruction that installs system packages.

    Parameters
    ----------
    kwargs : dict
        Must contain key 'pkgs' with list of packages to install, and key
        'pkg_manager' with a string of the package manager (apt or yum).
    """
    pkgs = ' '.join(kwargs['pkgs'])
    cmd = "{install}\n&& {clean}".format(**manage_pkgs[kwargs['pkg_manager']])
    cmd = cmd.format(pkgs=pkgs)
    return indent("RUN", cmd)

def _add_arbitrary_instruction(instruction, **kwargs):
    """Return `instruction`."""
    comment = "# User-defined instruction\n"
    return comment + instruction


class _DockerfileUsers(object):
    """Class to add instructions to add Dockerfile users. Has memory of users
    already added to the Dockerfile.
    """
    initialized_users = ['root']

    @classmethod
    def add(cls, user, **kwargs):
        instruction = "USER {0}"
        if user not in cls.initialized_users:
            cls.initialized_users.append(user)
            comment = "# Create new user: {0}"
            inst_user = ("RUN useradd --no-user-group --create-home"
                         " --shell /bin/bash {0}")
            instruction = "\n".join((comment, inst_user, instruction))
        return instruction.format(user)

    @classmethod
    def clear_memory(cls):
        cls.initialized_users = ['root']


def _add_common_dependencies(pkg_manager):
    """Return Dockerfile instructions to download dependencies common to
    many software packages.

    Parameters
    ----------
    pkg_manager : {'apt', 'yum'}
        Linux package manager.
    """
    deps = "bzip2 ca-certificates curl unzip"
    if pkg_manager == "yum":
        deps += " epel-release"

    comment = ("#----------------------------\n"
               "# Install common dependencies\n"
               "#----------------------------")
    cmd = "{install}\n&& {clean}".format(**manage_pkgs[pkg_manager])
    cmd = cmd.format(pkgs=deps)
    # Create directory for Miniconda as route and modify permissions so
    # non-root users can create their conda environments there.
    cmd += ("\n&& mkdir {0} && chmod 777 {0}"
            "".format(interfaces.Miniconda.INSTALL_PATH))
    cmd = indent("RUN", cmd)

    return "\n".join((comment, cmd))


def _add_neurodocker_header():
    """Return Dockerfile comment that references Neurodocker."""
    import datetime
    version = neurodocker.__version__
    timestamp = datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S")
    return ("# Generated by Neurodocker v{}."
            "\n#"
            "\n# Thank you for using Neurodocker. If you discover any issues "
            "\n# or ways to improve this software, please submit an issue or "
            "\n# pull request on our GitHub repository:"
            "\n#     https://github.com/kaczmarj/neurodocker"
            "\n#"
            "\n# Timestamp: {}".format(version, timestamp))


# Dictionary of each instruction or software package can be added to the
# Dockerfile and the function that returns the Dockerfile instruction(s).
dockerfile_implementations = {
    'software': {
        'afni': interfaces.AFNI,
        'ants': interfaces.ANTs,
        'freesurfer': interfaces.FreeSurfer,
        'fsl': interfaces.FSL,
        'miniconda': interfaces.Miniconda,
        'mrtrix3': interfaces.MRtrix3,
        'neurodebian': interfaces.NeuroDebian,
        'spm': interfaces.SPM,
    },
    'other': {
        'add': _add_add,
        'base': _add_base,
        'copy': _add_copy,
        'entrypoint': _add_entrypoint,
        'expose': _add_exposed_ports,
        'env': _add_env_vars,
        'install': _add_install,
        'instruction': _add_arbitrary_instruction,
        'user': _DockerfileUsers.add,
    },
}


def _get_dockerfile_chunk(instruction, options, specs):
    """Return piece of Dockerfile (str) to implement `instruction` with
    `options`. Include the dictionary of specifications.
    """
    software_keys = dockerfile_implementations['software'].keys()
    other_keys = dockerfile_implementations['other'].keys()

    if instruction in software_keys:
        for ii in ['pkg_manager', 'check_urls']:
            options.setdefault(ii, specs[ii])
        callable_ = dockerfile_implementations['software'][instruction]
        chunk = callable_(**options).cmd
    elif instruction in other_keys:
        if instruction == "install":
            options = {'pkgs': options, 'pkg_manager': specs['pkg_manager']}
            print(options)
        chunk = dockerfile_implementations['other'][instruction](options)
    else:
        raise ValueError("Instruction not understood: {}"
                         "".format(instruction))
    return chunk


def _get_dockerfile_chunks(specs):
    """Return list of Dockerfile chunks (str) given a dictionary of
    specifications.
    """
    import copy
    dockerfile_chunks = []
    specs = copy.deepcopy(specs)

    for instruction, options in specs['instructions']:
        chunk = _get_dockerfile_chunk(instruction, options, specs)
        dockerfile_chunks.append(chunk)

    _DockerfileUsers.clear_memory()
    return dockerfile_chunks


class Dockerfile(object):
    """Class to create Dockerfile.

    Parameters
    ----------
    specs : dict
        Dictionary of specifications.
    """

    def __init__(self, specs):
        from neurodocker.parser import _SpecsParser

        self.specs = specs
        _SpecsParser(specs)  # Raise exception on error in specs dict.
        self.cmd = self._create_cmd()

    def __repr__(self):
        return "{self.__class__.__name__}({self.cmd})".format(self=self)

    def __str__(self):
        return self.cmd

    def _create_cmd(self):
        """Return string representation of Dockerfile."""
        chunks = _get_dockerfile_chunks(self.specs)

        neurodocker_header = _add_neurodocker_header()
        common_deps_chunk = _add_common_dependencies(self.specs['pkg_manager'])

        chunks.insert(1, common_deps_chunk)
        chunks.insert(0, neurodocker_header)

        if self.specs['pkg_manager'] == 'apt':
            noninteractive = "ARG DEBIAN_FRONTEND=noninteractive"
            chunks.insert(2, noninteractive)
        return "\n\n".join(chunks) + "\n"

    def save(self, filepath="Dockerfile", **kwargs):
        """Save Dockerfile to `filepath`. `kwargs` are for `open()`."""
        with open(filepath, mode='w', **kwargs) as fp:
            fp.write(self.cmd)
