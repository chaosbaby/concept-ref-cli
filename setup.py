from setuptools import setup, find_packages
import os

def find_commands():
    """
    Auto-detect command scripts and map them to short aliases.
    Supports:
    - single file: commands/name.py
    - package folder: commands/name/main.py
    """
    cmds = {}
    cmd_dir = "commands"
    if os.path.exists(cmd_dir):
        for entry in os.listdir(cmd_dir):
            path = os.path.join(cmd_dir, entry)
            module_name = None
            entry_point = None

            if os.path.isfile(path) and entry.endswith(".py") and not entry.startswith("__"):
                module_name = entry[:-3]
                entry_point = f"commands.{module_name}:cli"
            elif os.path.isdir(path) and os.path.exists(os.path.join(path, "main.py")):
                module_name = entry
                entry_point = f"commands.{module_name}.main:cli"

            if module_name:
                # Priority Mapping
                if module_name in ["lexicon", "lxc"]:
                    cmd_name = "lxc"
                elif module_name == "cp":
                    cmd_name = "cpt"
                elif module_name == "common":
                    cmd_name = "cm"
                else:
                    cmd_name = module_name
                
                cmds[cmd_name] = entry_point
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
