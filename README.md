# rxp Python Requirements Extractor

`rxp.py` is a Python script that extracts and exports the required modules from a given Python file into a `requirements.txt` file.

## Features
- Extracts module imports (`import xxx` and `from xxx import yyy`).
- Detects duplicate import statements and displays warnings.
- Ignores built-in Python modules.
- Supports automatic naming for multiple exports.
- Saves the `requirements.txt` file in the script directory or a specified location.
- Provides a colorized and formatted CLI output using the `rich` library.

## Installation

Ensure you have the required dependencies installed:

```sh
pip install rich rich_argparse
pip install pydebugger #(optional for debugging, then set DEBUG env to '1')
```

## Usage

Run the script with the following command:

```sh
python rxp.py <your_script.py> 
#or
rxp <your_script.py> 
```

### Options:

| Option         | Description |
|---------------|-------------|
| `-o, --output`  | Specify an output file (default: `requirements.txt`). |
| `-q, --quiet`  | Overwrite if the output file already exists. |
| `-a, --auto-number` | Auto-number suffix for multiple exports (e.g., `requirements1.txt`, `requirements2.txt`). |
| `-s, --self`  | Save `requirements.txt` in the same directory as the source file instead of the current directory. |

### Example Usage:

```sh
python rxp.py my_script.py -o my_requirements.txt -q
#or just
rxp my_script.py
```

This will extract all the required modules from `my_script.py` and save them in `requirements.txt`, overwriting any existing file or auto-number suffix.

## How It Works
1. Reads the Python file and scans for `import` and `from ... import ...` statements.
2. Filters out built-in Python modules.
3. Warns about duplicate imports.
4. Exports third-party modules to a requirements file.

## Dependencies
- `rich`
- `rich_argparse`

## License
- Apache 2 License.

## Author
[Hadi Cahyadi](mailto:cumulus13@gmail.com)

[![Buy Me a Coffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/cumulus13)

[![Donate via Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/cumulus13)

[Support me on Patreon](https://www.patreon.com/cumulus13)

