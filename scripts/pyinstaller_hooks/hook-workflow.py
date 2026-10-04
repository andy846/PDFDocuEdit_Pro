"""Our local workflow package is not the unrelated PyPI `workflow` distribution.

Override the contrib hook which tries to copy that distribution's metadata.
Normal static import analysis still collects the application's workflow modules.
"""
