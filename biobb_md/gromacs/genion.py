#!/usr/bin/env python3

"""Module containing the Genion class and the command line interface."""
import os
import shutil
import argparse
from biobb_common.configuration import settings
from biobb_common.tools import file_utils as fu
from biobb_common.tools.file_utils import launchlogger
from biobb_common.command_wrapper import cmd_wrapper
from biobb_md.gromacs.common import get_gromacs_version
from biobb_md.gromacs.common import GromacsVersionError


class Genion:
    """Wrapper class for the GROMACS genion (http://manual.gromacs.org/current/onlinehelp/gmx-genion.html) module.

    Args:
        input_tpr_path (str): Path to the input portable run input TPR file.
        output_gro_path (str): Path to the input structure GRO file.
        input_top_zip_path (str): Path the input TOP topology in zip format.
        output_top_zip_path (str): Path the output topology TOP and ITP files zipball.
        properties (dic):
            * **output_top_path** (*str*) - ("gio.top") Path the output topology TOP file.
            * **replaced_group** (*str*) - ("SOL") Group of molecules that will be replaced by the solvent.
            * **neutral** (*bool*) - (False) Neutralize the charge of the system.
            * **concentration** (*float*) - (0.05) Concentration of the ions in (mol/liter).
            * **seed** (*int*) - (1993) Seed for random number generator.
            * **gmx_path** (*str*) - ("gmx") Path to the GROMACS executable binary.
            * **remove_tmp** (*bool*) - (True) [WF property] Remove temporal files.
            * **restart** (*bool*) - (False) [WF property] Do not execute if output files exist.
            * **container_path** (*string*) - (None)  Path to the binary executable of your container.
            * **container_image** (*string*) - ("gromacs/gromacs:latest") Container Image identifier.
            * **container_volume_path** (*string*) - ("/data") Path to an internal directory in the container.
            * **container_working_dir** (*string*) - (None) Path to the internal CWD in the container.
            * **container_user_id** (*string*) - (None) User number id to be mapped inside the container.
            * **container_shell_path** (*string*) - ("/bin/bash") Path to the binary executable of the container shell.
    """

    def __init__(self, input_tpr_path, output_gro_path, input_top_zip_path,
                 output_top_zip_path, properties=None, **kwargs):
        properties = properties or {}

        # Input/Output files
        self.io_dict = {
            "in": {"input_tpr_path": input_tpr_path},
            "out": {"output_gro_path": output_gro_path, "output_top_zip_path": output_top_zip_path}
        }
        # Should not be copied inside container
        self.input_top_zip_path = input_top_zip_path

        # Properties specific for BB
        self.output_top_path = properties.get('output_top_path', 'gio.top')
        self.replaced_group = properties.get('replaced_group', 'SOL')
        self.neutral = properties.get('neutral', False)
        self.concentration = properties.get('concentration', 0.05)
        self.seed = properties.get('seed', 1993)

        # container Specific
        self.container_path = properties.get('container_path')
        self.container_image = properties.get('container_image', 'gromacs/gromacs:latest')
        self.container_volume_path = properties.get('container_volume_path', '/data')
        self.container_working_dir = properties.get('container_working_dir')
        self.container_user_id = properties.get('container_user_id')
        self.container_shell_path = properties.get('container_shell_path', '/bin/bash')

        # Properties common in all GROMACS BB
        self.gmxlib = properties.get('gmxlib', None)
        self.gmx_path = properties.get('gmx_path', 'gmx')
        self.gmx_nobackup = properties.get('gmx_nobackup', True)
        self.gmx_nocopyright = properties.get('gmx_nocopyright', True)
        if self.gmx_nobackup:
            self.gmx_path += ' -nobackup'
        if self.gmx_nocopyright:
            self.gmx_path += ' -nocopyright'
        if not self.container_path:
            self.gmx_version = get_gromacs_version(self.gmx_path)

        # Properties common in all BB
        self.can_write_console_log = properties.get('can_write_console_log', True)
        self.global_log = properties.get('global_log', None)
        self.prefix = properties.get('prefix', None)
        self.step = properties.get('step', None)
        self.path = properties.get('path', '')
        self.remove_tmp = properties.get('remove_tmp', True)
        self.restart = properties.get('restart', False)

        # Check the properties
        fu.check_properties(self, properties)

    @launchlogger
    def launch(self):
        """Launches the execution of the GROMACS genion module."""
        tmp_files = []

        # Get local loggers from launchlogger decorator
        out_log = getattr(self, 'out_log', None)
        err_log = getattr(self, 'err_log', None)

        # Check GROMACS version
        if not self.container_path:
            if self.gmx_version < 512:
                raise GromacsVersionError("Gromacs version should be 5.1.2 or newer %d detected" % self.gmx_version)
            fu.log("GROMACS %s %d version detected" % (self.__class__.__name__, self.gmx_version), out_log)

        # Restart if needed
        if self.restart:
            if fu.check_complete_files(self.io_dict["out"].values()):
                fu.log('Restart is enabled, this step: %s will the skipped' % self.step, out_log, self.global_log)
                return 0

        # Unzip topology to topology_out
        top_file = fu.unzip_top(zip_file=self.input_top_zip_path, out_log=out_log)
        top_dir = os.path.dirname(top_file)
        tmp_files.append(top_dir)

        container_io_dict = fu.copy_to_container(self.container_path, self.container_volume_path, self.io_dict)

        if self.container_path:
            shutil.copytree(top_dir, os.path.join(container_io_dict.get("unique_dir"), os.path.basename(top_dir)))
            top_file = os.path.join(self.container_volume_path, os.path.basename(top_dir), os.path.basename(top_file))

        cmd = ['echo', '\"'+self.replaced_group+'\"', '|',
               self.gmx_path, 'genion',
               '-s', container_io_dict["in"]["input_tpr_path"],
               '-o', container_io_dict["out"]["output_gro_path"],
               '-p', top_file]

        if self.neutral:
            cmd.append('-neutral')

        if self.concentration:
            cmd.append('-conc')
            cmd.append(str(self.concentration))
            fu.log('To reach up %g mol/litre concentration' % self.concentration, out_log, self.global_log)

        if self.seed is not None:
            cmd.append('-seed')
            cmd.append(str(self.seed))

        new_env = None
        if self.gmxlib:
            new_env = os.environ.copy()
            new_env['GMXLIB'] = self.gmxlib

        cmd = fu.create_cmd_line(cmd, container_path=self.container_path,
                                 host_volume=container_io_dict.get("unique_dir"),
                                 container_volume=self.container_volume_path,
                                 container_working_dir=self.container_working_dir,
                                 container_user_uid=self.container_user_id,
                                 container_shell_path=self.container_shell_path,
                                 container_image=self.container_image,
                                 out_log=out_log, global_log=self.global_log)
        returncode = cmd_wrapper.CmdWrapper(cmd, out_log, err_log, self.global_log, new_env).launch()
        fu.copy_to_host(self.container_path, container_io_dict, self.io_dict)

        if self.container_path:
            top_file = os.path.join(container_io_dict.get("unique_dir"), os.path.basename(top_dir), os.path.basename(top_file))

        # zip topology
        fu.log('Compressing topology to: %s' % container_io_dict["out"]["output_top_zip_path"], out_log, self.global_log)
        fu.zip_top(zip_file=self.io_dict["out"]["output_top_zip_path"], top_file=top_file, out_log=out_log)

        tmp_files.append(container_io_dict.get("unique_dir"))
        if self.remove_tmp:
            fu.rm_file_list(tmp_files, out_log=out_log)

        return returncode


def main():
    parser = argparse.ArgumentParser(description="Wrapper for the GROMACS genion module.", formatter_class=lambda prog: argparse.RawTextHelpFormatter(prog, width=99999))
    parser.add_argument('-c', '--config', required=False, help="This file can be a YAML file, JSON file or JSON string")
    parser.add_argument('--system', required=False, help="Check 'https://biobb-common.readthedocs.io/en/latest/system_step.html' for help")
    parser.add_argument('--step', required=False, help="Check 'https://biobb-common.readthedocs.io/en/latest/system_step.html' for help")

    # Specific args of each building block
    required_args = parser.add_argument_group('required arguments')
    required_args.add_argument('--input_tpr_path', required=True)
    required_args.add_argument('--output_gro_path', required=True)
    required_args.add_argument('--input_top_zip_path', required=True)
    required_args.add_argument('--output_top_zip_path', required=True)

    args = parser.parse_args()
    config = args.config if args.config else None
    properties = settings.ConfReader(config=config, system=args.system).get_prop_dic()
    if args.step:
        properties = properties[args.step]

    # Specific call of each building block
    Genion(input_tpr_path=args.input_tpr_path, output_gro_path=args.output_gro_path,
           input_top_zip_path=args.input_top_zip_path, output_top_zip_path=args.output_top_zip_path,
           properties=properties).launch()


if __name__ == '__main__':
    main()
