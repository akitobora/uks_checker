from setuptools import setup, find_packages

setup(
    name="uks_checker",
    version="0.1.0",
    packages=find_packages(),  # найдёт uks_checker
    install_requires=[
        "requests",
        "beautifulsoup4",
        "python-telegram-bot",
        # и всё, что ещё в requirements.txt
    ],
    python_requires=">=3.8",
)
