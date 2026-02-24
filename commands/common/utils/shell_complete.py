import os
import subprocess
import click

def add_completion_commands(cli, prog_name):
    """
    为CLI应用添加补全命令
    
    Args:
        cli: click.Group 实例
        prog_name: 程序名称（用于环境变量和路径）
    """
    
    @cli.group(name='completion')
    def completion_cmd():
        """Manage shell completion scripts."""
        pass

    @completion_cmd.command(name='show')
    @click.argument('shell', type=click.Choice(['bash', 'zsh', 'fish']), required=False)
    def completion_show(shell):
        """Show the completion script for the specified shell."""
        if not shell:
            shell = os.path.basename(os.environ.get('SHELL', 'bash'))
        
        # Click's completion generation is triggered by environment variables.
        # We spawn a new process for the CLI itself with the right env var.
        env = os.environ.copy()
        env[f'_{prog_name.upper()}_COMPLETE'] = f'{shell}_source'
        
        result = subprocess.run([prog_name], env=env, capture_output=True, text=True)
        click.echo(result.stdout)

    @completion_cmd.command(name='install')
    @click.argument('shell', type=click.Choice(['bash', 'zsh', 'fish']), required=False)
    def completion_install(shell):
        """Install the completion script for the specified shell."""
        if not shell:
            shell = os.path.basename(os.environ.get('SHELL', 'bash'))

        rc_file = None
        install_line = f'eval "$(_{prog_name.upper()}_COMPLETE={shell}_source {prog_name})"'

        if shell == 'bash':
            rc_file = os.path.expanduser("~/.bashrc")
        elif shell == 'zsh':
            rc_file = os.path.expanduser("~/.zshrc")
        elif shell == 'fish':
            fish_completion_path = os.path.expanduser(f"~/.config/fish/completions/{prog_name}.fish")
            if not os.path.exists(os.path.dirname(fish_completion_path)):
                os.makedirs(os.path.dirname(fish_completion_path))
            
            env = os.environ.copy()
            env[f'_{prog_name.upper()}_COMPLETE'] = 'fish_source'
            
            with open(fish_completion_path, 'w') as f:
                result = subprocess.run([prog_name], env=env, capture_output=True, text=True)
                f.write(result.stdout)
                
            click.secho(f"✅ Installed completion for fish at {fish_completion_path}", fg='green')
            click.echo("Please restart your shell to activate.")
            return

        if not rc_file or not os.path.exists(rc_file):
            click.secho(f"Could not find shell config file for {shell}.", fg='red')
            return

        with open(rc_file, 'r+') as f:
            content = f.read()
            if install_line in content:
                click.secho(f"✅ Completion already installed in {rc_file}", fg='yellow')
                return
            
            # Add newline if file doesn't end with one
            if content and not content.endswith('\n'):
                f.write('\n')
            
            f.write(f"\n# {prog_name} completion\n")
            f.write(f"{install_line}\n")
        
        click.secho(f"✅ Installed completion in {rc_file}", fg='green')
        click.echo("Please restart your shell or run:")
        click.echo(f"  source {rc_file}")
    
    # Add the completion command group to the CLI
    cli.add_command(completion_cmd)
    
    return completion_cmd  # Return for potential further customization
