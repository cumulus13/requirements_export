import re
import sys
import importlib.metadata
import importlib.util
import stdlib_list
from rich.console import RenderableType
from rich_argparse import RichHelpFormatter
import argparse


class CustomRichHelpFormatter(RichHelpFormatter):
    def add_renderable(self, renderable: RenderableType) -> None:
        # padded = r.Padding.indent(renderable, self._current_indent)
        self._current_section.rich_items.append(renderable)

class RequirementsExporter:
    @classmethod
    def extract_imports(cls, file_path):
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

    @classmethod
    def is_builtin_module(cls, module):
        """Check if a module is a built-in standard library module."""
        return module in stdlib_list.stdlib_list()

    @classmethod
    def is_importable(cls, module):
        """Check if the module can be imported (ignoring standard lib modules)."""
        return importlib.util.find_spec(module) is not None and not cls.is_builtin_module(module)

    @classmethod
    def get_installed_version(cls, module):
        """Get installed package version, if available."""
        try:
            return importlib.metadata.version(module)
        except importlib.metadata.PackageNotFoundError:
            return None  # Module is not installed

    @classmethod
    def export_requirements(cls, modules, output_file="requirements.txt"):
        """Write discovered modules to requirements.txt with versions if available."""
        with open(output_file, "w", encoding="utf-8") as f:
            for module in sorted(modules):
                if not cls.is_importable(module):
                    continue  # Skip non-importable modules
                
                version = cls.get_installed_version(module)
                if version:
                    f.write(f"{module}=={version}\n")
                else:
                    f.write(f"{module}\n")  # Might need manual installation

    @classmethod
    def usage(cls):
        """Main usage method for the script."""
        parser = argparse.ArgumentParser(formatter_class=CustomRichHelpFormatter)
        parser.add_argument(
            "file_path",
            type=str,
            help="Path to the Python file to analyze for dependencies."
        )
        parser.add_argument(
            "-o", "--output",
            type=str,
            default="requirements.txt",
            help="Output file for the requirements (default: requirements.txt)."
        )
        args = parser.parse_args()
        return args

if __name__ == "__main__":
    args = RequirementsExporter.usage()
    modules = RequirementsExporter.extract_imports(args.file_path)
    RequirementsExporter.export_requirements(modules, args.output)
    print(f"Extracted {len(modules)} modules to {args.output}")
