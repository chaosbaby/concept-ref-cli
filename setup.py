from setuptools import setup, find_packages
import os

def find_commands():
    """
    Auto-detect command scripts and map them to short aliases.
    Standard mapping:
    - lexicon.py / lxc.py -> lxc
    - cp.py -> cpt
    - xh.py -> xh
    """
    cmds = {}
    cmd_dir = "commands"
    if os.path.exists(cmd_dir):
        for f in os.listdir(cmd_dir):
            if f.endswith(".py") and not f.startswith("__"):
                module_name = f[:-3]
                # Priority Mapping
                if module_name in ["lexicon", "lxc"]:
                    cmd_name = "lxc"
                elif module_name == "cp":
                    cmd_name = "cpt"
                else:
                    cmd_name = module_name
                
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
