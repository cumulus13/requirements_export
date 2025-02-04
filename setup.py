from setuptools import setup, find_packages

version = {}
with open("__version__.py") as fp:
    exec(fp.read(), version)
version = version['version']

setup(
    name="rxp",
    version=f"{version}",
    author="Hadi Cahyadi",
    author_email="cumulus13@gmail.com",
    url="https://github.com/cumulus13/requirements_export",
    project_urls={
        "Documentation": "https://github.com/cumulus13/requirements_export",
        "Code": "https://github.com/cumulus13/requirements_export",
    },
    maintainer_email="cumulus13@gmail.com",
    description="A Python script to extract and export required modules from a given Python file.",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "rxp=rxp.rxp:usage",
        ],
    },
    install_requires=[
        "rich",
        "rich_argparse"
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
    ],
    python_requires=">=3.7",
    license="Apache-2.0",
    license_files=["LICENSE"],
    python_requires=">=3.0",    
)
