import re
import sys
import importlib.metadata
import importlib.util
import stdlib_list

def extract_imports(file_path):
    """Extract top-level imported modules from a Python script."""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.readlines()

    import_pattern = re.compile(r"^\s*(?:import|from)\s+([\w\.]+)")
    modules = set()
    
    for line in content:
        match = import_pattern.match(line)
        if match:
            module = match.group(1).split(".")[0]  # Get top-level package
            modules.add(module)

    return modules

def is_builtin_module(module):
    """Check if a module is a built-in standard library module."""
    return module in stdlib_list.stdlib_list()

def is_importable(module):
    """Check if the module can be imported (ignoring standard lib modules)."""
    return importlib.util.find_spec(module) is not None and not is_builtin_module(module)

def get_installed_version(module):
    """Get installed package version, if available."""
    try:
        return importlib.metadata.version(module)
    except importlib.metadata.PackageNotFoundError:
        return None  # Module is not installed

def export_requirements(modules, output_file="requirements.txt"):
    """Write discovered modules to requirements.txt with versions if available."""
    with open(output_file, "w", encoding="utf-8") as f:
        for module in sorted(modules):
            if not is_importable(module):
                continue  # Skip non-importable modules
            
            version = get_installed_version(module)
            if version:
                f.write(f"{module}=={version}\n")
            else:
                f.write(f"{module}\n")  # Might need manual installation

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script.py <file.py>")
        sys.exit(1)
    
    file_path = sys.argv[1]
    modules = extract_imports(file_path)
    export_requirements(modules)
    print(f"Extracted {len(modules)} modules to requirements.txt")
