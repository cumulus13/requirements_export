import re
import os
import argparse
import sys
from pathlib import Path
from rich.console import Console
from rich_argparse import RichHelpFormatter, _lazy_rich as rr
from typing import ClassVar
import pkgutil
if os.getenv('DEBUG') == '1':
    from pydebugger.debug import debug
else:
    def debug(*args, **kargs):
        return

console = Console()

class CustomRichHelpFormatter(RichHelpFormatter):
    """A custom RichHelpFormatter with modified styles."""

    styles: ClassVar[dict[str, rr.StyleType]] = {
        "argparse.args": "bold #FFFF00",  # Changed from cyan
        "argparse.groups": "#AA55FF",   # Changed from dark_orange
        "argparse.help": "bold #00FFFF",    # Changed from default
        "argparse.metavar": "bold #FF00FF", # Changed from dark_cyan
        "argparse.syntax": "underline", # Changed from bold
        "argparse.text": "white",   # Changed from default
        "argparse.prog": "bold #00AAFF italic",     # Changed from grey50
        "argparse.default": "bold", # Changed from italic
    }
    
def get_modules():
    # Python 3.10+ provides `sys.stdlib_module_names`
    if hasattr(sys, "stdlib_module_names"):
        stdlib_modules = sys.stdlib_module_names
    else:
        # Fallback for older Python versions (not fully reliable)
        stdlib_path = os.path.dirname(sys.modules["os"].__file__)  # Locate stdlib
        stdlib_modules = {name for name in os.listdir(stdlib_path) if name.endswith(".py")}
        stdlib_modules = {name[:-3] for name in stdlib_modules}  # Remove `.py`

    # Built-in (C-based) modules
    builtin_modules = set(sys.builtin_module_names)

    # Combine both sets
    all_builtin_and_stdlib = builtin_modules | stdlib_modules

    # Print sorted list
    # print(sorted(all_builtin_and_stdlib))
    return sorted(all_builtin_and_stdlib)
    
def extract_imports_from_file(file_path):
    """
    Extracts module names from a Python file.
    Detects both 'import xxx' and 'from xxx import xxx' statements.
    Shows a warning on the line where duplicate import statements occur.
    Ignores built-in Python modules.
    """
    modules = set()
    duplicate_modules = {}
    built_in_modules = get_modules()
    debug(built_in_modules = built_in_modules)
    
    import_pattern = re.compile(r'^(\s*)import\s+([\w,\s]+)')
    from_import_pattern = re.compile(r'^(\s*)from\s+([\w.]+)\s+import\s+')
    
    if not os.path.exists(file_path):
        console.print("[white on red blink]File not found ![/]")
        return []
    
    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()
    
    for line_no, line in enumerate(lines, start=1):
        # Check for 'import xxx'
        match_import = import_pattern.match(line)
        if match_import:
            imported_modules = match_import.group(2).replace(" ", "").split(',')
            for module in imported_modules:
                debug(module = module)
                # if module in built_in_modules:
                #     continue
                if module in modules:
                    duplicate_modules[line_no] = module
                if module in built_in_modules:
                    modules.add(module)
        
        # Check for 'from xxx import yyy'
        match_from_import = from_import_pattern.match(line)
        if match_from_import:
            module = match_from_import.group(2).split('.')[0]  # Extract root module
            debug(module = module)
            # if module in built_in_modules:
            #     continue
            if module in modules:
                duplicate_modules[line_no] = module
            if not module in built_in_modules:
                modules.add(module)
    
    for line_no, module in duplicate_modules.items():
        console.print(f"[black on #FFFF00]Warning: Duplicate import[/] [white on red]'{str(module).strip()}'[/] [bold #FFAAFF]found on line[/] [white on blue]{line_no}[/] !")
    
    # print(f"modules: modules")
    return sorted([i.strip() for i in modules])
    
def export_requirements(file_path, quiet = False, auto_number = False, save_in_self = True, output_file='requirements.txt'):
    """
    Extracts module names and exports them to requirements.txt
    """
    if save_in_self:
        output_file = str(Path(file_path).parent / Path(output_file).stem) + ".txt"
    if output_file and Path(output_file).is_file():
        if quiet:
            output_file = Path.cwd() / output_file
        elif auto_number:
            n = 1
            while 1:
                if Path(output_file).is_file():
                    output_file = Path.cwd() / f'requirements{n}.conf'
                    n+=1
                else:
                    break
        else:
            q = console.input(f"[#FFFF00]'{str(output_file)}[/]' [white on red]is exits[/], [bold blue]auto create new[/] ([bold #FFAA00]y[/]): ")
            if q and q.lower() in ['y', 'yes']:
                n = 1
                while 1:
                    if Path(output_file).is_file():
                        output_file = Path.cwd() / f'requirements{n}.txt'
                        n+=1
                    else:
                        break
            
    output_file = str(output_file) if output_file and isinstance(output_file, Path) else output_file
    
    if file_path:
        modules = extract_imports_from_file(file_path)
        if modules:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(modules))
            output_name = str(Path(output_file).stem)
            output_name_split = output_name.split("requirements")
            # debug(output_name_split = output_name_split, debug = 1)
            if len(output_name_split) == 2 and output_name_split[1]:
                output_name = f"[bold #FFAA00]requirements[/][white on #5500FF]{output_name_split[1]}[/][bold #FFAA00].txt[/]"
            else:
                output_name = f"[bold #FFAA00]{output_file}[/]"
            
            console.print(f"[bold #00FFFF]Requirements exported to:[/] {output_name}")
        else:
            print("[white on red]No modules found to export !.[/]")

def usage():
    parser = argparse.ArgumentParser(formatter_class=CustomRichHelpFormatter)
    parser.add_argument('FILE', help = "File path", action = "store")
    parser.add_argument('-o', '--output', help = 'Specify an output file as, default = [bold #AAFF00]"requirements.txt"[/]', default = 'requirements.txt')
    parser.add_argument('-q', '--quiet', action='store_true', help = 'Overwrite if the output file already exists.')
    parser.add_argument('-a', '--auto-number', action='store_true', help = 'Auto number suffix to file, format will be [bold #AAFF00]"requirements[/][bold #FF00FF]\[n][/][bold #AAFF00].txt"[/]')
    parser.add_argument('-s', '--self', action = 'store_true', help = f"Save 'requirements[n].txt' in the same directory as the source file instead of the current directory, default is current directory: [bold #FFAA00]'{str(Path.cwd())}'[/]")
    
    if len(sys.argv) == 1:
        parser.print_help()
    else:
        args = parser.parse_args()
        export_requirements(args.FILE, args.quiet, args.auto_number, args.self, args.output)
        
if __name__ == "__main__":
    usage()
    
