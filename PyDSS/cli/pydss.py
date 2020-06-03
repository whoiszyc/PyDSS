"""Main CLI command for PyDSS."""

import logging


import click

from PyDSS.cli.create_project import create_project
from PyDSS.cli.add_post_process import add_post_process
from PyDSS.cli.excel_to_toml import excel_to_toml
from PyDSS.cli.export import export
from PyDSS.cli.extract import extract, extract_element_files
from PyDSS.cli.run import run
from PyDSS.cli.edit_scenario import edit_scenario
from PyDSS.cli.run_server import serve
1

logger = logging.getLogger(__name__)


@click.group()
def cli():
    """PyDSS commands"""

cli.add_command(create_project)
cli.add_command(add_post_process)
cli.add_command(excel_to_toml)
cli.add_command(export)
cli.add_command(extract)
cli.add_command(extract_element_files)
cli.add_command(run)
cli.add_command(edit_scenario)
cli.add_command(serve)