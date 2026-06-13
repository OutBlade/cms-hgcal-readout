from setuptools import setup, find_packages

setup(
    name="cms-hgcal-readout",
    version="0.1.0",
    description="ECON-D/T frame decoder and analysis toolkit for CMS HGCAL prototype readout",
    author="Barbara Kallfelz",
    author_email="barbarakallfelz94@gmail.com",
    python_requires=">=3.11",
    packages=find_packages(where="analysis"),
    install_requires=[
        "numpy>=1.26",
        "scipy>=1.12",
        "matplotlib>=3.8",
    ],
    extras_require={
        "full": ["uproot>=5.3", "awkward>=2.6"],
        "dev":  ["pytest>=8.0"],
    },
)
