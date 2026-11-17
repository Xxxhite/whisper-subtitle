"""Launch the subtitle command from the project root."""
from whisper_subtitle import cli

if __name__ == "__main__":
    raise SystemExit(cli.main())
else:
    # Preserve the existing import-based entry point for local integrations.
    import sys
    sys.modules[__name__] = cli
