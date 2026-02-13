from setuptools import setup, find_packages
import os

def find_commands():
    cmds = {}
    cmd_dir = "commands"
    if os.path.exists(cmd_dir):
        for f in os.listdir(cmd_dir):
            if f.endswith(".py") and not f.startswith("__"):
                module_name = f[:-3]
                cmd_name = "cpt" if module_name == "cp" else module_name
                cmds[cmd_name] = f"commands.{module_name}:cli"
    return cmds

setup(
    name="concept-ref-cli",
    version="0.1.0",
    packages=find_packages(),
    install_requires=["click", "zhconv"],
    entry_points={
        "console_scripts": [
            f"{k}={v}" for k, v in find_commands().items()
        ]
    },
)
