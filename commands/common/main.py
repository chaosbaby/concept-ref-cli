import click
import os
from commands.common.utils.shell_complete import add_completion_commands
DB_PATH = os.path.expanduser("~/.cihai.db")

@click.group()
def cli():
    """Main entry point for the CLI application."""
    pass

try:
    from commands.common.utils.json2sqlite import json2sqlite_cmd
    cli.add_command(json2sqlite_cmd)
    add_completion_commands(cli, prog_name='cm')
except ImportError as e:
    click.secho(f"Warning: Could not load 'query' command: {e}", fg='yellow')
    raise e

from commands.query import create_table_commands
lexicon_cmds = create_table_commands(
    db_path=DB_PATH,
    table_prefix="",
    tables = ['cihai'],
    help_text="查询词典数据库",
    # cache_values= True  # 启用值缓存以加速补全
)
for cmd in lexicon_cmds:
    cli.add_command(cmd)

freq_cmds = create_table_commands(
    db_path="~/.freq_dict.db",
    table_prefix="",
    tables = ['freq'],
    help_text="3.6m查询词频词性数据库",
    # cache_values= True  # 启用值缓存以加速补全
)

for cmd in freq_cmds:
    cli.add_command(cmd)

if __name__ == '__main__':
    cli()

