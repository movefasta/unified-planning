#!/usr/bin/env python3

from setuptools import setup, find_packages  # type: ignore
# import unified_planning


long_description = """============================================================
 Unified planning: A library that unifies planning frameworks
 ============================================================
    Insert long description here
"""

setup(
    name="unified_planning",
    version="0.5.0",
    description="Unified Planning Framework",
    author="AIPlan4EU Project",
    author_email="aiplan4eu@fbk.eu",
    url="https://www.aiplan4eu-project.eu",
    packages=find_packages(),
    include_package_data=True,
    python_requires=">=3.7",  # supported Python ranges
    install_requires=["pyparsing>=3", "networkx"],
    extras_require={
        "dev": ["tarski[arithmetic]", "pytest", "pytest-cov", "mypy"],
        "grpc": ["grpcio", "grpcio-tools", "grpc-stubs"],
        "tarski": ["tarski[arithmetic]"],
        "pyperplan": ["up-pyperplan==0.3.0.2.dev1"],
        "tamer": ["up-tamer==0.3.1.3.dev1"],
        "enhsp": ["up-enhsp==0.0.11"],
        "fast-downward": ["up-fast-downward==0.1.2"],
        "lpg": ["up-lpg==0.0.4.9"],
        "fmap": ["up-fmap==0.0.2"],
        "aries": ["up-aries>=0.0.4"],
        "engines": [
            "tarski[arithmetic]",
            "up-pyperplan==0.3.0.2.dev1",
            "up-tamer==0.3.1.3.dev1",
            "up-enhsp==0.0.11",
            "up-fast-downward==0.1.2",
            "up-lpg==0.0.4.9",
            "up-fmap==0.0.2",
            "up-aries>=0.0.4",
        ],
    },
    license="APACHE",
    keywords="planning logic STRIPS RDDL",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Science/Research",
        "Intended Audience :: Developers",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
    ],
)
